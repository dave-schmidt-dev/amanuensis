# pyright: reportPrivateUsage=false, reportUntypedFunctionDecorator=false
"""Cluster enumeration for the Hierarchize dispatch phase (Phase 2c M8 / T8.1).

The orchestrator walks ``mappings/probanda/`` for every penultimate
probandum and, for each penultimate that traces upward to an ``ultimate``
AND has at least one existing child (atom / cross-doc-relation /
interim probandum), yields a :class:`HierarchizeCluster` carrying the
parent + ultimate + candidate evidence + active Walton schemes.

Determinism contract: clusters are yielded in lexicographic order by
``parent_probandum_id`` so the dispatch queue is stable across runs and
CI replays.

These tests exercise the helper directly (no dispatch driver). They are
the upstream half of the Phase 2c M7 smoke test, which exercised the
downstream reconcile path on a hand-placed output file.
"""

from __future__ import annotations

from pathlib import Path

from amanuensis.dispatch.hierarchize_orchestrator import (
    HierarchizeCluster,
    enumerate_hierarchize_clusters,
)
from amanuensis.fs import Substrate


def test_enumerate_yields_cluster_per_penultimate(
    tmp_workspace_with_probandum_tree: dict[str, str],
) -> None:
    """A workspace with 2 penultimates yields exactly 2 clusters."""
    workspace = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace)

    clusters = list(enumerate_hierarchize_clusters(sub))
    assert len(clusters) == 2

    parent_ids = {c.parent_probandum_id for c in clusters}
    assert parent_ids == {
        tmp_workspace_with_probandum_tree["pen1"],
        tmp_workspace_with_probandum_tree["pen2"],
    }
    # Every cluster's ultimate is the planted ultimate.
    for c in clusters:
        assert c.ultimate_probandum["id"] == tmp_workspace_with_probandum_tree["ultimate"]
        assert c.parent_statement
        # candidate_evidence is non-empty and well-shaped.
        assert c.candidate_evidence
        for ev in c.candidate_evidence:
            assert ev["kind"] in {"atom", "cross-doc-relation", "probandum"}
            assert "id" in ev


def test_skips_orphan_penultimate(
    tmp_workspace_with_orphan_penultimate: Path,
) -> None:
    """A penultimate with no upward path to an ultimate is filtered out."""
    sub = Substrate(tmp_workspace_with_orphan_penultimate)
    clusters = list(enumerate_hierarchize_clusters(sub))
    assert clusters == [], f"orphan penultimate should not yield a cluster; got {clusters!r}"


def test_skips_empty_evidence_clusters(
    tmp_workspace_with_childless_penultimate: Path,
) -> None:
    """A penultimate with valid lineage but no outgoing children is filtered out."""
    sub = Substrate(tmp_workspace_with_childless_penultimate)
    clusters = list(enumerate_hierarchize_clusters(sub))
    assert clusters == [], f"childless penultimate should not yield a cluster; got {clusters!r}"


def test_deterministic_ordering(
    tmp_workspace_with_probandum_tree: dict[str, str],
) -> None:
    """Re-running enumeration yields identical parent ids in identical order."""
    workspace = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace)

    run1 = [c.parent_probandum_id for c in enumerate_hierarchize_clusters(sub)]
    run2 = [c.parent_probandum_id for c in enumerate_hierarchize_clusters(sub)]
    assert run1 == run2
    assert run1 == sorted(run1), (
        f"clusters should be yielded in lexicographic parent_probandum_id order; got {run1!r}"
    )


def test_walton_schemes_populated_from_snapshot(
    tmp_workspace_with_probandum_tree: dict[str, str],
) -> None:
    """Cluster's ``walton_schemes`` list mirrors the active snapshot's scheme names."""
    workspace = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace)
    snapshot = sub.load_walton_scheme_snapshot()
    assert snapshot is not None
    expected = {s.name for s in snapshot.schemes}

    clusters = list(enumerate_hierarchize_clusters(sub))
    assert clusters
    for c in clusters:
        assert set(c.walton_schemes) == expected
        # No duplicates.
        assert len(set(c.walton_schemes)) == len(c.walton_schemes)


def test_hierarchize_cluster_dataclass_shape() -> None:
    """``HierarchizeCluster`` is frozen and carries the documented fields."""
    c = HierarchizeCluster(
        parent_probandum_id="p-x",
        parent_statement="some statement",
        ultimate_probandum={"id": "p-u", "statement": "ultimate"},
        candidate_evidence=[],
        walton_schemes=["argument-from-sign"],
    )
    assert c.parent_probandum_id == "p-x"
    assert c.parent_statement == "some statement"
    assert c.ultimate_probandum == {"id": "p-u", "statement": "ultimate"}
    assert c.candidate_evidence == []
    assert c.walton_schemes == ["argument-from-sign"]
