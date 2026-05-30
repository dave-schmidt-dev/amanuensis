"""Workspace-level advisory flock (Phase 1 plan §5 — concurrency model).

Mutating operations on a substrate (CLI ``distill`` / ``dispatch`` /
clarification-resolve, web POST endpoints) MUST serialize their writes
against one another. They do so by holding an exclusive POSIX advisory
``flock`` on the sentinel file ``<workspace>/.amanuensis-lock`` for the
duration of the write. Read-only commands do NOT acquire the lock —
the atomic write-to-tmp-then-rename discipline (M1.6) keeps readers
safe even mid-write.

Why ``fcntl.flock`` (not ``fcntl.lockf``):

- ``flock`` is per-open-file-description, kernel-managed, and auto-
  released when the holder's last fd to the file is closed. That
  closure happens on clean exit AND on SIGKILL / segfault / OOM —
  the kernel walks the file table at process teardown and releases
  every flock the process held. This is the SIGKILL-recovery property
  the task requires.
- ``lockf`` semantics on Linux are byte-range and tied to the (pid,
  inode) pair; closing any fd to the file releases the lock. That's
  also acceptable but more surprising for a whole-file workspace lock.
- Plan §5 calls this "workspace flock" — we use the function it names.

POSIX-only. macOS and Linux both ship ``fcntl.flock``. Windows is out
of scope for Phase 1.

The lock file is created (mode 0o644) if it does not exist and is NOT
deleted on release — concurrent waiters may have already opened it,
and unlinking would create unnecessary filesystem churn without
affecting their inherited flock.
"""

from __future__ import annotations

import errno
import fcntl
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from ._errors import SubstrateMarkerMissing, WorkspaceLockTimeout

LOCK_FILENAME: str = ".amanuensis-lock"
"""Sentinel file at the workspace root that carries the workspace flock."""

DEFAULT_TIMEOUT_SECONDS: float = 5.0
"""Default acquire timeout. Web POST endpoints use this directly per plan §5."""

_POLL_INTERVAL_SECONDS: float = 0.1
"""Sleep between non-blocking ``flock`` attempts while inside the timeout window."""

_MARKER_FILENAME: str = "amanuensis.yaml"  # mirrors Substrate.MARKER_FILENAME


def _require_workspace_marker(workspace_root: Path) -> None:
    """Refuse to lock a directory that isn't an amanuensis workspace.

    Mirrors ``Substrate.__init__``'s INV-1 check without depending on
    the ``Substrate`` class — the lock layer is structurally below the
    substrate layer and may be acquired before any ``Substrate`` instance
    exists (e.g. by a CLI entry point that holds the lock for the whole
    command).
    """
    if not workspace_root.is_dir():
        raise SubstrateMarkerMissing(
            f"workspace_root {workspace_root} is not an existing directory."
        )
    marker = workspace_root / _MARKER_FILENAME
    if not marker.is_file():
        raise SubstrateMarkerMissing(
            f"amanuensis.yaml marker missing at {workspace_root}; "
            "refusing to acquire workspace lock on a non-workspace directory."
        )


@contextmanager
def acquire_workspace_lock(
    workspace_root: Path | str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Generator[None, None, None]:
    """Acquire an exclusive workspace-level advisory flock.

    Used by mutating operations (CLI ``distill`` / ``dispatch`` /
    clarification-resolve, web POST endpoints) to serialize substrate
    writes. Read-only operations do NOT acquire this lock — write-to-tmp-
    then-rename (M1.6) makes reads safe against in-flight writes.

    The lock is held on ``<workspace_root>/.amanuensis-lock``; the file
    is created (mode 0o644) if missing. POSIX kernel auto-releases the
    flock when the holder process exits (clean exit, SIGKILL, segfault,
    OOM kill — all release the flock).

    Polls every ``_POLL_INTERVAL_SECONDS`` (100ms) against a
    ``time.monotonic()`` deadline. ``timeout=0`` performs a single
    non-blocking attempt and raises on contention.

    Args:
        workspace_root: path to the workspace (must contain ``amanuensis.yaml``).
        timeout: seconds to wait before giving up. Must be >= 0.

    Raises:
        ValueError: if ``timeout`` is negative.
        SubstrateMarkerMissing: if ``workspace_root`` has no marker file.
        WorkspaceLockTimeout: if the lock cannot be acquired within
            ``timeout`` seconds.
    """
    if timeout < 0:
        raise ValueError(f"timeout must be >= 0; got {timeout!r}")

    root = Path(workspace_root).resolve()
    _require_workspace_marker(root)

    lock_path = root / LOCK_FILENAME
    # Open with O_CREAT|O_RDWR; mode 0o644 applies only on creation.
    # We keep the fd open for the lifetime of the context and close it
    # in the finally block — closing implicitly releases the flock.
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break  # Acquired.
            except BlockingIOError as exc:
                # EAGAIN / EWOULDBLOCK — lock is held by another process.
                # Any other OSError is a real fault and propagates.
                if exc.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WorkspaceLockTimeout(
                        f"could not acquire workspace lock at {lock_path} "
                        f"within {timeout:.1f}s; another amanuensis process "
                        "may be running (CLI distill/dispatch, or a web "
                        "POST endpoint mid-write)."
                    ) from None
                # Sleep up to the poll interval, but no longer than what
                # remains on the deadline — keeps timeout precision tight
                # when ``timeout`` is small.
                time.sleep(min(_POLL_INTERVAL_SECONDS, remaining))
        try:
            yield
        finally:
            # LOCK_UN is best-effort; closing the fd also releases the
            # flock. We do both so the release is observable even if a
            # later reopen of the same path occurs in the same process.
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                # Already released (e.g. fd somehow invalidated); the
                # close below will do nothing harmful.
                pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
