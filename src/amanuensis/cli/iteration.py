"""``amanuensis iteration <subcommand>`` — list / add iteration directives.

Subcommands
-----------
- ``iteration list`` — read-only; no flock. Walks
  ``iterations/`` at the workspace root.
- ``iteration add --directive TEXT --target-source ID`` — mutating;
  acquires workspace flock. Writes the directive and a paired
  ``iteration-issued`` PROV record.

Iteration directives live at the workspace level (one ``iterations/``
directory at the substrate root), not under any single distillation.
The ``--target-source`` flag identifies which distillation a directive
applies to and is recorded as the entry in ``target_artifacts``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, cast

import typer

from amanuensis.fs import Substrate, acquire_workspace_lock
from amanuensis.fs._serialize import parse_iteration_md
from amanuensis.schemas import AgentAttribution, IterationDirective, ProvenanceRecord, compute_id

from ._marker import require_marker, workspace_from_kwargs

app = typer.Typer(
    name="iteration",
    help="List and add workspace-level iteration directives.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command("list")
@require_marker
def list_iterations_command(
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """List every iteration directive at the workspace root (read-only)."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)
    iters_dir = substrate.root / "iterations"
    if not iters_dir.is_dir():
        typer.echo("# no iterations")
        return
    rows: list[IterationDirective] = []
    for path in sorted(iters_dir.iterdir()):
        if not path.is_file() or not path.name.endswith(".md"):
            continue
        if ".tmp." in path.name:
            continue
        try:
            iter_obj = parse_iteration_md(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(iter_obj)
    if not rows:
        typer.echo("# no iterations")
        return
    for it in rows:
        applied = "applied" if it.applied_at is not None else "issued"
        targets = ",".join(it.target_artifacts) or "(none)"
        typer.echo(
            f"{applied:8s}  {it.id}  phase={it.target_phase}  targets={targets}  "
            f"directive={it.directive[:80]!r}"
        )
    typer.echo(f"# {len(rows)} iteration(s)")


# Phases an iteration directive can target. Mirrors the schema literal so a
# misspelled CLI value is rejected at parse time rather than at write time.
_TARGET_PHASES: tuple[str, ...] = ("distill", "map", "extend", "synthesize")


@app.command("add")
@require_marker
def add_iteration_command(
    directive: Annotated[
        str,
        typer.Option("--directive", help="The directive text (what to revise / how)."),
    ],
    target_source: Annotated[
        str,
        typer.Option(
            "--target-source",
            help="Source id this directive applies to (recorded in target_artifacts).",
        ),
    ],
    rationale: Annotated[
        str,
        typer.Option(
            "--rationale",
            help="Why this directive is needed (a single line is fine).",
        ),
    ] = "(no rationale recorded)",
    target_phase: Annotated[
        str,
        typer.Option(
            "--target-phase",
            help=f"Phase the directive targets (choices: {', '.join(_TARGET_PHASES)}).",
        ),
    ] = "distill",
    issuer: Annotated[
        str,
        typer.Option(
            "--issuer",
            help="Identifier of the human issuing the directive.",
        ),
    ] = "cli",
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Add a new iteration directive (writes directive + issued PROV record)."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    if target_phase not in _TARGET_PHASES:
        from ._marker import fatal

        fatal(f"unknown target_phase {target_phase!r}; choices: {', '.join(_TARGET_PHASES)}")
        return
    # ``target_phase`` is already validated against the closed set above;
    # cast to the Literal so Pydantic strict mode accepts it.
    target_phase_lit = cast("Literal['distill', 'map', 'extend', 'synthesize']", target_phase)

    now = datetime.now(UTC)
    issued_by = AgentAttribution(
        kind="human",
        identifier=issuer,
        role="human_supervisor",
    )

    with acquire_workspace_lock(workspace_path):
        # 1. Build the issued PROV record. ``entity_id`` is the directive's
        #    own id, computed in step 2 — so we draft the PROV with a
        #    placeholder, compute the directive id (which doesn't depend
        #    on PROV — issued_provenance_id is volatile per the schema),
        #    then finalize.
        # First: build the directive draft with a placeholder PROV id.
        iter_draft = IterationDirective(
            id="i-" + "0" * 16,
            issued_at=now,
            issued_by=issued_by,
            target_phase=target_phase_lit,
            target_artifacts=[target_source],
            directive=directive,
            rationale=rationale,
            applied_at=None,
            applied_by=None,
            applied_outcome=None,
            issued_provenance_id="p-" + "0" * 16,
            applied_provenance_id=None,
            schema_version=1,
        )
        iter_id = compute_id(iter_draft)

        # Now build the PROV record whose entity_id == iter_id.
        prov_draft = ProvenanceRecord(
            id="p-" + "0" * 16,
            entity_type="iteration-issued",
            entity_id=iter_id,
            activity="iteration-issue",
            activity_started_at=now,
            activity_ended_at=now,
            used_entity_ids=[],
            was_attributed_to=issued_by,
            was_influenced_by=[],
            schema_version=1,
        )
        prov_id = compute_id(prov_draft)
        prov = prov_draft.model_copy(update={"id": prov_id})
        # PROV files for iteration directives are filed under the target
        # source's distillation (matches the clarification convention).
        substrate.add_provenance(target_source, prov)

        # Finalize the directive with the real PROV id.
        iter_obj = iter_draft.model_copy(
            update={
                "id": iter_id,
                "issued_provenance_id": prov.id,
            }
        )
        iter_path = substrate.add_iteration(iter_obj)

    typer.echo(f"issued iteration: {iter_obj.id}")
    typer.echo(f"path:        {iter_path}")
    typer.echo(f"provenance:  {substrate.provenance_path(target_source, prov.id)}")
