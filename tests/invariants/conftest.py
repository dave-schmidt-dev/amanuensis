"""Shared fixtures for ``tests/invariants/`` gate tests.

The gate tests in this directory exercise INV-3, INV-5, and INV-10 on a
hand-built fixture substrate (NOT the M2.1 PDFs — those are vocabulary-
design fixtures, not substrate state). The factories below mirror the
patterns in ``tests/validators/conftest.py`` but are re-declared here so
this directory's tests do not implicitly depend on collection order of
``tests/validators/conftest.py``.

The ``vocabulary_subset`` fixture builds a 3-entry hand-rolled
Vocabulary used by the INV-5 "snapshot vs global" gate test: we want a
known-small snapshot whose entries are a strict subset of the vendored
generic registry so we can assert that a predicate in the global
registry but NOT in the snapshot is rejected.
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
    RoleAttribution,
    Vocabulary,
    VocabularyEntry,
    compute_id,
)
from tests.invariants._types import MatchedAtomFactory

SOURCE_ID = "src-fixture-001"


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Empty workspace with the amanuensis.yaml marker (INV-1)."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: invariants-test\n",
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


def _operand() -> OperandRef:
    return OperandRef(
        role="obligor",
        kind="entity",
        value="ent-acme-corp",
        type_hint=None,
    )


def _atom_payload(
    role_attribution: RoleAttribution,
    *,
    source_id: str = SOURCE_ID,
    paragraph_index: int = 0,
    char_span: tuple[int, int] = (0, 42),
    predicate: str = "asserts_obligation",
    narrative: str = "ACME shall pay the invoiced amount within 30 days.",
    provenance_id: str = "p-fixture00000001",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "section_path": ["Part II", "§3.2", "(a)"],
        "paragraph_index": paragraph_index,
        "sentence_index": None,
        "char_span": char_span,
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": predicate,
        "operands": [_operand()],
        "narrative": narrative,
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


def _build_provenance(
    agent: AgentAttribution,
    *,
    entity_id: str,
    entity_type: str = "atom",
    source_id: str = SOURCE_ID,
) -> ProvenanceRecord:
    payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "activity": "extract_v1",
        "activity_started_at": datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC),
        "activity_ended_at": datetime(2026, 5, 29, 12, 0, 3, tzinfo=UTC),
        "used_entity_ids": [source_id],
        "was_attributed_to": agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    draft = ProvenanceRecord(**payload)
    payload["id"] = compute_id(draft)
    return ProvenanceRecord(**payload)


def _matched_atom_and_provenance(
    role_attribution: RoleAttribution,
    agent: AgentAttribution,
    *,
    source_id: str = SOURCE_ID,
    paragraph_index: int = 0,
    char_span: tuple[int, int] = (0, 42),
    predicate: str = "asserts_obligation",
    narrative: str = "ACME shall pay the invoiced amount within 30 days.",
) -> tuple[Atom, ProvenanceRecord]:
    """Build an Atom + matching ProvenanceRecord whose ids point at each other.

    Because both ids are content-addressable AND provenance_id is volatile
    in Atom's canonical-form hashing (see schemas/atom.py _VOLATILE_FIELDS),
    the atom's id does not depend on its provenance_id. So we can:
      1. Build a draft atom to learn its id.
      2. Build a provenance record whose entity_id = atom.id.
      3. Build the final atom with provenance_id = prov.id.
    """
    draft_atom = _build_atom(
        _atom_payload(
            role_attribution,
            source_id=source_id,
            paragraph_index=paragraph_index,
            char_span=char_span,
            predicate=predicate,
            narrative=narrative,
        )
    )
    prov = _build_provenance(agent, entity_id=draft_atom.id, source_id=source_id)
    atom = _build_atom(
        _atom_payload(
            role_attribution,
            source_id=source_id,
            paragraph_index=paragraph_index,
            char_span=char_span,
            predicate=predicate,
            narrative=narrative,
            provenance_id=prov.id,
        )
    )
    assert atom.id == draft_atom.id, "atom.id depends on volatile provenance_id (regression)"
    return atom, prov


@pytest.fixture
def matched_atom_factory(
    role_attribution: RoleAttribution, agent: AgentAttribution
) -> MatchedAtomFactory:
    """Returns a callable that builds (Atom, ProvenanceRecord) pairs.

    Each call yields a distinct atom (varied by char_span so the content
    hash differs) plus a fresh provenance record whose ``entity_id`` is
    the new atom's id. Use this to build N-atom fixture substrates.
    """

    def _make(
        *,
        source_id: str = SOURCE_ID,
        paragraph_index: int = 0,
        char_span: tuple[int, int] = (0, 42),
        predicate: str = "asserts_obligation",
        narrative: str = "ACME shall pay the invoiced amount within 30 days.",
    ) -> tuple[Atom, ProvenanceRecord]:
        return _matched_atom_and_provenance(
            role_attribution,
            agent,
            source_id=source_id,
            paragraph_index=paragraph_index,
            char_span=char_span,
            predicate=predicate,
            narrative=narrative,
        )

    return _make


@pytest.fixture
def vocabulary_subset() -> Vocabulary:
    """A small 3-entry vocabulary whose predicates are a STRICT SUBSET of
    the vendored generic registry (``vocabularies/generic/predicates.yaml``).

    Used by the INV-5 snapshot-vs-global gate test: a predicate that
    appears in the global registry but NOT in this subset must be rejected
    when the validator routes its lookup through the snapshot. The three
    entries (``asserts_obligation``, ``asserts_factual_event``,
    ``cites_evidence``) are all real predicates from the generic registry;
    aliases are kept minimal so the subset stays small and deliberate.
    """
    return Vocabulary(
        name="invariants-subset-v0.1",
        version="0.1.0",
        entries=[
            VocabularyEntry(
                predicate="asserts_obligation",
                aliases=["asserts_shall"],
                operand_types=[
                    OperandTypeSchema(name="obligor", kind="entity", required=True),
                ],
                qualifier_required=False,
                notes="subset for INV-5 gate test",
            ),
            VocabularyEntry(
                predicate="asserts_factual_event",
                aliases=[],
                operand_types=[],
                qualifier_required=False,
                notes="subset for INV-5 gate test",
            ),
            VocabularyEntry(
                predicate="cites_evidence",
                aliases=[],
                operand_types=[],
                qualifier_required=False,
                notes="subset for INV-5 gate test",
            ),
        ],
    )
