"""Reconciliation gate for Probandum + ProbandumEdge candidates (Phase 2c M6).

The Hierarchize role surfaces candidate probanda and edges as plain
dicts. ``_build_probandum`` / ``_build_probandum_edge`` are the
reconciler's choke points: they build the typed record, run the M3/M4
substrate gates (INV-16 tree-shape, INV-17 lineage-completeness,
INV-18 closed-vocab, INV-19 ACH alternatives), and on INV-17 / INV-18
failure auto-raise a Clarification rather than propagating. INV-16
(tree-shape) and INV-19 (ACH alternatives) failures propagate — the
auditor is expected to pre-check these shape-class invariants.

Coverage map:

- T6.2 — happy + scheme-missing paths for ``_build_probandum``.
- T6.3 — happy + lineage-incomplete paths for ``_build_probandum_edge``.

T6.4 (supersede flow) and T6.5 (re-add after lineage resolved) are
covered by additional tests in this same file landed in later commits.
"""

# pyright: reportPrivateUsage=false
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from amanuensis.dispatch.reconcile import (
    CandidateShapeError,
    _build_probandum,
    _build_probandum_edge,
)
from amanuensis.fs import Substrate
from amanuensis.schemas import (
    AgentAttribution,
    ProvenanceRecord,
    RoleAttribution,
    compute_id,
)

from .conftest import list_open_clarifications_for_source

# Stable attribution timestamp; pinned so content-addressable ids that
# embed ``RoleAttribution.at`` stay deterministic across runs.
_STABLE_AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


# --- Fixtures local to T6.2-6.5 -----------------------------------------


@pytest.fixture
def hierarchize_agent() -> AgentAttribution:
    """Stable AgentAttribution for the Hierarchize-role reconciler tests.

    The Phase 2c role string ("hierarchize") has not been added to
    ``AgentAttribution.role`` Literal yet (the schema enum is owned by
    a separate brief). The reconciler doesn't care about the literal
    role string — it only uses ``role_attributions[0].agent`` to stamp
    auto-raised clarifications. Using the closest existing role
    (``"auditor"``) keeps these tests focused on the M6 gate semantics
    rather than the role-enum extension.
    """
    return AgentAttribution(
        kind="llm",
        identifier="claude-opus-4-7",
        role="auditor",
    )


@pytest.fixture
def hierarchize_role_attribution(hierarchize_agent: AgentAttribution) -> RoleAttribution:
    """Stable RoleAttribution used by the Phase 2c reconciler tests."""
    return RoleAttribution(
        agent=hierarchize_agent,
        activity="proposed",
        at=_STABLE_AT,
    )


@pytest.fixture
def hierarchize_provenance(hierarchize_agent: AgentAttribution) -> ProvenanceRecord:
    """Synthetic ProvenanceRecord with a stable, computed id for Phase 2c.

    The Phase 2c ``entity_type`` strings (``"probandum"`` /
    ``"probandum-edge"``) are not yet present in the
    ``ProvenanceRecord.entity_type`` Literal (a separate brief owns
    that extension), so this fixture uses ``"cross-doc-relation"`` as
    a stand-in for the test stamp. The reconciler never inspects
    ``prov.entity_type`` — it only uses ``prov.id`` — so the choice
    does not affect the gate semantics under test.
    """
    payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": "cross-doc-relation",
        "entity_id": "p-placeholder",
        "activity": "hierarchize-reconcile",
        "activity_started_at": _STABLE_AT,
        "activity_ended_at": _STABLE_AT,
        "used_entity_ids": [],
        "was_attributed_to": hierarchize_agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    draft = ProvenanceRecord(**payload)
    payload["id"] = compute_id(draft)
    return ProvenanceRecord(**payload)


@pytest.fixture
def tmp_workspace_with_walton_snapshot(tmp_workspace: Path) -> Path:
    """Workspace + a pinned generic Walton-scheme snapshot.

    The INV-18 gate at probandum write-time consults this snapshot. Tests
    that need an active snapshot use this fixture; tests that exercise
    the scheme-missing path can still pin a snapshot here (the gate
    fires on the unknown scheme content, not snapshot absence).
    """
    Substrate(tmp_workspace).snapshot_walton_schemes()
    return tmp_workspace


@pytest.fixture
def tmp_workspace_with_walton_snapshot_and_distillation(
    tmp_workspace_with_walton_snapshot: Path,
) -> Path:
    """Walton-snapshotted workspace + one empty distillation directory.

    The Phase 2c clarification auto-raise helpers file under the first
    distillation when one exists. This fixture gives them a real
    distillation to file under so tests can read the clarification back
    from a predictable path.
    """
    (tmp_workspace_with_walton_snapshot / "distillations" / "src-A").mkdir(
        parents=True, exist_ok=True
    )
    return tmp_workspace_with_walton_snapshot


def _base_probandum_candidate(
    *,
    statement: str = "ACME breached the contract.",
    kind: str = "ultimate",
    scheme: str = "argument-from-expert-opinion",
    alternatives_considered: list[str] | None = None,
    confidence: str = "high",
) -> dict[str, Any]:
    """Return a syntactically-valid Hierarchize probandum candidate dict.

    ``alternatives_considered`` defaults to ``[]`` (legal only for
    ``ultimate``); callers building penultimate / interim probanda must
    supply a non-empty list to clear the INV-19 gate.
    """
    return {
        "statement": statement,
        "kind": kind,
        "scheme": scheme,
        "alternatives_considered": (
            alternatives_considered if alternatives_considered is not None else []
        ),
        "confidence": confidence,
    }


# --- T6.2: _build_probandum ---------------------------------------------


def test_valid_candidate_builds_probandum(
    tmp_workspace_with_walton_snapshot: Path,
    hierarchize_role_attribution: RoleAttribution,
    hierarchize_provenance: ProvenanceRecord,
) -> None:
    """A Hierarchize candidate that satisfies INV-18/19 commits a Probandum."""
    sub = Substrate(tmp_workspace_with_walton_snapshot)

    prob = _build_probandum(
        _base_probandum_candidate(),
        sub,
        hierarchize_provenance,
        role_attributions=[hierarchize_role_attribution],
    )

    assert prob is not None
    assert prob.statement == "ACME breached the contract."
    assert prob.scheme == "argument-from-expert-opinion"
    assert prob.provenance_id == hierarchize_provenance.id
    # The substrate now has the record (read-back path).
    written = list(sub.list_probanda())
    assert len(written) == 1
    assert written[0].id == prob.id


def test_unknown_scheme_raises_clarification(
    tmp_workspace_with_walton_snapshot_and_distillation: Path,
    hierarchize_role_attribution: RoleAttribution,
    hierarchize_provenance: ProvenanceRecord,
) -> None:
    """Unknown Walton scheme -> reconciler raises ``scheme-missing``.

    Asserts:

    1. ``_build_probandum`` returns ``None`` (NOT an exception).
    2. No Probandum lands in the substrate.
    3. Exactly one open ``scheme-missing`` Clarification is filed under
       the first distillation (the helper's source-id picker prefers a
       real source over the ``_mappings`` sentinel).
    4. The clarification's question text / context_refs references the
       proposed scheme name and probandum statement excerpt so a human
       supervisor can extend the snapshot or mark the candidate as a
       false positive.
    """
    sub = Substrate(tmp_workspace_with_walton_snapshot_and_distillation)

    candidate = _base_probandum_candidate(
        statement="ACME failed to perform under §3.",
        scheme="argument-from-pure-fabrication",  # not in catalogue
    )

    result = _build_probandum(
        candidate,
        sub,
        hierarchize_provenance,
        role_attributions=[hierarchize_role_attribution],
    )

    assert result is None
    # No Probandum was written.
    assert list(sub.list_probanda()) == []
    # The clarification landed under the first distillation.
    open_clarifications = list_open_clarifications_for_source(sub, "src-A", kind="scheme-missing")
    assert len(open_clarifications) == 1
    c = open_clarifications[0]
    assert c.kind == "scheme-missing"
    haystack = c.question + " " + " ".join(c.context_refs)
    assert "argument-from-pure-fabrication" in haystack
    assert "ACME failed to perform" in haystack


def test_probandum_candidate_shape_error_propagates(
    tmp_workspace_with_walton_snapshot: Path,
    hierarchize_role_attribution: RoleAttribution,
    hierarchize_provenance: ProvenanceRecord,
) -> None:
    """A malformed candidate raises ``CandidateShapeError`` (shape, not state)."""
    sub = Substrate(tmp_workspace_with_walton_snapshot)
    # ``kind`` is required by the schema's Literal; absence triggers
    # pydantic ValidationError which the reconciler wraps.
    bad = _base_probandum_candidate()
    bad.pop("kind")
    with pytest.raises(CandidateShapeError):
        _build_probandum(
            bad,
            sub,
            hierarchize_provenance,
            role_attributions=[hierarchize_role_attribution],
        )


# --- T6.3: _build_probandum_edge ----------------------------------------


def _seed_ultimate_and_penultimate(
    workspace: Path,
    hierarchize_role_attribution: RoleAttribution,
    hierarchize_provenance: ProvenanceRecord,
) -> tuple[str, str]:
    """Plant an ``ultimate`` + a ``penultimate`` probandum in the substrate.

    Returns ``(ultimate_id, penultimate_id)`` for the tests to reference
    when proposing edges.
    """
    sub = Substrate(workspace)
    ultimate = _build_probandum(
        _base_probandum_candidate(
            statement="ACME breached the contract.",
            kind="ultimate",
            alternatives_considered=[],
        ),
        sub,
        hierarchize_provenance,
        role_attributions=[hierarchize_role_attribution],
    )
    assert ultimate is not None

    penultimate = _build_probandum(
        _base_probandum_candidate(
            statement="ACME failed to pay on the due date.",
            kind="penultimate",
            alternatives_considered=["ACME paid on time", "Payment was waived"],
        ),
        sub,
        hierarchize_provenance,
        role_attributions=[hierarchize_role_attribution],
    )
    assert penultimate is not None
    return ultimate.id, penultimate.id


def _base_edge_candidate(
    *,
    parent_probandum_id: str,
    child_id: str,
    child_kind: str = "probandum",
    child_source_id: str | None = None,
    kind: str = "supports",
) -> dict[str, Any]:
    """Return a syntactically-valid Hierarchize edge candidate dict."""
    return {
        "parent_probandum_id": parent_probandum_id,
        "child_id": child_id,
        "child_kind": child_kind,
        "child_source_id": child_source_id,
        "kind": kind,
        "warrant": "Statement decomposes the parent's obligation.",
        "warrant_defensibility": "conventional",
        "warrant_basis": "Wigmore §III",
        "confidence": "high",
    }


def test_valid_edge_candidate_builds(
    tmp_workspace_with_walton_snapshot: Path,
    hierarchize_role_attribution: RoleAttribution,
    hierarchize_provenance: ProvenanceRecord,
) -> None:
    """An edge candidate that satisfies INV-16/17 commits a ProbandumEdge."""
    sub = Substrate(tmp_workspace_with_walton_snapshot)
    ult_id, pen_id = _seed_ultimate_and_penultimate(
        tmp_workspace_with_walton_snapshot,
        hierarchize_role_attribution,
        hierarchize_provenance,
    )

    edge = _build_probandum_edge(
        _base_edge_candidate(parent_probandum_id=ult_id, child_id=pen_id),
        sub,
        hierarchize_provenance,
        role_attributions=[hierarchize_role_attribution],
    )

    assert edge is not None
    assert edge.parent_probandum_id == ult_id
    assert edge.child_id == pen_id
    # The substrate now has the edge (read-back path).
    written = list(sub.list_probandum_edges())
    assert len(written) == 1
    assert written[0].id == edge.id


def test_lineage_incomplete_raises_clarification(
    tmp_workspace_with_walton_snapshot_and_distillation: Path,
    hierarchize_role_attribution: RoleAttribution,
    hierarchize_provenance: ProvenanceRecord,
) -> None:
    """Orphan parent (no path to ultimate) -> reconciler raises ``lineage-incomplete``.

    Asserts:

    1. ``_build_probandum_edge`` returns ``None``.
    2. No ProbandumEdge lands in the substrate.
    3. Exactly one open ``lineage-incomplete`` Clarification is filed
       under the first distillation.
    4. The clarification's context_refs carries both the parent and
       child ids so a human supervisor can navigate either way.
    """
    sub = Substrate(tmp_workspace_with_walton_snapshot_and_distillation)
    # Two penultimate probanda — neither linked to an ultimate.
    orphan_parent = _build_probandum(
        _base_probandum_candidate(
            statement="Orphan parent — no ultimate lineage.",
            kind="penultimate",
            alternatives_considered=["alt-1"],
        ),
        sub,
        hierarchize_provenance,
        role_attributions=[hierarchize_role_attribution],
    )
    orphan_child = _build_probandum(
        _base_probandum_candidate(
            statement="Orphan child — also has no lineage path.",
            kind="penultimate",
            alternatives_considered=["alt-2"],
        ),
        sub,
        hierarchize_provenance,
        role_attributions=[hierarchize_role_attribution],
    )
    assert orphan_parent is not None
    assert orphan_child is not None

    result = _build_probandum_edge(
        _base_edge_candidate(
            parent_probandum_id=orphan_parent.id,
            child_id=orphan_child.id,
        ),
        sub,
        hierarchize_provenance,
        role_attributions=[hierarchize_role_attribution],
    )

    assert result is None
    # No edge was written.
    assert list(sub.list_probandum_edges()) == []
    open_clarifications = list_open_clarifications_for_source(
        sub, "src-A", kind="lineage-incomplete"
    )
    assert len(open_clarifications) == 1
    c = open_clarifications[0]
    assert c.kind == "lineage-incomplete"
    # Both endpoints appear in context_refs.
    haystack_refs = " ".join(c.context_refs)
    assert orphan_parent.id in haystack_refs
    assert orphan_child.id in haystack_refs
