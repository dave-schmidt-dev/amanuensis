"""INV-1 marker enforcement at the CLI surface.

Every marker-protected command must refuse to run without
``amanuensis.yaml`` at the workspace root. The decorator emits a clear
stderr error and exits with code 2 (preflight failure, distinct from
the command body's own non-zero exit codes).

This test parametrizes across every marker-protected command so a
future command added without ``@require_marker`` fails the gate.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from amanuensis.cli import app

runner = CliRunner()

ArgvFactory = Callable[[Path], list[str]]


# Command invocations exercised by the parametric check. Each entry is a
# factory that takes a tmp_path workspace (without marker) and returns
# the argv to pass to ``runner.invoke``. The decorator must refuse.
_FACTORIES: list[ArgvFactory] = [
    lambda ws: ["status", "--workspace", str(ws)],
    lambda ws: ["atom", "list", "any-src", "--workspace", str(ws)],
    lambda ws: ["atom", "show", "any-src", "a-x", "--workspace", str(ws)],
    lambda ws: ["atom", "validate", "any-src", "--workspace", str(ws)],
    lambda ws: ["clarification", "list", "--workspace", str(ws)],
    lambda ws: [
        "clarification",
        "resolve",
        "c-x",
        "--resolution",
        "ok",
        "--workspace",
        str(ws),
    ],
    lambda ws: ["iteration", "list", "--workspace", str(ws)],
    lambda ws: [
        "iteration",
        "add",
        "--directive",
        "do x",
        "--target-source",
        "src",
        "--workspace",
        str(ws),
    ],
    lambda ws: ["vocabulary", "list", "--workspace", str(ws)],
    lambda ws: ["vocabulary", "show", "asserts_obligation", "--workspace", str(ws)],
    lambda ws: ["vocabulary", "snapshot", "src", "--workspace", str(ws)],
    lambda ws: ["install-skills", "--workspace", str(ws)],
]


@pytest.mark.parametrize("argv_factory", _FACTORIES)
def test_marker_protected_command_refuses_without_marker(
    tmp_path: Path, argv_factory: ArgvFactory
) -> None:
    # tmp_path has no marker — the decorator must reject every command.
    assert not (tmp_path / "amanuensis.yaml").exists()
    argv = argv_factory(tmp_path)
    result = runner.invoke(app, argv)
    assert result.exit_code == 2, (
        f"expected exit 2 from marker check; got {result.exit_code}\noutput: {result.output}"
    )
    # Click 8.4 merges stderr into result.output by default (no mix_stderr).
    assert "amanuensis.yaml" in result.output or "marker" in result.output.lower()


def test_status_runs_with_marker_present(tmp_path: Path) -> None:
    """Sanity: with the marker present, ``status`` exits cleanly."""
    (tmp_path / "amanuensis.yaml").write_text(
        "schema_version: 1\nproject_name: marker-test\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["status", "--workspace", str(tmp_path)])
    assert result.exit_code == 0, (
        f"expected exit 0 with marker present; got {result.exit_code}\noutput: {result.output}"
    )
