"""Status + replay-log routes (M8.7).

Two read-only HTML pages for the supervisor:

- ``GET /replay-log`` — flat, most-recent-first table of replay-log
  entries across every distillation in the workspace, with optional
  filters for ``actor``, ``activity``, ``date``, and ``limit``.
- ``GET /status`` — labeled key-value list of workspace-wide stats
  (workspace path, marker version, totals across all distillations,
  replay-log size, vocabulary registry).

The replay log lives **per-distillation** at
``<workspace>/distillations/<source-id>/replay-log/<yyyy-mm-dd>/<seq:012>.yaml``
(see M1.7's :class:`amanuensis.fs.replay_log.ReplayLog`). This module
walks that tree directly with ``os.scandir`` rather than constructing
one :class:`ReplayLog` per distillation — the goal is a workspace-wide
view, and a stat-only walk keeps the page render cheap.

The existing JSON ``GET /healthz`` route on ``app.py`` is preserved
verbatim; ``/status`` is the HTML companion (supervisor-facing) while
``/healthz`` stays JSON for monitoring scrapers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from amanuensis.fs import Substrate
from amanuensis.schemas import ReplayLogEntry
from amanuensis.vocabulary import VocabularyLoadError, load_vocabulary

from ..dependencies import WORKSPACE_ENV_VAR, get_substrate
from ._substrate_counts import (
    _count_files,  # pyright: ignore[reportPrivateUsage] — package-internal helper
    list_distillation_source_ids,
)

router = APIRouter()

# Default page size for the replay-log table — keeps the render bounded
# on workspaces with thousands of entries. The supervisor can override
# via ``?limit=`` (capped at ``_MAX_LIMIT``).
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 1000


@dataclass(frozen=True)
class _ReplayLogRow:
    """Renderable replay-log row — flat tuple of strings + the parsed entry.

    The template iterates ``rows`` and reads each entry's fields
    directly; ``source_id`` is carried alongside because the entry
    itself does not encode which distillation it belongs to (that lives
    in the file's parent path).
    """

    source_id: str
    day: str
    seq: int
    entry: ReplayLogEntry


def _scan_replay_log(
    workspace_root: Path,
    *,
    date_filter: str | None,
    actor_filter: str | None,
    activity_filter: str | None,
    limit: int,
) -> list[_ReplayLogRow]:
    """Walk every distillation's replay log and return matching rows.

    The walk is purely stat-driven until a file matches the date
    filter — only then do we ``yaml.safe_load`` + ``model_validate``
    the entry. ``actor_filter`` and ``activity_filter`` are substring
    matches (case-sensitive) applied after parsing.

    Returned rows are sorted by ``(day, seq)`` descending so the most
    recent entry is first. The list is truncated to ``limit`` entries.
    Corrupt entry files (unparseable YAML or schema-invalid payloads)
    are skipped silently — a broken replay-log entry should not blank
    the page; the supervisor can investigate via the on-disk file.
    """
    distillations_root = workspace_root / "distillations"
    if not distillations_root.is_dir():
        return []

    rows: list[_ReplayLogRow] = []

    with os.scandir(distillations_root) as dist_iter:
        for dist_entry in dist_iter:
            if not dist_entry.is_dir():
                continue
            source_id = dist_entry.name
            replay_log_dir = Path(dist_entry.path) / "replay-log"
            if not replay_log_dir.is_dir():
                continue

            with os.scandir(replay_log_dir) as day_iter:
                day_dirs = [
                    Path(day.path)
                    for day in day_iter
                    if day.is_dir() and (date_filter is None or day.name == date_filter)
                ]

            for day_dir in day_dirs:
                day_name = day_dir.name
                with os.scandir(day_dir) as file_iter:
                    file_paths = [
                        Path(file.path)
                        for file in file_iter
                        if file.is_file()
                        and file.name.endswith(".yaml")
                        and ".tmp." not in file.name
                    ]
                for entry_path in file_paths:
                    try:
                        raw = yaml.safe_load(entry_path.read_text(encoding="utf-8"))
                        entry = ReplayLogEntry.model_validate(raw)
                    except (OSError, yaml.YAMLError, ValueError):
                        # Skip unreadable / malformed entries; surfacing
                        # an exception would mask the rest of the log.
                        continue

                    if actor_filter and actor_filter not in entry.actor.identifier:
                        continue
                    if activity_filter and activity_filter not in entry.activity:
                        continue

                    rows.append(
                        _ReplayLogRow(
                            source_id=source_id,
                            day=day_name,
                            seq=entry.seq,
                            entry=entry,
                        )
                    )

    # Most-recent first. Sorting by (day, seq) descending matches the
    # write-order semantics: within a day, seq is monotonically
    # assigned by ``ReplayLog.append`` under the workspace flock; days
    # sort lexicographically (which matches chronological order for
    # ``YYYY-MM-DD``).
    rows.sort(key=lambda r: (r.day, r.seq), reverse=True)
    return rows[:limit]


@router.get("/replay-log", response_class=HTMLResponse)
async def replay_log(
    request: Request,
    substrate: Annotated[Substrate, Depends(get_substrate)],
    actor: Annotated[
        str | None,
        Query(description="Substring match against entry.actor.identifier"),
    ] = None,
    activity: Annotated[
        str | None,
        Query(description="Substring match against entry.activity"),
    ] = None,
    date: Annotated[
        str | None,
        Query(description="YYYY-MM-DD; defaults to today's UTC date"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=_MAX_LIMIT, description="Max rows to return (capped at 1000)"),
    ] = _DEFAULT_LIMIT,
) -> HTMLResponse:
    """Render the replay-log table with optional filters.

    The ``date`` filter defaults to today's UTC date so the supervisor
    lands on the current day's activity by default. An explicit empty
    string (``?date=``) means "no date filter" — useful when looking
    for an entry whose day the supervisor does not remember.
    """
    # An explicit ?date= (empty string) disables the date filter; a
    # missing query parameter defaults to today. ``Query`` gives us
    # ``None`` for "not provided" and ``""`` for "provided but empty".
    if date is None:
        effective_date: str | None = datetime.now(UTC).strftime("%Y-%m-%d")
    elif date == "":
        effective_date = None
    else:
        effective_date = date

    rows = _scan_replay_log(
        substrate.root,
        date_filter=effective_date,
        actor_filter=actor or None,
        activity_filter=activity or None,
        limit=limit,
    )

    templates = request.app.state.templates
    return templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "replay_log.html",
        {
            "workspace_path": str(substrate.root),
            "rows": rows,
            "actor": actor or "",
            "activity": activity or "",
            # Surface what the route actually filtered on so the form
            # round-trips the default-applied date back to the user.
            "date": effective_date or "",
            "limit": limit,
        },
    )


@dataclass(frozen=True)
class _ReplayLogStats:
    """File-count + byte-size totals across every distillation's replay log."""

    file_count: int
    total_bytes: int


def _replay_log_stats(workspace_root: Path) -> _ReplayLogStats:
    """Walk the replay-log tree once and return aggregate file/byte counts.

    Stat-only walk: never opens the YAML payloads. Skips ``.tmp.*``
    writer leftovers and the ``.next-seq`` counter file (which lives at
    the replay-log dir root, not inside a day subdir).
    """
    distillations_root = workspace_root / "distillations"
    if not distillations_root.is_dir():
        return _ReplayLogStats(file_count=0, total_bytes=0)

    file_count = 0
    total_bytes = 0
    with os.scandir(distillations_root) as dist_iter:
        for dist_entry in dist_iter:
            if not dist_entry.is_dir():
                continue
            replay_log_dir = Path(dist_entry.path) / "replay-log"
            if not replay_log_dir.is_dir():
                continue
            with os.scandir(replay_log_dir) as day_iter:
                for day_entry in day_iter:
                    if not day_entry.is_dir():
                        continue
                    with os.scandir(day_entry.path) as file_iter:
                        for file_entry in file_iter:
                            if not file_entry.is_file():
                                continue
                            name = file_entry.name
                            if not name.endswith(".yaml"):
                                continue
                            if ".tmp." in name:
                                continue
                            file_count += 1
                            try:
                                total_bytes += file_entry.stat().st_size
                            except OSError:
                                # File vanished mid-walk; ignore. The
                                # count we already incremented is fine
                                # — the next refresh corrects it.
                                continue
    return _ReplayLogStats(file_count=file_count, total_bytes=total_bytes)


@dataclass(frozen=True)
class _StatusContext:
    """All the labelled key-value pairs the /status page renders."""

    workspace_path: str
    marker_version: str
    distillation_count: int
    total_atoms: int
    total_relations: int
    total_clarifications_open: int
    total_clarifications_resolved: int
    total_iterations: int
    replay_log_file_count: int
    replay_log_total_bytes: int
    vocabulary_registry_path: str
    vocabulary_entry_count: int


def _read_marker_version(workspace_root: Path) -> str:
    """Parse ``amanuensis.yaml`` and return ``schema_version`` as a string.

    Returns ``"unknown"`` if the marker is missing, unparseable, or
    lacks the field — ``get_substrate`` already proved the marker
    exists for any request that reaches this route, so the only
    realistic miss-case is a malformed marker (which is itself worth
    surfacing rather than 500ing).
    """
    marker = workspace_root / "amanuensis.yaml"
    try:
        raw = marker.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError):
        return "unknown"
    if not isinstance(parsed, dict):
        return "unknown"
    version = parsed.get("schema_version")  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
    if version is None:
        return "unknown"
    return str(version)  # pyright: ignore[reportUnknownArgumentType]


def _resolve_vocabulary_registry(workspace_root: Path) -> tuple[str, int]:
    """Return ``(registry_path, entry_count)`` for the workspace vocabulary.

    Resolution priority mirrors :mod:`amanuensis.cli._common` (the CLI
    is the canonical resolver):

    1. ``domain.vocabulary_registry`` from the marker — supports both a
       file path and a directory containing ``predicates.yaml``.
    2. The bundled ``vocabularies/generic/predicates.yaml`` shipped
       alongside the package source tree.

    Returns ``("<unresolved>", 0)`` when neither candidate exists or
    when the resolved file is unparseable. Duplicating the resolver
    here (rather than importing :mod:`amanuensis.cli._common`) keeps
    the web package's import graph free of the CLI package.
    """
    marker = workspace_root / "amanuensis.yaml"
    candidates: list[Path] = []

    if marker.is_file():
        try:
            parsed = yaml.safe_load(marker.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            parsed = None
        if isinstance(parsed, dict):
            domain = parsed.get("domain")  # pyright: ignore[reportUnknownMemberType]
            if isinstance(domain, dict):
                registry_value = domain.get("vocabulary_registry")  # pyright: ignore[reportUnknownMemberType]
                if isinstance(registry_value, str) and registry_value:
                    expanded = Path(os.path.expandvars(os.path.expanduser(registry_value)))
                    if expanded.is_dir():
                        candidates.append(expanded / "predicates.yaml")
                    else:
                        candidates.append(expanded)

    # Bundled generic registry at <repo>/vocabularies/generic/predicates.yaml.
    # __file__ is src/amanuensis/web/routes/status.py → parents[4] = repo root.
    bundled = Path(__file__).resolve().parents[4] / "vocabularies" / "generic" / "predicates.yaml"
    candidates.append(bundled)

    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            vocab = load_vocabulary(candidate)
        except VocabularyLoadError:
            continue
        return str(candidate), len(vocab.entries)

    return "<unresolved>", 0


def _collect_status_context(substrate: Substrate) -> _StatusContext:
    """Assemble every label/value pair shown on the /status page."""
    source_ids = list_distillation_source_ids(substrate)

    total_atoms = 0
    total_relations = 0
    total_open = 0
    total_resolved = 0
    for source_id in source_ids:
        distillation_root = substrate.root / "distillations" / source_id
        total_atoms += _count_files(distillation_root / "atoms", suffix=".md")
        total_relations += _count_files(distillation_root / "relations", suffix=".yaml")
        total_open += _count_files(distillation_root / "clarifications" / "open", suffix=".md")
        total_resolved += _count_files(
            distillation_root / "clarifications" / "resolved", suffix=".md"
        )

    # Iterations live at workspace level (``<workspace>/iterations/<id>.md``).
    total_iterations = _count_files(substrate.root / "iterations", suffix=".md")

    replay_stats = _replay_log_stats(substrate.root)
    vocab_path, vocab_entry_count = _resolve_vocabulary_registry(substrate.root)

    return _StatusContext(
        workspace_path=str(substrate.root),
        marker_version=_read_marker_version(substrate.root),
        distillation_count=len(source_ids),
        total_atoms=total_atoms,
        total_relations=total_relations,
        total_clarifications_open=total_open,
        total_clarifications_resolved=total_resolved,
        total_iterations=total_iterations,
        replay_log_file_count=replay_stats.file_count,
        replay_log_total_bytes=replay_stats.total_bytes,
        vocabulary_registry_path=vocab_path,
        vocabulary_entry_count=vocab_entry_count,
    )


@router.get("/status", response_class=HTMLResponse)
async def status_page(
    request: Request,
    substrate: Annotated[Substrate, Depends(get_substrate)],
) -> HTMLResponse:
    """Render the HTML status page (companion to the JSON ``/healthz``)."""
    ctx = _collect_status_context(substrate)
    templates = request.app.state.templates
    return templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "status.html",
        {
            "stats": ctx,
            "workspace_env_var": WORKSPACE_ENV_VAR,
        },
    )
