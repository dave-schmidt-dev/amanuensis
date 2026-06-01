"""CLI tests for ``amanuensis map walton-scheme`` sub-commands (Phase 2c M9 / T9.8).

Two verbs:

- ``walton-scheme show``  — read-only; prints the active snapshot.
- ``walton-scheme snapshot [--extend]`` — pins the bundled generic
  catalogue (idempotent on identical content; mandatory ``--extend``
  to evolve a divergent snapshot).

The fixture ``cli_workspace`` (an empty workspace with the INV-1
marker) is used for the snapshot-creation tests. The extend path
modifies the on-disk snapshot directly so we can trigger the archive
branch on a clean workspace.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from amanuensis.cli.map import map_app
from amanuensis.fs import Substrate

runner = CliRunner()


# ---------------------------------------------------------------------------
# walton-scheme show
# ---------------------------------------------------------------------------


def test_show_renders_snapshot(tmp_workspace_with_walton_snapshot: Path) -> None:
    """``walton-scheme show`` prints the pinned snapshot content."""
    result = runner.invoke(
        map_app,
        ["walton-scheme", "show", "--workspace", str(tmp_workspace_with_walton_snapshot)],
    )
    assert result.exit_code == 0, result.output
    # The bundled catalogue includes argument-from-sign.
    assert "argument-from-sign" in result.stdout
    assert "version" in result.stdout.lower()


def test_show_returns_error_when_no_snapshot(cli_workspace: Path) -> None:
    """``walton-scheme show`` on a workspace with no snapshot exits non-zero."""
    result = runner.invoke(
        map_app,
        ["walton-scheme", "show", "--workspace", str(cli_workspace)],
    )
    assert result.exit_code != 0
    haystack = (result.stdout or "") + (result.stderr or "")
    assert "not found" in haystack.lower() or "snapshot" in haystack.lower()


# ---------------------------------------------------------------------------
# walton-scheme snapshot
# ---------------------------------------------------------------------------


def test_snapshot_creates_pin(cli_workspace: Path) -> None:
    """A fresh workspace pins the bundled generic catalogue."""
    result = runner.invoke(
        map_app,
        ["walton-scheme", "snapshot", "--workspace", str(cli_workspace)],
    )
    assert result.exit_code == 0, result.output
    snapshot_path = Substrate(cli_workspace).walton_scheme_snapshot_path()
    assert snapshot_path.is_file()
    body = snapshot_path.read_text(encoding="utf-8")
    assert "argument-from-sign" in body


def test_snapshot_idempotent_on_identical_content(cli_workspace: Path) -> None:
    """A second snapshot with identical content is a no-op (still exits 0)."""
    first = runner.invoke(
        map_app,
        ["walton-scheme", "snapshot", "--workspace", str(cli_workspace)],
    )
    assert first.exit_code == 0, first.output
    second = runner.invoke(
        map_app,
        ["walton-scheme", "snapshot", "--workspace", str(cli_workspace)],
    )
    assert second.exit_code == 0, second.output


def test_snapshot_extend_archives_prior(cli_workspace: Path) -> None:
    """``--extend`` archives the prior snapshot and writes the new one."""
    # Step 1: pin the bundle.
    pin = runner.invoke(
        map_app,
        ["walton-scheme", "snapshot", "--workspace", str(cli_workspace)],
    )
    assert pin.exit_code == 0, pin.output

    # Step 2: tamper with the on-disk snapshot so it diverges from the
    # bundled catalogue. The next ``snapshot --extend`` must archive
    # this tampered version and write the bundle as the new active.
    sub = Substrate(cli_workspace)
    snapshot_path = sub.walton_scheme_snapshot_path()
    original_bundle_bytes = snapshot_path.read_bytes()
    tampered = (
        "version: 1\n"
        "schemes:\n"
        "  - name: argument-from-sign\n"
        "    description: Tampered for the extend-archive test.\n"
    )
    snapshot_path.write_text(tampered, encoding="utf-8")

    # Step 3: ``snapshot --extend`` should succeed.
    result = runner.invoke(
        map_app,
        ["walton-scheme", "snapshot", "--extend", "--workspace", str(cli_workspace)],
    )
    assert result.exit_code == 0, result.output

    # The active snapshot now matches the bundled catalogue again.
    assert snapshot_path.read_bytes() == original_bundle_bytes
    # An archive directory was created with the prior (tampered) bytes.
    archive_dir = cli_workspace / "mappings" / "walton-scheme-archive"
    assert archive_dir.is_dir()
    archived_files = list(archive_dir.glob("*.yaml"))
    assert len(archived_files) == 1
    assert archived_files[0].read_text(encoding="utf-8") == tampered


def test_snapshot_rejects_divergent_without_extend(cli_workspace: Path) -> None:
    """A divergent on-disk snapshot without ``--extend`` exits non-zero."""
    pin = runner.invoke(
        map_app,
        ["walton-scheme", "snapshot", "--workspace", str(cli_workspace)],
    )
    assert pin.exit_code == 0, pin.output
    # Tamper.
    snapshot_path = Substrate(cli_workspace).walton_scheme_snapshot_path()
    snapshot_path.write_text(
        "version: 1\nschemes:\n  - name: argument-from-sign\n    description: tampered\n",
        encoding="utf-8",
    )
    # Re-run without --extend.
    result = runner.invoke(
        map_app,
        ["walton-scheme", "snapshot", "--workspace", str(cli_workspace)],
    )
    assert result.exit_code != 0
    haystack = (result.stdout or "") + (result.stderr or "")
    assert "extend" in haystack.lower() or "already" in haystack.lower()
