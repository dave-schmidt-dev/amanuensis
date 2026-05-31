"""Tests for the ``amanuensis map`` Typer sub-app."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
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


# ---------------------------------------------------------------------------
# T7.2: map orchestrator tests
# ---------------------------------------------------------------------------


def test_map_on_empty_workspace_exits_clean(tmp_path: Path) -> None:
    workspace = _make_workspace(tmp_path)
    res = runner.invoke(app, ["map", "--workspace", str(workspace), "--non-interactive"])
    assert res.exit_code == 0
    assert "no distillations" in res.stdout.lower()


def test_map_populated_workspace_pins_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _make_workspace(tmp_path)
    # Plant a minimal distillation
    (workspace / "distillations" / "src1" / "atoms").mkdir(parents=True)
    (workspace / "distillations" / "src1" / "relations").mkdir(parents=True)
    # Install skills into the fake harness home.
    fake_home = tmp_path / "fake_home"
    skills_dir = fake_home / ".claude" / "skills" / "amanuensis"
    skills_dir.mkdir(parents=True)
    (skills_dir / "map_resolve.md").write_text("---\nrole: map-resolve\n---\nbody")
    (skills_dir / "map_audit.md").write_text("---\nrole: map-audit\n---\nbody")
    monkeypatch.setenv("AMANUENSIS_HARNESS_HOME", str(fake_home))
    res = runner.invoke(app, ["map", "--workspace", str(workspace), "--non-interactive"])
    assert res.exit_code == 0, f"stdout={res.stdout!r} stderr={res.stderr!r}"
    snapshot = workspace / "mappings" / "entity-vocabulary-snapshot.yaml"
    assert snapshot.is_file(), f"snapshot not pinned at {snapshot}"
    queue_files = list((workspace / "dispatch" / "queue").glob("map-resolve-*.yaml"))
    assert len(queue_files) == 1, f"expected 1 queue file, got {queue_files!r}"


def test_map_second_run_does_not_repin_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _make_workspace(tmp_path)
    (workspace / "distillations" / "src1" / "atoms").mkdir(parents=True)
    (workspace / "distillations" / "src1" / "relations").mkdir(parents=True)
    # Install skills into the fake harness home.
    fake_home = tmp_path / "fake_home"
    skills_dir = fake_home / ".claude" / "skills" / "amanuensis"
    skills_dir.mkdir(parents=True)
    (skills_dir / "map_resolve.md").write_text("---\nrole: map-resolve\n---\nbody")
    (skills_dir / "map_audit.md").write_text("---\nrole: map-audit\n---\nbody")
    monkeypatch.setenv("AMANUENSIS_HARNESS_HOME", str(fake_home))
    res1 = runner.invoke(app, ["map", "--workspace", str(workspace), "--non-interactive"])
    assert res1.exit_code == 0
    snapshot = workspace / "mappings" / "entity-vocabulary-snapshot.yaml"
    bytes1 = snapshot.read_bytes()
    # Re-run; snapshot should be untouched (idempotent).
    res2 = runner.invoke(app, ["map", "--workspace", str(workspace), "--non-interactive"])
    assert res2.exit_code == 0
    bytes2 = snapshot.read_bytes()
    assert bytes1 == bytes2


# ---------------------------------------------------------------------------
# T7.3: skill preflight tests (PM-11)
# ---------------------------------------------------------------------------


def test_map_missing_skills_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _make_workspace(tmp_path)
    # Plant a distillation so we get past the empty-workspace branch.
    (workspace / "distillations" / "src1" / "atoms").mkdir(parents=True)
    # Point harness home at an empty tmp dir — no skills installed.
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("AMANUENSIS_HARNESS_HOME", str(fake_home))
    res = runner.invoke(app, ["map", "--workspace", str(workspace), "--non-interactive"])
    assert res.exit_code == 2
    assert "map-resolve/map-audit skills not installed" in (res.stdout + res.stderr).lower() or (
        "map-resolve" in (res.stdout + res.stderr).lower()
    )


def test_map_present_skills_proceed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = _make_workspace(tmp_path)
    (workspace / "distillations" / "src1" / "atoms").mkdir(parents=True)
    (workspace / "distillations" / "src1" / "relations").mkdir(parents=True)
    # Install skills into the fake harness home.
    fake_home = tmp_path / "fake_home"
    skills_dir = fake_home / ".claude" / "skills" / "amanuensis"
    skills_dir.mkdir(parents=True)
    (skills_dir / "map_resolve.md").write_text("---\nrole: map-resolve\n---\nbody")
    (skills_dir / "map_audit.md").write_text("---\nrole: map-audit\n---\nbody")
    monkeypatch.setenv("AMANUENSIS_HARNESS_HOME", str(fake_home))
    res = runner.invoke(app, ["map", "--workspace", str(workspace), "--non-interactive"])
    assert res.exit_code == 0, f"stdout={res.stdout!r} stderr={res.stderr!r}"
