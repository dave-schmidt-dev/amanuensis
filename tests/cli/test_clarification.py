"""``amanuensis clarification`` CLI tests — list + resolve."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.fs import Substrate
from amanuensis.fs._serialize import parse_clarification_md
from amanuensis.schemas import Clarification

from .conftest import SOURCE_ID

runner = CliRunner()


def test_clarification_list_with_no_clarifications(cli_workspace: Path) -> None:
    """Empty substrate emits the '# no clarifications' marker, exit 0."""
    result = runner.invoke(app, ["clarification", "list", "--workspace", str(cli_workspace)])
    assert result.exit_code == 0
    assert "no clarifications" in result.stdout


def test_clarification_list_shows_planted(
    cli_workspace: Path, planted_clarification: Clarification
) -> None:
    """A planted open clarification appears in the list output."""
    result = runner.invoke(app, ["clarification", "list", "--workspace", str(cli_workspace)])
    assert result.exit_code == 0
    assert planted_clarification.id in result.stdout
    assert "open" in result.stdout
    assert SOURCE_ID in result.stdout


def test_clarification_list_filter_by_status(
    cli_workspace: Path, planted_clarification: Clarification
) -> None:
    """--status resolved hides an open clarification."""
    result = runner.invoke(
        app,
        ["clarification", "list", "--status", "resolved", "--workspace", str(cli_workspace)],
    )
    assert result.exit_code == 0
    # Planted is open; resolved filter yields no rows.
    assert planted_clarification.id not in result.stdout
    assert "no clarifications" in result.stdout


def test_clarification_resolve_flips_status_and_writes_prov(
    cli_workspace: Path,
    cli_substrate: Substrate,
    planted_clarification: Clarification,
) -> None:
    """Resolve moves the file open/ -> resolved/ and writes the paired PROV."""
    open_path = cli_substrate.clarification_path(
        SOURCE_ID, planted_clarification.id, resolved=False
    )
    assert open_path.is_file()

    result = runner.invoke(
        app,
        [
            "clarification",
            "resolve",
            planted_clarification.id,
            "--resolution",
            "ACME is the parent.",
            "--workspace",
            str(cli_workspace),
        ],
    )
    assert result.exit_code == 0, result.stdout

    # Open variant is gone; resolved variant is canonical now.
    assert not open_path.is_file()
    resolved_path = cli_substrate.clarification_path(
        SOURCE_ID, planted_clarification.id, resolved=True
    )
    assert resolved_path.is_file()
    resolved_clar = parse_clarification_md(resolved_path.read_text(encoding="utf-8"))
    assert resolved_clar.status == "resolved"
    assert resolved_clar.resolution == "ACME is the parent."
    assert resolved_clar.resolved_provenance_id is not None
    # The resolved PROV file exists at the canonical path.
    prov_path = cli_substrate.provenance_path(SOURCE_ID, resolved_clar.resolved_provenance_id)
    assert prov_path.is_file()


def test_clarification_resolve_unknown_id_fails(cli_workspace: Path) -> None:
    """Resolving a non-existent clarification fails with a clear error."""
    result = runner.invoke(
        app,
        [
            "clarification",
            "resolve",
            "c-deadbeefdeadbeef",
            "--resolution",
            "n/a",
            "--workspace",
            str(cli_workspace),
        ],
    )
    assert result.exit_code != 0
