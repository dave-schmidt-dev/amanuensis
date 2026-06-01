"""T2.3 — Substrate.add_probandum_edge + parent/child existence gates.

Covers:
- ``add_probandum_edge`` writes to ``mappings/probandum-edges/<id>.yaml``.
- Idempotent on byte-identical content (INV-13).
- Parent existence gate: ``parent_probandum_id`` must exist in
  ``mappings/probanda/``. Raises ``ParentProbandumMissing``.
- Child existence gate (per ``child_kind``):
    - ``probandum`` → ``mappings/probanda/<id>.md``
    - ``atom`` → ``distillations/<source>/atoms/<id>.md``
    - ``cross-doc-relation`` → ``mappings/relations/<id>.yaml``
  Raises ``EdgeChildMissing``.

T4.1 — INV-16 cycle + tree-shape gate (added):
- Self-loop, two-cycle, and three-cycle parent→child chains rejected
  with ``ProbandumTreeViolation``.
- Long linear chain (10 deep) accepted.
- Multi-parent (probandum already has an incoming edge) rejected with
  ``ProbandumTreeViolation`` (Wigmore trees are trees, not DAGs).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import (
    EdgeChildMissing,
    ParentProbandumMissing,
    ProbandumTreeViolation,
    Substrate,
)
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.schemas import (
    Probandum,
    ProbandumEdge,
    ProbandumEdgeSupersede,
    RoleAttribution,
    compute_id,
)


def _new(workspace: Path) -> Substrate:
    return Substrate(workspace)


def _edge(
    *,
    parent_probandum_id: str,
    child_id: str,
    child_kind: str = "probandum",
    child_source_id: str | None = None,
    role_attribution: RoleAttribution,
    **overrides: Any,
) -> ProbandumEdge:
    """Build a ProbandumEdge whose id matches ``compute_id``."""
    payload: dict[str, Any] = {
        "id": "q-" + "0" * 16,
        "parent_probandum_id": parent_probandum_id,
        "child_id": child_id,
        "child_kind": child_kind,
        "child_source_id": child_source_id,
        "kind": "supports",
        "warrant": "Child entails parent.",
        "warrant_defensibility": "conventional",
        "warrant_basis": "fixture",
        "confidence": "medium",
        "provenance_id": "p-fixture-edge-001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    payload.update(overrides)
    draft = ProbandumEdge(**payload)
    payload["id"] = compute_id(draft)
    return ProbandumEdge(**payload)


def test_add_edge_writes_to_mappings(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
    )
    sub.add_probandum_edge(edge)
    path = workspace / "mappings" / "probandum-edges" / f"{edge.id}.yaml"
    assert path.is_file()


def test_add_edge_is_idempotent(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
    )
    sub.add_probandum_edge(edge)
    # Second write with identical content must not raise; exactly one file.
    sub.add_probandum_edge(edge)
    edges_dir = workspace / "mappings" / "probandum-edges"
    files = [f for f in edges_dir.iterdir() if f.is_file() and f.suffix == ".yaml"]
    assert len(files) == 1


def test_rejects_missing_parent(tmp_workspace: Path, role_attribution: RoleAttribution) -> None:
    sub = _new(tmp_workspace)
    edge = _edge(
        parent_probandum_id="p-nonexistent-aaaa",
        child_id="p-nonexistent-bbbb",
        child_kind="probandum",
        role_attribution=role_attribution,
    )
    with pytest.raises(ParentProbandumMissing):
        sub.add_probandum_edge(edge)


def test_rejects_missing_probandum_child(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, _pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id="p-nonexistent-cccc",
        child_kind="probandum",
        role_attribution=role_attribution,
    )
    with pytest.raises(EdgeChildMissing, match="probandum"):
        sub.add_probandum_edge(edge)


def test_rejects_missing_atom_child(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, _pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id="a-nonexistent-atom",
        child_kind="atom",
        child_source_id="src-fixture-001",
        role_attribution=role_attribution,
    )
    with pytest.raises(EdgeChildMissing, match="atom"):
        sub.add_probandum_edge(edge)


def test_rejects_missing_cross_doc_relation_child(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, _pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id="x-nonexistent-cdr0",
        child_kind="cross-doc-relation",
        role_attribution=role_attribution,
    )
    with pytest.raises(EdgeChildMissing, match="cross-doc-relation"):
        sub.add_probandum_edge(edge)


def test_accepts_atom_child_when_atom_exists(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    """Edge with child_kind=atom where the atom exists on disk passes the gate."""
    workspace, ult, _pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    # Plant a placeholder atom .md file at the canonical path (we don't
    # need a real Atom — the gate only checks existence).
    atom_path = workspace / "distillations" / "src-fixture-001" / "atoms" / "a-planted-aaaa.md"
    atomic_write_text(atom_path, "---\nplaceholder: true\n---\nplanted atom\n")
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id="a-planted-aaaa",
        child_kind="atom",
        child_source_id="src-fixture-001",
        role_attribution=role_attribution,
    )
    sub.add_probandum_edge(edge)
    assert (workspace / "mappings" / "probandum-edges" / f"{edge.id}.yaml").is_file()


# --- T2.4: list_probandum_edges with composable filters --------------


def test_list_probandum_edges_filters_by_parent(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    # Plant a second penultimate and an interim so we have a small tree:
    #   ult -> pen      (e1)
    #   ult -> pen2     (e2)
    #   pen -> interim  (e3, distinct parent — exercises the filter)
    from tests.fs.conftest import make_probandum

    pen2 = make_probandum(
        role_attribution,
        kind="penultimate",
        statement="A second penultimate proposition.",
        alternatives_considered=["alt"],
    )
    interim = make_probandum(
        role_attribution,
        kind="interim",
        statement="An interim probandum under pen.",
        alternatives_considered=["alt"],
    )
    sub.add_probandum(pen2)
    sub.add_probandum(interim)

    e1 = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="Edge 1",
    )
    e2 = _edge(
        parent_probandum_id=ult.id,
        child_id=pen2.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="Edge 2",
    )
    e3 = _edge(
        parent_probandum_id=pen.id,
        child_id=interim.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="Edge 3 (different parent)",
    )
    sub.add_probandum_edge(e1)
    sub.add_probandum_edge(e2)
    sub.add_probandum_edge(e3)

    under_ult = list(sub.list_probandum_edges(parent_probandum_id=ult.id))
    assert {e.id for e in under_ult} == {e1.id, e2.id}


def test_list_probandum_edges_filters_by_child_kind(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    # Plant an atom so we can build an atom-child edge.
    atom_path = workspace / "distillations" / "src-fixture-001" / "atoms" / "a-planted-aaaa.md"
    atomic_write_text(atom_path, "---\nx: 1\n---\nplanted\n")

    e_prob = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
    )
    e_atom = _edge(
        parent_probandum_id=ult.id,
        child_id="a-planted-aaaa",
        child_kind="atom",
        child_source_id="src-fixture-001",
        role_attribution=role_attribution,
    )
    sub.add_probandum_edge(e_prob)
    sub.add_probandum_edge(e_atom)

    only_atoms = list(sub.list_probandum_edges(child_kind="atom"))
    assert len(only_atoms) == 1
    assert only_atoms[0].id == e_atom.id


def test_list_probandum_edges_filters_by_kind(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    e_supports = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        kind="supports",
        warrant="Supports child.",
    )
    e_attacks = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        kind="attacks",
        warrant="Attacks child.",
    )
    sub.add_probandum_edge(e_supports)
    sub.add_probandum_edge(e_attacks)

    only_attacks = list(sub.list_probandum_edges(kind="attacks"))
    assert len(only_attacks) == 1
    assert only_attacks[0].id == e_attacks.id


def test_list_probandum_edges_lists_all(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    e1 = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="Edge 1",
    )
    e2 = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="Edge 2 (different warrant => different id).",
    )
    sub.add_probandum_edge(e1)
    sub.add_probandum_edge(e2)

    all_edges = list(sub.list_probandum_edges())
    assert {e.id for e in all_edges} == {e1.id, e2.id}


def test_list_probandum_edges_empty_when_no_dir(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    assert list(sub.list_probandum_edges()) == []


# --- T2.5: edge supersede + chain walking ----------------------------


def _edge_supersede(
    role_attribution: RoleAttribution,
    old_edge: ProbandumEdge,
    new_edge: ProbandumEdge,
    **overrides: object,
) -> ProbandumEdgeSupersede:
    from datetime import UTC, datetime

    payload: dict[str, object] = {
        "id": "o-" + "0" * 16,
        "supersedes_id": old_edge.id,
        "superseded_by_id": new_edge.id,
        "kind": "probandum-edge",
        "reason": "Supervisor tightened warrant basis.",
        "provenance_id": "p-fixture-esup-001",
        "role_attributions": [role_attribution],
        "at": datetime(2026, 6, 1, 9, 30, 0, tzinfo=UTC),
        "schema_version": 1,
    }
    payload.update(overrides)
    draft = ProbandumEdgeSupersede(**payload)  # type: ignore[arg-type]
    payload["id"] = compute_id(draft)
    return ProbandumEdgeSupersede(**payload)  # type: ignore[arg-type]


def test_add_probandum_edge_supersede_writes_to_supersedes_dir(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    e_old = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="Old warrant.",
    )
    e_new = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="New, tighter warrant.",
    )
    sub.add_probandum_edge(e_old)
    sub.add_probandum_edge(e_new)
    sup = _edge_supersede(role_attribution, e_old, e_new)
    sub.add_probandum_edge_supersede(sup)

    path = workspace / "mappings" / "supersedes" / f"{sup.id}.yaml"
    assert path.is_file()
    assert sup.id.startswith("o-")


def test_add_probandum_edge_supersede_is_idempotent(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    e_old = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="Old.",
    )
    e_new = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="New.",
    )
    sub.add_probandum_edge(e_old)
    sub.add_probandum_edge(e_new)
    sup = _edge_supersede(role_attribution, e_old, e_new)
    sub.add_probandum_edge_supersede(sup)
    sub.add_probandum_edge_supersede(sup)  # idempotent
    sup_dir = workspace / "mappings" / "supersedes"
    files = [f for f in sup_dir.iterdir() if f.is_file() and f.name.startswith("o-")]
    assert len(files) == 1


def test_latest_probandum_edge_for_returns_terminus(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    e_old = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="Old.",
    )
    e_new = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="New.",
    )
    sub.add_probandum_edge(e_old)
    sub.add_probandum_edge(e_new)
    sup = _edge_supersede(role_attribution, e_old, e_new)
    sub.add_probandum_edge_supersede(sup)

    got = sub.latest_probandum_edge_for(e_old.id)
    assert got is not None
    assert got.id == e_new.id

    got2 = sub.latest_probandum_edge_for(e_new.id)
    assert got2 is not None
    assert got2.id == e_new.id


def test_list_supersedes_kind_probandum_edge_filter(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    e_old = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="Old.",
    )
    e_new = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="New.",
    )
    sub.add_probandum_edge(e_old)
    sub.add_probandum_edge(e_new)
    sup = _edge_supersede(role_attribution, e_old, e_new)
    sub.add_probandum_edge_supersede(sup)

    listed = list(sub.list_supersedes(kind="probandum-edge"))
    assert len(listed) == 1
    assert isinstance(listed[0], ProbandumEdgeSupersede)
    assert listed[0].id == sup.id


# --- T2.6: round-trip byte stability for cross-doc-relation child ----


def test_probandum_edge_with_cross_doc_relation_child_round_trip(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    """Edge with child_kind=cross-doc-relation round-trips byte-identically.

    Plants a placeholder ``x-*.yaml`` in ``mappings/relations/`` (the
    child existence gate only checks for file presence; the gate does
    NOT re-parse the cross-doc relation here), then writes an edge
    twice and asserts the bytes on disk are unchanged after the second
    write.
    """
    from amanuensis.fs._atomic import atomic_write_text

    workspace, ult, _pen = tmp_workspace_with_probanda
    # Plant a placeholder x-*.yaml file so the cross-doc-relation child
    # existence check passes (the gate only verifies file presence).
    cdr_id = "x-planted-cdr0001"
    cdr_path = workspace / "mappings" / "relations" / f"{cdr_id}.yaml"
    atomic_write_text(cdr_path, "id: x-planted-cdr0001\nkind: supports\n")

    sub = _new(workspace)
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id=cdr_id,
        child_kind="cross-doc-relation",
        role_attribution=role_attribution,
        warrant="The cross-doc relation supports the ultimate probandum.",
    )
    sub.add_probandum_edge(edge)
    edge_path = workspace / "mappings" / "probandum-edges" / f"{edge.id}.yaml"
    first_bytes = edge_path.read_bytes()
    # Idempotent re-add: should be a no-op (no rewrite).
    sub.add_probandum_edge(edge)
    second_bytes = edge_path.read_bytes()
    assert first_bytes == second_bytes
    # Round-trip read returns the same model.
    got = sub.get_probandum_edge(edge.id)
    assert got == edge


# --- T4.1: INV-16 cycle + tree-shape gate ----------------------------
#
# Acyclic AND tree-shaped (no multi-parent). Spec §INV-16 says
# "acyclic"; spec §Risks #1 says "tree" — we implement the stronger
# discipline. Both violations raise ``ProbandumTreeViolation`` with a
# reason that names which discipline was breached.


def _plant_probandum(
    workspace: Path, role_attribution: RoleAttribution, **overrides: Any
) -> Probandum:
    """Plant a probandum via the substrate so its id is content-addressable.

    The fixture's Walton-scheme snapshot is already pinned so the INV-18
    gate clears.
    """
    from tests.fs.conftest import make_probandum

    p = make_probandum(role_attribution, **overrides)
    Substrate(workspace).add_probandum(p)
    return p


def test_self_loop_rejected(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    """An edge from a probandum to itself is rejected as a self-cycle."""
    workspace, ult, _pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id=ult.id,
        child_kind="probandum",
        role_attribution=role_attribution,
    )
    with pytest.raises(ProbandumTreeViolation, match=r"self-loop|cycle"):
        sub.add_probandum_edge(edge)


def test_two_cycle_rejected(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    """Edges ``ult → pen`` then ``pen → ult`` are rejected (back-edge).

    The first edge is a normal parent-to-child link. The second would
    close a two-cycle by making the original parent a child of its own
    child.
    """
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    e_fwd = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
    )
    sub.add_probandum_edge(e_fwd)
    # Now try the back-edge.
    e_back = _edge(
        parent_probandum_id=pen.id,
        child_id=ult.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="Back-edge attempting to close two-cycle.",
    )
    with pytest.raises(ProbandumTreeViolation, match="cycle"):
        sub.add_probandum_edge(e_back)


def test_three_cycle_rejected(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    """Edges ``a → b → c`` followed by ``c → a`` form a three-cycle."""
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    # Plant a third probandum (interim).
    p3 = _plant_probandum(
        workspace,
        role_attribution,
        kind="interim",
        statement="Third probandum in the cycle.",
        alternatives_considered=["alt"],
    )
    e_ab = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="a → b",
    )
    e_bc = _edge(
        parent_probandum_id=pen.id,
        child_id=p3.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="b → c",
    )
    sub.add_probandum_edge(e_ab)
    sub.add_probandum_edge(e_bc)
    e_ca = _edge(
        parent_probandum_id=p3.id,
        child_id=ult.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="c → a (closes three-cycle).",
    )
    with pytest.raises(ProbandumTreeViolation, match="cycle"):
        sub.add_probandum_edge(e_ca)


def test_long_chain_accepted(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    """A 10-deep linear chain p0 → p1 → ... → p9 passes the cycle gate."""
    from tests.fs.conftest import make_probandum

    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    # We already have ``ult`` (level 0) and ``pen`` (level 1); plant
    # 8 more interim probanda to reach a 10-deep chain.
    chain = [ult, pen]
    for i in range(8):
        p = make_probandum(
            role_attribution,
            kind="interim",
            statement=f"Chain level {i + 2} probandum.",
            alternatives_considered=["alt"],
        )
        sub.add_probandum(p)
        chain.append(p)

    # Link ult -> pen first (so pen has lineage to ultimate); then chain
    # each subsequent level off its predecessor.
    from itertools import pairwise

    for parent, child in pairwise(chain):
        edge = _edge(
            parent_probandum_id=parent.id,
            child_id=child.id,
            child_kind="probandum",
            role_attribution=role_attribution,
            warrant=f"Link {parent.id[:6]} → {child.id[:6]}.",
        )
        sub.add_probandum_edge(edge)

    # All 9 edges land on disk.
    edges_dir = workspace / "mappings" / "probandum-edges"
    files = [f for f in edges_dir.iterdir() if f.is_file() and f.suffix == ".yaml"]
    assert len(files) == 9


def test_multi_parent_rejected(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    """A probandum that already has a parent edge cannot acquire a second one.

    Wigmore trees are trees (per spec §Risks #1): every non-root
    probandum has at most one incoming probandum-edge. INV-16 enforces
    tree-shape, not just acyclicity.
    """
    from tests.fs.conftest import make_probandum

    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    # Plant a second penultimate as a co-parent candidate.
    ult2 = make_probandum(
        role_attribution,
        kind="ultimate",
        statement="A different ultimate probandum.",
        alternatives_considered=[],
    )
    sub.add_probandum(ult2)
    e_first = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="First parent.",
    )
    sub.add_probandum_edge(e_first)
    # The second edge tries to make ult2 a second parent of pen.
    e_second = _edge(
        parent_probandum_id=ult2.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
        warrant="Second parent (tree-shape violation).",
    )
    with pytest.raises(ProbandumTreeViolation, match=r"multi-parent|multiple parents"):
        sub.add_probandum_edge(e_second)
