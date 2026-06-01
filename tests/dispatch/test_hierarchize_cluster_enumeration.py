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

from datetime import UTC, datetime
from pathlib import Path

import pytest

from amanuensis.dispatch.hierarchize_orchestrator import (
    HierarchizeCluster,
    enumerate_hierarchize_clusters,
)
from amanuensis.fs import Substrate
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import serialize_atom_md
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    OperandRef,
    Probandum,
    ProbandumEdge,
    RoleAttribution,
    compute_id,
)

# Stable timestamp pinned across fixtures (content-addressable ids depend
# on RoleAttribution.at, so this keeps fixture ids stable).
_STABLE_AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def _role_attr() -> RoleAttribution:
    return RoleAttribution(
        agent=AgentAttribution(kind="llm", identifier="hierarchize", role="hierarchize"),
        activity="proposed",
        at=_STABLE_AT,
    )


def _plant_atom(workspace: Path, atom: Atom) -> None:
    """Write an atom directly under ``distillations/<src>/atoms/``."""
    path = workspace / "distillations" / atom.source_id / "atoms" / f"{atom.id}.md"
    atomic_write_text(path, serialize_atom_md(atom))


def _build_atom(*, atom_id: str, source_id: str, narrative: str, char_offset: int = 0) -> Atom:
    return Atom(
        id=atom_id,
        source_id=source_id,
        section_path=["body"],
        paragraph_index=0,
        sentence_index=None,
        char_span=(char_offset, char_offset + 30),
        scale_anchor="paragraph",
        kind="claim",
        predicate="alleges",
        operands=[OperandRef(role="subject", kind="entity", value="e-x", type_hint=None)],
        narrative=narrative,
        qualifier_level=None,
        qualifier_basis=None,
        provenance_id="p-fixture00000010",
        role_attributions=[_role_attr()],
        schema_version=1,
    )


@pytest.fixture
def tmp_workspace_with_probandum_tree(tmp_path: Path) -> dict[str, str]:
    """Plant a workspace with:

    - 1 ultimate probandum
    - 2 penultimate probanda, both linked upward to the ultimate via
      probandum-edges
    - 2 atoms in src-A; each penultimate has one atom-child via an
      outgoing edge so both clusters have non-empty evidence
    - the bundled Walton-scheme snapshot pinned

    Returns a dict mapping role names to substrate ids so the tests can
    reference real ids without re-deriving content-addressable hashes.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: t8-1-probandum-tree\n",
        encoding="utf-8",
    )
    (tmp_path / "distillations" / "src-A").mkdir(parents=True, exist_ok=True)

    sub = Substrate(tmp_path)
    sub.snapshot_walton_schemes()

    role_attr = _role_attr()

    # Atoms.
    atom_pen1 = _build_atom(
        atom_id="a-pen1evidence001",
        source_id="src-A",
        narrative="Smith failed to deliver the April 2024 shipment.",
        char_offset=0,
    )
    atom_pen2 = _build_atom(
        atom_id="a-pen2evidence002",
        source_id="src-A",
        narrative="Smith refused to remit the late-payment fees.",
        char_offset=100,
    )
    _plant_atom(tmp_path, atom_pen1)
    _plant_atom(tmp_path, atom_pen2)

    # Ultimate.
    ultimate_draft = Probandum(
        id="p-placeholder",
        statement="ACME prevails on its breach claim against Smith.",
        kind="ultimate",
        scheme="argument-from-expert-opinion",
        alternatives_considered=[],
        confidence="high",
        provenance_id="p-fixture00000099",
        role_attributions=[role_attr],
        schema_version=1,
    )
    ultimate = ultimate_draft.model_copy(update={"id": compute_id(ultimate_draft)})
    sub.add_probandum(ultimate)

    # Two penultimates.
    pen1_draft = Probandum(
        id="p-placeholder",
        statement="Smith breached §3 by failing to deliver the April 2024 shipment.",
        kind="penultimate",
        scheme="argument-from-sign",
        alternatives_considered=[
            "Smith tendered but ACME rejected for unrelated quality reasons.",
            "Smith and ACME mutually deferred the April 2024 delivery.",
        ],
        confidence="high",
        provenance_id="p-fixture00000099",
        role_attributions=[role_attr],
        schema_version=1,
    )
    pen1 = pen1_draft.model_copy(update={"id": compute_id(pen1_draft)})
    sub.add_probandum(pen1)

    pen2_draft = Probandum(
        id="p-placeholder",
        statement="Smith breached §5 by refusing late-payment fee remittance.",
        kind="penultimate",
        scheme="argument-from-sign",
        alternatives_considered=[
            "The §5 fee schedule was orally waived by the parties.",
            "ACME's invoicing irregularities triggered a good-faith dispute.",
        ],
        confidence="medium",
        provenance_id="p-fixture00000099",
        role_attributions=[role_attr],
        schema_version=1,
    )
    pen2 = pen2_draft.model_copy(update={"id": compute_id(pen2_draft)})
    sub.add_probandum(pen2)

    # Linking edges ultimate -> each penultimate (so INV-17 lineage
    # holds for any further edges anchored at the penultimates).
    def _edge(
        parent_id: str, child_id: str, child_kind: str, child_source_id: str | None, suffix: str
    ) -> ProbandumEdge:
        draft = ProbandumEdge(
            id="q-placeholder",
            parent_probandum_id=parent_id,
            child_id=child_id,
            child_kind=child_kind,  # pyright: ignore[reportArgumentType]
            child_source_id=child_source_id,
            kind="supports",
            warrant=f"Decomposition warrant for {suffix}.",
            warrant_defensibility="methodology-derived",
            warrant_basis="Wigmore §III decomposition.",
            confidence="high",
            provenance_id="p-fixture00000099",
            role_attributions=[role_attr],
            schema_version=1,
        )
        return draft.model_copy(update={"id": compute_id(draft)})

    sub.add_probandum_edge(_edge(ultimate.id, pen1.id, "probandum", None, "ult->pen1"))
    sub.add_probandum_edge(_edge(ultimate.id, pen2.id, "probandum", None, "ult->pen2"))

    # Each penultimate has one atom-child so candidate_evidence is non-empty.
    sub.add_probandum_edge(_edge(pen1.id, atom_pen1.id, "atom", "src-A", "pen1->atom1"))
    sub.add_probandum_edge(_edge(pen2.id, atom_pen2.id, "atom", "src-A", "pen2->atom2"))

    return {
        "workspace": str(tmp_path),
        "ultimate": ultimate.id,
        "pen1": pen1.id,
        "pen2": pen2.id,
        "atom1": atom_pen1.id,
        "atom2": atom_pen2.id,
    }


@pytest.fixture
def tmp_workspace_with_orphan_penultimate(tmp_path: Path) -> Path:
    """Penultimate with NO upward link to an ultimate; must be skipped."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: t8-1-orphan\n",
        encoding="utf-8",
    )
    (tmp_path / "distillations" / "src-A").mkdir(parents=True, exist_ok=True)

    sub = Substrate(tmp_path)
    sub.snapshot_walton_schemes()
    role_attr = _role_attr()

    # Plant an atom so the penultimate has children even without an ultimate.
    atom = _build_atom(
        atom_id="a-orphanevid0001",
        source_id="src-A",
        narrative="Orphan-supporting fact.",
        char_offset=0,
    )
    _plant_atom(tmp_path, atom)

    # Penultimate only (no ultimate planted, no incoming edges).
    pen_draft = Probandum(
        id="p-placeholder",
        statement="Orphan penultimate with no upward lineage.",
        kind="penultimate",
        scheme="argument-from-sign",
        alternatives_considered=[
            "Some realistic alternative one.",
            "Some realistic alternative two.",
        ],
        confidence="medium",
        provenance_id="p-fixture00000099",
        role_attributions=[role_attr],
        schema_version=1,
    )
    pen = pen_draft.model_copy(update={"id": compute_id(pen_draft)})
    sub.add_probandum(pen)

    # No upward edge to plant — that's what makes this an orphan. We
    # can't even add an atom-child edge to the orphan without
    # tripping INV-17 (the gate refuses edges whose parent's lineage
    # doesn't reach an ultimate). So the orphan has neither incoming
    # nor outgoing edges. That's the most realistic orphan shape.
    return tmp_path


@pytest.fixture
def tmp_workspace_with_childless_penultimate(tmp_path: Path) -> Path:
    """Penultimate with upward lineage but NO outgoing children — skipped."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: t8-1-childless\n",
        encoding="utf-8",
    )
    (tmp_path / "distillations" / "src-A").mkdir(parents=True, exist_ok=True)

    sub = Substrate(tmp_path)
    sub.snapshot_walton_schemes()
    role_attr = _role_attr()

    ultimate_draft = Probandum(
        id="p-placeholder",
        statement="Ultimate with one childless penultimate.",
        kind="ultimate",
        scheme="argument-from-expert-opinion",
        alternatives_considered=[],
        confidence="high",
        provenance_id="p-fixture00000099",
        role_attributions=[role_attr],
        schema_version=1,
    )
    ultimate = ultimate_draft.model_copy(update={"id": compute_id(ultimate_draft)})
    sub.add_probandum(ultimate)

    pen_draft = Probandum(
        id="p-placeholder",
        statement="Childless penultimate with valid upward lineage.",
        kind="penultimate",
        scheme="argument-from-sign",
        alternatives_considered=[
            "Some realistic alternative one.",
            "Some realistic alternative two.",
        ],
        confidence="medium",
        provenance_id="p-fixture00000099",
        role_attributions=[role_attr],
        schema_version=1,
    )
    pen = pen_draft.model_copy(update={"id": compute_id(pen_draft)})
    sub.add_probandum(pen)

    linking_draft = ProbandumEdge(
        id="q-placeholder",
        parent_probandum_id=ultimate.id,
        child_id=pen.id,
        child_kind="probandum",
        child_source_id=None,
        kind="supports",
        warrant="Linking warrant.",
        warrant_defensibility="methodology-derived",
        warrant_basis="Wigmore §III decomposition.",
        confidence="high",
        provenance_id="p-fixture00000099",
        role_attributions=[role_attr],
        schema_version=1,
    )
    linking = linking_draft.model_copy(update={"id": compute_id(linking_draft)})
    sub.add_probandum_edge(linking)

    return tmp_path


# --- T8.1 tests --------------------------------------------------------


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
