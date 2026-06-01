"""Shared fixtures for ``tests/fs/`` — substrate workspace + model builders.

The ``tmp_workspace`` fixture creates a minimal valid workspace (an
empty tmpdir with an ``amanuensis.yaml`` marker) so ``Substrate`` can be
constructed without tripping INV-1. The model builders return Pydantic
instances whose ``id`` already matches ``compute_id()`` — production
substrate writes should always go through that discipline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    Clarification,
    Entity,
    EntitySupersede,
    IterationDirective,
    OperandRef,
    Probandum,
    ProvenanceRecord,
    Relation,
    Resolution,
    ResolutionSupersede,
    RoleAttribution,
    compute_id,
)

# Canonical source id used across the substrate fixtures (path-safe).
SOURCE_ID = "src-fixture-001"


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """A minimal valid workspace: an empty dir with the marker file."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: test\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def agent() -> AgentAttribution:
    return AgentAttribution(
        kind="llm",
        identifier="claude-opus-4-7",
        role="extractor",
    )


@pytest.fixture
def human_agent() -> AgentAttribution:
    return AgentAttribution(
        kind="human",
        identifier="dave",
        role="human_supervisor",
    )


@pytest.fixture
def role_attribution(agent: AgentAttribution) -> RoleAttribution:
    return RoleAttribution(
        agent=agent,
        activity="proposed",
        at=datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def operand() -> OperandRef:
    return OperandRef(
        role="subject",
        kind="entity",
        value="ent-acme-corp",
        type_hint=None,
    )


def _atom_with_hash(payload: dict[str, Any]) -> Atom:
    """Build an Atom and rebuild it with id = compute_id(self)."""
    payload["id"] = "a-" + "0" * 16
    draft = Atom(**payload)
    payload["id"] = compute_id(draft)
    return Atom(**payload)


@pytest.fixture
def atom(role_attribution: RoleAttribution, operand: OperandRef) -> Atom:
    payload: dict[str, Any] = {
        "source_id": SOURCE_ID,
        "section_path": ["Part II", "§3.2", "(a)"],
        "paragraph_index": 0,
        "sentence_index": None,
        "char_span": (0, 42),
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": "asserts_obligation",
        "operands": [operand],
        "narrative": "ACME shall pay the invoiced amount within 30 days.",
        "qualifier_level": None,
        "qualifier_basis": None,
        "provenance_id": "p-fixture00000001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    return _atom_with_hash(payload)


def _relation_with_hash(payload: dict[str, Any]) -> Relation:
    payload["id"] = "r-" + "0" * 16
    draft = Relation(**payload)
    payload["id"] = compute_id(draft)
    return Relation(**payload)


@pytest.fixture
def relation(role_attribution: RoleAttribution) -> Relation:
    payload: dict[str, Any] = {
        "source_id": SOURCE_ID,
        "from_atom_id": "a-fixture0001000",
        "to_atom_id": "a-fixture0002000",
        "kind": "supports",
        "warrant": "Payment obligation flows from execution of contract.",
        "warrant_defensibility": "literature-backed",
        "warrant_basis": "Restatement (Second) of Contracts §1",
        "confidence": "high",
        "provenance_id": "p-fixture00000002",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    return _relation_with_hash(payload)


def _provenance_with_hash(payload: dict[str, Any]) -> ProvenanceRecord:
    payload["id"] = "p-" + "0" * 16
    draft = ProvenanceRecord(**payload)
    payload["id"] = compute_id(draft)
    return ProvenanceRecord(**payload)


@pytest.fixture
def provenance(agent: AgentAttribution) -> ProvenanceRecord:
    payload: dict[str, Any] = {
        "entity_type": "atom",
        "entity_id": "a-fixture0001000",
        "activity": "extract_v1",
        "activity_started_at": datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC),
        "activity_ended_at": datetime(2026, 5, 29, 12, 0, 3, tzinfo=UTC),
        "used_entity_ids": ["src-fixture-001"],
        "was_attributed_to": agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    return _provenance_with_hash(payload)


def _clarification_with_hash(payload: dict[str, Any]) -> Clarification:
    payload["id"] = "c-" + "0" * 16
    draft = Clarification(**payload)
    payload["id"] = compute_id(draft)
    return Clarification(**payload)


@pytest.fixture
def clarification(agent: AgentAttribution) -> Clarification:
    payload: dict[str, Any] = {
        "status": "open",
        "kind": "warrant-defensibility-contested",
        "raised_at": datetime(2026, 5, 29, 12, 5, 0, tzinfo=UTC),
        "raised_by": agent,
        "raised_by_activity": "audit_v1",
        "context_refs": ["a-fixture0001000"],
        "question": "Is 'ACME' the parent corp or a subsidiary?",
        "options": ["parent", "subsidiary"],
        "resolved_at": None,
        "resolved_by": None,
        "resolution": None,
        "raised_provenance_id": "p-fixture00000002",
        "resolved_provenance_id": None,
        "schema_version": 2,
    }
    return _clarification_with_hash(payload)


@pytest.fixture
def resolved_clarification(agent: AgentAttribution, human_agent: AgentAttribution) -> Clarification:
    payload: dict[str, Any] = {
        "status": "resolved",
        "kind": "warrant-defensibility-contested",
        "raised_at": datetime(2026, 5, 29, 12, 5, 0, tzinfo=UTC),
        "raised_by": agent,
        "raised_by_activity": "audit_v1",
        "context_refs": ["a-fixture0001000"],
        "question": "Is 'ACME' the parent corp or a subsidiary?",
        "options": ["parent", "subsidiary"],
        "resolved_at": datetime(2026, 5, 29, 14, 0, 0, tzinfo=UTC),
        "resolved_by": human_agent,
        "resolution": "parent",
        "raised_provenance_id": "p-fixture00000002",
        "resolved_provenance_id": "p-fixture00000003",
        "schema_version": 2,
    }
    return _clarification_with_hash(payload)


def _iteration_with_hash(payload: dict[str, Any]) -> IterationDirective:
    payload["id"] = "i-" + "0" * 16
    draft = IterationDirective(**payload)
    payload["id"] = compute_id(draft)
    return IterationDirective(**payload)


@pytest.fixture
def iteration(human_agent: AgentAttribution) -> IterationDirective:
    payload: dict[str, Any] = {
        "issued_at": datetime(2026, 5, 29, 13, 0, 0, tzinfo=UTC),
        "issued_by": human_agent,
        "target_phase": "distill",
        "target_artifacts": ["a-fixture0001000", "atoms/*.md"],
        "directive": "Re-extract §3 with stricter qualifier discipline.",
        "rationale": "Auditor flagged inconsistent qualifier levels in §3.",
        "applied_at": None,
        "applied_by": None,
        "applied_outcome": None,
        "issued_provenance_id": "p-fixture00000003",
        "applied_provenance_id": None,
        "schema_version": 1,
    }
    return _iteration_with_hash(payload)


# --- Phase 2a model builders -----------------------------------------


def _entity_with_hash(payload: dict[str, Any]) -> Entity:
    payload["id"] = "e-" + "0" * 16
    draft = Entity(**payload)
    payload["id"] = compute_id(draft)
    return Entity(**payload)


def make_entity(
    role_attribution: RoleAttribution,
    *,
    canonical_name: str = "ACME Corp.",
    kind: str = "party",
    aliases: list[str] | None = None,
    notes: str | None = None,
) -> Entity:
    """Build an Entity fixture with correct content-addressable id."""
    payload: dict[str, Any] = {
        "kind": kind,
        "canonical_name": canonical_name,
        "aliases": aliases if aliases is not None else ["ACME", "Acme Corporation"],
        "notes": notes,
        "provenance_id": "p-fixture00000010",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    return _entity_with_hash(payload)


@pytest.fixture
def entity(role_attribution: RoleAttribution) -> Entity:
    return make_entity(role_attribution)


def _resolution_with_hash(payload: dict[str, Any]) -> Resolution:
    payload["id"] = "j-" + "0" * 16
    draft = Resolution(**payload)
    payload["id"] = compute_id(draft)
    return Resolution(**payload)


def make_resolution(
    role_attribution: RoleAttribution,
    entity: Entity,
    *,
    source_id: str = SOURCE_ID,
    atom_id: str = "a-fixture0001000",
    operand_index: int = 0,
    confidence: str = "high",
) -> Resolution:
    """Build a Resolution fixture with correct content-addressable id."""
    payload: dict[str, Any] = {
        "source_id": source_id,
        "atom_id": atom_id,
        "operand_index": operand_index,
        "entity_id": entity.id,
        "confidence": confidence,
        "basis": "Exact name match against canonical entity.",
        "provenance_id": "p-fixture00000011",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    return _resolution_with_hash(payload)


@pytest.fixture
def resolution(role_attribution: RoleAttribution, entity: Entity) -> Resolution:
    return make_resolution(role_attribution, entity)


def _resolution_supersede_with_hash(payload: dict[str, Any]) -> ResolutionSupersede:
    payload["id"] = "s-" + "0" * 16
    draft = ResolutionSupersede(**payload)
    payload["id"] = compute_id(draft)
    return ResolutionSupersede(**payload)


def make_resolution_supersede(
    role_attribution: RoleAttribution,
    old_resolution: Resolution,
    new_resolution: Resolution,
) -> ResolutionSupersede:
    """Build a ResolutionSupersede fixture with correct id."""
    payload: dict[str, Any] = {
        "kind": "resolution",
        "superseded_resolution_id": old_resolution.id,
        "replacement_resolution_id": new_resolution.id,
        "reason": "Supervisor corrected entity mapping.",
        "provenance_id": "p-fixture00000012",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    return _resolution_supersede_with_hash(payload)


def _entity_supersede_with_hash(payload: dict[str, Any]) -> EntitySupersede:
    payload["id"] = "t-" + "0" * 16
    draft = EntitySupersede(**payload)
    payload["id"] = compute_id(draft)
    return EntitySupersede(**payload)


def make_entity_supersede(
    role_attribution: RoleAttribution,
    old_entity: Entity,
    new_entity: Entity,
) -> EntitySupersede:
    """Build an EntitySupersede fixture with correct id."""
    payload: dict[str, Any] = {
        "kind": "entity",
        "superseded_entity_id": old_entity.id,
        "replacement_entity_id": new_entity.id,
        "reason": "Supervisor merged duplicate entities.",
        "provenance_id": "p-fixture00000013",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    return _entity_supersede_with_hash(payload)


# --- Phase 2b INV-15 fixtures (M3) -----------------------------------
#
# These fixtures plant Entity + Resolution records on disk via direct
# file writes (bypassing the substrate's content-addressable id check)
# so the cross-doc-relation gate tests can use a literal entity id like
# ``e-smith`` and matching endpoints ``a-fixture0001`` / ``a-fixture0002``
# — the same literals the M2 ``_rel()`` helper hard-codes. The id check
# on Entity/Resolution would otherwise force us to thread real
# content-hashes through every M2 test, multiplying churn for no gain
# (the gate is what we're exercising, not Entity content-addressing).

_PHASE2B_ENTITY_ID = "e-smith"
_PHASE2B_FROM_SOURCE = "src-A"
_PHASE2B_FROM_ATOM = "a-fixture0001"
_PHASE2B_TO_SOURCE = "src-B"
_PHASE2B_TO_ATOM = "a-fixture0002"


# --- Phase 2c probandum builders -------------------------------------


def _probandum_with_hash(payload: dict[str, Any]) -> Probandum:
    payload["id"] = "p-" + "0" * 16
    draft = Probandum(**payload)
    payload["id"] = compute_id(draft)
    return Probandum(**payload)


def _probandum_basic_payload(
    role_attribution: RoleAttribution,
    *,
    statement: str = "ACME breached the contract by failing to pay.",
    kind: str = "ultimate",
    scheme: str = "argument-from-expert-opinion",
    alternatives_considered: list[str] | None = None,
    confidence: str = "high",
) -> Probandum:
    """Build a Probandum fixture with correct content-addressable id.

    Default ``alternatives_considered`` is ``[]`` (legal for ``ultimate``;
    callers that build penultimate / interim probanda must pass a
    non-empty list to clear the ACH alternatives gate).
    """
    payload: dict[str, Any] = {
        "statement": statement,
        "kind": kind,
        "scheme": scheme,
        "alternatives_considered": alternatives_considered
        if alternatives_considered is not None
        else [],
        "confidence": confidence,
        "provenance_id": "p-fixture-prob-001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    return _probandum_with_hash(payload)


def _forged_entity(entity_id: str, role_attribution: RoleAttribution) -> Entity:
    """Build an Entity whose ``id`` is the literal value (no hash check)."""
    return Entity(
        id=entity_id,
        kind="party",
        canonical_name="Smith",
        aliases=[],
        notes=None,
        provenance_id="p-fixture-inv15-ent",
        role_attributions=[role_attribution],
        schema_version=1,
    )


def _forged_resolution(
    *,
    resolution_id: str,
    source_id: str,
    atom_id: str,
    entity_id: str,
    role_attribution: RoleAttribution,
) -> Resolution:
    """Build a Resolution whose ``id`` is the literal value (no hash check)."""
    return Resolution(
        id=resolution_id,
        source_id=source_id,
        atom_id=atom_id,
        operand_index=0,
        entity_id=entity_id,
        confidence="high",
        basis="fixture-planted resolution for INV-15 gate",
        provenance_id="p-fixture-inv15-res",
        role_attributions=[role_attribution],
        schema_version=1,
    )


def plant_entity(tmp_path: Path, entity: Entity) -> None:
    """Write an Entity directly to disk at ``mappings/entities/<id>.md``.

    Bypasses ``Substrate.add_entity`` (which would reject the literal id
    via ``_require_id_matches``). The gate test does not care that the
    entity's id is the canonical hash — it only cares that an Entity
    record exists at the canonical path with the given id.
    """
    from amanuensis.fs._atomic import atomic_write_text
    from amanuensis.fs._serialize import serialize_entity_md

    path = tmp_path / "mappings" / "entities" / f"{entity.id}.md"
    atomic_write_text(path, serialize_entity_md(entity))


def plant_resolution(tmp_path: Path, resolution: Resolution) -> None:
    """Write a Resolution directly to disk at ``mappings/resolutions/<id>.yaml``.

    Bypasses ``Substrate.add_resolution`` for the same reason as
    ``plant_entity``.
    """
    from amanuensis.fs._atomic import atomic_write_text
    from amanuensis.fs._serialize import serialize_resolution_yaml

    path = tmp_path / "mappings" / "resolutions" / f"{resolution.id}.yaml"
    atomic_write_text(path, serialize_resolution_yaml(resolution))


# Public aliases — exported for use by test modules under tests/fs/.
forged_entity = _forged_entity
forged_resolution = _forged_resolution
PHASE2B_ENTITY_ID = _PHASE2B_ENTITY_ID
PHASE2B_FROM_SOURCE = _PHASE2B_FROM_SOURCE
PHASE2B_FROM_ATOM = _PHASE2B_FROM_ATOM
PHASE2B_TO_SOURCE = _PHASE2B_TO_SOURCE
PHASE2B_TO_ATOM = _PHASE2B_TO_ATOM


@pytest.fixture
def tmp_workspace_with_bilateral_resolutions(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> Path:
    """Workspace with ``e-smith`` Entity + BOTH endpoint Resolutions.

    Plants:
    - Entity ``e-smith``.
    - Resolution j-from-1 mapping ``(src-A, a-fixture0001, 0) → e-smith``.
    - Resolution j-to-1 mapping ``(src-B, a-fixture0002, 0) → e-smith``.

    A CrossDocRelation with ``shared_entities=["e-smith"]`` and the
    matching endpoints passes INV-15 against this workspace.
    """
    entity = _forged_entity(_PHASE2B_ENTITY_ID, role_attribution)
    plant_entity(tmp_workspace, entity)
    res_from = _forged_resolution(
        resolution_id="j-from-aaaaaaaa",
        source_id=_PHASE2B_FROM_SOURCE,
        atom_id=_PHASE2B_FROM_ATOM,
        entity_id=_PHASE2B_ENTITY_ID,
        role_attribution=role_attribution,
    )
    res_to = _forged_resolution(
        resolution_id="j-to-bbbbbbbbbb",
        source_id=_PHASE2B_TO_SOURCE,
        atom_id=_PHASE2B_TO_ATOM,
        entity_id=_PHASE2B_ENTITY_ID,
        role_attribution=role_attribution,
    )
    plant_resolution(tmp_workspace, res_from)
    plant_resolution(tmp_workspace, res_to)
    return tmp_workspace


@pytest.fixture
def tmp_workspace_with_partial_resolutions(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> Path:
    """Workspace with ``e-smith`` Entity + only the TO-endpoint Resolution.

    No resolution maps ``(src-A, a-fixture0001, 0) → e-smith``, so the
    INV-15 gate fires with "from endpoint does not resolve".
    """
    entity = _forged_entity(_PHASE2B_ENTITY_ID, role_attribution)
    plant_entity(tmp_workspace, entity)
    res_to = _forged_resolution(
        resolution_id="j-to-bbbbbbbbbb",
        source_id=_PHASE2B_TO_SOURCE,
        atom_id=_PHASE2B_TO_ATOM,
        entity_id=_PHASE2B_ENTITY_ID,
        role_attribution=role_attribution,
    )
    plant_resolution(tmp_workspace, res_to)
    return tmp_workspace


@pytest.fixture
def tmp_workspace_with_partial_resolutions_to_missing(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> Path:
    """Workspace with ``e-smith`` Entity + only the FROM-endpoint Resolution.

    Mirrors ``tmp_workspace_with_partial_resolutions`` — the gate fires
    with "to endpoint does not resolve".
    """
    entity = _forged_entity(_PHASE2B_ENTITY_ID, role_attribution)
    plant_entity(tmp_workspace, entity)
    res_from = _forged_resolution(
        resolution_id="j-from-aaaaaaaa",
        source_id=_PHASE2B_FROM_SOURCE,
        atom_id=_PHASE2B_FROM_ATOM,
        entity_id=_PHASE2B_ENTITY_ID,
        role_attribution=role_attribution,
    )
    plant_resolution(tmp_workspace, res_from)
    return tmp_workspace


@pytest.fixture
def tmp_workspace_with_dangling_entity_ref(tmp_workspace: Path) -> Path:
    """Workspace with no Entity records — shared_entities reference dangles."""
    return tmp_workspace


# --- Phase 2c probanda fixture (M2 + M4) -----------------------------


@pytest.fixture
def tmp_workspace_with_probanda(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> tuple[Path, Probandum, Probandum]:
    """Workspace with one ultimate + one penultimate probandum planted.

    Used by M2 edge tests (parent existence gate) and (later) M4 lineage
    tests. The probanda are written via ``Substrate.add_probandum`` so
    their canonical paths and ids are consistent with normal substrate
    discipline.

    Returns the workspace path, the ultimate probandum, and the
    penultimate probandum (for the caller to reference by id).
    """
    from amanuensis.fs import Substrate

    sub = Substrate(tmp_workspace)
    ult = _probandum_basic_payload(
        role_attribution,
        kind="ultimate",
        statement="ACME breached the contract.",
        alternatives_considered=[],
    )
    pen = _probandum_basic_payload(
        role_attribution,
        kind="penultimate",
        statement="ACME failed to pay on the due date.",
        alternatives_considered=["ACME paid on time", "Payment was waived"],
    )
    sub.add_probandum(ult)
    sub.add_probandum(pen)
    return tmp_workspace, ult, pen
