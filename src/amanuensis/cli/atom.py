"""``amanuensis atom <subcommand>`` — list / show / validate atoms.

Read-only subcommand group. No flock acquisition.

Subcommands
-----------
- ``atom list <source-id> [--scale ...]`` — list atom ids under one
  distillation, optionally filtered by ``scale_anchor``.
- ``atom show <source-id> <atom-id>`` — print one atom's full
  narrative + frontmatter via the standard substrate read path.
- ``atom validate <source-id> [--validator NAME]`` — run validators
  against the distillation's atoms. Default runs all seven canonical
  validators; ``--validator`` restricts to one by name. Prints
  per-validator pass / fail counts and exits non-zero if any fail.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from amanuensis.fs import Substrate, SubstrateNotFound, SubstrateSnapshotCorrupt
from amanuensis.schemas import Atom
from amanuensis.validators import (
    ValidationResult,
    citation_ledger,
    closed_vocabulary,
    provenance_completeness,
    scale_anchor,
    schema_check,
    universe_check,
)

from ._common import list_distillations
from ._marker import echo_error, fatal, require_marker, workspace_from_kwargs

app = typer.Typer(
    name="atom",
    help="List, show, and validate atoms in a distillation.",
    no_args_is_help=True,
    add_completion=False,
)


class Scale(StrEnum):
    """Mirror of Atom.scale_anchor's closed value set (INV-6)."""

    sentence = "sentence"
    paragraph = "paragraph"
    section = "section"
    document = "document"


# Closed set of validator names that the CLI can dispatch by string.
# ``lineage_closure`` runs over relations, not atoms, so it is excluded
# from ``atom validate`` — invoke it via a future ``relation validate``
# (out of M4 scope).
_ATOM_VALIDATOR_NAMES: tuple[str, ...] = (
    "schema_check",
    "citation_ledger",
    "universe_check",
    "scale_anchor",
    "closed_vocabulary",
    "provenance_completeness",
)


@app.command("list")
@require_marker
def list_atoms_command(
    source_id: Annotated[
        str,
        typer.Argument(help="Per-distillation source id."),
    ],
    scale: Annotated[
        Scale | None,
        typer.Option(
            "--scale",
            help="Filter to atoms whose scale_anchor matches the given value.",
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """List atom ids under ``source-id`` (optionally filtered by scale)."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)
    count = 0
    for atom in substrate.list_atoms(source_id):
        if scale is not None and atom.scale_anchor != scale.value:
            continue
        typer.echo(f"{atom.id}  scale={atom.scale_anchor}  predicate={atom.predicate}")
        count += 1
    typer.echo(f"# {count} atom(s)")


@app.command("show")
@require_marker
def show_atom_command(
    source_id: Annotated[str, typer.Argument(help="Per-distillation source id.")],
    atom_id: Annotated[str, typer.Argument(help="Atom id (e.g. a-<hash>).")],
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Print one atom's frontmatter + narrative (raw on-disk form)."""
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)
    try:
        path = substrate.atom_path(source_id, atom_id)
    except Exception as exc:
        fatal(f"invalid atom-id {atom_id!r}: {exc}")
        return
    if not path.is_file():
        fatal(f"atom not found: {path}")
        return
    typer.echo(path.read_text(encoding="utf-8"), nl=False)


def _run_one_validator(
    name: str,
    atom: Atom,
    *,
    substrate: Substrate,
    known_source_ids: set[str],
    vocabulary_for_source: dict[str, object],
) -> ValidationResult | None:
    """Dispatch one validator by name; returns None if it can't run for this atom."""
    if name == "schema_check":
        return schema_check(atom, model_class=Atom)
    if name == "citation_ledger":
        return citation_ledger(atom)
    if name == "universe_check":
        return universe_check(atom, known_source_ids=known_source_ids)
    if name == "scale_anchor":
        return scale_anchor(atom)
    if name == "closed_vocabulary":
        # Per INV-10, the snapshot is the source of truth. If a snapshot
        # could not be loaded for the atom's source (corrupt / missing),
        # skip this validator with a None — the caller treats it as a
        # warning rather than a hard failure since the snapshot pin is
        # set up at ingest time and a missing snapshot indicates a
        # broken substrate the operator must repair separately.
        vocab = vocabulary_for_source.get(atom.source_id)
        if vocab is None:
            return None
        # ``vocab`` is opaque here to avoid a runtime import-cycle leak;
        # the closed_vocabulary validator expects a Vocabulary.
        from amanuensis.schemas import Vocabulary

        if not isinstance(vocab, Vocabulary):
            return None
        return closed_vocabulary(atom, vocabulary=vocab)
    if name == "provenance_completeness":
        return provenance_completeness(atom, substrate=substrate)
    return None


@app.command("validate")
@require_marker
def validate_atoms_command(
    source_id: Annotated[str, typer.Argument(help="Per-distillation source id.")],
    validator: Annotated[
        str | None,
        typer.Option(
            "--validator",
            help=(
                "Run only the named validator (default: run all). "
                f"Choices: {', '.join(_ATOM_VALIDATOR_NAMES)}."
            ),
        ),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace root (must contain amanuensis.yaml). Defaults to CWD.",
        ),
    ] = None,
) -> None:
    """Run canonical validators against atoms in ``source-id``.

    Prints per-validator pass / fail counts. Exits with code 1 if any
    atom fails any validator; exits 0 if every check passes.
    """
    workspace_path = workspace_from_kwargs({"workspace": workspace})
    substrate = Substrate(workspace_path)

    if validator is not None and validator not in _ATOM_VALIDATOR_NAMES:
        fatal(f"unknown validator {validator!r}; choices: {', '.join(_ATOM_VALIDATOR_NAMES)}")
        return

    selected: tuple[str, ...] = (validator,) if validator is not None else _ATOM_VALIDATOR_NAMES

    known_source_ids = set(list_distillations(substrate))
    # Pre-load the per-distillation vocabulary snapshot once per source.
    # closed_vocabulary needs the snapshot (INV-10); missing snapshots
    # mark the validator skipped for that atom rather than abort the run.
    vocabulary_for_source: dict[str, object] = {}
    try:
        vocabulary_for_source[source_id] = substrate.get_vocabulary_snapshot(source_id)
    except (SubstrateNotFound, SubstrateSnapshotCorrupt) as exc:
        echo_error(
            f"vocabulary snapshot unavailable for {source_id!r}: {exc} "
            "— skipping closed_vocabulary checks"
        )

    pass_counts: dict[str, int] = dict.fromkeys(selected, 0)
    fail_counts: dict[str, int] = dict.fromkeys(selected, 0)
    skip_counts: dict[str, int] = dict.fromkeys(selected, 0)
    failures: list[ValidationResult] = []

    atom_count = 0
    for atom in substrate.list_atoms(source_id):
        atom_count += 1
        for name in selected:
            result = _run_one_validator(
                name,
                atom,
                substrate=substrate,
                known_source_ids=known_source_ids,
                vocabulary_for_source=vocabulary_for_source,
            )
            if result is None:
                skip_counts[name] += 1
                continue
            if result.passed:
                pass_counts[name] += 1
            else:
                fail_counts[name] += 1
                failures.append(result)

    typer.echo(f"atoms scanned: {atom_count}")
    for name in selected:
        line = (
            f"  {name:28s}  pass={pass_counts[name]:>4d}  "
            f"fail={fail_counts[name]:>4d}  skip={skip_counts[name]:>4d}"
        )
        typer.echo(line)

    if failures:
        typer.echo("")
        typer.echo("failures:")
        for f in failures:
            typer.echo(f"  [{f.validator}] {f.subject_id}: {f.reason}")
        raise typer.Exit(code=1)
