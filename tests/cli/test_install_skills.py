"""``amanuensis install-skills`` CLI tests — stub-level detection (M4.3)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from amanuensis.cli import app

runner = CliRunner()


def test_install_skills_all_runs_to_completion(cli_workspace: Path) -> None:
    """`install-skills --harness all` exits 0 and emits a status line per harness."""
    result = runner.invoke(
        app,
        ["install-skills", "--harness", "all", "--workspace", str(cli_workspace)],
    )
    assert result.exit_code == 0, result.stdout
    # The four supported harnesses must each get a status line (detected
    # or not). Match the prefixes the CLI emits in its detection loop.
    for harness in ("claude", "codex", "cursor", "gemini"):
        assert harness in result.stdout, f"expected mention of {harness} in:\n{result.stdout}"
    # The header is also present.
    assert "install-skills" in result.stdout


def test_install_skills_specific_harness_runs(cli_workspace: Path) -> None:
    """Targeting one harness only emits its line."""
    result = runner.invoke(
        app,
        ["install-skills", "--harness", "claude", "--workspace", str(cli_workspace)],
    )
    assert result.exit_code == 0, result.stdout
    assert "claude" in result.stdout
    # Other harnesses NOT mentioned in their detection-row form (the
    # "codex" / "gemini" strings can appear in the workspace path, so
    # check the per-row format the CLI emits: "<harness>:" with padding).
    # The stub's loop emits at most one row when a single harness is
    # selected, so the simpler check is that we see only one
    # "detected:"/"not found:" prefix.
    detect_lines = [
        line
        for line in result.stdout.splitlines()
        if line.startswith("detected:") or line.startswith("not found:")
    ]
    assert len(detect_lines) == 1


def test_install_skills_is_idempotent(cli_workspace: Path) -> None:
    """Re-running yields identical exit code and output (stub is side-effect-free)."""
    args = ["install-skills", "--harness", "all", "--workspace", str(cli_workspace)]
    first = runner.invoke(app, args)
    second = runner.invoke(app, args)
    assert first.exit_code == second.exit_code == 0
    assert first.stdout == second.stdout


def test_install_skills_requires_marker(tmp_path: Path) -> None:
    """No marker => the @require_marker decorator blocks the command."""
    # tmp_path has NO amanuensis.yaml — the marker check should fire.
    result = runner.invoke(
        app,
        ["install-skills", "--workspace", str(tmp_path)],
    )
    assert result.exit_code != 0
