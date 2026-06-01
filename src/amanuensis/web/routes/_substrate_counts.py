"""Private substrate-walking helpers for the dashboard + source overview.

The :class:`amanuensis.fs.Substrate` API exposes ``list_atoms`` but does
not yet expose ``list_relations`` / ``list_clarifications`` /
``list_distillations``. M8.2 needs simple counts for the dashboard, so
this module walks the canonical Phase 1 layout directly:

::

    <workspace>/distillations/<source-id>/
      atoms/*.md
      relations/*.yaml
      clarifications/open/*.md
      clarifications/resolved/*.md
      source-mirror/manifest.yaml

Walking the filesystem here (instead of extending Substrate's API) keeps
M8.2 scope-bounded: dashboard counts are a UI concern. A follow-up
(tracked in TASKS.md) will promote these helpers to the Substrate class
once a second consumer needs them.

Determinism
-----------
All listing helpers sort their output lexicographically so the dashboard
table is stable across runs. ``.tmp.*`` writer leftovers are skipped to
mirror ``Substrate.list_atoms``.

Defensive filtering (Phase 2b cleanup-5)
----------------------------------------
``list_distillation_source_ids`` filters out subdirectory names that
fail :func:`amanuensis.fs.substrate._validate_id_component`. iCloud
and Dropbox sync daemons create duplicate dirs with embedded spaces
(``phase1-smoke 2``) that would otherwise feed the offending name into
``Substrate.manifest_path`` etc. and 500 the dashboard route. Skipped
names emit a single ``logging.WARNING`` via the ``amanuensis.web``
logger so a supervisor can spot the orphan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from amanuensis.fs import Substrate
from amanuensis.fs._errors import SubstrateInvalidId
from amanuensis.fs.substrate import (  # pyright: ignore[reportPrivateUsage]
    _validate_id_component,
)
from amanuensis.schemas import SourceMirrorManifest

_log = logging.getLogger("amanuensis.web")


@dataclass(frozen=True)
class DistillationCounts:
    """Per-distillation counts used by the dashboard row."""

    source_id: str
    atoms: int
    relations: int
    clarifications_open: int
    clarifications_resolved: int
    has_manifest: bool
    paragraph_count: int | None  # None when no manifest is present.


def list_distillation_source_ids(substrate: Substrate) -> list[str]:
    """Return every ``source_id`` that has a ``distillations/<source-id>/`` dir.

    Lex-sorted for deterministic dashboard ordering. Non-directories
    are skipped (a stray file under ``distillations/`` would otherwise
    crash later count walkers).

    Phase 2b cleanup-5: subdirectories whose name is not a valid
    path-safe id (per Substrate's ``_validate_id_component``) are also
    skipped + each one is logged at WARNING level so a supervisor sees
    the diagnostic. The trigger is iCloud / Dropbox sync daemons that
    clone subdirectories with embedded spaces (``phase1-smoke 2``);
    without the filter the dashboard 500s on the first count walker
    that pipes the name into a Substrate path helper.
    """
    distillations_root = substrate.root / "distillations"
    if not distillations_root.is_dir():
        return []
    valid: list[str] = []
    for entry in distillations_root.iterdir():
        if not entry.is_dir():
            continue
        try:
            _validate_id_component(entry.name, label="source_id")
        except SubstrateInvalidId as exc:
            _log.warning(
                "ignored non-path-safe distillation directory: %r (%s)",
                entry.name,
                exc,
            )
            continue
        valid.append(entry.name)
    return sorted(valid)


def _count_files(directory: Path, *, suffix: str) -> int:
    """Count regular files in ``directory`` ending in ``suffix``.

    Skips ``.tmp.*`` writer leftovers (atomic-write sentinel) and any
    subdirectories. Returns 0 if the directory does not exist (a
    distillation with no atoms / no relations is valid).
    """
    if not directory.is_dir():
        return 0
    count = 0
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        name = entry.name
        if not name.endswith(suffix):
            continue
        if ".tmp." in name:
            continue
        count += 1
    return count


def collect_counts(substrate: Substrate, source_id: str) -> DistillationCounts:
    """Walk one distillation's directories and return all counts.

    Cheap stat-only walk (no YAML / Markdown parsing). The manifest is
    detected by file existence; paragraph count is read from the
    manifest YAML only when the manifest exists.
    """
    distillation_root = substrate.root / "distillations" / source_id
    atoms = _count_files(distillation_root / "atoms", suffix=".md")
    relations = _count_files(distillation_root / "relations", suffix=".yaml")
    clarifications_open = _count_files(distillation_root / "clarifications" / "open", suffix=".md")
    clarifications_resolved = _count_files(
        distillation_root / "clarifications" / "resolved", suffix=".md"
    )

    manifest_path = substrate.manifest_path(source_id)
    has_manifest = manifest_path.is_file()
    paragraph_count: int | None = None
    if has_manifest:
        manifest = load_manifest(manifest_path)
        paragraph_count = len(manifest.paragraphs)

    return DistillationCounts(
        source_id=source_id,
        atoms=atoms,
        relations=relations,
        clarifications_open=clarifications_open,
        clarifications_resolved=clarifications_resolved,
        has_manifest=has_manifest,
        paragraph_count=paragraph_count,
    )


def load_manifest(manifest_path: Path) -> SourceMirrorManifest:
    """Parse + validate a source-mirror manifest from its on-disk YAML.

    The dashboard + source overview both need this; centralising the
    parse keeps the YAML loader (``safe_load``) consistent and means
    schema validation happens in exactly one place.
    """
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    return SourceMirrorManifest.model_validate(raw)
