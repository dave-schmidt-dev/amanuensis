"""``amanuensis install-skills`` CLI tests — copy + idempotence + dry-run (M7.6)."""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

import pytest
from typer.testing import CliRunner

from amanuensis.cli import app

runner = CliRunner()

# Sentinel binary path returned by the patched ``shutil.which`` for harnesses
# the test wants to claim are "installed". The value is opaque — install logic
# only checks for truthiness — so an obviously fake path makes the intent
# legible in failure output.
_FAKE_BINARY = "/usr/local/bin/__fake-harness__"

# The eight bundled skill filenames that M7.1+M5 (Phase 2a) ships and that M7.6 installs.
# Kept in sync with ``src/amanuensis/skills/``; if the source-of-truth set
# changes, this list is the canonical place to update tests.
_BUNDLED_SKILLS = {
    "distill.md",
    "distill_audit.md",
    "distill_constructive.md",
    "distill_contrarian.md",
    "distill_extract.md",
    "distill_premortem.md",
    "map_audit.md",
    "map_resolve.md",
}


def _patch_which(monkeypatch: pytest.MonkeyPatch, *, present: set[str]) -> None:
    """Patch ``shutil.which`` so only binaries in ``present`` resolve.

    The install-skills command resolves harness presence via
    ``shutil.which(binary)``. Tests parameterise which harnesses to
    claim are installed without depending on the developer's actual
    PATH. The stub returns ``None`` for every name not in ``present``
    (including names install-skills never asks about) — the real
    ``shutil.which`` is intentionally not delegated to, so tests stay
    PATH-independent.
    """

    def _fake_which(name: str, *args: object, **kwargs: object) -> str | None:
        # The CLI only ever calls shutil.which with the four harness
        # binary names; *args/**kwargs are declared for signature
        # compatibility but never exercised in this codepath.
        del args, kwargs
        if name in present:
            return _FAKE_BINARY
        return None

    monkeypatch.setattr(shutil, "which", _fake_which)


def _install_dir_for(home: Path, harness_suffix: str) -> Path:
    """Compute the ``<home>/<suffix>/amanuensis`` install dir."""
    return home / harness_suffix / "amanuensis"


# --- Detection-level smoke tests (preserved from M4.3, adapted to --harness-target) ---


def test_install_skills_all_runs_to_completion(
    cli_workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`install-skills --harness all` exits 0 and emits a status line per harness."""
    # No harnesses "detected" in this run; we only assert each gets a line.
    _patch_which(monkeypatch, present=set())
    tmp_home = tmp_path / "harness-home"
    result = runner.invoke(
        app,
        [
            "install-skills",
            "--harness",
            "all",
            "--workspace",
            str(cli_workspace),
            "--harness-target",
            str(tmp_home),
        ],
    )
    assert result.exit_code == 0, result.stdout
    for harness in ("claude", "codex", "cursor", "gemini"):
        assert harness in result.stdout, f"expected mention of {harness} in:\n{result.stdout}"
    assert "install-skills" in result.stdout


def test_install_skills_is_idempotent(
    cli_workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running yields identical exit code and output when no harnesses install."""
    _patch_which(monkeypatch, present=set())
    tmp_home = tmp_path / "harness-home"
    args = [
        "install-skills",
        "--harness",
        "all",
        "--workspace",
        str(cli_workspace),
        "--harness-target",
        str(tmp_home),
    ]
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


# --- M7.6: actual file installation behaviour --------------------------


def test_install_skills_copies_all_bundled_skills_for_detected_harness(
    cli_workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A detected harness gets every bundled skill copied into <home>/.claude/skills/amanuensis."""
    _patch_which(monkeypatch, present={"claude"})
    tmp_home = tmp_path / "harness-home"
    result = runner.invoke(
        app,
        [
            "install-skills",
            "--harness",
            "all",
            "--workspace",
            str(cli_workspace),
            "--harness-target",
            str(tmp_home),
        ],
    )
    assert result.exit_code == 0, result.stdout

    install_dir = _install_dir_for(tmp_home, ".claude/skills")
    assert install_dir.is_dir(), f"expected {install_dir} to exist; stdout:\n{result.stdout}"

    installed = {p.name for p in install_dir.iterdir() if p.is_file()}
    assert installed == _BUNDLED_SKILLS, f"expected {_BUNDLED_SKILLS}, got {installed}"

    # Each copied file must be byte-identical to the bundled source.
    skills_root = resources.files("amanuensis.skills")
    for name in _BUNDLED_SKILLS:
        src = skills_root / name
        dst_bytes = (install_dir / name).read_bytes()
        assert dst_bytes == src.read_bytes(), f"content mismatch for {name}"

    # Undetected harnesses must NOT receive an install dir.
    for suffix in (".codex/skills", ".cursor/skills", ".gemini/skills"):
        assert not _install_dir_for(tmp_home, suffix).exists(), (
            f"undetected harness {suffix} should not have an install dir"
        )


def test_install_skills_is_idempotent_when_content_matches(
    cli_workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running install-skills does not touch destination files whose bytes already match."""
    _patch_which(monkeypatch, present={"claude"})
    tmp_home = tmp_path / "harness-home"
    args = [
        "install-skills",
        "--harness",
        "claude",
        "--workspace",
        str(cli_workspace),
        "--harness-target",
        str(tmp_home),
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.stdout

    install_dir = _install_dir_for(tmp_home, ".claude/skills")
    # Snapshot mtimes after the first install.
    first_mtimes = {p.name: p.stat().st_mtime_ns for p in install_dir.iterdir()}
    assert set(first_mtimes) == _BUNDLED_SKILLS

    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.stdout

    second_mtimes = {p.name: p.stat().st_mtime_ns for p in install_dir.iterdir()}
    # No file should have been rewritten — mtimes must be unchanged.
    assert first_mtimes == second_mtimes, (
        "expected idempotent no-op; some destination file was rewritten"
    )

    # The second run should still report what it considered (debuggable trace).
    assert "installed:" in second.stdout


def test_install_skills_overwrites_on_content_drift(
    cli_workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a destination file diverges from the bundled source, re-install rewrites it."""
    _patch_which(monkeypatch, present={"claude"})
    tmp_home = tmp_path / "harness-home"
    args = [
        "install-skills",
        "--harness",
        "claude",
        "--workspace",
        str(cli_workspace),
        "--harness-target",
        str(tmp_home),
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.stdout

    install_dir = _install_dir_for(tmp_home, ".claude/skills")
    target = install_dir / "distill.md"
    drifted = b"# tampered content - should be overwritten\n"
    target.write_bytes(drifted)
    assert target.read_bytes() == drifted

    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.stdout

    skills_root = resources.files("amanuensis.skills")
    expected = (skills_root / "distill.md").read_bytes()
    assert target.read_bytes() == expected, (
        "expected drifted destination to be overwritten with bundled source"
    )


def test_install_skills_dry_run_writes_nothing(
    cli_workspace: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--dry-run` previews actions but never creates the install directory."""
    _patch_which(monkeypatch, present={"claude"})
    tmp_home = tmp_path / "harness-home"
    result = runner.invoke(
        app,
        [
            "install-skills",
            "--harness",
            "claude",
            "--workspace",
            str(cli_workspace),
            "--harness-target",
            str(tmp_home),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.stdout

    # No install dir should exist for any harness, detected or not.
    for suffix in (".claude/skills", ".codex/skills", ".cursor/skills", ".gemini/skills"):
        assert not _install_dir_for(tmp_home, suffix).exists(), f"dry-run must not create {suffix}"
    # Output must signal the dry-run mode.
    assert "dry-run" in result.stdout
    assert "would install" in result.stdout


def test_install_skills_help_hides_harness_target(
    cli_workspace: Path,
) -> None:
    """``--help`` advertises ``--dry-run`` but hides the test seam ``--harness-target``."""
    from click import unstyle

    result = runner.invoke(app, ["install-skills", "--help"])
    assert result.exit_code == 0, result.stdout
    # Strip ANSI: Rich styles each character span separately under FORCE_COLOR
    # (set by GitHub Actions), which would break a naive substring check.
    plain = unstyle(result.stdout)
    assert "--dry-run" in plain
    assert "--harness-target" not in plain
