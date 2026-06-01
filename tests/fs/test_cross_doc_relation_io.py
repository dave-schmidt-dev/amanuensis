"""T2 — Substrate cross-doc relation IO (Phase 2b M2) + T3.1 INV-15 gate.

Covers:
- ``add_cross_doc_relation`` writes to ``mappings/relations/<id>.yaml``
- Cross-source constraint: ``from_source_id != to_source_id`` (T2.1 gate)
- Idempotency on byte-identical content
- ``MutationOfImmutableRecord`` on tampered on-disk content (INV-13)
- INV-15 shared-entity gate (T3.1): every shared entity must exist and be
  resolved by BOTH endpoints

M2 tests requiring a passing gate are parameterized against the
``tmp_workspace_with_bilateral_resolutions`` fixture (which plants
``e-smith`` + matching from/to Resolutions so the default ``_rel()``
payload satisfies INV-15). M2-specific negative tests (cross-source
gate, divergent-content) still use the bare ``tmp_workspace`` because
they fail before INV-15 runs OR are run against gate-passing fixtures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import (
    CrossSourceConstraintViolation,
    MutationOfImmutableRecord,
    SharedEntityGateViolation,
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
    tmp_workspace_with_bilateral_resolutions: Path, role_attribution: RoleAttribution
) -> None:
    workspace = tmp_workspace_with_bilateral_resolutions
    sub = _new(workspace)
    rel = _rel(role_attribution)
    sub.add_cross_doc_relation(rel)
    path = workspace / "mappings" / "relations" / f"{rel.id}.yaml"
    assert path.is_file()


# --- T2.2: idempotency + immutability + cross-source rejection -------


def test_add_cross_doc_relation_is_idempotent(
    tmp_workspace_with_bilateral_resolutions: Path, role_attribution: RoleAttribution
) -> None:
    workspace = tmp_workspace_with_bilateral_resolutions
    sub = _new(workspace)
    rel = _rel(role_attribution)
    sub.add_cross_doc_relation(rel)
    # Second write with identical content must not raise; exactly one file
    # must exist on disk.
    sub.add_cross_doc_relation(rel)
    relations_dir = workspace / "mappings" / "relations"
    files = [p for p in relations_dir.iterdir() if p.is_file() and p.suffix == ".yaml"]
    assert len(files) == 1


def test_add_cross_doc_relation_raises_on_diverging_content(
    tmp_workspace_with_bilateral_resolutions: Path, role_attribution: RoleAttribution
) -> None:
    """Tampered on-disk content at the same path triggers INV-13."""
    workspace = tmp_workspace_with_bilateral_resolutions
    sub = _new(workspace)
    rel = _rel(role_attribution)
    sub.add_cross_doc_relation(rel)
    path = workspace / "mappings" / "relations" / f"{rel.id}.yaml"
    # Append a manual edit so existing bytes diverge from canonical form.
    path.write_text(path.read_text(encoding="utf-8") + "# manual edit\n", encoding="utf-8")
    with pytest.raises(MutationOfImmutableRecord):
        sub.add_cross_doc_relation(rel)


def test_rejects_intra_source(tmp_workspace: Path, role_attribution: RoleAttribution) -> None:
    """from_source_id == to_source_id → CrossSourceConstraintViolation.

    The cross-source gate fires BEFORE INV-15, so bare ``tmp_workspace``
    (no planted entity/resolutions) is sufficient.
    """
    sub = _new(tmp_workspace)
    rel = _rel(role_attribution, to_source_id="src-A")  # same as from_source_id
    with pytest.raises(CrossSourceConstraintViolation):
        sub.add_cross_doc_relation(rel)


# --- T2.3: list_cross_doc_relations with composable filters ----------


def test_list_cross_doc_relations_filters_by_kind(
    tmp_workspace_with_bilateral_resolutions: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace_with_bilateral_resolutions)
    supports = _rel(role_attribution, kind="supports")
    attacks = _rel(role_attribution, kind="attacks")
    sub.add_cross_doc_relation(supports)
    sub.add_cross_doc_relation(attacks)
    result = list(sub.list_cross_doc_relations(kind="supports"))
    assert len(result) == 1
    assert result[0].id == supports.id


def test_list_cross_doc_relations_filters_by_source(
    tmp_workspace_with_bilateral_resolutions: Path, role_attribution: RoleAttribution
) -> None:
    from tests.fs.conftest import (
        forged_entity,
        forged_resolution,
        plant_entity,
        plant_resolution,
    )

    workspace = tmp_workspace_with_bilateral_resolutions
    sub = _new(workspace)
    # Plant additional shared entity ``e-other`` resolved by src-C/a-fixture0001
    # and src-A/a-fixture0002 (the from/to endpoints of rel_ca below).
    plant_entity(workspace, forged_entity("e-other", role_attribution))
    plant_resolution(
        workspace,
        forged_resolution(
            resolution_id="j-other-from",
            source_id="src-C",
            atom_id="a-fixture0001",
            entity_id="e-other",
            role_attribution=role_attribution,
        ),
    )
    plant_resolution(
        workspace,
        forged_resolution(
            resolution_id="j-other-to",
            source_id="src-A",
            atom_id="a-fixture0002",
            entity_id="e-other",
            role_attribution=role_attribution,
        ),
    )
    # Edge 1: src-A → src-B (uses default ``e-smith`` from bilateral fixture)
    rel_ab = _rel(role_attribution, from_source_id="src-A", to_source_id="src-B")
    # Edge 2: src-C → src-A — uses ``e-other`` (just planted above).
    rel_ca = _rel(
        role_attribution,
        from_source_id="src-C",
        to_source_id="src-A",
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
    tmp_workspace_with_bilateral_resolutions: Path, role_attribution: RoleAttribution
) -> None:
    from tests.fs.conftest import (
        forged_entity,
        forged_resolution,
        plant_entity,
        plant_resolution,
    )

    workspace = tmp_workspace_with_bilateral_resolutions
    sub = _new(workspace)
    # Plant ``e-jones`` resolved by the same default endpoints as ``e-smith``.
    plant_entity(workspace, forged_entity("e-jones", role_attribution))
    plant_resolution(
        workspace,
        forged_resolution(
            resolution_id="j-jones-from",
            source_id="src-A",
            atom_id="a-fixture0001",
            entity_id="e-jones",
            role_attribution=role_attribution,
        ),
    )
    plant_resolution(
        workspace,
        forged_resolution(
            resolution_id="j-jones-to",
            source_id="src-B",
            atom_id="a-fixture0002",
            entity_id="e-jones",
            role_attribution=role_attribution,
        ),
    )
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
    tmp_workspace_with_bilateral_resolutions: Path, role_attribution: RoleAttribution
) -> None:
    workspace = tmp_workspace_with_bilateral_resolutions
    sub = _new(workspace)
    rel_old = _rel(role_attribution)
    rel_new = _rel(role_attribution, warrant_basis="refined basis")
    sub.add_cross_doc_relation(rel_old)
    sub.add_cross_doc_relation(rel_new)

    sup = _supersede(role_attribution, rel_old, rel_new)
    sub.add_cross_doc_relation_supersede(sup)
    path = workspace / "mappings" / "supersedes" / f"{sup.id}.yaml"
    assert path.is_file()
    assert sup.id.startswith("v-")


def test_supersede_is_idempotent(
    tmp_workspace_with_bilateral_resolutions: Path, role_attribution: RoleAttribution
) -> None:
    workspace = tmp_workspace_with_bilateral_resolutions
    sub = _new(workspace)
    rel_old = _rel(role_attribution)
    rel_new = _rel(role_attribution, warrant_basis="refined basis")
    sub.add_cross_doc_relation(rel_old)
    sub.add_cross_doc_relation(rel_new)
    sup = _supersede(role_attribution, rel_old, rel_new)
    sub.add_cross_doc_relation_supersede(sup)
    # Identical re-write: must not raise.
    sub.add_cross_doc_relation_supersede(sup)
    sup_dir = workspace / "mappings" / "supersedes"
    files = [p for p in sup_dir.iterdir() if p.is_file() and p.name.startswith("v-")]
    assert len(files) == 1


# --- T2.5: latest_cross_doc_relation_for chain walking ---------------


def test_latest_returns_terminal_of_chain(
    tmp_workspace_with_bilateral_resolutions: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace_with_bilateral_resolutions)
    rel_old = _rel(role_attribution, warrant_basis="initial basis")
    rel_new = _rel(role_attribution, warrant_basis="refined basis")
    sub.add_cross_doc_relation(rel_old)
    sub.add_cross_doc_relation(rel_new)
    sup = _supersede(role_attribution, rel_old, rel_new)
    sub.add_cross_doc_relation_supersede(sup)

    # Walking from the superseded id returns the replacement.
    got = sub.latest_cross_doc_relation_for(rel_old.id)
    assert got is not None
    assert got.id == rel_new.id

    # Walking from the replacement (no further supersede) returns itself.
    got2 = sub.latest_cross_doc_relation_for(rel_new.id)
    assert got2 is not None
    assert got2.id == rel_new.id


def test_latest_returns_none_for_unknown_id(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """No relations on disk → walking any id returns None.

    Bare ``tmp_workspace`` is sufficient because the walk does not pass
    through ``add_cross_doc_relation`` (no INV-15 invocation).
    """
    sub = _new(tmp_workspace)
    assert sub.latest_cross_doc_relation_for("x-notexistent00000") is None


# --- T2.6: round-trip byte stability ---------------------------------


def test_round_trip_byte_identical(
    tmp_workspace_with_bilateral_resolutions: Path, role_attribution: RoleAttribution
) -> None:
    """Canonical-form serialization is deterministic across writes.

    Re-adding an identical record must NOT mutate the on-disk bytes —
    this codifies the canonical-yaml-dump stability invariant the
    idempotency guard depends on.
    """
    from tests.fs.conftest import (
        forged_entity,
        forged_resolution,
        plant_entity,
        plant_resolution,
    )

    workspace = tmp_workspace_with_bilateral_resolutions
    # Plant e-jones + e-doe with bilateral resolutions so the gate passes
    # for the multi-shared-entity payload.
    for extra in ("e-jones", "e-doe"):
        plant_entity(workspace, forged_entity(extra, role_attribution))
        plant_resolution(
            workspace,
            forged_resolution(
                resolution_id=f"j-{extra}-from",
                source_id="src-A",
                atom_id="a-fixture0001",
                entity_id=extra,
                role_attribution=role_attribution,
            ),
        )
        plant_resolution(
            workspace,
            forged_resolution(
                resolution_id=f"j-{extra}-to",
                source_id="src-B",
                atom_id="a-fixture0002",
                entity_id=extra,
                role_attribution=role_attribution,
            ),
        )

    sub = _new(workspace)
    rel = _rel(
        role_attribution,
        shared_entities=["e-smith", "e-jones", "e-doe"],
    )
    sub.add_cross_doc_relation(rel)
    path = workspace / "mappings" / "relations" / f"{rel.id}.yaml"
    first_bytes = path.read_bytes()
    # Idempotent re-add: should be a no-op (no rewrite).
    sub.add_cross_doc_relation(rel)
    second_bytes = path.read_bytes()
    assert first_bytes == second_bytes


# --- T3.1: INV-15 shared-entity gate at substrate write-time ---------


def test_rejects_empty_shared_entities(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """``shared_entities`` empty → SharedEntityGateViolation (INV-15)."""
    sub = _new(tmp_workspace)
    rel = _rel(role_attribution, shared_entities=[])
    with pytest.raises(SharedEntityGateViolation, match="shared_entities is empty"):
        sub.add_cross_doc_relation(rel)


def test_rejects_shared_entity_not_resolved_by_from_endpoint(
    tmp_workspace_with_partial_resolutions: Path, role_attribution: RoleAttribution
) -> None:
    """Only the to-endpoint Resolution exists → gate fires on the from-endpoint."""
    sub = _new(tmp_workspace_with_partial_resolutions)
    rel = _rel(
        role_attribution,
        from_atom_id="a-fixture0001",
        from_source_id="src-A",
        to_atom_id="a-fixture0002",
        to_source_id="src-B",
        shared_entities=["e-smith"],
    )
    with pytest.raises(SharedEntityGateViolation, match=r"from endpoint .* does not resolve"):
        sub.add_cross_doc_relation(rel)


def test_rejects_shared_entity_not_resolved_by_to_endpoint(
    tmp_workspace_with_partial_resolutions_to_missing: Path,
    role_attribution: RoleAttribution,
) -> None:
    """Mirror of the previous test — only the from-endpoint Resolution exists."""
    sub = _new(tmp_workspace_with_partial_resolutions_to_missing)
    rel = _rel(
        role_attribution,
        from_atom_id="a-fixture0001",
        from_source_id="src-A",
        to_atom_id="a-fixture0002",
        to_source_id="src-B",
        shared_entities=["e-smith"],
    )
    with pytest.raises(SharedEntityGateViolation, match=r"to endpoint .* does not resolve"):
        sub.add_cross_doc_relation(rel)


def test_rejects_missing_entity(
    tmp_workspace_with_dangling_entity_ref: Path, role_attribution: RoleAttribution
) -> None:
    """``shared_entities`` references an id with no Entity record on disk."""
    sub = _new(tmp_workspace_with_dangling_entity_ref)
    rel = _rel(role_attribution, shared_entities=["e-nonexistent"])
    with pytest.raises(SharedEntityGateViolation, match="not found in mappings/entities"):
        sub.add_cross_doc_relation(rel)


def test_accepts_shared_entity_resolved_by_both_endpoints(
    tmp_workspace_with_bilateral_resolutions: Path, role_attribution: RoleAttribution
) -> None:
    """Both endpoints have a Resolution to ``e-smith`` → gate passes."""
    sub = _new(tmp_workspace_with_bilateral_resolutions)
    rel = _rel(
        role_attribution,
        from_atom_id="a-fixture0001",
        from_source_id="src-A",
        to_atom_id="a-fixture0002",
        to_source_id="src-B",
        shared_entities=["e-smith"],
    )
    sub.add_cross_doc_relation(rel)  # no raise
