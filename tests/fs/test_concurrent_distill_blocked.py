"""Concurrency tests for ``acquire_workspace_lock`` (M1.8 — plan §5).

The lock serializes mutating substrate operations (CLI ``distill`` /
``dispatch`` / clarification-resolve, web POST endpoints) without
blocking read paths. These tests exercise:

1. Happy path — single acquire succeeds; sentinel file persists.
2. Contention with timeout — a held lock causes a second acquire to
   raise ``WorkspaceLockTimeout``.
3. Recovery after release — a brief hold lets a later acquire succeed
   within the deadline.
4. Marker-missing refusal — locking a non-workspace directory raises
   ``SubstrateMarkerMissing`` (defense in depth against caller error).
5. SIGKILL release — abruptly terminating the holder releases the
   flock (POSIX kernel auto-release on process teardown). We use
   ``os._exit(1)`` from a spawn child for cross-platform reliability;
   the kernel runs the same fd-table teardown path it runs for SIGKILL.
6. ``timeout=0`` fast-fail when the lock is held.
7. Negative timeout rejected with ``ValueError``.

Child processes use ``multiprocessing.get_context("spawn")`` per the
M1.6 pattern (avoids forked-state surprises on macOS).
"""

from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path

import pytest

from amanuensis.fs import (
    LOCK_FILENAME,
    SubstrateMarkerMissing,
    WorkspaceLockTimeout,
    acquire_workspace_lock,
)

# --- Child entry points (module-level for spawn pickling) ------------


def _hold_lock_then_exit_cleanly(workspace_str: str, hold_seconds: float) -> None:
    """Acquire the workspace lock, hold for ``hold_seconds``, then exit 0."""
    with acquire_workspace_lock(Path(workspace_str), timeout=5.0):
        time.sleep(hold_seconds)


def _hold_lock_then_sigkill_self(workspace_str: str, ready_marker_str: str) -> None:
    """Acquire the lock, signal readiness, then exit abruptly while holding it.

    ``os._exit(1)`` bypasses Python's contextmanager ``__exit__`` and
    finally blocks — the kernel must auto-release the flock for the
    parent's later acquire to succeed. This is the SIGKILL-recovery
    invariant under test (the kernel performs the same fd-table walk
    on ``os._exit`` and SIGKILL — both skip user-space cleanup).
    """
    ready_marker = Path(ready_marker_str)
    # Enter the context manually so we can write the readiness marker
    # AFTER the lock is held, then abandon the contextmanager state.
    cm = acquire_workspace_lock(Path(workspace_str), timeout=5.0)
    cm.__enter__()
    ready_marker.write_text("ready", encoding="utf-8")
    # Spin a short moment to make sure the parent observes readiness
    # before we die. (Not strictly necessary — the parent polls — but
    # makes the test's intent obvious.)
    time.sleep(0.05)
    os._exit(1)


# --- Tests -----------------------------------------------------------


def test_happy_path_acquire_release(tmp_workspace: Path) -> None:
    """Single acquire/release leaves the sentinel file in place."""
    with acquire_workspace_lock(tmp_workspace, timeout=1.0):
        pass
    # Sentinel file persists by design — see lock.py rationale.
    assert (tmp_workspace / LOCK_FILENAME).is_file()


def test_lock_is_reentrant_serially(tmp_workspace: Path) -> None:
    """After release, a second acquire in the same process succeeds quickly."""
    with acquire_workspace_lock(tmp_workspace, timeout=1.0):
        pass
    t0 = time.monotonic()
    with acquire_workspace_lock(tmp_workspace, timeout=1.0):
        pass
    # Re-acquire should be effectively instantaneous (well under the
    # timeout). Generous bound to keep CI noise low.
    assert time.monotonic() - t0 < 0.5


def test_second_concurrent_acquire_times_out(tmp_workspace: Path) -> None:
    """Lock held by a child process forces parent's acquire to time out."""
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(
        target=_hold_lock_then_exit_cleanly,
        args=(str(tmp_workspace), 2.0),
    )
    proc.start()
    try:
        # Give the child a moment to acquire before we contend.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            # Try a zero-timeout acquire to see if the child has it yet.
            try:
                with acquire_workspace_lock(tmp_workspace, timeout=0.0):
                    # Child hasn't acquired yet — release and retry.
                    pass
                time.sleep(0.05)
            except WorkspaceLockTimeout:
                # Child holds the lock; proceed to the real assertion.
                break
        else:
            pytest.fail("child never acquired the workspace lock")

        # Now the parent's real timed acquire MUST time out.
        t0 = time.monotonic()
        with pytest.raises(WorkspaceLockTimeout) as excinfo:
            with acquire_workspace_lock(tmp_workspace, timeout=0.5):
                pytest.fail("acquire should have raised, not entered")
        elapsed = time.monotonic() - t0
        # The timeout error message should be informative and name the path.
        msg = str(excinfo.value)
        assert LOCK_FILENAME in msg
        assert "0.5" in msg
        # Should respect the timeout (not block forever). Allow generous
        # upper bound for CI scheduler jitter.
        assert 0.4 <= elapsed < 2.0, f"elapsed={elapsed:.3f}s outside expected window"
    finally:
        proc.join(timeout=5)
        if proc.is_alive():  # pragma: no cover — defensive
            proc.terminate()
            proc.join(timeout=5)
        assert proc.exitcode == 0


def test_second_acquire_succeeds_after_release(tmp_workspace: Path) -> None:
    """Lock held briefly by a child; parent waits and succeeds before timeout."""
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(
        target=_hold_lock_then_exit_cleanly,
        args=(str(tmp_workspace), 0.3),
    )
    proc.start()
    try:
        # Wait for the child to actually hold the lock before contending.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                with acquire_workspace_lock(tmp_workspace, timeout=0.0):
                    pass
                time.sleep(0.05)
            except WorkspaceLockTimeout:
                break
        else:
            pytest.fail("child never acquired the workspace lock")

        # Parent acquires with timeout > child's remaining hold.
        with acquire_workspace_lock(tmp_workspace, timeout=2.0):
            pass  # Success.
    finally:
        proc.join(timeout=5)
        assert proc.exitcode == 0


def test_marker_missing_raises(tmp_path: Path) -> None:
    """Locking a directory without ``amanuensis.yaml`` is refused."""
    # tmp_path has no marker file — that's the point.
    with pytest.raises(SubstrateMarkerMissing):
        with acquire_workspace_lock(tmp_path, timeout=0.1):
            pytest.fail("acquire should have refused")


def test_nonexistent_workspace_raises(tmp_path: Path) -> None:
    """A workspace_root that doesn't exist raises ``SubstrateMarkerMissing``."""
    missing = tmp_path / "does-not-exist"
    with pytest.raises(SubstrateMarkerMissing):
        with acquire_workspace_lock(missing, timeout=0.1):
            pytest.fail("acquire should have refused")


def test_sigkill_of_holder_releases_lock(tmp_workspace: Path) -> None:
    """Abrupt child death releases the flock (POSIX kernel auto-release).

    The child uses ``os._exit(1)`` while holding the lock. Python's
    contextmanager finally block is bypassed — only the kernel's fd-
    table teardown can release the flock. If this test passes, the
    SIGKILL-recovery property documented in M1.8 holds.
    """
    ctx = multiprocessing.get_context("spawn")
    ready_marker = tmp_workspace / ".ready"
    proc = ctx.Process(
        target=_hold_lock_then_sigkill_self,
        args=(str(tmp_workspace), str(ready_marker)),
    )
    proc.start()
    try:
        # Wait for the child to signal it acquired the lock.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if ready_marker.exists():
                break
            time.sleep(0.02)
        else:
            pytest.fail("child never signalled lock acquisition")

        # Wait for the child to die.
        proc.join(timeout=5)
        assert not proc.is_alive()
        assert proc.exitcode == 1  # Our chosen abrupt-exit code.

        # The lock MUST now be acquirable — if the kernel did not auto-
        # release on os._exit, this would time out.
        with acquire_workspace_lock(tmp_workspace, timeout=1.0):
            pass
    finally:
        if proc.is_alive():  # pragma: no cover — defensive
            proc.terminate()
            proc.join(timeout=5)


def test_timeout_zero_fast_fails_when_held(tmp_workspace: Path) -> None:
    """``timeout=0`` does a single non-blocking attempt; raises if held."""
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(
        target=_hold_lock_then_exit_cleanly,
        args=(str(tmp_workspace), 1.0),
    )
    proc.start()
    try:
        # Wait until the child holds the lock.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                with acquire_workspace_lock(tmp_workspace, timeout=0.0):
                    pass
                time.sleep(0.05)
            except WorkspaceLockTimeout:
                break
        else:
            pytest.fail("child never acquired the workspace lock")

        # A zero-timeout acquire must fast-fail (no polling loop).
        t0 = time.monotonic()
        with pytest.raises(WorkspaceLockTimeout):
            with acquire_workspace_lock(tmp_workspace, timeout=0.0):
                pytest.fail("acquire should have raised, not entered")
        # Should be effectively instantaneous — generous bound for CI.
        assert time.monotonic() - t0 < 0.2
    finally:
        proc.join(timeout=5)
        assert proc.exitcode == 0


def test_negative_timeout_raises_value_error(tmp_workspace: Path) -> None:
    """Negative timeout is rejected with ``ValueError`` (caller bug)."""
    with pytest.raises(ValueError):
        with acquire_workspace_lock(tmp_workspace, timeout=-1.0):
            pytest.fail("acquire should have refused")
