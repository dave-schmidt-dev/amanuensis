"""Integration tests for the Hierarchize phase wiring in ``amanuensis map``.

The Phase 2c M8 orchestrator runs Hierarchize after Connect. When the
Walton-scheme snapshot is pinned, ``amanuensis map`` emits a
``Hierarchize phase:`` summary line; when the snapshot is absent it
silently skips Hierarchize (the operator hasn't engaged Phase 2c yet).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.fs import Substrate

runner = CliRunner()


def _bare_workspace(tmp_path: Path) -> Path:
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text("schema_version: 1\nproject_name: hierarchize-phase-test\n")
    return tmp_path


def test_map_runs_hierarchize_phase_after_connect_when_snapshot_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With Walton snapshot pinned, ``amanuensis map`` emits the Hierarchize summary."""
    workspace = _bare_workspace(tmp_path)
    (workspace / "distillations" / "src-x" / "atoms").mkdir(parents=True)

    # Pin the Walton snapshot so the orchestrator emits the Hierarchize
    # summary line. (No probanda planted → enqueued=0, but the summary
    # is still emitted in the "no clusters" form.)
    sub = Substrate(workspace)
    sub.snapshot_walton_schemes()

    # Empty harness skills dir would normally fail preflight, so use
    # --connect-only to skip resolve/audit preflight (matches the
    # operator workflow that scopes ``map`` to Connect + Hierarchize).
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("AMANUENSIS_HARNESS_HOME", str(fake_home))

    res = runner.invoke(
        app,
        ["map", "--workspace", str(workspace), "--connect-only"],
    )
    assert res.exit_code == 0, (
        f"unexpected exit_code={res.exit_code}; stdout={res.stdout!r} stderr={res.stderr!r}"
    )
    # The Hierarchize summary line is emitted.
    assert "Hierarchize phase:" in res.stdout, (
        f"expected 'Hierarchize phase:' in stdout; got {res.stdout!r}"
    )


def test_map_skips_hierarchize_when_snapshot_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the Walton snapshot, the Hierarchize phase is silently skipped."""
    workspace = _bare_workspace(tmp_path)
    (workspace / "distillations" / "src-x" / "atoms").mkdir(parents=True)
    # No snapshot pinned.

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("AMANUENSIS_HARNESS_HOME", str(fake_home))

    res = runner.invoke(
        app,
        ["map", "--workspace", str(workspace), "--connect-only"],
    )
    assert res.exit_code == 0
    assert "Hierarchize phase:" not in res.stdout, (
        "Hierarchize summary should NOT be emitted when Walton snapshot is missing"
    )


def test_map_emits_connect_then_hierarchize_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Connect summary appears before Hierarchize summary in stdout."""
    workspace = _bare_workspace(tmp_path)
    (workspace / "distillations" / "src-x" / "atoms").mkdir(parents=True)

    sub = Substrate(workspace)
    sub.snapshot_walton_schemes()

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("AMANUENSIS_HARNESS_HOME", str(fake_home))

    res = runner.invoke(
        app,
        ["map", "--workspace", str(workspace), "--connect-only"],
    )
    assert res.exit_code == 0
    out = res.stdout
    connect_idx = max(out.find("connect:"), out.find("Connect phase:"))
    hierarchize_idx = out.find("Hierarchize phase:")
    assert connect_idx >= 0, f"expected connect summary in stdout; got {out!r}"
    assert hierarchize_idx >= 0, f"expected hierarchize summary in stdout; got {out!r}"
    assert connect_idx < hierarchize_idx, (
        "Connect summary must appear before Hierarchize summary in stdout"
    )
