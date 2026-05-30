"""``amanuensis distill <source-id>`` — orchestrator CLI (M7.3).

Covers:

- Refusal when the source-mirror manifest is missing.
- Default role set (extractor + auditor) produces two queue entries.
- Explicit role set including a stub (contrarian) skips the stub, still
  enqueues the active roles, and records a replay-log entry for the skip.
- Workspace flock contention: a second ``distill`` invocation blocks
  when the lock is held by the test and surfaces a timeout error.
"""

from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.dispatch.queue import list_queue
from amanuensis.fs import Substrate, acquire_workspace_lock

runner = CliRunner()


SOURCE_ID = "distill-cli-src"


def _plant_source_mirror(workspace: Path, source_id: str = SOURCE_ID) -> Path:
    """Create an empty manifest.yaml so the existence check passes.

    The distill command only checks the manifest path exists; it does
    not parse the manifest (that happens at dispatch / reconciliation
    time). An empty file is therefore sufficient for the orchestrator's
    preflight.
    """
    substrate = Substrate(workspace)
    manifest_path = substrate.manifest_path(source_id)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("", encoding="utf-8")
    return manifest_path


def _read_replay_entries(workspace: Path, source_id: str = SOURCE_ID) -> list[dict[str, Any]]:
    """Walk the per-distillation replay-log tree and return parsed entries."""
    log_root = workspace / "distillations" / source_id / "replay-log"
    if not log_root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    for day_dir in sorted(log_root.iterdir()):
        if not day_dir.is_dir():
            continue
        for entry_path in sorted(day_dir.glob("*.yaml")):
            parsed: Any = yaml.safe_load(entry_path.read_text(encoding="utf-8"))
            assert isinstance(parsed, dict)
            typed_entry: dict[str, Any] = parsed
            entries.append(typed_entry)
    return entries


# --- 1. Refusal: no source-mirror -----------------------------------------


def test_distill_refuses_without_source_mirror(cli_workspace: Path) -> None:
    """No manifest under ``distillations/<src>/source-mirror/`` → clear error.

    The error message must name ``amanuensis ingest`` so the supervisor
    knows what to run first. Exit code is non-zero (``fatal`` raises
    ``typer.Exit(1)``).
    """
    # Pre-condition: no source-mirror planted.
    assert not (cli_workspace / "distillations").exists()

    result = runner.invoke(
        app,
        ["distill", SOURCE_ID, "--workspace", str(cli_workspace)],
    )
    assert result.exit_code != 0, (
        f"expected non-zero exit when source-mirror is missing; got 0\noutput: {result.output}"
    )
    # The error must name the ingest command so the operator knows what to run.
    assert "amanuensis ingest" in result.output
    assert SOURCE_ID in result.output


# --- 2. Default role set --------------------------------------------------


def test_distill_default_role_set_is_extractor_plus_auditor(cli_workspace: Path) -> None:
    """No ``--role-set`` → queue holds exactly extractor + auditor entries."""
    _plant_source_mirror(cli_workspace)

    result = runner.invoke(
        app,
        ["distill", SOURCE_ID, "--workspace", str(cli_workspace)],
    )
    assert result.exit_code == 0, (
        f"expected exit 0; got {result.exit_code}\noutput: {result.output}"
    )

    entries = list_queue(cli_workspace)
    roles = sorted(entry.role for _, entry in entries)
    assert roles == ["auditor", "extractor"], f"expected [auditor, extractor] in queue; got {roles}"


# --- 3. Stub roles are skipped --------------------------------------------


def test_distill_enqueues_active_roles_skips_stubs(cli_workspace: Path) -> None:
    """``--role-set extractor,auditor,contrarian`` enqueues 2, skips 1.

    Asserts:
    - Queue holds exactly extractor + auditor (NOT contrarian).
    - Replay log holds at least one entry whose ``substrate_changes``
      reference the skipped contrarian role.
    """
    _plant_source_mirror(cli_workspace)

    result = runner.invoke(
        app,
        [
            "distill",
            SOURCE_ID,
            "--role-set",
            "extractor,auditor,contrarian",
            "--workspace",
            str(cli_workspace),
        ],
    )
    assert result.exit_code == 0, (
        f"expected exit 0; got {result.exit_code}\noutput: {result.output}"
    )

    entries = list_queue(cli_workspace)
    roles = sorted(entry.role for _, entry in entries)
    assert roles == ["auditor", "extractor"], (
        f"expected only extractor + auditor in queue; got {roles}"
    )
    # No contrarian queue entry.
    assert not any(entry.role == "contrarian" for _, entry in entries)

    # The skip notice was emitted to stderr (merged into result.output
    # by CliRunner under Click 8.4) and references the stub role.
    assert "contrarian" in result.output
    assert "skipping stub" in result.output.lower()

    # Replay-log entry was appended for the skip.
    replay_entries = _read_replay_entries(cli_workspace)
    skip_entries = [
        e
        for e in replay_entries
        if any(
            isinstance(change, str) and "role-skipped:contrarian" in change
            for change in e.get("substrate_changes", [])  # type: ignore[union-attr]
        )
    ]
    assert skip_entries, (
        f"expected at least one replay-log entry recording the contrarian skip; "
        f"got entries: {replay_entries}"
    )
    # The skip entry's activity is the orchestrator's name.
    assert skip_entries[0]["activity"] == "distill-orchestrate"


# --- 4. Workspace flock contention ----------------------------------------


def _hold_lock_then_exit_cleanly(workspace_str: str, hold_seconds: float) -> None:
    """Acquire the workspace lock, hold for ``hold_seconds``, then exit 0.

    Module-level so the spawn multiprocessing context can serialize the
    target for the child interpreter.
    """
    with acquire_workspace_lock(Path(workspace_str), timeout=5.0):
        time.sleep(hold_seconds)
    os._exit(0)


def test_distill_acquires_flock(cli_workspace: Path) -> None:
    """A held workspace lock causes ``distill`` to wait before proceeding.

    Pattern mirrors ``tests/fs/test_concurrent_distill_blocked.py``: a
    child spawn process grabs the flock for a few seconds; the main
    process invokes the CLI command via CliRunner and asserts it took
    at least most of that hold to return — proving the flock acquire is
    real (vs. silently ignored).
    """
    _plant_source_mirror(cli_workspace)

    ctx = multiprocessing.get_context("spawn")
    hold_seconds = 1.5
    proc = ctx.Process(
        target=_hold_lock_then_exit_cleanly,
        args=(str(cli_workspace), hold_seconds),
    )
    proc.start()
    try:
        # Wait until the child actually holds the lock before invoking
        # distill — otherwise the CLI may grab the lock first.
        from amanuensis.fs import WorkspaceLockTimeout

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                with acquire_workspace_lock(cli_workspace, timeout=0.0):
                    pass
                time.sleep(0.05)
            except WorkspaceLockTimeout:
                break
        else:
            pytest.fail("child never acquired the workspace lock")

        t0 = time.monotonic()
        result = runner.invoke(
            app,
            ["distill", SOURCE_ID, "--workspace", str(cli_workspace)],
        )
        elapsed = time.monotonic() - t0
        assert result.exit_code == 0, (
            f"expected exit 0 after lock release; got {result.exit_code}\noutput: {result.output}"
        )
        # The CLI must have waited a meaningful portion of the child's
        # hold before proceeding — proves the flock acquire is wired up.
        # Generous lower bound to keep CI scheduler jitter from flaking.
        assert elapsed >= 0.5, (
            f"distill returned in {elapsed:.2f}s but child held the lock for "
            f"~{hold_seconds}s; the flock acquire may not be wired up"
        )
    finally:
        proc.join(timeout=10)
        if proc.is_alive():  # pragma: no cover - defensive
            proc.terminate()
            proc.join(timeout=5)
