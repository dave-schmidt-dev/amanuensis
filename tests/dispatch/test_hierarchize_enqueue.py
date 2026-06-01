# pyright: reportPrivateUsage=false, reportUntypedFunctionDecorator=false
"""Per-cluster enqueue for the Hierarchize dispatch phase (Phase 2c M8 / T8.2).

Verifies that :func:`enqueue_hierarchize_clusters` writes one queue
entry per qualifying penultimate cluster, that the ``inputs_hash`` is
content-addressable (stable across re-runs of identical substrate
state), and that the queue layer's idempotent overwrite semantics keep
the on-disk entry count stable on re-enqueue.

See also:
    ``tests/dispatch/test_hierarchize_cluster_enumeration.py`` — the
    upstream enumeration helper this enqueue path consumes.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from amanuensis.dispatch.hierarchize_orchestrator import (
    enqueue_hierarchize_clusters,
    enumerate_hierarchize_clusters,
)
from amanuensis.fs import Substrate


def test_enqueue_writes_one_entry_per_cluster(
    tmp_workspace_with_probandum_tree: dict[str, str],
) -> None:
    """One queue entry per qualifying cluster lands under dispatch/queue/."""
    workspace = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace)
    cluster_count = sum(1 for _ in enumerate_hierarchize_clusters(sub))
    assert cluster_count == 2  # the two penultimate clusters from the fixture

    n = enqueue_hierarchize_clusters(sub)
    queue_dir = workspace / "dispatch" / "queue"
    entries = list(queue_dir.glob("hierarchize-*.yaml"))
    assert len(entries) == n == cluster_count


def test_enqueue_is_idempotent(
    tmp_workspace_with_probandum_tree: dict[str, str],
) -> None:
    """Re-running enqueue keeps the on-disk entry count stable.

    The ``inputs_hash`` is content-addressable, so a second enqueue
    against an unchanged substrate state writes byte-identical files
    over the existing queue entries (atomic overwrite via the queue
    layer). The number of entries on disk should not double.
    """
    workspace = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace)
    n_first = enqueue_hierarchize_clusters(sub)
    n_second = enqueue_hierarchize_clusters(sub)
    assert n_first == n_second
    queue_dir = workspace / "dispatch" / "queue"
    entries = list(queue_dir.glob("hierarchize-*.yaml"))
    assert len(entries) == n_first, (
        f"second enqueue should not double the on-disk entry count; "
        f"got {len(entries)} entries after {n_second} clusters re-enqueued"
    )


def test_enqueue_inputs_hash_is_deterministic(
    tmp_workspace_with_probandum_tree: dict[str, str],
) -> None:
    """Hash filenames are stable across re-runs of identical substrate state."""
    workspace = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace)
    queue_dir = workspace / "dispatch" / "queue"

    enqueue_hierarchize_clusters(sub)
    first_names = sorted(p.name for p in queue_dir.glob("hierarchize-*.yaml"))

    # Drop the queue and re-enqueue from scratch — hashes must match.
    for p in queue_dir.glob("hierarchize-*.yaml"):
        p.unlink()
    enqueue_hierarchize_clusters(sub)
    second_names = sorted(p.name for p in queue_dir.glob("hierarchize-*.yaml"))

    assert first_names == second_names, (
        "queue entry filenames (which embed inputs_hash) should be stable "
        "across enqueue runs against identical substrate state"
    )


def test_enqueue_payload_shape(
    tmp_workspace_with_probandum_tree: dict[str, str],
) -> None:
    """Queue entry payload carries the cluster shape the Hierarchize role consumes."""
    workspace = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace)
    enqueue_hierarchize_clusters(sub)

    queue_dir = workspace / "dispatch" / "queue"
    entries = sorted(queue_dir.glob("hierarchize-*.yaml"))
    assert entries, "expected at least one queue entry"

    raw = yaml.safe_load(entries[0].read_text(encoding="utf-8"))
    assert raw["role"] == "hierarchize"
    assert "inputs_hash" in raw
    assert raw.get("prompt"), "prompt body should be embedded"
    inputs = raw["inputs"]
    assert set(inputs.keys()) >= {
        "parent_probandum_id",
        "parent_statement",
        "ultimate_probandum",
        "candidate_evidence",
        "walton_schemes",
    }
    assert isinstance(inputs["candidate_evidence"], list)
    assert isinstance(inputs["walton_schemes"], list)
    assert inputs["walton_schemes"], "walton_schemes should not be empty"
