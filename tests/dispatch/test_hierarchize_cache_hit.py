# pyright: reportUntypedFunctionDecorator=false
"""Hierarchize phase respects the inputs-hash cache (Phase 2c M8 / T8.4, INV-4).

The Hierarchize phase's per-cluster ``inputs_hash`` is content-addressable
on the cluster's canonical form (parent + ultimate + evidence +
walton_schemes). The cache invariant (INV-4) for the overall dispatch
architecture says: identical inputs → identical ``inputs_hash`` → cache
hit (no fresh harness invocation; existing output is reused).

This test exercises the orchestrator-level guarantee: a second
``run_hierarchize_phase`` against unchanged substrate state writes the
SAME queue entries (byte-identical filenames; the queue layer's atomic
overwrite means the on-disk count stays stable). The real harness
short-circuit happens further downstream in
``amanuensis.llm.cached_call``; the Hierarchize phase respects it out
of the box because the inputs_hash is deterministic per cluster.

What this test does NOT prove: that the harness itself was not invoked.
Because we don't run the harness in tests (M11.2's first-engagement
contract), the meaningful surface is "did the orchestrator stay on the
cache-friendly path".
"""

from __future__ import annotations

from pathlib import Path

from amanuensis.dispatch.hierarchize_orchestrator import (
    enqueue_hierarchize_clusters,
    run_hierarchize_phase,
)
from amanuensis.fs import Substrate


def test_hierarchize_phase_cache_hit_on_second_run(
    tmp_workspace_with_probandum_tree: dict[str, str],
) -> None:
    """Two consecutive runs produce identical inputs_hash filenames (cache-friendly)."""
    workspace = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace)
    queue_dir = workspace / "dispatch" / "queue"

    report_a = run_hierarchize_phase(sub)
    names_a = sorted(p.name for p in queue_dir.glob("hierarchize-*.yaml"))

    report_b = run_hierarchize_phase(sub)
    names_b = sorted(p.name for p in queue_dir.glob("hierarchize-*.yaml"))

    assert report_a.enqueued == report_b.enqueued
    assert names_a == names_b, (
        "second hierarchize-phase run wrote different inputs_hash filenames; "
        "the cluster canonical-form hash is not deterministic"
    )


def test_hierarchize_phase_idempotent_on_repeat_invocation(
    tmp_workspace_with_probandum_tree: dict[str, str],
) -> None:
    """Repeated ``run_hierarchize_phase`` calls do not grow on-disk queue count.

    The cache invariant INV-4 means re-enqueueing identical clusters
    overwrites the existing queue entry rather than appending a sibling.
    Operators can re-run ``amanuensis map`` without paying a fresh
    harness invocation for already-dispatched clusters.
    """
    workspace = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace)
    queue_dir = workspace / "dispatch" / "queue"

    n_first = enqueue_hierarchize_clusters(sub)
    on_disk_first = len(list(queue_dir.glob("hierarchize-*.yaml")))

    # Multiple repeat invocations.
    for _ in range(3):
        run_hierarchize_phase(sub)
    on_disk_after = len(list(queue_dir.glob("hierarchize-*.yaml")))

    assert on_disk_first == n_first == on_disk_after, (
        f"queue count drifted across repeat runs: first={n_first} "
        f"on_disk_first={on_disk_first} on_disk_after={on_disk_after}"
    )


def test_hierarchize_phase_cache_hit_via_mocked_harness(
    tmp_workspace_with_probandum_tree: dict[str, str],
    monkeypatch,
) -> None:
    """Mock-harness call-count is stable across re-runs of identical substrate state.

    Phase 2c M8 T8.4: simulates the cache short-circuit by monkeypatching
    the harness invocation surface so we can count the number of times
    a fresh "harness call" would have happened. Because the orchestrator
    relies on the same inputs_hash filename across runs, the queue layer
    overwrites the existing entry byte-for-byte and the downstream cache
    layer keys off that hash. The orchestrator therefore preserves the
    cache contract for free; we count enqueue invocations as a proxy for
    "fresh harness work".

    The orchestrator does NOT actually invoke a harness — that's the
    supervisor's job between phases. So the "invocation count" we
    measure is the number of cluster enqueues, which equals the number
    of harness invocations that WOULD occur if the supervisor drove
    every fresh queue entry through the harness. Stable count across
    re-runs = stable inputs_hash = cache contract upheld.
    """
    from amanuensis.dispatch import hierarchize_orchestrator as orch

    workspace = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace)

    invocation_count = 0
    real_enqueue = orch.enqueue

    def counting_enqueue(workspace_root: Path, entry):
        nonlocal invocation_count
        invocation_count += 1
        return real_enqueue(workspace_root, entry)

    monkeypatch.setattr(orch, "enqueue", counting_enqueue)

    run_hierarchize_phase(sub)
    first_count = invocation_count
    assert first_count > 0, "fixture should yield at least one cluster"

    run_hierarchize_phase(sub)
    # Re-running against identical substrate state: enqueues the SAME
    # number of clusters (byte-identical overwrites at the queue
    # layer); downstream cache short-circuits the harness call.
    assert invocation_count == 2 * first_count, (
        f"expected enqueue count to double exactly (one fresh enqueue per cluster "
        f"per run, byte-identical hashes); got first_count={first_count} "
        f"total={invocation_count}"
    )

    # The on-disk queue file count, however, is stable (overwrite, not append).
    queue_dir = workspace / "dispatch" / "queue"
    on_disk = len(list(queue_dir.glob("hierarchize-*.yaml")))
    assert on_disk == first_count, (
        f"on-disk queue count should equal first_count (atomic overwrite); "
        f"got on_disk={on_disk} first_count={first_count}"
    )
