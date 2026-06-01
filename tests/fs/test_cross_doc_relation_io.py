"""T2 — Substrate cross-doc relation IO (Phase 2b M2).

Covers:
- ``add_cross_doc_relation`` writes to ``mappings/relations/<id>.yaml``
- Cross-source constraint: ``from_source_id != to_source_id`` (T2.1 gate)
- Idempotency on byte-identical content
- ``MutationOfImmutableRecord`` on tampered on-disk content (INV-13)

INV-15 (shared-entity gate) is M3 territory — these tests deliberately do
NOT exercise INV-15.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import (
    CrossSourceConstraintViolation,
    MutationOfImmutableRecord,
    Substrate,
)
from amanuensis.schemas import (
    CrossDocRelation,
    CrossDocRelationSupersede,
    RoleAttribution,
    compute_id,
)


def _new(workspace: Path) -> Substrate:
    return Substrate(workspace)


def _rel_payload(role_attribution: RoleAttribution, **overrides: Any) -> dict[str, Any]:
    """Minimum-valid CrossDocRelation kwargs (id placeholder; caller fixes)."""
    payload: dict[str, Any] = {
        "id": "x-" + "0" * 16,
        "from_atom_id": "a-fixture0001",
        "from_source_id": "src-A",
        "to_atom_id": "a-fixture0002",
        "to_source_id": "src-B",
        "kind": "supports",
        "warrant": "Both atoms refer to the same Smith party.",
        "warrant_defensibility": "conventional",
        "warrant_basis": "Naming conventions match across documents.",
        "confidence": "medium",
        "shared_entities": ["e-smith"],
        "provenance_id": "p-fixture-cdr-001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    payload.update(overrides)
    return payload


def _rel(role_attribution: RoleAttribution, **overrides: Any) -> CrossDocRelation:
    """Build a CrossDocRelation whose id matches ``compute_id``."""
    payload = _rel_payload(role_attribution, **overrides)
    draft = CrossDocRelation(**payload)
    payload["id"] = compute_id(draft)
    return CrossDocRelation(**payload)


def _supersede(
    role_attribution: RoleAttribution,
    old_rel: CrossDocRelation,
    new_rel: CrossDocRelation,
    **overrides: Any,
) -> CrossDocRelationSupersede:
    """Build a CrossDocRelationSupersede whose id matches ``compute_id``."""
    from datetime import UTC, datetime

    payload: dict[str, Any] = {
        "id": "v-" + "0" * 16,
        "supersedes_id": old_rel.id,
        "superseded_by_id": new_rel.id,
        "kind": "cross-doc-relation",
        "reason": "Supervisor refined warrant.",
        "provenance_id": "p-fixture-cdrsup-001",
        "role_attributions": [role_attribution],
        "at": datetime(2026, 5, 31, 22, 0, 0, tzinfo=UTC),
        "schema_version": 1,
    }
    payload.update(overrides)
    draft = CrossDocRelationSupersede(**payload)
    payload["id"] = compute_id(draft)
    return CrossDocRelationSupersede(**payload)


# --- T2.1: happy-path write ------------------------------------------


def test_add_cross_doc_relation_writes_to_mappings_relations(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    rel = _rel(role_attribution)
    sub.add_cross_doc_relation(rel)
    path = tmp_workspace / "mappings" / "relations" / f"{rel.id}.yaml"
    assert path.is_file()


# --- T2.2: idempotency + immutability + cross-source rejection -------


def test_add_cross_doc_relation_is_idempotent(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    rel = _rel(role_attribution)
    sub.add_cross_doc_relation(rel)
    # Second write with identical content must not raise; exactly one file
    # must exist on disk.
    sub.add_cross_doc_relation(rel)
    relations_dir = tmp_workspace / "mappings" / "relations"
    files = [p for p in relations_dir.iterdir() if p.is_file() and p.suffix == ".yaml"]
    assert len(files) == 1


def test_add_cross_doc_relation_raises_on_diverging_content(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """Tampered on-disk content at the same path triggers INV-13."""
    sub = _new(tmp_workspace)
    rel = _rel(role_attribution)
    sub.add_cross_doc_relation(rel)
    path = tmp_workspace / "mappings" / "relations" / f"{rel.id}.yaml"
    # Append a manual edit so existing bytes diverge from canonical form.
    path.write_text(path.read_text(encoding="utf-8") + "# manual edit\n", encoding="utf-8")
    with pytest.raises(MutationOfImmutableRecord):
        sub.add_cross_doc_relation(rel)


def test_rejects_intra_source(tmp_workspace: Path, role_attribution: RoleAttribution) -> None:
    """from_source_id == to_source_id → CrossSourceConstraintViolation."""
    sub = _new(tmp_workspace)
    rel = _rel(role_attribution, to_source_id="src-A")  # same as from_source_id
    with pytest.raises(CrossSourceConstraintViolation):
        sub.add_cross_doc_relation(rel)


# --- T2.3: list_cross_doc_relations with composable filters ----------


def test_list_cross_doc_relations_filters_by_kind(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    supports = _rel(role_attribution, kind="supports")
    attacks = _rel(role_attribution, kind="attacks")
    sub.add_cross_doc_relation(supports)
    sub.add_cross_doc_relation(attacks)
    result = list(sub.list_cross_doc_relations(kind="supports"))
    assert len(result) == 1
    assert result[0].id == supports.id


def test_list_cross_doc_relations_filters_by_source(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    # Edge 1: src-A → src-B
    rel_ab = _rel(role_attribution, from_source_id="src-A", to_source_id="src-B")
    # Edge 2: src-C → src-A (so src-A appears as a target on edge 2)
    rel_ca = _rel(
        role_attribution,
        from_source_id="src-C",
        to_source_id="src-A",
        # different shared_entities so this isn't a duplicate hash
        shared_entities=["e-other"],
    )
    sub.add_cross_doc_relation(rel_ab)
    sub.add_cross_doc_relation(rel_ca)

    # touching_source="src-A" should return BOTH (either endpoint matches).
    touching = list(sub.list_cross_doc_relations(touching_source="src-A"))
    assert {r.id for r in touching} == {rel_ab.id, rel_ca.id}

    # to_source="src-B" should return only rel_ab.
    to_b = list(sub.list_cross_doc_relations(to_source="src-B"))
    assert len(to_b) == 1
    assert to_b[0].id == rel_ab.id


def test_list_cross_doc_relations_filters_by_shared_entity(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    rel_smith = _rel(role_attribution, shared_entities=["e-smith"])
    rel_jones = _rel(role_attribution, shared_entities=["e-jones"])
    rel_both = _rel(role_attribution, shared_entities=["e-smith", "e-jones"])
    sub.add_cross_doc_relation(rel_smith)
    sub.add_cross_doc_relation(rel_jones)
    sub.add_cross_doc_relation(rel_both)

    result = list(sub.list_cross_doc_relations(shared_entity="e-smith"))
    assert {r.id for r in result} == {rel_smith.id, rel_both.id}


# --- T2.4: add_cross_doc_relation_supersede --------------------------


def test_add_supersede_writes_to_mappings_supersedes(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    rel_old = _rel(role_attribution)
    rel_new = _rel(role_attribution, warrant_basis="refined basis")
    sub.add_cross_doc_relation(rel_old)
    sub.add_cross_doc_relation(rel_new)

    sup = _supersede(role_attribution, rel_old, rel_new)
    sub.add_cross_doc_relation_supersede(sup)
    path = tmp_workspace / "mappings" / "supersedes" / f"{sup.id}.yaml"
    assert path.is_file()
    assert sup.id.startswith("v-")


def test_supersede_is_idempotent(tmp_workspace: Path, role_attribution: RoleAttribution) -> None:
    sub = _new(tmp_workspace)
    rel_old = _rel(role_attribution)
    rel_new = _rel(role_attribution, warrant_basis="refined basis")
    sub.add_cross_doc_relation(rel_old)
    sub.add_cross_doc_relation(rel_new)
    sup = _supersede(role_attribution, rel_old, rel_new)
    sub.add_cross_doc_relation_supersede(sup)
    # Identical re-write: must not raise.
    sub.add_cross_doc_relation_supersede(sup)
    sup_dir = tmp_workspace / "mappings" / "supersedes"
    files = [p for p in sup_dir.iterdir() if p.is_file() and p.name.startswith("v-")]
    assert len(files) == 1
