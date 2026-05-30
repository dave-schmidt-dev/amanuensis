"""Queue / outputs / failures protocol tests (M6.1).

Five contracts:

1. ``enqueue`` writes the entry at the canonical path.
2. ``dequeue`` round-trips: enqueue → dequeue returns the same entry.
3. ``move_to_failures`` retires the queue entry and writes the sidecar.
4. ``move_to_outputs`` writes the output, unlinks the queue entry.
5. ``list_queue`` returns entries in lex order (deterministic regardless
   of mtime).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from amanuensis.dispatch.queue import (
    dequeue,
    enqueue,
    list_queue,
    move_to_failures,
    move_to_outputs,
)
from amanuensis.llm import DispatchQueueEntry

from .conftest import make_entry


def test_enqueue_writes_entry_at_canonical_path(dispatch_workspace: Path) -> None:
    """Canonical path is dispatch/queue/<role>-<inputs_hash>.yaml."""
    entry = make_entry(role="extractor", inputs_hash="abc" + "0" * 61)
    path = enqueue(dispatch_workspace, entry)
    expected = dispatch_workspace / "dispatch" / "queue" / f"extractor-{entry.inputs_hash}.yaml"
    assert path == expected
    assert path.is_file()


def test_enqueue_dequeue_round_trip(dispatch_workspace: Path) -> None:
    """enqueue → dequeue returns the same entry."""
    entry = make_entry(role="auditor", inputs_hash="b" * 64)
    enqueue(dispatch_workspace, entry)

    picked = dequeue(dispatch_workspace)
    assert picked is not None
    queue_path, parsed = picked
    assert queue_path.is_file()  # dequeue does NOT remove
    assert parsed.role == entry.role
    assert parsed.prompt == entry.prompt
    assert parsed.inputs == entry.inputs
    assert parsed.model_id == entry.model_id
    assert parsed.inputs_hash == entry.inputs_hash


def test_dequeue_empty_queue_returns_none(dispatch_workspace: Path) -> None:
    """Empty queue (no directory) returns None."""
    assert dequeue(dispatch_workspace) is None


def test_move_to_failures_retires_entry_and_writes_sidecar(
    dispatch_workspace: Path,
) -> None:
    """Queue entry vanishes; failures/<basename> + .failure.yaml appear."""
    entry = make_entry(role="extractor", inputs_hash="c" * 64)
    queue_path = enqueue(dispatch_workspace, entry)

    moved = move_to_failures(
        dispatch_workspace,
        queue_path,
        reason="timeout",
        detail="harness exceeded 600s",
    )

    assert not queue_path.exists(), "queue entry should be moved away"
    assert moved.is_file()
    assert moved.parent == dispatch_workspace / "dispatch" / "failures"
    assert moved.name == queue_path.name

    # The moved entry round-trips through the queue schema.
    moved_payload: Any = yaml.safe_load(moved.read_text(encoding="utf-8"))
    parsed_entry = DispatchQueueEntry(**moved_payload)
    assert parsed_entry.role == entry.role
    assert parsed_entry.inputs_hash == entry.inputs_hash

    sidecar = moved.parent / (moved.stem + ".failure.yaml")
    assert sidecar.is_file()
    sidecar_payload: Any = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    assert sidecar_payload["reason"] == "timeout"
    assert sidecar_payload["detail"] == "harness exceeded 600s"
    assert "failed_at_iso" in sidecar_payload


def test_move_to_failures_without_detail(dispatch_workspace: Path) -> None:
    """``detail=None`` is preserved as null in the sidecar."""
    entry = make_entry(inputs_hash="d" * 64)
    queue_path = enqueue(dispatch_workspace, entry)
    moved = move_to_failures(
        dispatch_workspace,
        queue_path,
        reason="output-parse-error",
    )
    sidecar = moved.parent / (moved.stem + ".failure.yaml")
    sidecar_payload: Any = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    assert sidecar_payload["reason"] == "output-parse-error"
    assert sidecar_payload["detail"] is None


def test_move_to_outputs_writes_payload_and_unlinks_queue(
    dispatch_workspace: Path,
) -> None:
    """Output appears under dispatch/outputs/; queue entry is removed."""
    entry = make_entry(role="extractor", inputs_hash="e" * 64)
    queue_path = enqueue(dispatch_workspace, entry)

    payload: dict[str, Any] = {"atoms": [{"id": "a-1", "predicate": "p"}]}
    out_path = move_to_outputs(
        dispatch_workspace,
        queue_path,
        role=entry.role,
        inputs_hash=entry.inputs_hash,
        output_payload=payload,
    )
    assert not queue_path.exists()
    assert out_path.is_file()
    assert out_path.name == "output.yaml"
    assert out_path.parent.name == f"extractor-{entry.inputs_hash}"

    # The bytes round-trip via safe-load.
    loaded: Any = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert loaded == payload


def test_list_queue_returns_lex_sorted(dispatch_workspace: Path) -> None:
    """Three entries enqueued; list_queue returns them in lex (name) order."""
    a = make_entry(role="auditor", inputs_hash="a" * 64)
    b = make_entry(role="extractor", inputs_hash="b" * 64)
    c = make_entry(role="extractor", inputs_hash="c" * 64)
    enqueue(dispatch_workspace, a)
    enqueue(dispatch_workspace, b)
    enqueue(dispatch_workspace, c)

    entries = list_queue(dispatch_workspace)
    assert len(entries) == 3
    names = [p.name for p, _ in entries]
    assert names == sorted(names), f"expected lex-sorted, got {names}"


def test_list_queue_empty(dispatch_workspace: Path) -> None:
    """No queue directory: empty list."""
    assert list_queue(dispatch_workspace) == []


def test_dequeue_picks_oldest_by_mtime(dispatch_workspace: Path) -> None:
    """Two entries with different mtimes: dequeue returns the older one."""
    import os
    import time

    e1 = make_entry(role="auditor", inputs_hash="1" * 64)
    p1 = enqueue(dispatch_workspace, e1)
    # Backdate p1's mtime so it is unambiguously older even within the
    # same filesystem tick.
    old_time = time.time() - 60
    os.utime(p1, (old_time, old_time))

    e2 = make_entry(role="auditor", inputs_hash="2" * 64)
    enqueue(dispatch_workspace, e2)

    picked = dequeue(dispatch_workspace)
    assert picked is not None
    chosen_path, _entry = picked
    assert chosen_path == p1, "oldest entry should be dequeued first"


def test_enqueue_overwrite_idempotent(dispatch_workspace: Path) -> None:
    """Re-enqueueing the same hash overwrites; only one queue file."""
    e1 = make_entry(role="extractor", inputs_hash="f" * 64, prompt="v1")
    enqueue(dispatch_workspace, e1)
    e2 = make_entry(role="extractor", inputs_hash="f" * 64, prompt="v2")
    enqueue(dispatch_workspace, e2)

    entries = list_queue(dispatch_workspace)
    assert len(entries) == 1
    _path, parsed = entries[0]
    assert parsed.prompt == "v2"
