"""``amanuensis reconcile`` — drain dispatch outputs into the substrate (M7.4).

Mutating command. Reads every pending ``dispatch/outputs/<role>-<hash>/
output.yaml``, runs the role-appropriate validators, commits clean
atoms / relations / PROV records to the substrate, raises clarifications
for dirty ones (including CR-7 warrant-defensibility-contested), and
moves consumed output files into ``dispatch/outputs/_consumed/`` so the
command is idempotent.

The flock is acquired inside :func:`amanuensis.dispatch.reconcile.reconcile_outputs`;
the CLI body itself just builds the substrate handle and forwards.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import Substrate

from ._marker import require_marker, workspace_from_kwargs


@require_marker
def reconcile_command(
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Drain dispatch outputs: validate, commit, raise clarifications."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace_path)

    # One-line per category so the operator gets a quick scan of what
    # changed. Detailed inspection is via ``amanuensis atom list`` etc.
    typer.echo(f"reconcile: atoms_committed={len(result.atoms_committed)}")
    typer.echo(f"reconcile: relations_committed={len(result.relations_committed)}")
    typer.echo(f"reconcile: clarifications_raised={len(result.clarifications_raised)}")
    typer.echo(f"reconcile: outputs_consumed={len(result.outputs_consumed)}")

    if result.errors:
        typer.echo("")
        typer.echo("errors (output left in place for manual triage):")
        for path, reason in result.errors:
            typer.echo(f"  {path}: {reason}")
        # Exit non-zero so CI / scripts see the failure.
        raise typer.Exit(code=1)
