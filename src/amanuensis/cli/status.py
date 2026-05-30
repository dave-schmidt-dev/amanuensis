"""``amanuensis status`` — terse workspace summary (read-only).

Walks the substrate's distillations and counts atoms / relations /
clarifications. Read-only; does NOT acquire the workspace flock. The
``--json`` flag swaps the human-readable text output for a single
JSON document so dashboards / scripts can parse it.

Counts collected per distillation
---------------------------------
- ``paragraphs``: from the source-mirror manifest if present, else 0.
- ``atoms``: count of ``.md`` files under ``atoms/`` (skipping
  ``.tmp.*`` writer leftovers).
- ``relations``: count of ``.yaml`` files under ``relations/``.
- ``clarifications_open`` / ``clarifications_resolved``: by sub-bucket.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated

import typer

from amanuensis.fs import Substrate

from ._common import list_distillations
from ._marker import require_marker, workspace_from_kwargs


@dataclass(frozen=True, slots=True)
class _DistillationSummary:
    """Per-distillation counts; mirrors the JSON output shape."""

    source_id: str
    paragraphs: int
    atoms: int
    relations: int
    clarifications_open: int
    clarifications_resolved: int


def _count_files(directory: Path, suffix: str) -> int:
    """Count files in ``directory`` with the given suffix, skipping ``.tmp.*``."""
    if not directory.is_dir():
        return 0
    n = 0
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        name = entry.name
        if not name.endswith(suffix):
            continue
        if ".tmp." in name:
            continue
        n += 1
    return n


def _count_paragraphs(substrate: Substrate, source_id: str) -> int:
    """Return the manifest's paragraph count, or 0 if no manifest yet."""
    manifest_path = substrate.manifest_path(source_id)
    if not manifest_path.is_file():
        return 0
    # Counting paragraphs from on-disk files (vs. parsing the manifest)
    # keeps this read-only operation cheap and resilient to a manifest
    # in an inconsistent state mid-write — atomic writes make that rare
    # but not impossible.
    paragraphs_dir = substrate.source_mirror_root(source_id) / "paragraphs"
    return _count_files(paragraphs_dir, ".md")


def _summarize_distillation(substrate: Substrate, source_id: str) -> _DistillationSummary:
    """Walk one distillation's directories and tally each artifact class."""
    dist_root = substrate.root / "distillations" / source_id
    atoms = _count_files(dist_root / "atoms", ".md")
    relations = _count_files(dist_root / "relations", ".yaml")
    clarifications_open = _count_files(dist_root / "clarifications" / "open", ".md")
    clarifications_resolved = _count_files(dist_root / "clarifications" / "resolved", ".md")
    return _DistillationSummary(
        source_id=source_id,
        paragraphs=_count_paragraphs(substrate, source_id),
        atoms=atoms,
        relations=relations,
        clarifications_open=clarifications_open,
        clarifications_resolved=clarifications_resolved,
    )


def _emit_json(workspace_root: Path, summaries: list[_DistillationSummary]) -> None:
    """Print machine-parseable summary; sorted keys for stable diff."""
    payload = {
        "workspace_root": str(workspace_root),
        "distillation_count": len(summaries),
        "distillations": [asdict(s) for s in summaries],
    }
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _emit_human(workspace_root: Path, summaries: list[_DistillationSummary]) -> None:
    """Print a terse human-readable summary."""
    typer.echo(f"workspace:       {workspace_root}")
    typer.echo(f"distillations:   {len(summaries)}")
    if not summaries:
        typer.echo("  (no distillations yet — run `amanuensis ingest <pdf>` to create one)")
        return
    for s in summaries:
        typer.echo(f"  {s.source_id}")
        typer.echo(f"    paragraphs:               {s.paragraphs}")
        typer.echo(f"    atoms:                    {s.atoms}")
        typer.echo(f"    relations:                {s.relations}")
        typer.echo(f"    clarifications (open):    {s.clarifications_open}")
        typer.echo(f"    clarifications (resolved):{s.clarifications_resolved}")


@require_marker
def status_command(
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit machine-parseable JSON instead of human-readable text.",
        ),
    ] = False,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Print workspace + per-distillation summary counts (read-only)."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)
    summaries = [
        _summarize_distillation(substrate, source_id) for source_id in list_distillations(substrate)
    ]
    if json_output:
        _emit_json(substrate.root, summaries)
    else:
        _emit_human(substrate.root, summaries)
