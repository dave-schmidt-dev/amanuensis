"""Shared fixtures for schema tests.

Factories build valid Atom / Relation / Provenance / Clarification /
IterationDirective / ReplayLogEntry / Vocabulary payloads with stub
IDs; M1.5 will replace those stubs with real content-addressable hashes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    Clarification,
    IterationDirective,
    OperandRef,
    OperandTypeSchema,
    ProvenanceRecord,
    Relation,
    ReplayLogEntry,
    RoleAttribution,
    Vocabulary,
    VocabularyEntry,
)


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


@pytest.fixture
def atom_payload(
    role_attribution: RoleAttribution,
    operand: OperandRef,
) -> dict[str, Any]:
    """Minimum-valid Atom payload as a dict (constructor kwargs)."""
    return {
        "id": "a-fixture0001",
        "source_id": "src-fixture-001",
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
        "provenance_id": "prov-fixture-0001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }


@pytest.fixture
def atom(atom_payload: dict[str, Any]) -> Atom:
    return Atom(**atom_payload)


@pytest.fixture
def relation_payload(role_attribution: RoleAttribution) -> dict[str, Any]:
    """Minimum-valid Relation payload."""
    return {
        "id": "r-fixture0001",
        "source_id": "src-fixture-001",
        "from_atom_id": "a-fixture0001",
        "to_atom_id": "a-fixture0002",
        "kind": "supports",
        "warrant": "Payment obligation flows from execution of contract.",
        "warrant_defensibility": "literature-backed",
        "warrant_basis": "Restatement (Second) of Contracts §1",
        "confidence": "high",
        "provenance_id": "prov-fixture-0002",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }


@pytest.fixture
def relation(relation_payload: dict[str, Any]) -> Relation:
    return Relation(**relation_payload)


# --- M1.4 fixtures ----------------------------------------------------


@pytest.fixture
def provenance_payload(agent: AgentAttribution) -> dict[str, Any]:
    """Minimum-valid ProvenanceRecord payload."""
    return {
        "id": "p-fixture00000001",
        "entity_type": "atom",
        "entity_id": "a-fixture0001",
        "activity": "extract_v1",
        "activity_started_at": datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC),
        "activity_ended_at": datetime(2026, 5, 29, 12, 0, 3, tzinfo=UTC),
        "used_entity_ids": ["src-fixture-001"],
        "was_attributed_to": agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }


@pytest.fixture
def provenance(provenance_payload: dict[str, Any]) -> ProvenanceRecord:
    return ProvenanceRecord(**provenance_payload)


@pytest.fixture
def clarification_payload(agent: AgentAttribution) -> dict[str, Any]:
    """Minimum-valid Clarification payload (status=open)."""
    return {
        "id": "c-fixture00000001",
        "status": "open",
        "kind": "warrant-defensibility-contested",
        "raised_at": datetime(2026, 5, 29, 12, 5, 0, tzinfo=UTC),
        "raised_by": agent,
        "raised_by_activity": "audit_v1",
        "context_refs": ["a-fixture0001"],
        "question": "Is 'ACME' the parent corp or a subsidiary?",
        "options": ["parent", "subsidiary"],
        "resolved_at": None,
        "resolved_by": None,
        "resolution": None,
        "raised_provenance_id": "p-fixture00000002",
        "resolved_provenance_id": None,
        "schema_version": 2,
    }


@pytest.fixture
def clarification(clarification_payload: dict[str, Any]) -> Clarification:
    return Clarification(**clarification_payload)


@pytest.fixture
def iteration_payload(human_agent: AgentAttribution) -> dict[str, Any]:
    """Minimum-valid IterationDirective payload (status: issued, not applied)."""
    return {
        "id": "i-fixture00000001",
        "issued_at": datetime(2026, 5, 29, 13, 0, 0, tzinfo=UTC),
        "issued_by": human_agent,
        "target_phase": "distill",
        "target_artifacts": ["a-fixture0001", "atoms/*.json"],
        "directive": "Re-extract §3 with stricter qualifier discipline.",
        "rationale": "Auditor flagged inconsistent qualifier levels in §3.",
        "applied_at": None,
        "applied_by": None,
        "applied_outcome": None,
        "issued_provenance_id": "p-fixture00000003",
        "applied_provenance_id": None,
        "schema_version": 1,
    }


@pytest.fixture
def iteration(iteration_payload: dict[str, Any]) -> IterationDirective:
    return IterationDirective(**iteration_payload)


@pytest.fixture
def replay_log_payload(agent: AgentAttribution) -> dict[str, Any]:
    """Minimum-valid ReplayLogEntry payload (optional cost fields omitted)."""
    return {
        "seq": 1,
        "timestamp": datetime(2026, 5, 29, 12, 0, 3, tzinfo=UTC),
        "actor": agent,
        "activity": "extract_v1",
        "inputs_hash": "h-inputs-0001",
        "outputs_hash": "h-outputs-0001",
        "cache_hit": False,
        "substrate_changes": ["atoms/a-fixture0001.json"],
        "duration_seconds": 2.71,
        "schema_version": 1,
    }


@pytest.fixture
def replay_log_entry(replay_log_payload: dict[str, Any]) -> ReplayLogEntry:
    return ReplayLogEntry(**replay_log_payload)


@pytest.fixture
def operand_type_schema() -> OperandTypeSchema:
    return OperandTypeSchema(
        name="payer",
        kind="entity",
        required=True,
        type_hint=None,
    )


@pytest.fixture
def vocabulary_entry_payload(
    operand_type_schema: OperandTypeSchema,
) -> dict[str, Any]:
    """Minimum-valid VocabularyEntry payload."""
    return {
        "predicate": "asserts_payment",
        "aliases": ["promises_payment"],
        "operand_types": [
            operand_type_schema,
            OperandTypeSchema(
                name="amount",
                kind="literal",
                required=True,
                type_hint="money",
            ),
        ],
        "qualifier_required": False,
        "notes": "Used for contractual payment obligations.",
    }


@pytest.fixture
def vocabulary_entry(vocabulary_entry_payload: dict[str, Any]) -> VocabularyEntry:
    return VocabularyEntry(**vocabulary_entry_payload)


@pytest.fixture
def vocabulary_payload(vocabulary_entry: VocabularyEntry) -> dict[str, Any]:
    """Minimum-valid Vocabulary payload."""
    return {
        "name": "generic",
        "version": "0.1.0",
        "entries": [vocabulary_entry],
    }


@pytest.fixture
def vocabulary(vocabulary_payload: dict[str, Any]) -> Vocabulary:
    return Vocabulary(**vocabulary_payload)
