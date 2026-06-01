"""Cluster enumeration for the Connector dispatch phase (Phase 2b M6 / T6.1).

The orchestrator walks ``mappings/entities`` + ``mappings/resolutions`` and
yields a :class:`ConnectCluster` per canonical entity that has atoms in
two or more distinct distillations. Single-source clusters are filtered
out (the Connector role is cross-doc only; see ``map_connect.md``).

Determinism contract: clusters are yielded in lexicographic order by
``entity_id`` so the dispatch queue is stable across runs and CI replays.

These tests exercise the helper directly (no dispatch driver). They are
the upstream half of the T5.4 smoke test, which exercised the downstream
reconcile path on a hand-placed output file.
"""

from __future__ import annotations

from pathlib import Path

from amanuensis.dispatch.connect_orchestrator import (
    ConnectCluster,
    enumerate_connect_clusters,
)
from amanuensis.fs import Substrate


def test_enumerate_clusters_yields_atoms_per_entity(
    tmp_workspace_with_3_distillations_and_resolutions: Path,
) -> None:
    """Multi-source clusters land; each cluster carries every resolved atom."""
    sub = Substrate(tmp_workspace_with_3_distillations_and_resolutions)
    clusters = list(enumerate_connect_clusters(sub))
    by_entity = {c.entity_id: c for c in clusters}
    assert "e-smith" in by_entity
    assert "e-jones" in by_entity
    assert by_entity["e-smith"].entity_kind == "party"
    # e-smith spans 3 atoms across 3 sources.
    smith_atoms = by_entity["e-smith"].atoms
    assert len(smith_atoms) == 3
    smith_sources = {a["source_id"] for a in smith_atoms}
    assert smith_sources == {"src-1", "src-2", "src-3"}
    # Each atom dict carries the documented keys.
    for a in smith_atoms:
        assert set(a.keys()) >= {
            "atom_id",
            "source_id",
            "text",
            "predicate",
            "operand_refs",
        }
        assert isinstance(a["operand_refs"], list)


def test_enumerate_clusters_skips_single_source(
    tmp_workspace_with_single_source_cluster: Path,
) -> None:
    """A cluster whose atoms are all in one source must be filtered out."""
    sub = Substrate(tmp_workspace_with_single_source_cluster)
    assert list(enumerate_connect_clusters(sub)) == []


def test_enumerate_clusters_multi_source_requirement(
    tmp_workspace_with_3_distillations_and_resolutions: Path,
) -> None:
    """Every emitted cluster references at least two distinct source_ids.

    This re-checks the multi-source predicate on every cluster the
    enumerator produces (defensive — the loner cluster in the fixture
    must not surface).
    """
    sub = Substrate(tmp_workspace_with_3_distillations_and_resolutions)
    clusters = list(enumerate_connect_clusters(sub))
    assert clusters, "expected at least one multi-source cluster"
    for c in clusters:
        sources = {a["source_id"] for a in c.atoms}
        assert len(sources) >= 2, f"cluster {c.entity_id!r} has only one source: {sources!r}"
        assert c.entity_id != "e-loner", "single-source loner cluster leaked through enumeration"


def test_enumerate_clusters_is_deterministic_by_entity_id(
    tmp_workspace_with_3_distillations_and_resolutions: Path,
) -> None:
    """Re-running enumeration yields identical entity ids in identical order."""
    sub = Substrate(tmp_workspace_with_3_distillations_and_resolutions)
    ids_run_1 = [c.entity_id for c in enumerate_connect_clusters(sub)]
    ids_run_2 = [c.entity_id for c in enumerate_connect_clusters(sub)]
    assert ids_run_1 == ids_run_2
    assert ids_run_1 == sorted(ids_run_1)


def test_connect_cluster_dataclass_shape() -> None:
    """``ConnectCluster`` is frozen and carries the three documented fields."""
    c = ConnectCluster(entity_id="e-x", entity_kind="party", atoms=[])
    assert c.entity_id == "e-x"
    assert c.entity_kind == "party"
    assert c.atoms == []
