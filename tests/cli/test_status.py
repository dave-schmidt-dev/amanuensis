"""``amanuensis status`` — workspace summary (human + JSON)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.fs import Substrate
from amanuensis.schemas import Atom, ProvenanceRecord
from tests.cli.conftest import SOURCE_ID

runner = CliRunner()


def test_status_empty_workspace(cli_workspace: Path) -> None:
    """Fresh workspace: status reports 0 distillations cleanly."""
    result = runner.invoke(app, ["status", "--workspace", str(cli_workspace)])
    assert result.exit_code == 0, (
        f"status failed (exit={result.exit_code})\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "distillations:" in result.stdout
    assert "0" in result.stdout


def test_status_json_output_parses(cli_workspace: Path) -> None:
    """``--json`` emits a JSON document with the expected shape."""
    result = runner.invoke(app, ["status", "--json", "--workspace", str(cli_workspace)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["distillation_count"] == 0
    assert payload["distillations"] == []
    assert "workspace_root" in payload


def test_status_with_planted_atom_reports_count(
    cli_workspace: Path,
    cli_substrate: Substrate,
    planted_atom: tuple[Atom, ProvenanceRecord],
) -> None:
    """A distillation with one atom shows up in the per-distillation counts."""
    _ = planted_atom  # fixture side-effect plants the atom
    result = runner.invoke(app, ["status", "--workspace", str(cli_workspace)])
    assert result.exit_code == 0
    assert SOURCE_ID in result.stdout
    assert "atoms:" in result.stdout
    # JSON shape sanity.
    json_result = runner.invoke(app, ["status", "--json", "--workspace", str(cli_workspace)])
    payload = json.loads(json_result.stdout)
    assert payload["distillation_count"] == 1
    [summary] = payload["distillations"]
    assert summary["source_id"] == SOURCE_ID
    assert summary["atoms"] == 1
