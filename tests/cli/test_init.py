"""``amanuensis init`` — workspace bootstrap.

Verifies the marker, docs/ dir, and .gitignore creation; verifies
idempotency (a second run is a no-op for the marker and doesn't
clobber an existing .gitignore).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.fs import Substrate

runner = CliRunner()


def test_init_creates_marker_docs_and_gitignore(tmp_path: Path) -> None:
    """Fresh init creates the marker, docs/, and .gitignore."""
    target = tmp_path / "fresh-workspace"
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0, (
        f"init failed (exit={result.exit_code})\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # Marker present and parses to the expected shape.
    marker = target / "amanuensis.yaml"
    assert marker.is_file()
    payload = yaml.safe_load(marker.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["project_name"] == "fresh-workspace"
    # docs/ present.
    assert (target / "docs").is_dir()
    # .gitignore present and contains expected entries.
    gitignore_text = (target / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in gitignore_text
    assert ".venv/" in gitignore_text
    # Substrate can now be constructed without tripping INV-1.
    Substrate(target)


def test_init_defaults_to_cwd(tmp_path: Path) -> None:
    """No PATH argument => init operates on tmp_path via cwd."""
    # We can't change cwd in-process portably; pass tmp_path explicitly.
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "amanuensis.yaml").is_file()


def test_init_is_idempotent(tmp_path: Path) -> None:
    """Second init is a no-op for the marker; doesn't clobber .gitignore."""
    target = tmp_path / "ws"
    runner.invoke(app, ["init", str(target)])

    # Hand-edit the marker so we can detect any clobber.
    marker = target / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: ws\nposture: {}\n",
        encoding="utf-8",
    )
    marker_before = marker.read_text(encoding="utf-8")

    # Hand-edit .gitignore similarly.
    gitignore = target / ".gitignore"
    gitignore.write_text("# hand-curated\nfoo.bak\n", encoding="utf-8")
    gitignore_before = gitignore.read_text(encoding="utf-8")

    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0
    assert "already exists" in result.stdout

    # Neither file was rewritten.
    assert marker.read_text(encoding="utf-8") == marker_before
    assert gitignore.read_text(encoding="utf-8") == gitignore_before


def test_init_creates_target_directory_if_missing(tmp_path: Path) -> None:
    """init creates the directory itself if it doesn't yet exist."""
    target = tmp_path / "nested" / "dir" / "ws"
    assert not target.exists()
    result = runner.invoke(app, ["init", str(target)])
    assert result.exit_code == 0
    assert target.is_dir()
    assert (target / "amanuensis.yaml").is_file()
