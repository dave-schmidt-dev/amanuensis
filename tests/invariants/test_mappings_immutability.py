# pyright: reportPrivateUsage=false
"""Gate test for INV-13 (Entity and Resolution records are immutable).

Quoting the Phase 2a design spec INV-13 verbatim:

    Once written, ``Entity`` / ``Resolution`` records are not rewritten.
    ``EntitySupersede`` / ``ResolutionSupersede`` records carry corrections
    with PROV.

What this gate certifies
------------------------
The original Phase 2a baseline (cases 1-4): idempotent / mutation-guard
pairs over ``Entity`` and ``Resolution``, plus the
``ResolutionSupersede`` chain walker. Phase 2b adds the same pairs over
``CrossDocRelation`` + ``CrossDocRelationSupersede`` (and the
``EntitySupersede`` cleanup-4 pair). Phase 2c (M5 / T5.3) extends the
coverage over the four new record kinds — ``Probandum``,
``ProbandumEdge``, ``ProbandumSupersede``, ``ProbandumEdgeSupersede`` —
each with the same two-case shape (idempotent + mutation-guard).

Scope
-----
Fixture substrates are hand-built. Gate lives in ``tests/invariants/``
and is wired into ``pytest -m invariants``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from amanuensis.fs import Substrate
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._errors import MutationOfImmutableRecord
from amanuensis.fs._serialize import (
    serialize_cross_doc_relation_yaml,
    serialize_entity_md,
    serialize_entity_supersede_yaml,
    serialize_probandum_edge_supersede_yaml,
    serialize_probandum_edge_yaml,
    serialize_probandum_md,
    serialize_probandum_supersede_yaml,
    serialize_resolution_supersede_yaml,
    serialize_yaml,
)
from amanuensis.schemas import AgentAttribution, RoleAttribution
from tests.invariants.conftest import (
    _INV15_ENTITY_ID,
    _INV15_FROM_ATOM,
    _INV15_FROM_SOURCE,
    _INV15_TO_ATOM,
    _INV15_TO_SOURCE,
    _MAPPINGS_ATOM_ID,
    _MAPPINGS_SOURCE_ID,
    _build_cross_doc_relation_supersede,
    _build_entity,
    _build_entity_supersede,
    _build_probandum,
    _build_probandum_edge,
    _build_probandum_edge_supersede,
    _build_probandum_supersede,
    _build_resolution,
    _build_resolution_supersede,
    _inv15_build_relation,
    _inv15_forged_entity,
    _inv15_forged_resolution,
    _inv15_plant_entity,
    _inv15_plant_resolution,
)

pytestmark = pytest.mark.invariants

# Stable timestamp for all test-local constructions.
_AT = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)

# Shared test-local attribution helpers — same shape as conftest fixtures.
_AGENT = AgentAttribution(
    kind="llm",
    identifier="claude-opus-4-7",
    role="map-resolve",
)
_RA = RoleAttribution(agent=_AGENT, activity="proposed", at=_AT)


# ---------------------------------------------------------------------------
# Case 1: add_entity idempotent for identical content
# ---------------------------------------------------------------------------


def test_entity_add_idempotent(populated_mappings_workspace: Path) -> None:
    """add_entity is a no-op on second write of identical content."""
    s = Substrate(populated_mappings_workspace)
    entities_before = list(s.list_entities())
    assert len(entities_before) == 1, f"expected 1 entity, got {entities_before!r}"

    entity = entities_before[0]
    # Re-adding the same entity must not raise.
    s.add_entity(entity)
    entities_after = list(s.list_entities())
    assert len(entities_after) == 1, "add_entity duplicated the entity"


# ---------------------------------------------------------------------------
# Case 2: add_entity raises MutationOfImmutableRecord on content change
# ---------------------------------------------------------------------------


def test_entity_mutation_raises(tmp_path: Path) -> None:
    """add_entity raises MutationOfImmutableRecord when on-disk content diverges.

    Strategy:
    - Build entity_v1 with kind="organization" and write it via the
      substrate normally.
    - Forge entity_v1's on-disk file with kind="person" directly
      (bypassing the substrate guard via atomic_write_text + model_copy).
    - Call substrate.add_entity(entity_v1): the id check passes (v1's id
      matches its own content), but the on-disk file now has kind="person",
      so the non-volatile comparison fires MutationOfImmutableRecord.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: inv13-mutation-test\n",
        encoding="utf-8",
    )
    s = Substrate(tmp_path)

    # Build and write entity_v1 normally.
    entity_v1, prov_v1 = _build_entity(_RA, _AGENT, kind="organization")
    atomic_write_text(s.mappings_provenance_path(prov_v1.id), serialize_yaml(prov_v1))
    s.add_entity(entity_v1)

    # Forge the on-disk file: same id, different non-volatile field (kind).
    forged = entity_v1.model_copy(update={"kind": "person"})
    atomic_write_text(s.entity_path(entity_v1.id), serialize_entity_md(forged))

    # Re-adding entity_v1 (id matches its own hash) against forged disk content
    # must raise MutationOfImmutableRecord.
    with pytest.raises(MutationOfImmutableRecord):
        s.add_entity(entity_v1)


# ---------------------------------------------------------------------------
# Case 3: add_resolution idempotent for identical content
# ---------------------------------------------------------------------------


def test_resolution_add_idempotent(populated_mappings_workspace: Path) -> None:
    """add_resolution is a no-op on second write of identical content."""
    s = Substrate(populated_mappings_workspace)
    resolutions_before = list(s.list_resolutions())
    assert len(resolutions_before) == 1, f"expected 1 resolution, got {resolutions_before!r}"

    resolution = resolutions_before[0]
    # Re-adding the same resolution must not raise.
    s.add_resolution(resolution)
    resolutions_after = list(s.list_resolutions())
    assert len(resolutions_after) == 1, "add_resolution duplicated the resolution"


# ---------------------------------------------------------------------------
# Case 4: supersede chain allows corrections without triggering mutation guard
# ---------------------------------------------------------------------------


def test_supersede_chain_allows_correction(tmp_path: Path) -> None:
    """A ResolutionSupersede corrects a resolution without hitting the immutability guard.

    Writes resolution_v1, adds a ResolutionSupersede pointing to
    resolution_v2, then verifies that latest_resolution_for returns v2.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: inv13-supersede-test\n",
        encoding="utf-8",
    )
    s = Substrate(tmp_path)

    # Build entity first.
    entity, entity_prov = _build_entity(_RA, _AGENT)
    atomic_write_text(s.mappings_provenance_path(entity_prov.id), serialize_yaml(entity_prov))
    s.add_entity(entity)

    # Write resolution_v1 (confidence=high).
    res_v1, prov_v1 = _build_resolution(
        _RA,
        _AGENT,
        source_id=_MAPPINGS_SOURCE_ID,
        atom_id=_MAPPINGS_ATOM_ID,
        entity_id=entity.id,
        confidence="high",
    )
    atomic_write_text(s.mappings_provenance_path(prov_v1.id), serialize_yaml(prov_v1))
    s.add_resolution(res_v1)

    # Write resolution_v2 (different basis) directly — bypasses duplicate-triple guard.
    res_v2, prov_v2 = _build_resolution(
        _RA,
        _AGENT,
        source_id=_MAPPINGS_SOURCE_ID,
        atom_id=_MAPPINGS_ATOM_ID,
        entity_id=entity.id,
        confidence="medium",
        basis="supervisor override",
    )
    atomic_write_text(s.mappings_provenance_path(prov_v2.id), serialize_yaml(prov_v2))
    atomic_write_text(s.resolution_path(res_v2.id), serialize_yaml(res_v2))

    # Write the supersede record: v1 → v2.
    supersede, sup_prov = _build_resolution_supersede(
        _RA,
        _AGENT,
        superseded_resolution_id=res_v1.id,
        replacement_resolution_id=res_v2.id,
    )
    atomic_write_text(s.mappings_provenance_path(sup_prov.id), serialize_yaml(sup_prov))
    s.add_resolution_supersede(supersede)

    # latest_resolution_for must return v2 (v1 is superseded).
    latest = s.latest_resolution_for(_MAPPINGS_SOURCE_ID, _MAPPINGS_ATOM_ID, operand_index=0)
    assert latest is not None, "expected a non-None latest resolution"
    assert latest.id == res_v2.id, (
        f"expected latest resolution to be {res_v2.id!r}, got {latest.id!r}"
    )
    # v1 is still on disk (immutable — not deleted).
    assert s.resolution_path(res_v1.id).is_file(), (
        "resolution v1 should still exist on disk (immutability: no deletion)"
    )


# ---------------------------------------------------------------------------
# Phase 2b — INV-13 extended to CrossDocRelation
# ---------------------------------------------------------------------------
#
# Mirrors cases 1, 2, and 4 above for CrossDocRelation: idempotent
# re-add, mutation guard against tampered on-disk content, and supersede-
# chain semantics. CrossDocRelation immutability is enforced by
# Substrate.add_cross_doc_relation; CrossDocRelationSupersede records
# carry corrections (Phase 2b).


def _populated_cross_doc_workspace(tmp_path: Path, project_name: str) -> Path:
    """Build a workspace with bilateral resolutions for the standard endpoints.

    Plants ``e-smith`` Entity + Resolutions for both
    ``(src-A, a-fixture0001)`` and ``(src-B, a-fixture0002)`` so any
    CrossDocRelation with ``shared_entities=["e-smith"]`` and matching
    endpoints passes INV-15.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(f"schema_version: 1\nproject_name: {project_name}\n", encoding="utf-8")
    entity = _inv15_forged_entity(_INV15_ENTITY_ID, _RA)
    _inv15_plant_entity(tmp_path, entity)
    _inv15_plant_resolution(
        tmp_path,
        _inv15_forged_resolution(
            resolution_id="j-inv13-from",
            source_id=_INV15_FROM_SOURCE,
            atom_id=_INV15_FROM_ATOM,
            entity_id=_INV15_ENTITY_ID,
            role_attribution=_RA,
        ),
    )
    _inv15_plant_resolution(
        tmp_path,
        _inv15_forged_resolution(
            resolution_id="j-inv13-to",
            source_id=_INV15_TO_SOURCE,
            atom_id=_INV15_TO_ATOM,
            entity_id=_INV15_ENTITY_ID,
            role_attribution=_RA,
        ),
    )
    return tmp_path


def test_cross_doc_relation_add_idempotent(tmp_path: Path) -> None:
    """add_cross_doc_relation is a no-op on second write of identical content."""
    workspace = _populated_cross_doc_workspace(tmp_path, "inv13-cdr-idempotent")
    s = Substrate(workspace)
    rel = _inv15_build_relation(_RA, shared_entities=[_INV15_ENTITY_ID])
    s.add_cross_doc_relation(rel)
    # Re-adding the same relation must not raise.
    s.add_cross_doc_relation(rel)
    relations = list(s.list_cross_doc_relations())
    assert len(relations) == 1, "add_cross_doc_relation duplicated the relation"


def test_cross_doc_relation_mutation_raises(tmp_path: Path) -> None:
    """add_cross_doc_relation raises MutationOfImmutableRecord on tampered on-disk content."""
    workspace = _populated_cross_doc_workspace(tmp_path, "inv13-cdr-mutation")
    s = Substrate(workspace)
    rel = _inv15_build_relation(_RA, shared_entities=[_INV15_ENTITY_ID])
    s.add_cross_doc_relation(rel)
    # Forge the on-disk file: same id (so the immutability guard rather
    # than the id check fires), different non-volatile content.
    forged = rel.model_copy(update={"warrant_basis": "forged by hand"})
    atomic_write_text(
        s.cross_doc_relation_path(rel.id),
        serialize_cross_doc_relation_yaml(forged),
    )
    with pytest.raises(MutationOfImmutableRecord):
        s.add_cross_doc_relation(rel)


def test_cross_doc_relation_supersede_chain_allows_correction(tmp_path: Path) -> None:
    """A CrossDocRelationSupersede corrects a relation without hitting the immutability guard.

    Writes rel_v1, writes rel_v2 (different warrant_basis), records the
    supersede, then verifies that ``latest_cross_doc_relation_for(v1.id)``
    returns v2.
    """
    workspace = _populated_cross_doc_workspace(tmp_path, "inv13-cdr-supersede")
    s = Substrate(workspace)
    rel_v1 = _inv15_build_relation(
        _RA, shared_entities=[_INV15_ENTITY_ID], warrant_basis="initial basis"
    )
    rel_v2 = _inv15_build_relation(
        _RA, shared_entities=[_INV15_ENTITY_ID], warrant_basis="refined basis"
    )
    s.add_cross_doc_relation(rel_v1)
    s.add_cross_doc_relation(rel_v2)
    supersede = _build_cross_doc_relation_supersede(
        _RA, superseded_id=rel_v1.id, replacement_id=rel_v2.id
    )
    s.add_cross_doc_relation_supersede(supersede)

    # Walking from v1 returns v2; v1 is still on disk (immutable, not deleted).
    latest = s.latest_cross_doc_relation_for(rel_v1.id)
    assert latest is not None, "expected a non-None latest cross-doc relation"
    assert latest.id == rel_v2.id, (
        f"expected latest cross-doc relation to be {rel_v2.id!r}, got {latest.id!r}"
    )
    assert s.cross_doc_relation_path(rel_v1.id).is_file(), (
        "cross-doc relation v1 should still exist on disk (immutability: no deletion)"
    )


# ---------------------------------------------------------------------------
# Phase 2b cleanup-4 — INV-13 extended to Phase 2a supersede records
# ---------------------------------------------------------------------------
#
# Phase 2a's add_entity_supersede / add_resolution_supersede wrote
# unconditionally via atomic_write_text. Phase 2b's
# add_cross_doc_relation_supersede gained an immutability guard
# (idempotent on identical content; MutationOfImmutableRecord on
# divergent content). cleanup-4 backports the guard to the Phase 2a
# pair so the supersede write surface is uniform across all three
# kinds (s-, t-, v-).


def _populated_supersede_pair_workspace(tmp_path: Path, project_name: str) -> Substrate:
    """Build a workspace + Substrate populated with the entities and
    resolutions needed to write s- and t- supersede records.

    Two entities (ent_old, ent_new); two resolutions on the same atom
    at distinct operand indexes (res_old, res_new); supersede records
    pointing res_old → res_new and ent_old → ent_new are NOT pre-written
    — the caller decides when to call add_*_supersede.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(f"schema_version: 1\nproject_name: {project_name}\n", encoding="utf-8")
    s = Substrate(tmp_path)
    return s


def test_resolution_supersede_idempotent(tmp_path: Path) -> None:
    """add_resolution_supersede is a no-op on second write of identical content."""
    s = _populated_supersede_pair_workspace(tmp_path, "inv13-rs-idempotent")

    entity, entity_prov = _build_entity(_RA, _AGENT)
    atomic_write_text(s.mappings_provenance_path(entity_prov.id), serialize_yaml(entity_prov))
    s.add_entity(entity)

    res_old, prov_old = _build_resolution(
        _RA, _AGENT, source_id=_MAPPINGS_SOURCE_ID, atom_id=_MAPPINGS_ATOM_ID, entity_id=entity.id
    )
    res_new, prov_new = _build_resolution(
        _RA,
        _AGENT,
        source_id=_MAPPINGS_SOURCE_ID,
        atom_id=_MAPPINGS_ATOM_ID,
        entity_id=entity.id,
        operand_index=1,
    )
    atomic_write_text(s.mappings_provenance_path(prov_old.id), serialize_yaml(prov_old))
    atomic_write_text(s.mappings_provenance_path(prov_new.id), serialize_yaml(prov_new))
    s.add_resolution(res_old)
    s.add_resolution(res_new)

    supersede, sup_prov = _build_resolution_supersede(
        _RA, _AGENT, superseded_resolution_id=res_old.id, replacement_resolution_id=res_new.id
    )
    atomic_write_text(s.mappings_provenance_path(sup_prov.id), serialize_yaml(sup_prov))

    s.add_resolution_supersede(supersede)
    # Re-adding the byte-identical record must not raise (cleanup-4).
    s.add_resolution_supersede(supersede)
    assert s.supersede_path(supersede.id).is_file()


def test_resolution_supersede_mutation_raises(tmp_path: Path) -> None:
    """add_resolution_supersede raises MutationOfImmutableRecord on tampered content."""
    s = _populated_supersede_pair_workspace(tmp_path, "inv13-rs-mutation")

    entity, entity_prov = _build_entity(_RA, _AGENT)
    atomic_write_text(s.mappings_provenance_path(entity_prov.id), serialize_yaml(entity_prov))
    s.add_entity(entity)

    res_old, prov_old = _build_resolution(
        _RA, _AGENT, source_id=_MAPPINGS_SOURCE_ID, atom_id=_MAPPINGS_ATOM_ID, entity_id=entity.id
    )
    res_new, prov_new = _build_resolution(
        _RA,
        _AGENT,
        source_id=_MAPPINGS_SOURCE_ID,
        atom_id=_MAPPINGS_ATOM_ID,
        entity_id=entity.id,
        operand_index=1,
    )
    atomic_write_text(s.mappings_provenance_path(prov_old.id), serialize_yaml(prov_old))
    atomic_write_text(s.mappings_provenance_path(prov_new.id), serialize_yaml(prov_new))
    s.add_resolution(res_old)
    s.add_resolution(res_new)

    supersede, sup_prov = _build_resolution_supersede(
        _RA, _AGENT, superseded_resolution_id=res_old.id, replacement_resolution_id=res_new.id
    )
    atomic_write_text(s.mappings_provenance_path(sup_prov.id), serialize_yaml(sup_prov))
    s.add_resolution_supersede(supersede)

    # Forge: same id, different non-volatile content (reason).
    forged = supersede.model_copy(update={"reason": "FORGED by hand"})
    atomic_write_text(
        s.supersede_path(supersede.id),
        serialize_resolution_supersede_yaml(forged),
    )
    with pytest.raises(MutationOfImmutableRecord):
        s.add_resolution_supersede(supersede)


def test_entity_supersede_idempotent(tmp_path: Path) -> None:
    """add_entity_supersede is a no-op on second write of identical content."""
    s = _populated_supersede_pair_workspace(tmp_path, "inv13-es-idempotent")

    ent_old, ent_old_prov = _build_entity(_RA, _AGENT)
    ent_new, ent_new_prov = _build_entity(_RA, _AGENT, canonical_name="New Corp.")
    atomic_write_text(s.mappings_provenance_path(ent_old_prov.id), serialize_yaml(ent_old_prov))
    atomic_write_text(s.mappings_provenance_path(ent_new_prov.id), serialize_yaml(ent_new_prov))
    s.add_entity(ent_old)
    s.add_entity(ent_new)

    supersede, sup_prov = _build_entity_supersede(
        _RA, _AGENT, superseded_entity_id=ent_old.id, replacement_entity_id=ent_new.id
    )
    atomic_write_text(s.mappings_provenance_path(sup_prov.id), serialize_yaml(sup_prov))

    s.add_entity_supersede(supersede)
    # Re-adding the byte-identical record must not raise (cleanup-4).
    s.add_entity_supersede(supersede)
    assert s.supersede_path(supersede.id).is_file()


def test_entity_supersede_mutation_raises(tmp_path: Path) -> None:
    """add_entity_supersede raises MutationOfImmutableRecord on tampered content."""
    s = _populated_supersede_pair_workspace(tmp_path, "inv13-es-mutation")

    ent_old, ent_old_prov = _build_entity(_RA, _AGENT)
    ent_new, ent_new_prov = _build_entity(_RA, _AGENT, canonical_name="New Corp.")
    atomic_write_text(s.mappings_provenance_path(ent_old_prov.id), serialize_yaml(ent_old_prov))
    atomic_write_text(s.mappings_provenance_path(ent_new_prov.id), serialize_yaml(ent_new_prov))
    s.add_entity(ent_old)
    s.add_entity(ent_new)

    supersede, sup_prov = _build_entity_supersede(
        _RA, _AGENT, superseded_entity_id=ent_old.id, replacement_entity_id=ent_new.id
    )
    atomic_write_text(s.mappings_provenance_path(sup_prov.id), serialize_yaml(sup_prov))
    s.add_entity_supersede(supersede)

    # Forge: same id, different non-volatile content (reason).
    forged = supersede.model_copy(update={"reason": "FORGED by hand"})
    atomic_write_text(
        s.supersede_path(supersede.id),
        serialize_entity_supersede_yaml(forged),
    )
    with pytest.raises(MutationOfImmutableRecord):
        s.add_entity_supersede(supersede)


# ---------------------------------------------------------------------------
# Phase 2c — INV-13 extended to Probandum + ProbandumEdge + their supersedes
# ---------------------------------------------------------------------------
#
# Each new record kind gets two cases mirroring the existing pairs above:
#   1. Idempotent identical re-add does not raise.
#   2. Divergent content re-add raises MutationOfImmutableRecord.
#
# Probandum + ProbandumEdge tests pre-pin the generic Walton-scheme
# snapshot so the INV-18 closed-vocabulary gate at write-time is
# satisfied. ProbandumEdge tests additionally plant an ultimate +
# penultimate so INV-16 / INV-17 / parent+child existence gates pass.


def _populated_probandum_workspace(tmp_path: Path, project_name: str) -> Substrate:
    """Build a workspace + Substrate with the Walton snapshot pinned.

    Probandum writes require an on-disk Walton-scheme snapshot to clear
    the INV-18 closed-vocabulary gate. Mirrors
    ``tmp_workspace_with_walton_snapshot`` from ``tests/fs/conftest.py``.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(f"schema_version: 1\nproject_name: {project_name}\n", encoding="utf-8")
    s = Substrate(tmp_path)
    s.snapshot_walton_schemes()
    return s


def test_probandum_add_idempotent(tmp_path: Path) -> None:
    """add_probandum is a no-op on second write of identical content."""
    s = _populated_probandum_workspace(tmp_path, "inv13-prob-idempotent")

    probandum = _build_probandum(_RA, _AGENT)
    s.add_probandum(probandum)
    # Re-adding the byte-identical record must not raise.
    s.add_probandum(probandum)
    assert s.probandum_path(probandum.id).is_file()


def test_probandum_mutation_raises(tmp_path: Path) -> None:
    """add_probandum raises MutationOfImmutableRecord on tampered content."""
    s = _populated_probandum_workspace(tmp_path, "inv13-prob-mutation")

    probandum = _build_probandum(_RA, _AGENT)
    s.add_probandum(probandum)

    # Forge: same id, different non-volatile content (statement body).
    forged = probandum.model_copy(update={"statement": "FORGED statement body."})
    atomic_write_text(s.probandum_path(probandum.id), serialize_probandum_md(forged))

    with pytest.raises(MutationOfImmutableRecord):
        s.add_probandum(probandum)


def _populated_probandum_tree_workspace(
    tmp_path: Path, project_name: str
) -> tuple[Substrate, str, str]:
    """Build a workspace + planted ultimate + penultimate pair for edge tests.

    Returns ``(substrate, ultimate_id, penultimate_id)``. The ultimate
    parent traces to itself (trivially) so INV-17 lineage passes; the
    penultimate carries a non-empty alternatives_considered list so the
    INV-19 ACH alternatives gate also clears.
    """
    s = _populated_probandum_workspace(tmp_path, project_name)
    ult = _build_probandum(_RA, _AGENT, kind="ultimate")
    pen = _build_probandum(
        _RA,
        _AGENT,
        kind="penultimate",
        statement="A penultimate proposition.",
        alternatives_considered=["alt1", "alt2"],
    )
    s.add_probandum(ult)
    s.add_probandum(pen)
    return s, ult.id, pen.id


def test_probandum_edge_add_idempotent(tmp_path: Path) -> None:
    """add_probandum_edge is a no-op on second write of identical content."""
    s, ult_id, pen_id = _populated_probandum_tree_workspace(tmp_path, "inv13-pe-idempotent")
    edge = _build_probandum_edge(
        _RA,
        _AGENT,
        parent_probandum_id=ult_id,
        child_id=pen_id,
        child_kind="probandum",
    )
    s.add_probandum_edge(edge)
    # Re-adding the byte-identical edge must not raise.
    s.add_probandum_edge(edge)
    assert s.probandum_edge_path(edge.id).is_file()


def test_probandum_edge_mutation_raises(tmp_path: Path) -> None:
    """add_probandum_edge raises MutationOfImmutableRecord on tampered content."""
    s, ult_id, pen_id = _populated_probandum_tree_workspace(tmp_path, "inv13-pe-mutation")
    edge = _build_probandum_edge(
        _RA,
        _AGENT,
        parent_probandum_id=ult_id,
        child_id=pen_id,
        child_kind="probandum",
    )
    s.add_probandum_edge(edge)

    # Forge: same id, different non-volatile content (warrant_basis).
    forged = edge.model_copy(update={"warrant_basis": "FORGED by hand"})
    atomic_write_text(
        s.probandum_edge_path(edge.id),
        serialize_probandum_edge_yaml(forged),
    )
    with pytest.raises(MutationOfImmutableRecord):
        s.add_probandum_edge(edge)


def test_probandum_supersede_idempotent(tmp_path: Path) -> None:
    """add_probandum_supersede is a no-op on second write of identical content."""
    s = _populated_probandum_workspace(tmp_path, "inv13-ps-idempotent")

    # Two probanda (old + new) so the supersede ids point at plausible records.
    # add_probandum_supersede itself does not check referenced-record
    # existence, but planting the pair keeps the workspace coherent.
    prob_old = _build_probandum(_RA, _AGENT, statement="Original statement.")
    prob_new = _build_probandum(_RA, _AGENT, statement="Refined statement.")
    s.add_probandum(prob_old)
    s.add_probandum(prob_new)

    supersede = _build_probandum_supersede(
        _RA, _AGENT, superseded_probandum_id=prob_old.id, replacement_probandum_id=prob_new.id
    )

    s.add_probandum_supersede(supersede)
    # Re-adding the byte-identical record must not raise.
    s.add_probandum_supersede(supersede)
    assert s.supersede_path(supersede.id).is_file()


def test_probandum_supersede_mutation_raises(tmp_path: Path) -> None:
    """add_probandum_supersede raises MutationOfImmutableRecord on tampered content."""
    s = _populated_probandum_workspace(tmp_path, "inv13-ps-mutation")

    prob_old = _build_probandum(_RA, _AGENT, statement="Original statement.")
    prob_new = _build_probandum(_RA, _AGENT, statement="Refined statement.")
    s.add_probandum(prob_old)
    s.add_probandum(prob_new)

    supersede = _build_probandum_supersede(
        _RA, _AGENT, superseded_probandum_id=prob_old.id, replacement_probandum_id=prob_new.id
    )
    s.add_probandum_supersede(supersede)

    # Forge: same id, different non-volatile content (reason).
    forged = supersede.model_copy(update={"reason": "FORGED by hand"})
    atomic_write_text(
        s.supersede_path(supersede.id),
        serialize_probandum_supersede_yaml(forged),
    )
    with pytest.raises(MutationOfImmutableRecord):
        s.add_probandum_supersede(supersede)


def test_probandum_edge_supersede_idempotent(tmp_path: Path) -> None:
    """add_probandum_edge_supersede is a no-op on second write of identical content."""
    s, ult_id, pen_id = _populated_probandum_tree_workspace(tmp_path, "inv13-pes-idempotent")
    # Two distinct edges on the same parent->child link (different warrant).
    edge_old = _build_probandum_edge(
        _RA,
        _AGENT,
        parent_probandum_id=ult_id,
        child_id=pen_id,
        warrant="Original warrant.",
    )
    edge_new = _build_probandum_edge(
        _RA,
        _AGENT,
        parent_probandum_id=ult_id,
        child_id=pen_id,
        warrant="Tighter warrant.",
    )
    s.add_probandum_edge(edge_old)
    s.add_probandum_edge(edge_new)

    supersede = _build_probandum_edge_supersede(
        _RA,
        _AGENT,
        superseded_edge_id=edge_old.id,
        replacement_edge_id=edge_new.id,
    )

    s.add_probandum_edge_supersede(supersede)
    # Re-adding the byte-identical record must not raise.
    s.add_probandum_edge_supersede(supersede)
    assert s.supersede_path(supersede.id).is_file()


def test_probandum_edge_supersede_mutation_raises(tmp_path: Path) -> None:
    """add_probandum_edge_supersede raises MutationOfImmutableRecord on tampered content."""
    s, ult_id, pen_id = _populated_probandum_tree_workspace(tmp_path, "inv13-pes-mutation")
    edge_old = _build_probandum_edge(
        _RA,
        _AGENT,
        parent_probandum_id=ult_id,
        child_id=pen_id,
        warrant="Original warrant.",
    )
    edge_new = _build_probandum_edge(
        _RA,
        _AGENT,
        parent_probandum_id=ult_id,
        child_id=pen_id,
        warrant="Tighter warrant.",
    )
    s.add_probandum_edge(edge_old)
    s.add_probandum_edge(edge_new)

    supersede = _build_probandum_edge_supersede(
        _RA,
        _AGENT,
        superseded_edge_id=edge_old.id,
        replacement_edge_id=edge_new.id,
    )
    s.add_probandum_edge_supersede(supersede)

    # Forge: same id, different non-volatile content (reason).
    forged = supersede.model_copy(update={"reason": "FORGED by hand"})
    atomic_write_text(
        s.supersede_path(supersede.id),
        serialize_probandum_edge_supersede_yaml(forged),
    )
    with pytest.raises(MutationOfImmutableRecord):
        s.add_probandum_edge_supersede(supersede)
