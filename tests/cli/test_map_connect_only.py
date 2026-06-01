"""``--connect-only`` flag tests for ``amanuensis map`` (Phase 2b M6 / T6.5).

The flag short-circuits the Phase 2a resolve/audit handoff and runs ONLY
the Phase 2b Connect phase. Useful for two operator workflows:

1. **Iteration**: the resolve+audit substrate has settled and the
   operator is iterating on the Connector role (re-running it as the
   skill prompt or vocabulary evolves).
2. **No-skill environments**: a system without the map-resolve /
   map-audit skills installed can still run the Connect phase via the
   bundled connect skill resource. ``--connect-only`` skips the
   resolve-skill preflight that would otherwise hard-fail.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from amanuensis.cli import app

runner = CliRunner()


def _make_workspace(tmp_path: Path) -> Path:
    """Bare workspace with the INV-1 marker; no distillations or skills."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text("schema_version: 1\nproject_name: connect-only-test\n")
    return tmp_path


def test_connect_only_skips_resolve_audit_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--connect-only`` proceeds even when resolve/audit skills are missing.

    Without ``--connect-only`` an empty harness skills dir hard-fails at
    the T7.3 preflight with exit code 2. With the flag, the preflight
    is skipped entirely and the Connect phase runs against the (empty)
    substrate to a zero-enqueued no-op.
    """
    workspace = _make_workspace(tmp_path)
    # Plant a distillation so we get past the empty-workspace branch.
    (workspace / "distillations" / "src-x" / "atoms").mkdir(parents=True)
    # Empty harness skills dir → preflight would fail without --connect-only.
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("AMANUENSIS_HARNESS_HOME", str(fake_home))

    res = runner.invoke(
        app,
        ["map", "--workspace", str(workspace), "--connect-only"],
    )
    assert res.exit_code == 0, (
        f"--connect-only should bypass the resolve/audit skill preflight; "
        f"got exit_code={res.exit_code} stderr={res.stderr!r}"
    )
    # No resolve/audit handoff was produced.
    assert "Enqueued role: map-resolve-" not in res.stdout
    # Connect phase summary was emitted.
    assert "connect:" in res.stdout or "Connect phase:" in res.stdout


def test_default_invocation_requires_resolve_audit_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``--connect-only``, missing resolve/audit skills still hard-fails.

    Regression guard for the T7.3 preflight contract: adding the Connect
    phase MUST NOT silently relax the existing skill preflight.
    """
    workspace = _make_workspace(tmp_path)
    (workspace / "distillations" / "src-x" / "atoms").mkdir(parents=True)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("AMANUENSIS_HARNESS_HOME", str(fake_home))

    res = runner.invoke(
        app,
        ["map", "--workspace", str(workspace), "--non-interactive"],
    )
    assert res.exit_code == 2, (
        f"missing skills should still fail without --connect-only; "
        f"got exit_code={res.exit_code} stdout={res.stdout!r}"
    )


def test_connect_only_empty_workspace_short_circuits(tmp_path: Path) -> None:
    """An empty workspace with ``--connect-only`` shows the friendly no-distillations message.

    The empty-workspace branch runs before any phase, so it's hit
    regardless of the ``--connect-only`` flag. Confirms the flag does
    NOT bypass the no-distillations guard.
    """
    workspace = _make_workspace(tmp_path)
    res = runner.invoke(
        app,
        ["map", "--workspace", str(workspace), "--connect-only"],
    )
    assert res.exit_code == 0
    assert "no distillations" in res.stdout.lower()


def test_connect_only_flag_appears_in_help() -> None:
    """``--help`` documents the new flag."""
    res = runner.invoke(app, ["map", "--help"])
    assert res.exit_code == 0
    assert "--connect-only" in res.stdout
