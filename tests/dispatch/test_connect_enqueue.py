"""Per-cluster enqueue for the Connector dispatch phase (Phase 2b M6 / T6.2).

Verifies that :func:`enqueue_connect_clusters` writes one queue entry per
multi-source cluster, that the ``inputs_hash`` is content-addressable
(stable across re-runs of identical substrate state), and that the queue
layer's idempotent overwrite semantics keep the on-disk entry count
stable on re-enqueue.

See also:
    ``tests/dispatch/test_cluster_enumeration.py`` — the upstream
    enumeration helper this enqueue path consumes.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from amanuensis.dispatch.connect_orchestrator import (
    enqueue_connect_clusters,
    enumerate_connect_clusters,
)
from amanuensis.fs import Substrate


def test_enqueue_writes_one_queue_entry_per_cluster(
    tmp_workspace_with_3_distillations_and_resolutions: Path,
) -> None:
    """One queue entry per multi-source cluster lands under dispatch/queue/."""
    sub = Substrate(tmp_workspace_with_3_distillations_and_resolutions)
    cluster_count = sum(1 for _ in enumerate_connect_clusters(sub))
    assert cluster_count >= 2  # e-smith + e-jones at minimum

    n = enqueue_connect_clusters(sub)
    queue_dir = tmp_workspace_with_3_distillations_and_resolutions / "dispatch" / "queue"
    entries = list(queue_dir.glob("connect-*.yaml"))
    assert len(entries) == n == cluster_count


def test_enqueue_skips_when_no_multi_source_clusters(
    tmp_workspace_with_single_source_cluster: Path,
) -> None:
    """A workspace with no multi-source clusters writes no queue entries."""
    sub = Substrate(tmp_workspace_with_single_source_cluster)
    n = enqueue_connect_clusters(sub)
    assert n == 0
    queue_dir = tmp_workspace_with_single_source_cluster / "dispatch" / "queue"
    if queue_dir.is_dir():
        entries = list(queue_dir.glob("connect-*.yaml"))
        assert entries == []


def test_enqueue_is_idempotent_via_inputs_hash(
    tmp_workspace_with_3_distillations_and_resolutions: Path,
) -> None:
    """Re-running enqueue keeps the on-disk entry count stable.

    The ``inputs_hash`` is content-addressable, so a second enqueue
    against an unchanged substrate state writes byte-identical files
    over the existing queue entries (atomic overwrite via the queue
    layer). The number of entries on disk should not double.
    """
    sub = Substrate(tmp_workspace_with_3_distillations_and_resolutions)
    n_first = enqueue_connect_clusters(sub)
    n_second = enqueue_connect_clusters(sub)
    assert n_first == n_second
    queue_dir = tmp_workspace_with_3_distillations_and_resolutions / "dispatch" / "queue"
    entries = list(queue_dir.glob("connect-*.yaml"))
    assert len(entries) == n_first, (
        f"second enqueue should not double the on-disk entry count; "
        f"got {len(entries)} entries after {n_second} clusters re-enqueued"
    )


def test_enqueue_inputs_hash_is_deterministic(
    tmp_workspace_with_3_distillations_and_resolutions: Path,
) -> None:
    """Hash filenames are stable across re-runs of identical substrate state."""
    sub = Substrate(tmp_workspace_with_3_distillations_and_resolutions)
    queue_dir = tmp_workspace_with_3_distillations_and_resolutions / "dispatch" / "queue"

    enqueue_connect_clusters(sub)
    first_names = sorted(p.name for p in queue_dir.glob("connect-*.yaml"))

    # Drop the queue and re-enqueue from scratch — hashes must match.
    for p in queue_dir.glob("connect-*.yaml"):
        p.unlink()
    enqueue_connect_clusters(sub)
    second_names = sorted(p.name for p in queue_dir.glob("connect-*.yaml"))

    assert first_names == second_names, (
        "queue entry filenames (which embed inputs_hash) should be stable "
        "across enqueue runs against identical substrate state"
    )


def test_enqueue_payload_shape(
    tmp_workspace_with_3_distillations_and_resolutions: Path,
) -> None:
    """Queue entry payload carries the cluster shape the Connector role consumes."""
    sub = Substrate(tmp_workspace_with_3_distillations_and_resolutions)
    enqueue_connect_clusters(sub)

    queue_dir = tmp_workspace_with_3_distillations_and_resolutions / "dispatch" / "queue"
    entries = sorted(queue_dir.glob("connect-*.yaml"))
    assert entries, "expected at least one queue entry"

    # Inspect one entry — they all share the same shape.
    raw = yaml.safe_load(entries[0].read_text(encoding="utf-8"))
    assert raw["role"] == "connect"
    assert "inputs_hash" in raw
    assert raw.get("prompt"), "prompt body should be embedded"
    inputs = raw["inputs"]
    assert set(inputs.keys()) >= {"entity_id", "entity_kind", "atoms"}
    for atom in inputs["atoms"]:
        assert set(atom.keys()) >= {
            "atom_id",
            "source_id",
            "text",
            "predicate",
            "operand_refs",
        }
