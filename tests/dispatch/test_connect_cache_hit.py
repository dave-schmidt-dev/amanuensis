"""Connect phase respects the inputs-hash cache (Phase 2b M6 / T6.4, INV-4).

The Connect phase's per-cluster ``inputs_hash`` is content-addressable
on the cluster's canonical form. The cache invariant (INV-4) for the
overall dispatch architecture says: identical inputs → identical
``inputs_hash`` → cache hit (no fresh harness invocation; existing
output is reused).

This test exercises the orchestrator-level guarantee: a second
``run_connect_phase`` against unchanged substrate state writes the
SAME queue entries (byte-identical filenames; the queue layer's
atomic overwrite means the on-disk count stays stable). The real
harness short-circuit happens further downstream in
``amanuensis.llm.cached_call``; the Connect phase respects it out of
the box because the inputs_hash is deterministic per cluster.

What this test does NOT prove: that the harness itself was not
invoked. Because we don't run the harness in tests (M11.2's
first-engagement contract), the meaningful surface is "did the
orchestrator stay on the cache-friendly path". That's what we assert.
"""

from __future__ import annotations

from pathlib import Path

from amanuensis.dispatch.connect_orchestrator import (
    enqueue_connect_clusters,
    run_connect_phase,
)
from amanuensis.fs import Substrate


def test_connect_phase_inputs_hash_stable_across_runs(
    tmp_workspace_with_3_distillations_and_resolutions: Path,
) -> None:
    """Two consecutive runs produce identical inputs_hash filenames."""
    sub = Substrate(tmp_workspace_with_3_distillations_and_resolutions)
    queue_dir = tmp_workspace_with_3_distillations_and_resolutions / "dispatch" / "queue"

    report_a = run_connect_phase(sub)
    names_a = sorted(p.name for p in queue_dir.glob("connect-*.yaml"))

    report_b = run_connect_phase(sub)
    names_b = sorted(p.name for p in queue_dir.glob("connect-*.yaml"))

    assert report_a.enqueued == report_b.enqueued
    assert names_a == names_b, (
        "second connect-phase run wrote different inputs_hash filenames; "
        "the cluster canonical-form hash is not deterministic"
    )


def test_connect_phase_idempotent_on_repeat_invocation(
    tmp_workspace_with_3_distillations_and_resolutions: Path,
) -> None:
    """Repeated ``run_connect_phase`` calls do not grow on-disk queue count.

    The cache invariant INV-4 means re-enqueueing identical clusters
    overwrites the existing queue entry rather than appending a sibling.
    Operators can re-run ``amanuensis map`` without paying a fresh
    harness invocation for already-dispatched clusters.
    """
    sub = Substrate(tmp_workspace_with_3_distillations_and_resolutions)
    queue_dir = tmp_workspace_with_3_distillations_and_resolutions / "dispatch" / "queue"

    n_first = enqueue_connect_clusters(sub)
    on_disk_first = len(list(queue_dir.glob("connect-*.yaml")))

    # Multiple repeat invocations.
    for _ in range(3):
        run_connect_phase(sub)
    on_disk_after = len(list(queue_dir.glob("connect-*.yaml")))

    assert on_disk_first == n_first == on_disk_after, (
        f"queue count drifted across repeat runs: first={n_first} "
        f"on_disk_first={on_disk_first} on_disk_after={on_disk_after}"
    )


def test_connect_phase_empty_workspace_is_clean_noop(tmp_path: Path) -> None:
    """``run_connect_phase`` on an empty workspace returns a zero-enqueued report."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text("schema_version: 1\nproject_name: connect-cache-empty\n")
    sub = Substrate(tmp_path)
    report = run_connect_phase(sub)
    assert report.enqueued == 0
    assert report.outputs_consumed == 0
    assert report.relations_committed == []
    assert report.errors == []
