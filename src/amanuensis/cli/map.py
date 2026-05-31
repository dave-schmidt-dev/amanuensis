"""``amanuensis map <subcommand>`` — entity resolution registry (Phase 2a).

Sub-apps / commands
-------------------
- ``map`` (orchestrator) — stub; T7.2 fills in the warp-plan cycle.
- ``map status`` — read-only workspace summary; T7.4.
- ``map entity {list,show,merge}`` — entity CRUD; T7.5-T7.7 stubs.
- ``map resolution {show,supersede}`` — resolution inspection; T7.8-T7.9 stubs.
- ``map vocabulary {show,snapshot}`` — vocabulary registry; T7.10 stubs.

Hard rules upheld here
-----------------------
- INV-1: every non-stub command is wrapped in ``@require_marker``.
- INV-4: ``map status`` is read-only; no flock, no replay-log writes.
- INV-8: substrate access is mediated through ``Substrate`` exclusively.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from amanuensis.fs import ReplayLog, Substrate

from ._marker import require_marker, workspace_from_kwargs

# ---------------------------------------------------------------------------
# Top-level app
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="map",
    help="Resolve entities across distillations; manage the mapping registry.",
    no_args_is_help=True,
    add_completion=False,
)

# ---------------------------------------------------------------------------
# Nested sub-apps
# ---------------------------------------------------------------------------

entity_app = typer.Typer(
    name="entity",
    help="Inspect and manage canonical entities.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(entity_app, name="entity", help="Inspect and manage canonical entities.")

resolution_app = typer.Typer(
    name="resolution",
    help="Inspect and supersede resolution records.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(
    resolution_app,
    name="resolution",
    help="Inspect and supersede resolution records.",
)

vocabulary_app = typer.Typer(
    name="vocabulary",
    help="Show and snapshot the entity-kind vocabulary.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(
    vocabulary_app,
    name="vocabulary",
    help="Show and snapshot the entity-kind vocabulary.",
)

# ---------------------------------------------------------------------------
# Top-level map orchestrator (stub — T7.2 fills this in)
# ---------------------------------------------------------------------------


@app.command("map")
def map_command() -> None:
    """Run the full map warp-plan cycle (stub; T7.2)."""
    typer.echo("TODO: map")


# ---------------------------------------------------------------------------
# map status (T7.4)
# ---------------------------------------------------------------------------


_RESOLUTION_CLARIFICATION_KINDS = frozenset({"resolution-disputed", "resolution-ambiguous"})


@dataclass(frozen=True, slots=True)
class _MapStatusCounts:
    """Per-distillation or workspace-aggregate map status counts."""

    entity_operand_count: int
    resolved_count: int
    unresolved_count: int
    open_clarification_count: int
    last_map_run_at: str  # ISO 8601 UTC or "never"


def _compute_last_map_run_at(workspace_path: Path) -> str:
    """Return newest mappings replay-log entry timestamp, or 'never'."""
    try:
        log = ReplayLog.for_mappings(workspace_path)
    except Exception:
        return "never"
    newest: datetime | None = None
    for entry in log.list_entries():
        ts = entry.timestamp
        if newest is None or ts > newest:
            newest = ts
    if newest is None:
        return "never"
    return newest.astimezone(UTC).isoformat()


def _status_for_source(
    substrate: Substrate,
    source_id: str,
    last_map_run_at: str,
) -> _MapStatusCounts:
    """Compute map status counts for one distillation."""
    entity_operand_count = 0
    resolved_count = 0

    for atom in substrate.list_atoms(source_id):
        for idx, operand in enumerate(atom.operands):
            if operand.kind != "entity":
                continue
            entity_operand_count += 1
            resolution = substrate.latest_resolution_for(source_id, atom.id, idx)
            if resolution is not None:
                resolved_count += 1

    # substrate.list_clarifications has no source_id filter, so walk the
    # per-distillation open/ directory directly to count resolution-kind
    # clarifications for this source only.
    open_clarification_count = _count_open_resolution_clarifications(substrate, source_id)

    unresolved_count = max(0, entity_operand_count - resolved_count - open_clarification_count)

    return _MapStatusCounts(
        entity_operand_count=entity_operand_count,
        resolved_count=resolved_count,
        unresolved_count=unresolved_count,
        open_clarification_count=open_clarification_count,
        last_map_run_at=last_map_run_at,
    )


def _count_open_resolution_clarifications(substrate: Substrate, source_id: str) -> int:
    """Count open clarifications with resolution kinds for one distillation."""
    clar_open_dir = substrate.root / "distillations" / source_id / "clarifications" / "open"
    if not clar_open_dir.is_dir():
        return 0
    from amanuensis.fs._serialize import (
        parse_clarification_md,
    )

    count = 0
    for path in sorted(clar_open_dir.iterdir()):
        if not path.is_file() or not path.name.endswith(".md"):
            continue
        if ".tmp." in path.name:
            continue
        try:
            clar = parse_clarification_md(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if clar.kind in _RESOLUTION_CLARIFICATION_KINDS:
            count += 1
    return count


def _counts_to_dict(counts: _MapStatusCounts) -> dict[str, object]:
    """Serialise a _MapStatusCounts to a plain dict for JSON output."""
    return {
        "entity_operand_count": counts.entity_operand_count,
        "resolved_count": counts.resolved_count,
        "unresolved_count": counts.unresolved_count,
        "open_clarification_count": counts.open_clarification_count,
        "last_map_run_at": counts.last_map_run_at,
    }


def _emit_status_json(
    workspace_path: Path,
    per_distillation: dict[str, _MapStatusCounts],
    aggregate: _MapStatusCounts,
) -> None:
    """Print sorted-key JSON status payload."""
    payload: dict[str, object] = {
        "workspace_root": str(workspace_path),
        "workspace_aggregate": _counts_to_dict(aggregate),
    }
    if per_distillation:
        payload["per_distillation"] = {
            src: _counts_to_dict(c) for src, c in sorted(per_distillation.items())
        }
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _emit_status_human(
    workspace_path: Path,
    per_distillation: dict[str, _MapStatusCounts],
    aggregate: _MapStatusCounts,
) -> None:
    """Print human-readable map status summary."""
    typer.echo(f"workspace:             {workspace_path}")
    typer.echo("--- workspace_aggregate ---")
    typer.echo(f"  entity_operand_count:    {aggregate.entity_operand_count}")
    typer.echo(f"  resolved_count:          {aggregate.resolved_count}")
    typer.echo(f"  unresolved_count:        {aggregate.unresolved_count}")
    typer.echo(f"  open_clarification_count:{aggregate.open_clarification_count}")
    typer.echo(f"  last_map_run_at:         {aggregate.last_map_run_at}")
    for source_id, counts in sorted(per_distillation.items()):
        typer.echo(f"--- {source_id} ---")
        typer.echo(f"  entity_operand_count:    {counts.entity_operand_count}")
        typer.echo(f"  resolved_count:          {counts.resolved_count}")
        typer.echo(f"  unresolved_count:        {counts.unresolved_count}")
        typer.echo(f"  open_clarification_count:{counts.open_clarification_count}")
        typer.echo(f"  last_map_run_at:         {counts.last_map_run_at}")


@app.command("status")
@require_marker
def status_command(
    source_id_filter: Annotated[
        str | None,
        typer.Option(
            "--source-id",
            help="Filter to a single distillation by source-id.",
        ),
    ] = None,
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
    """Print map status counts for the workspace (read-only; INV-4)."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    # Validate --source-id if supplied.
    all_source_ids = list(substrate.list_distillations())
    if source_id_filter is not None and source_id_filter not in all_source_ids:
        typer.echo(
            f"no source-id {source_id_filter!r} under distillations/",
            err=False,
        )
        raise typer.Exit(code=1)

    source_ids = [source_id_filter] if source_id_filter is not None else all_source_ids

    last_map_run_at = _compute_last_map_run_at(workspace_path)

    per_distillation: dict[str, _MapStatusCounts] = {
        src: _status_for_source(substrate, src, last_map_run_at) for src in source_ids
    }

    # Aggregate across all selected distillations.
    agg_entity = sum(c.entity_operand_count for c in per_distillation.values())
    agg_resolved = sum(c.resolved_count for c in per_distillation.values())
    agg_open_clar = sum(c.open_clarification_count for c in per_distillation.values())
    agg_unresolved = max(0, agg_entity - agg_resolved - agg_open_clar)
    aggregate = _MapStatusCounts(
        entity_operand_count=agg_entity,
        resolved_count=agg_resolved,
        unresolved_count=agg_unresolved,
        open_clarification_count=agg_open_clar,
        last_map_run_at=last_map_run_at,
    )

    if json_output:
        _emit_status_json(workspace_path, per_distillation, aggregate)
    else:
        _emit_status_human(workspace_path, per_distillation, aggregate)


# ---------------------------------------------------------------------------
# entity sub-commands (stubs — T7.5-T7.7)
# ---------------------------------------------------------------------------


@entity_app.command("list")
def entity_list_command() -> None:
    """List canonical entities (stub; T7.5)."""
    typer.echo("TODO: list")


@entity_app.command("show")
def entity_show_command() -> None:
    """Show a canonical entity (stub; T7.6)."""
    typer.echo("TODO: show")


@entity_app.command("merge")
def entity_merge_command() -> None:
    """Merge two entities (stub; T7.7)."""
    typer.echo("TODO: merge")


# ---------------------------------------------------------------------------
# resolution sub-commands (stubs — T7.8-T7.9)
# ---------------------------------------------------------------------------


@resolution_app.command("show")
def resolution_show_command() -> None:
    """Show a resolution record (stub; T7.8)."""
    typer.echo("TODO: show")


@resolution_app.command("supersede")
def resolution_supersede_command() -> None:
    """Supersede a resolution record (stub; T7.9)."""
    typer.echo("TODO: supersede")


# ---------------------------------------------------------------------------
# vocabulary sub-commands (stubs — T7.10)
# ---------------------------------------------------------------------------


@vocabulary_app.command("show")
def vocabulary_show_command() -> None:
    """Show the active entity-kind vocabulary (stub; T7.10)."""
    typer.echo("TODO: show")


@vocabulary_app.command("snapshot")
def vocabulary_snapshot_command() -> None:
    """Snapshot the entity-kind vocabulary (stub; T7.10)."""
    typer.echo("TODO: snapshot")
