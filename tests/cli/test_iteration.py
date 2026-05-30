"""``amanuensis iteration`` CLI tests — list + add."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.fs import Substrate
from amanuensis.fs._serialize import parse_iteration_md

from .conftest import SOURCE_ID

runner = CliRunner()


def test_iteration_list_empty(cli_workspace: Path) -> None:
    """Empty substrate emits '# no iterations'."""
    result = runner.invoke(app, ["iteration", "list", "--workspace", str(cli_workspace)])
    assert result.exit_code == 0
    assert "no iterations" in result.stdout


def test_iteration_add_writes_directive_and_prov(
    cli_workspace: Path, cli_substrate: Substrate, planted_atom: object
) -> None:
    """Adding a directive writes the iteration file + paired issued PROV."""
    # planted_atom ensures the SOURCE_ID distillation exists (so the PROV
    # record's directory parent is ready). The iteration add CLI files
    # PROV under the target source's distillation per the source convention.
    _ = planted_atom

    result = runner.invoke(
        app,
        [
            "iteration",
            "add",
            "--directive",
            "Re-extract atoms with stricter scale-anchor discipline.",
            "--target-source",
            SOURCE_ID,
            "--rationale",
            "Auditor flagged section-anchored atoms as paragraph-anchored.",
            "--target-phase",
            "distill",
            "--workspace",
            str(cli_workspace),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "issued iteration" in result.stdout

    # One file in iterations/ — confirms write happened.
    iters_dir = cli_substrate.root / "iterations"
    assert iters_dir.is_dir()
    written = [p for p in iters_dir.iterdir() if p.suffix == ".md" and ".tmp." not in p.name]
    assert len(written) == 1
    iter_obj = parse_iteration_md(written[0].read_text(encoding="utf-8"))
    assert iter_obj.target_phase == "distill"
    assert iter_obj.target_artifacts == [SOURCE_ID]
    assert "Re-extract atoms" in iter_obj.directive
    # Issued PROV record exists at the canonical path under the target source.
    assert cli_substrate.provenance_path(SOURCE_ID, iter_obj.issued_provenance_id).is_file()


def test_iteration_list_shows_added(cli_workspace: Path, planted_atom: object) -> None:
    """After adding, `iteration list` finds the directive."""
    _ = planted_atom
    runner.invoke(
        app,
        [
            "iteration",
            "add",
            "--directive",
            "Tighten clarifications on contested warrants.",
            "--target-source",
            SOURCE_ID,
            "--workspace",
            str(cli_workspace),
        ],
    )
    result = runner.invoke(app, ["iteration", "list", "--workspace", str(cli_workspace)])
    assert result.exit_code == 0
    assert "Tighten clarifications" in result.stdout
    assert SOURCE_ID in result.stdout


def test_iteration_add_rejects_unknown_target_phase(
    cli_workspace: Path, planted_atom: object
) -> None:
    """Unknown --target-phase fails clearly without writing anything."""
    _ = planted_atom
    result = runner.invoke(
        app,
        [
            "iteration",
            "add",
            "--directive",
            "x",
            "--target-source",
            SOURCE_ID,
            "--target-phase",
            "bogus",
            "--workspace",
            str(cli_workspace),
        ],
    )
    assert result.exit_code != 0
