"""SR-4 — concurrent map + distill share the workspace flock.

Validates that ``amanuensis map`` and ``amanuensis distill`` cannot run
simultaneously: each acquires the workspace flock, so the second
waits/times-out per the standard lock-contention contract.

The two tests look near-identical because the flock is workspace-scoped
(not verb-scoped). That is the point: the SR-4 contract is symmetric —
the test pair documents it from both supervisor-facing angles.
"""

from __future__ import annotations

import multiprocessing
import time
from multiprocessing.process import BaseProcess
from pathlib import Path

import pytest

from amanuensis.fs import WorkspaceLockTimeout, acquire_workspace_lock

# --- Child entry point (module-level for spawn pickling) ----------------


def _hold_lock(workspace_str: str, hold_seconds: float, ready_marker_str: str) -> None:
    """Child entry point — acquire the lock, signal readiness, hold, release."""
    ready_marker = Path(ready_marker_str)
    with acquire_workspace_lock(Path(workspace_str), timeout=5.0):
        ready_marker.write_text("ready", encoding="utf-8")
        time.sleep(hold_seconds)


# --- Helpers ------------------------------------------------------------


def _spawn_holder(workspace: Path, hold_seconds: float) -> tuple[BaseProcess, Path]:
    """Spawn a child that holds the workspace lock; wait until it is held.

    The child writes a ready-marker file inside the workspace once it has
    acquired the flock.  The parent polls for that marker before returning,
    so callers can be confident the lock is held before they try to contend.
    """
    ready_marker = workspace / ".holder-ready"
    ctx = multiprocessing.get_context("spawn")
    proc: BaseProcess = ctx.Process(
        target=_hold_lock,
        args=(str(workspace), hold_seconds, str(ready_marker)),
    )
    proc.start()
    # Wait up to 5 s for the child to signal it holds the lock.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if ready_marker.exists():
            return proc, ready_marker
        time.sleep(0.02)
    # Child never signalled — clean up and fail the test.
    proc.terminate()
    proc.join(timeout=5)
    pytest.fail("holder child never acquired the workspace lock")


def _make_workspace(tmp_path: Path) -> Path:
    """Plant the amanuensis.yaml marker so flock acquisition succeeds."""
    (tmp_path / "amanuensis.yaml").write_text(
        "schema_version: 1\nproject_name: ccd-test\n",
        encoding="utf-8",
    )
    return tmp_path


# --- Tests --------------------------------------------------------------


def test_map_blocks_during_distill(tmp_path: Path) -> None:
    """When distill holds the flock, an attempt to map fast-fails with WorkspaceLockTimeout.

    The distill verb acquires the workspace flock while writing atoms to the
    substrate.  A concurrent map invocation must not proceed; it times out
    and raises WorkspaceLockTimeout.  This is the SR-4 contract from the
    distill-holds / map-contends direction.
    """
    workspace = _make_workspace(tmp_path)
    holder, _marker = _spawn_holder(workspace, hold_seconds=2.0)
    try:
        # Attempt to acquire the flock as the "map" verb would.
        with pytest.raises(WorkspaceLockTimeout):
            with acquire_workspace_lock(workspace, timeout=0.5):
                pass  # we should not reach here
    finally:
        holder.join(timeout=5.0)


def test_distill_blocks_during_map(tmp_path: Path) -> None:
    """When map holds the flock, an attempt to distill fast-fails with WorkspaceLockTimeout.

    The map verb acquires the workspace flock while writing resolutions to the
    substrate.  A concurrent distill invocation must not proceed; it times out
    and raises WorkspaceLockTimeout.  This is the SR-4 contract from the
    map-holds / distill-contends direction.

    The test body is symmetric with ``test_map_blocks_during_distill`` because
    the flock is workspace-scoped, not verb-keyed.  The distinction exists
    purely at the documentation level (the docstrings call out which verb holds
    and which contends), asserting the SR-4 contract from both directions.
    """
    workspace = _make_workspace(tmp_path)
    holder, _marker = _spawn_holder(workspace, hold_seconds=2.0)
    try:
        # Attempt to acquire the flock as the "distill" verb would.
        with pytest.raises(WorkspaceLockTimeout):
            with acquire_workspace_lock(workspace, timeout=0.5):
                pass  # we should not reach here
    finally:
        holder.join(timeout=5.0)
