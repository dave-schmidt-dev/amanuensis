"""``amanuensis atom <subcommand>`` — list / show / validate."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.fs import Substrate
from amanuensis.schemas import Atom, ProvenanceRecord
from tests.cli.conftest import SOURCE_ID

runner = CliRunner()


def test_atom_list_shows_planted_atom(
    cli_workspace: Path,
    cli_substrate: Substrate,
    planted_atom: tuple[Atom, ProvenanceRecord],
) -> None:
    atom, _ = planted_atom
    result = runner.invoke(
        app,
        ["atom", "list", SOURCE_ID, "--workspace", str(cli_workspace)],
    )
    assert result.exit_code == 0, (
        f"atom list failed (exit={result.exit_code})\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert atom.id in result.stdout
    assert "1 atom" in result.stdout


def test_atom_list_filters_by_scale(
    cli_workspace: Path,
    cli_substrate: Substrate,
    planted_atom: tuple[Atom, ProvenanceRecord],
) -> None:
    """Scale filter: planted atom has scale=paragraph; filtering on `section` hides it."""
    _ = planted_atom
    result = runner.invoke(
        app,
        ["atom", "list", SOURCE_ID, "--scale", "section", "--workspace", str(cli_workspace)],
    )
    assert result.exit_code == 0
    assert "0 atom" in result.stdout


def test_atom_show_prints_frontmatter_and_body(
    cli_workspace: Path,
    cli_substrate: Substrate,
    planted_atom: tuple[Atom, ProvenanceRecord],
) -> None:
    atom, _ = planted_atom
    result = runner.invoke(
        app,
        ["atom", "show", SOURCE_ID, atom.id, "--workspace", str(cli_workspace)],
    )
    assert result.exit_code == 0
    assert "predicate: asserts_obligation" in result.stdout
    assert "ACME shall pay" in result.stdout


def test_atom_show_missing_id_fails(
    cli_workspace: Path,
    cli_substrate: Substrate,
    planted_atom: tuple[Atom, ProvenanceRecord],
) -> None:
    """Asking for an unknown atom id exits non-zero."""
    _ = planted_atom
    result = runner.invoke(
        app,
        ["atom", "show", SOURCE_ID, "a-nonexistent", "--workspace", str(cli_workspace)],
    )
    assert result.exit_code != 0
    assert "not found" in result.stderr


def test_atom_validate_default_runs_all(
    cli_workspace: Path,
    cli_substrate: Substrate,
    planted_atom: tuple[Atom, ProvenanceRecord],
) -> None:
    """Without ``--validator`` every canonical validator runs against the atom."""
    _ = planted_atom
    result = runner.invoke(
        app,
        ["atom", "validate", SOURCE_ID, "--workspace", str(cli_workspace)],
    )
    assert result.exit_code == 0, (
        f"atom validate failed (exit={result.exit_code})\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # Every named validator should appear in the per-validator counts.
    for name in (
        "schema_check",
        "citation_ledger",
        "universe_check",
        "scale_anchor",
        "closed_vocabulary",
        "provenance_completeness",
    ):
        assert name in result.stdout, f"validator {name!r} missing from output"
    assert "atoms scanned: 1" in result.stdout


def test_atom_validate_named_validator_only(
    cli_workspace: Path,
    cli_substrate: Substrate,
    planted_atom: tuple[Atom, ProvenanceRecord],
) -> None:
    """``--validator scale_anchor`` runs only that one validator."""
    _ = planted_atom
    result = runner.invoke(
        app,
        [
            "atom",
            "validate",
            SOURCE_ID,
            "--validator",
            "scale_anchor",
            "--workspace",
            str(cli_workspace),
        ],
    )
    assert result.exit_code == 0
    assert "scale_anchor" in result.stdout
    # Other validators should NOT appear since selection is exclusive.
    assert "citation_ledger" not in result.stdout


def test_atom_validate_unknown_validator_fails(
    cli_workspace: Path,
    cli_substrate: Substrate,
    planted_atom: tuple[Atom, ProvenanceRecord],
) -> None:
    _ = planted_atom
    result = runner.invoke(
        app,
        [
            "atom",
            "validate",
            SOURCE_ID,
            "--validator",
            "not_a_validator",
            "--workspace",
            str(cli_workspace),
        ],
    )
    assert result.exit_code != 0
    assert "unknown validator" in result.stderr
