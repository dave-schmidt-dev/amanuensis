"""Reconciliation gate tests (M7.4).

Covers the three core contracts of :func:`amanuensis.dispatch.reconcile.reconcile_outputs`:

1. A valid extractor output commits the atom + its PROV record and moves
   the output file under ``_consumed/``.
2. An extractor output whose atom violates ``closed_vocabulary`` (unknown
   predicate) does NOT commit the atom but DOES raise a clarification.
3. A second reconcile run after a first successful one is a no-op
   (idempotency by virtue of the ``_consumed/`` move).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from amanuensis.dispatch.reconcile import reconcile_outputs
from amanuensis.fs import Substrate
from amanuensis.schemas import (
    OperandTypeSchema,
    Vocabulary,
    VocabularyEntry,
)

# --- Local fixtures ----------------------------------------------------


def _make_workspace(tmp_path: Path) -> Path:
    """Plant an INV-1 marker so Substrate / acquire_workspace_lock accept it."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: reconcile-test\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_vocabulary() -> Vocabulary:
    return Vocabulary(
        name="reconcile-test-vocab",
        version="0.1.0",
        entries=[
            VocabularyEntry(
                predicate="asserts_obligation",
                aliases=[],
                operand_types=[
                    OperandTypeSchema(name="subject", kind="entity", required=True),
                ],
                qualifier_required=False,
                notes="reconcile-test entry",
            ),
        ],
    )


def _plant_distillation(workspace: Path, source_id: str) -> Substrate:
    """Create a distillations/<source_id>/ tree + snapshot the vocabulary.

    universe_check needs the source-id to exist on disk (so it's in the
    known_source_ids set); closed_vocabulary needs the snapshot pin.
    """
    substrate = Substrate(workspace)
    # Ensure the distillation dir exists so reconcile's source_ids walk
    # picks it up.
    (workspace / "distillations" / source_id).mkdir(parents=True, exist_ok=True)
    substrate.snapshot_vocabulary(source_id, _make_vocabulary())
    return substrate


def _plant_extractor_output(
    workspace: Path,
    inputs_hash: str,
    payload: dict[str, Any],
) -> Path:
    """Drop a ``dispatch/outputs/extractor-<hash>/output.yaml`` with ``payload``."""
    out_dir = workspace / "dispatch" / "outputs" / f"extractor-{inputs_hash}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "output.yaml"
    out_path.write_text(
        yaml.safe_dump(payload, sort_keys=True, default_flow_style=False),
        encoding="utf-8",
    )
    return out_path


def _valid_atom_payload(source_id: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "section_path": ["Part I", "§1"],
        "paragraph_index": 0,
        "char_span": [0, 30],
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": "asserts_obligation",
        "operands": [
            {"role": "subject", "kind": "entity", "value": "ent-acme"},
        ],
        "narrative": "ACME shall pay within 30 days.",
        "qualifier_level": None,
        "qualifier_basis": None,
    }


# --- 1. Valid atom commits + file moves to _consumed/ ------------------


def test_reconcile_extractor_output_commits_valid_atoms(tmp_path: Path) -> None:
    """A clean atom is committed; its PROV record is written; file moves to _consumed/."""
    workspace = _make_workspace(tmp_path)
    source_id = "reconcile-src-valid"
    substrate = _plant_distillation(workspace, source_id)

    inputs_hash = "h" * 64
    out_path = _plant_extractor_output(
        workspace,
        inputs_hash,
        {"proposed_atoms": [_valid_atom_payload(source_id)]},
    )

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert len(result.atoms_committed) == 1, (
        f"expected 1 atom committed, got {result.atoms_committed!r} "
        f"(errors={result.errors!r}, clars={result.clarifications_raised!r})"
    )
    atom_id = result.atoms_committed[0]
    assert atom_id.startswith("a-"), f"unexpected atom id shape: {atom_id!r}"

    # Atom file exists under the canonical substrate path.
    atom_path = substrate.atom_path(source_id, atom_id)
    assert atom_path.is_file(), f"atom file missing at {atom_path}"

    # The atom's PROV record exists and references the atom.
    atom = substrate.get_atom(source_id, atom_id)
    prov = substrate.get_provenance(source_id, atom.provenance_id)
    assert prov.entity_id == atom_id

    # The output file moved under _consumed/.
    assert not out_path.exists(), "original output.yaml should have been moved"
    consumed_path = (
        workspace
        / "dispatch"
        / "outputs"
        / "_consumed"
        / f"extractor-{inputs_hash}"
        / "output.yaml"
    )
    assert consumed_path.is_file(), f"output not moved to _consumed/: {consumed_path}"
    assert len(result.outputs_consumed) == 1
    assert result.outputs_consumed[0] == consumed_path

    # No clarifications, no errors.
    assert result.clarifications_raised == []
    assert result.errors == []


# --- 2. Closed-vocabulary violation raises clarification, no commit ----


def test_reconcile_invalid_atom_raises_clarification(tmp_path: Path) -> None:
    """Unknown predicate ⇒ no atom committed; one clarification raised."""
    workspace = _make_workspace(tmp_path)
    source_id = "reconcile-src-bad-vocab"
    substrate = _plant_distillation(workspace, source_id)

    inputs_hash = "i" * 64
    bad_atom = _valid_atom_payload(source_id)
    bad_atom["predicate"] = "totally_unknown_predicate"  # not in vocabulary
    _plant_extractor_output(
        workspace,
        inputs_hash,
        {"proposed_atoms": [bad_atom]},
    )

    result = reconcile_outputs(substrate=substrate, workspace_root=workspace)

    assert result.atoms_committed == [], (
        f"invalid atom should NOT commit; got {result.atoms_committed!r}"
    )
    assert len(result.clarifications_raised) == 1, (
        f"expected 1 clarification, got {result.clarifications_raised!r} (errors={result.errors!r})"
    )

    # The clarification names the failing validator in its question text.
    clar_id = result.clarifications_raised[0]
    clar_path = substrate.clarification_path(source_id, clar_id, resolved=False)
    assert clar_path.is_file(), f"clarification not written at {clar_path}"
    clar_body = clar_path.read_text(encoding="utf-8")
    # The clarification's question mentions the failing validator name.
    assert "closed_vocabulary" in clar_body, (
        f"clarification body should reference the failing validator; got {clar_body!r}"
    )

    # The output file was still moved to _consumed/ — reconcile is
    # idempotent regardless of whether atoms were admitted.
    consumed_path = (
        workspace
        / "dispatch"
        / "outputs"
        / "_consumed"
        / f"extractor-{inputs_hash}"
        / "output.yaml"
    )
    assert consumed_path.is_file()


# --- 3. Idempotency: a second run does nothing -------------------------


def test_reconcile_idempotent(tmp_path: Path) -> None:
    """Two back-to-back reconcile runs: second one sees an empty queue."""
    workspace = _make_workspace(tmp_path)
    source_id = "reconcile-src-idem"
    substrate = _plant_distillation(workspace, source_id)

    inputs_hash = "j" * 64
    _plant_extractor_output(
        workspace,
        inputs_hash,
        {"proposed_atoms": [_valid_atom_payload(source_id)]},
    )

    first = reconcile_outputs(substrate=substrate, workspace_root=workspace)
    assert len(first.atoms_committed) == 1
    assert len(first.outputs_consumed) == 1

    second = reconcile_outputs(substrate=substrate, workspace_root=workspace)
    assert second.atoms_committed == []
    assert second.relations_committed == []
    assert second.clarifications_raised == []
    assert second.outputs_consumed == []
    assert second.errors == []


# --- 4. CLI smoke ------------------------------------------------------


def test_reconcile_cli_help_exits_zero(tmp_path: Path) -> None:
    """``amanuensis reconcile --help`` succeeds and lists the --workspace flag."""
    from typer.testing import CliRunner

    from amanuensis.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["reconcile", "--help"])
    assert result.exit_code == 0, (
        f"reconcile --help failed (exit={result.exit_code})\nstdout: {result.stdout}"
    )
    assert "--workspace" in result.stdout


def test_reconcile_cli_empty_workspace_exits_zero(tmp_path: Path) -> None:
    """``amanuensis reconcile`` on a fresh workspace with no outputs exits 0."""
    from typer.testing import CliRunner

    from amanuensis.cli import app

    workspace = _make_workspace(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["reconcile", "--workspace", str(workspace)])
    assert result.exit_code == 0, (
        f"reconcile failed (exit={result.exit_code})\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    assert "atoms_committed=0" in result.stdout
    assert "outputs_consumed=0" in result.stdout
