"""Queue / outputs / failures protocol (M6.1).

The dispatch driver is a separate process from the writer of a
:class:`DispatchQueueEntry` — typically the supervisor's ``distill``
command writes the entry, then the operator (or a long-running daemon)
runs ``amanuensis dispatch`` to drain the queue. This module is the
filesystem contract that lets the two processes coordinate without IPC:

::

    <workspace>/
      dispatch/
        queue/<role>-<inputs_hash>.yaml          (the work item)
        outputs/<role>-<inputs_hash>/output.yaml (success — payload landed)
        failures/<role>-<inputs_hash>.yaml       (the original queue entry)
        failures/<role>-<inputs_hash>.failure.yaml (sidecar: reason + detail)

Atomicity discipline:

- Every write goes through :func:`amanuensis.fs._atomic.atomic_write_text`
  so a concurrent reader never observes a torn file.
- Move-to-failures / move-to-outputs use :func:`os.replace` (same-FS
  atomic rename) for the queue-entry side, and ``atomic_write_text``
  followed by ``unlink`` for the payload side.
- Directory creation is always ``mkdir(parents=True, exist_ok=True)`` —
  the protocol is idempotent against a partially-populated dispatch
  tree.

This module does NOT acquire the workspace flock. The dispatch driver
(M6.5) acquires the flock for the multi-file payload+cache+replay-log
transaction; the queue helpers are leaf operations that the driver
sequences inside its own locked section.

Why "peek, don't remove" on ``dequeue``:
The driver must be able to inspect the entry, run a possibly long
subprocess, AND retain the option to route to failures — all without
risking a re-dequeue picking the same entry up from a parallel run. In
practice we run a single-threaded driver (the workspace flock enforces
that), so leaving the entry in place until the dispatch outcome is
known is the simplest correct semantics; the driver explicitly calls
:func:`move_to_failures` or :func:`move_to_outputs` to retire it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import _safe_dump, _safe_load  # pyright: ignore[reportPrivateUsage]
from amanuensis.llm.queue import DispatchQueueEntry

QUEUE_FILE_MODE: int = 0o644
"""Mode for queue / failure files (coordination messages; no sensitive payload)."""

OUTPUT_FILE_MODE: int = 0o600
"""Mode for output payloads (CV-15: may carry sensitive LLM material)."""


# --- Path resolvers (pure path computation; no FS access) -------------


def _queue_dir(workspace_root: Path) -> Path:
    return workspace_root / "dispatch" / "queue"


def _outputs_dir(workspace_root: Path) -> Path:
    return workspace_root / "dispatch" / "outputs"


def _failures_dir(workspace_root: Path) -> Path:
    return workspace_root / "dispatch" / "failures"


def _queue_path(workspace_root: Path, role: str, inputs_hash: str) -> Path:
    return _queue_dir(workspace_root) / f"{role}-{inputs_hash}.yaml"


def _output_dir(workspace_root: Path, role: str, inputs_hash: str) -> Path:
    return _outputs_dir(workspace_root) / f"{role}-{inputs_hash}"


# --- Enqueue ----------------------------------------------------------


def enqueue(workspace_root: Path, entry: DispatchQueueEntry) -> Path:
    """Atomically write ``entry`` to the queue and return its path.

    The destination is
    ``<workspace>/dispatch/queue/<role>-<inputs_hash>.yaml``. The write
    is atomic (write-to-tmp-then-rename); if a queue entry already exists
    at the same path, it is overwritten — the caller has just re-stated
    the request, and the driver should consume the latest snapshot. This
    mirrors :mod:`amanuensis.llm.cached_call`'s idempotency contract.
    """
    path = _queue_path(workspace_root, entry.role, entry.inputs_hash)
    payload: dict[str, Any] = entry.model_dump(mode="python")
    atomic_write_text(path, _safe_dump(payload))
    _chmod_safe(path, QUEUE_FILE_MODE)
    return path


# --- Dequeue (peek; do NOT unlink) ------------------------------------


def dequeue(workspace_root: Path) -> tuple[Path, DispatchQueueEntry] | None:
    """Return the oldest queue entry (by mtime) without removing it.

    The driver removes the entry only after a successful dispatch (via
    :func:`move_to_outputs` or :func:`move_to_failures`). Returns
    ``None`` if the queue is empty (directory missing or directory
    present but no ``.yaml`` files).

    Tie-breaker for entries with equal mtime: lexicographic filename
    order. ``mtime`` is the floor float seconds (filesystem resolution
    varies), so ties are common on fast tests.
    """
    queue_dir = _queue_dir(workspace_root)
    if not queue_dir.is_dir():
        return None

    candidates: list[Path] = []
    for child in queue_dir.iterdir():
        if not child.is_file():
            continue
        if not child.name.endswith(".yaml"):
            continue
        if ".tmp." in child.name:
            # Skip atomic-write tmp leftovers from a crashed writer.
            continue
        candidates.append(child)

    if not candidates:
        return None

    # Sort by (mtime, name) so ties are deterministic.
    candidates.sort(key=lambda p: (p.stat().st_mtime, p.name))
    chosen = candidates[0]
    entry = _load_queue_entry(chosen)
    return chosen, entry


def list_queue(workspace_root: Path) -> list[tuple[Path, DispatchQueueEntry]]:
    """Lex-sorted snapshot of every current queue entry.

    Used by tests (deterministic ordering across mtime ties) and by
    diagnostic tooling that wants to inspect the backlog without
    consuming it. The sort key is the filename, not the mtime, so the
    output is stable across runs that produce entries within the same
    filesystem mtime tick.
    """
    queue_dir = _queue_dir(workspace_root)
    if not queue_dir.is_dir():
        return []
    out: list[tuple[Path, DispatchQueueEntry]] = []
    for child in sorted(queue_dir.iterdir(), key=lambda p: p.name):
        if not child.is_file():
            continue
        if not child.name.endswith(".yaml"):
            continue
        if ".tmp." in child.name:
            continue
        out.append((child, _load_queue_entry(child)))
    return out


def _load_queue_entry(path: Path) -> DispatchQueueEntry:
    """Parse + validate one queue entry from disk."""
    text = path.read_text(encoding="utf-8")
    raw = _safe_load(text)
    return DispatchQueueEntry(**raw)


# --- Move-to-failures -------------------------------------------------


def move_to_failures(
    workspace_root: Path,
    queue_path: Path,
    *,
    reason: str,
    detail: str | None = None,
) -> Path:
    """Move a queue entry to ``dispatch/failures/`` with a sidecar reason.

    Writes two files atomically (in sequence; the sidecar lands first so
    a reader walking the failures directory always sees the reason BEFORE
    seeing the moved entry):

    1. ``failures/<basename>.failure.yaml`` — ``{reason, detail,
       failed_at_iso}``.
    2. ``failures/<basename>`` — the original queue payload (moved via
       ``os.replace``).

    Returns the path of the moved queue entry (the ``.yaml`` file). The
    sidecar's path is sibling-by-construction; callers reconstruct it as
    ``returned_path.with_suffix(".failure.yaml")`` if they need it.

    Why two files instead of merging the failure metadata into the queue
    entry: keeping the original entry byte-identical to what the queue
    held means an operator can move it back to ``queue/`` to retry,
    without having to scrub injected diagnostic fields. The sidecar is
    the diagnostic; the entry is the workload.
    """
    failures_dir = _failures_dir(workspace_root)
    failures_dir.mkdir(parents=True, exist_ok=True)

    dest_entry = failures_dir / queue_path.name
    # Sidecar: same basename, but ".failure.yaml" extension. ``.yaml``
    # entry name "extractor-abc.yaml" → sidecar "extractor-abc.failure.yaml".
    sidecar_name = queue_path.stem + ".failure.yaml"
    sidecar_path = failures_dir / sidecar_name

    sidecar_payload: dict[str, Any] = {
        "reason": reason,
        "detail": detail,
        "failed_at_iso": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        "original_queue_filename": queue_path.name,
    }
    atomic_write_text(sidecar_path, _safe_dump(sidecar_payload))
    _chmod_safe(sidecar_path, QUEUE_FILE_MODE)

    # Now move the queue entry. ``os.replace`` is atomic on the same FS.
    os.replace(queue_path, dest_entry)
    _chmod_safe(dest_entry, QUEUE_FILE_MODE)
    return dest_entry


# --- Move-to-outputs --------------------------------------------------


def move_to_outputs(
    workspace_root: Path,
    queue_path: Path,
    *,
    role: str,
    inputs_hash: str,
    output_payload: dict[str, Any],
) -> Path:
    """Write the role's output and remove the queue entry.

    Writes
    ``dispatch/outputs/<role>-<inputs_hash>/output.yaml`` (mode 0600 per
    CV-15), then unlinks the queue entry. Returns the output path.

    The output file's shape is whatever ``output_payload`` carries — the
    role's structured output as parsed by the driver. The dispatch driver
    is responsible for wrapping the parsed payload with whatever metadata
    the reconciliation layer (M7.4) needs.

    The order of operations matters: write the output FIRST, then unlink
    the queue entry. If the driver crashes between the two steps, the
    queue still holds the entry and the next dispatch run will re-execute
    — the output write is idempotent (atomic rename overwrites cleanly)
    and the cache + replay-log writes are content-addressable so the
    second run reaches the same state.
    """
    out_dir = _output_dir(workspace_root, role, inputs_hash)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "output.yaml"

    payload_text = yaml.safe_dump(
        output_payload,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
    )
    atomic_write_text(out_path, payload_text)
    _chmod_safe(out_path, OUTPUT_FILE_MODE)

    # Output written successfully; retire the queue entry. Tolerate the
    # entry having vanished (concurrent operator cleanup) — the contract
    # is "queue entry no longer present" and we've reached that state.
    try:
        queue_path.unlink()
    except FileNotFoundError:  # pragma: no cover - racy cleanup; defensive
        pass

    return out_path


# --- chmod helper (shared with cached_call's pattern) ----------------


def _chmod_safe(path: Path, mode: int) -> None:
    """Apply ``mode`` to ``path``; tolerate the file vanishing mid-call."""
    try:
        os.chmod(path, mode)
    except FileNotFoundError:  # pragma: no cover - racy cleanup; defensive
        pass
