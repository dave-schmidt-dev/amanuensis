"""``amanuensis dispatch`` CLI tests (M6.5).

Two contracts:

1. ``dispatch --check`` emits JSON with the four known harness keys and
   exits 0 (when the workspace marker is present).
2. ``dispatch --check`` refuses (exit 2) without the marker, in keeping
   with INV-1 and the marker decorator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.dispatch.driver import KNOWN_HARNESSES

runner = CliRunner()


def test_dispatch_check_emits_json(cli_workspace: Path) -> None:
    """``--check`` prints a JSON object keyed by the four known harnesses."""
    result = runner.invoke(app, ["dispatch", "--check", "--workspace", str(cli_workspace)])
    assert result.exit_code == 0, (
        f"dispatch --check failed (exit={result.exit_code})\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    payload: dict[str, Any] = json.loads(result.stdout)
    assert set(payload.keys()) == set(KNOWN_HARNESSES)
    for harness, value in payload.items():
        assert value is None or isinstance(value, str), (
            f"{harness}: expected null or string, got {type(value).__name__}"
        )


def test_dispatch_check_refuses_without_marker(tmp_path: Path) -> None:
    """No ``amanuensis.yaml`` marker ⇒ exit 2 with a clear error."""
    # Fresh tmpdir without the marker.
    result = runner.invoke(app, ["dispatch", "--check", "--workspace", str(tmp_path)])
    assert result.exit_code == 2, (
        f"expected exit 2 (marker missing), got {result.exit_code}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_dispatch_check_workspace_defaults_to_cwd(cli_workspace: Path, monkeypatch: Any) -> None:
    """No ``--workspace`` ⇒ defaults to CWD."""
    monkeypatch.chdir(cli_workspace)
    result = runner.invoke(app, ["dispatch", "--check"])
    assert result.exit_code == 0
    payload: dict[str, Any] = json.loads(result.stdout)
    assert set(payload.keys()) == set(KNOWN_HARNESSES)


def test_dispatch_drain_empty_queue_exits_zero(cli_workspace: Path) -> None:
    """Empty queue + ``--once`` ⇒ exit 0 with a 0-processed report."""
    result = runner.invoke(app, ["dispatch", "--once", "--workspace", str(cli_workspace)])
    assert result.exit_code == 0
    assert "processed 0" in result.stdout


def test_dispatch_drain_empty_queue_without_once(cli_workspace: Path) -> None:
    """Empty queue, no ``--once`` ⇒ exit 0 (the loop breaks on first empty pull)."""
    result = runner.invoke(app, ["dispatch", "--workspace", str(cli_workspace)])
    assert result.exit_code == 0
    assert "processed 0" in result.stdout
