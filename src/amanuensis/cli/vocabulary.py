"""``amanuensis vocabulary <subcommand>`` — inspect predicates + snapshots.

All read-only; no flock acquisition.

Subcommands
-----------
- ``vocabulary list`` — print every canonical predicate in the active
  vocabulary (one per line, with the entry's aliases summarised).
- ``vocabulary show <predicate>`` — print one entry's full YAML
  representation (canonical predicate, aliases, operand_types,
  qualifier_required, notes).
- ``vocabulary snapshot <source-id>`` — print the per-distillation
  vocabulary snapshot bytes (INV-10).

The active vocabulary is resolved via ``load_active_vocabulary`` (see
``_common.py``): workspace's ``domain.vocabulary_registry`` first,
then the bundled generic registry, then the in-memory placeholder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml

from amanuensis.fs import Substrate

from ._common import load_active_vocabulary
from ._marker import fatal, require_marker, workspace_from_kwargs

app = typer.Typer(
    name="vocabulary",
    help="Inspect the active vocabulary registry and per-distillation snapshots.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command("list")
@require_marker
def list_vocabulary_command(
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """List every canonical predicate in the active vocabulary."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    vocab = load_active_vocabulary(workspace_path)
    typer.echo(f"# vocabulary: {vocab.name} v{vocab.version}  ({len(vocab.entries)} entries)")
    for entry in vocab.entries:
        aliases = f"  aliases={','.join(entry.aliases)}" if entry.aliases else ""
        typer.echo(f"{entry.predicate}{aliases}")


@app.command("show")
@require_marker
def show_vocabulary_command(
    predicate: Annotated[str, typer.Argument(help="Predicate (canonical or alias) to show.")],
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Print one vocabulary entry's full YAML representation."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    vocab = load_active_vocabulary(workspace_path)
    canonical = vocab.resolve(predicate)
    if canonical is None:
        fatal(f"predicate {predicate!r} is not registered in vocabulary {vocab.name!r}")
        return
    entry = vocab.entries_by_predicate[canonical]
    typer.echo(yaml.safe_dump(entry.model_dump(mode="json"), sort_keys=False), nl=False)


@app.command("snapshot")
@require_marker
def snapshot_vocabulary_command(
    source_id: Annotated[str, typer.Argument(help="Per-distillation source id.")],
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Print the per-distillation vocabulary snapshot (INV-10)."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)
    path = substrate.vocabulary_snapshot_path(source_id)
    if not path.is_file():
        fatal(f"no vocabulary snapshot for source_id {source_id!r} (looked at {path})")
        return
    typer.echo(path.read_text(encoding="utf-8"), nl=False)
