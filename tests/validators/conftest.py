"""Shared fixtures for ``tests/validators/``.

Reuses the agent / role / operand / atom / relation / provenance / vocabulary
builders from ``tests/fs/conftest.py`` semantics, but re-derives them here so
this directory's tests do not implicitly depend on ``tests/fs/conftest.py``
collection order. The ``tmp_workspace`` fixture also lives here so substrate-
backed validators (``provenance_completeness``, ``lineage_closure``) can build
a minimal workspace without crossing test-package boundaries.

The ``vocabulary`` fixture builds a small two-entry registry rather than
loading the vendored generic registry — closed_vocabulary tests want a
controlled set, not the production list.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    OperandRef,
    OperandTypeSchema,
    ProvenanceRecord,
    Relation,
    RoleAttribution,
    Vocabulary,
    VocabularyEntry,
    compute_id,
)
from tests.validators._types import AtomFactory, ProvenanceFactory, RelationFactory

SOURCE_ID = "src-fixture-001"


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Empty workspace with the amanuensis.yaml marker (INV-1)."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: validators-test\n",
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


def _atom_payload(
    role_attribution: RoleAttribution,
    operand: OperandRef,
    *,
    provenance_id: str = "p-fixture00000001",
    predicate: str = "asserts_obligation",
) -> dict[str, Any]:
    return {
        "source_id": SOURCE_ID,
        "section_path": ["Part II", "§3.2", "(a)"],
        "paragraph_index": 0,
        "sentence_index": None,
        "char_span": (0, 42),
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": predicate,
        "operands": [operand],
        "narrative": "ACME shall pay the invoiced amount within 30 days.",
        "qualifier_level": None,
        "qualifier_basis": None,
        "provenance_id": provenance_id,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }


def _build_atom(payload: dict[str, Any]) -> Atom:
    payload = dict(payload)
    payload["id"] = "a-" + "0" * 16
    draft = Atom(**payload)
    payload["id"] = compute_id(draft)
    return Atom(**payload)


@pytest.fixture
def atom(role_attribution: RoleAttribution, operand: OperandRef) -> Atom:
    return _build_atom(_atom_payload(role_attribution, operand))


@pytest.fixture
def atom_factory(role_attribution: RoleAttribution, operand: OperandRef) -> AtomFactory:
    """Returns a callable that builds Atoms with overridable fields."""

    def _make(**overrides: Any) -> Atom:
        base = _atom_payload(role_attribution, operand)
        base.update(overrides)
        return _build_atom(base)

    return _make


def _build_provenance(
    agent: AgentAttribution,
    *,
    entity_id: str,
    entity_type: str = "atom",
) -> ProvenanceRecord:
    payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "activity": "extract_v1",
        "activity_started_at": datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC),
        "activity_ended_at": datetime(2026, 5, 29, 12, 0, 3, tzinfo=UTC),
        "used_entity_ids": [SOURCE_ID],
        "was_attributed_to": agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    draft = ProvenanceRecord(**payload)
    payload["id"] = compute_id(draft)
    return ProvenanceRecord(**payload)


@pytest.fixture
def provenance_factory(agent: AgentAttribution) -> ProvenanceFactory:
    """Build a provenance record bound to a given entity_id."""

    def _make(*, entity_id: str) -> ProvenanceRecord:
        return _build_provenance(agent, entity_id=entity_id)

    return _make


def _build_relation(
    role_attribution: RoleAttribution,
    *,
    from_atom_id: str,
    to_atom_id: str,
    source_id: str = SOURCE_ID,
) -> Relation:
    payload: dict[str, Any] = {
        "id": "r-" + "0" * 16,
        "source_id": source_id,
        "from_atom_id": from_atom_id,
        "to_atom_id": to_atom_id,
        "kind": "supports",
        "warrant": "Payment obligation flows from execution of contract.",
        "warrant_defensibility": "literature-backed",
        "warrant_basis": "Restatement (Second) of Contracts §1",
        "confidence": "high",
        "provenance_id": "p-fixture00000002",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    draft = Relation(**payload)
    payload["id"] = compute_id(draft)
    return Relation(**payload)


@pytest.fixture
def relation_factory(role_attribution: RoleAttribution) -> RelationFactory:
    """Build relations with overridable endpoint ids / source."""

    def _make(
        *,
        from_atom_id: str,
        to_atom_id: str,
        source_id: str = SOURCE_ID,
    ) -> Relation:
        return _build_relation(
            role_attribution,
            from_atom_id=from_atom_id,
            to_atom_id=to_atom_id,
            source_id=source_id,
        )

    return _make


@pytest.fixture
def vocabulary() -> Vocabulary:
    """A small two-entry vocabulary with one alias.

    Hand-rolled rather than loaded from disk so closed_vocabulary tests
    don't accidentally couple to the vendored generic registry's evolving
    contents.
    """
    return Vocabulary(
        name="test-vocab",
        version="0.0.1",
        entries=[
            VocabularyEntry(
                predicate="asserts_obligation",
                aliases=["asserts_shall"],
                operand_types=[
                    OperandTypeSchema(name="subject", kind="entity", required=True),
                ],
                qualifier_required=False,
                notes="canonical obligation assertion",
            ),
            VocabularyEntry(
                predicate="asserts_factual_event",
                aliases=[],
                operand_types=[],
                qualifier_required=False,
                notes="bare factual claim",
            ),
        ],
    )
