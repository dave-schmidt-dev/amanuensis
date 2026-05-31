"""Tests for the ``amanuensis map`` Typer sub-app."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from amanuensis.cli import app

runner = CliRunner()


def test_map_help_lists_all_verbs() -> None:
    res = runner.invoke(app, ["map", "--help"])
    assert res.exit_code == 0
    for verb in ("status", "entity", "resolution", "vocabulary"):
        assert verb in res.stdout


def test_map_entity_help_lists_verbs() -> None:
    res = runner.invoke(app, ["map", "entity", "--help"])
    assert res.exit_code == 0
    for verb in ("list", "show", "merge"):
        assert verb in res.stdout


def test_map_resolution_help_lists_verbs() -> None:
    res = runner.invoke(app, ["map", "resolution", "--help"])
    assert res.exit_code == 0
    for verb in ("show", "supersede"):
        assert verb in res.stdout


def test_map_vocabulary_help_lists_verbs() -> None:
    res = runner.invoke(app, ["map", "vocabulary", "--help"])
    assert res.exit_code == 0
    for verb in ("show", "snapshot"):
        assert verb in res.stdout


# ---------------------------------------------------------------------------
# T7.4: map status tests
# ---------------------------------------------------------------------------


def _make_workspace(tmp_path: Path) -> Path:
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text("schema_version: 1\nproject_name: map-test\n")
    return tmp_path


def test_map_status_empty_workspace(tmp_path: Path) -> None:
    """Status on an empty workspace prints all zero counts and 'never'."""
    workspace = _make_workspace(tmp_path)
    res = runner.invoke(app, ["map", "status", "--workspace", str(workspace)])
    assert res.exit_code == 0
    # Default human-readable form; just check the keys appear.
    for key in (
        "entity_operand_count",
        "resolved_count",
        "unresolved_count",
        "open_clarification_count",
        "last_map_run_at",
    ):
        assert key in res.stdout
    assert "never" in res.stdout


def test_map_status_json_output(tmp_path: Path) -> None:
    """--json emits sorted-key JSON parseable to a dict with the five keys."""
    workspace = _make_workspace(tmp_path)
    res = runner.invoke(app, ["map", "status", "--workspace", str(workspace), "--json"])
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["workspace_aggregate"]["entity_operand_count"] == 0
    assert payload["workspace_aggregate"]["resolved_count"] == 0
    assert payload["workspace_aggregate"]["unresolved_count"] == 0
    assert payload["workspace_aggregate"]["open_clarification_count"] == 0
    assert payload["workspace_aggregate"]["last_map_run_at"] == "never"


def test_map_status_unknown_source_id_exits_1(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    res = runner.invoke(
        app,
        ["map", "status", "--workspace", str(workspace), "--source-id", "nonexistent"],
    )
    assert res.exit_code == 1
    assert "no source-id" in res.stdout.lower() or "no source-id" in res.stderr.lower()
