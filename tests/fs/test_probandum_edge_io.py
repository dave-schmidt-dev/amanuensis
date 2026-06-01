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

INV-16 (no-cycle) and INV-17 (lineage) are deferred to M4 — this file
does NOT exercise them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import (
    EdgeChildMissing,
    ParentProbandumMissing,
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
    # Plant a second penultimate so we have two children of `ult`.
    from tests.fs.conftest import _probandum_basic_payload

    pen2 = _probandum_basic_payload(
        role_attribution,
        kind="penultimate",
        statement="A second penultimate proposition.",
        alternatives_considered=["alt"],
    )
    sub.add_probandum(pen2)

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
        child_id=pen2.id,
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
