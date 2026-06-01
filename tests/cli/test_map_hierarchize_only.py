"""``--hierarchize-only`` flag tests for ``amanuensis map`` (Phase 2c M8 / T8.5).

The flag short-circuits the Phase 2a resolve/audit handoff AND the
Phase 2b Connect phase and runs ONLY the Phase 2c Hierarchize phase.
Useful for operator workflows that are iterating on the Hierarchize
role against an already-connected substrate.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.fs import Substrate

runner = CliRunner()


def _make_workspace(tmp_path: Path) -> Path:
    """Bare workspace with the INV-1 marker; no distillations or skills."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text("schema_version: 1\nproject_name: hierarchize-only-test\n")
    return tmp_path


def test_hierarchize_only_skips_other_phases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--hierarchize-only`` skips resolve/audit + Connect entirely.

    Stdout must NOT contain the resolve/audit handoff line, must NOT
    contain the Connect summary, and MUST contain the Hierarchize
    summary line.
    """
    workspace = _make_workspace(tmp_path)
    (workspace / "distillations" / "src-x" / "atoms").mkdir(parents=True)

    # Pin the Walton snapshot so the Hierarchize phase runs.
    sub = Substrate(workspace)
    sub.snapshot_walton_schemes()

    # Empty harness skills dir would normally fail preflight, but
    # --hierarchize-only skips preflight entirely.
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("AMANUENSIS_HARNESS_HOME", str(fake_home))

    res = runner.invoke(
        app,
        ["map", "--workspace", str(workspace), "--hierarchize-only"],
    )
    assert res.exit_code == 0, (
        f"--hierarchize-only should bypass preflight + connect phase; "
        f"got exit_code={res.exit_code} stdout={res.stdout!r} stderr={res.stderr!r}"
    )
    # No resolve/audit handoff was produced.
    assert "Enqueued role: map-resolve-" not in res.stdout
    # No Connect summary.
    assert "Connect phase:" not in res.stdout
    assert "connect:" not in res.stdout
    # Hierarchize summary IS emitted.
    assert "Hierarchize phase:" in res.stdout, (
        f"expected 'Hierarchize phase:' in stdout; got {res.stdout!r}"
    )


def test_hierarchize_only_requires_walton_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a Walton snapshot, ``--hierarchize-only`` is a hard error.

    The operator has explicitly asked for the Hierarchize phase, so a
    missing snapshot is not silently skipped (the default-path
    behavior).
    """
    workspace = _make_workspace(tmp_path)
    (workspace / "distillations" / "src-x" / "atoms").mkdir(parents=True)
    # No snapshot pinned.

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("AMANUENSIS_HARNESS_HOME", str(fake_home))

    res = runner.invoke(
        app,
        ["map", "--workspace", str(workspace), "--hierarchize-only"],
    )
    assert res.exit_code == 2, (
        f"missing walton snapshot under --hierarchize-only should hard-fail; "
        f"got exit_code={res.exit_code} stdout={res.stdout!r} stderr={res.stderr!r}"
    )


def test_hierarchize_only_empty_workspace_short_circuits(tmp_path: Path) -> None:
    """Empty workspace with ``--hierarchize-only`` shows the friendly no-distillations message."""
    workspace = _make_workspace(tmp_path)
    res = runner.invoke(
        app,
        ["map", "--workspace", str(workspace), "--hierarchize-only"],
    )
    assert res.exit_code == 0
    assert "no distillations" in res.stdout.lower()


def test_hierarchize_only_flag_appears_in_help() -> None:
    """``--help`` documents the new flag."""
    res = runner.invoke(app, ["map", "--help"])
    assert res.exit_code == 0
    assert "--hierarchize-only" in res.stdout
