"""Shared fixtures for ``tests/cli/`` — workspace + Substrate-backed builders.

The ``cli_workspace`` fixture creates a minimal valid workspace (an
empty tmpdir with the INV-1 marker) so marker-protected commands run
without tripping ``@require_marker``. Several command tests also need
to plant a hand-built substrate state (an atom, a clarification, a
vocabulary snapshot) — fixtures here keep those builders DRY.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import Substrate
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    Clarification,
    OperandRef,
    OperandTypeSchema,
    ProvenanceRecord,
    RoleAttribution,
    Vocabulary,
    VocabularyEntry,
    compute_id,
)

SOURCE_ID = "cli-fixture-src"


@pytest.fixture
def cli_workspace(tmp_path: Path) -> Path:
    """An empty tmpdir with the INV-1 marker."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: cli-test\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def cli_substrate(cli_workspace: Path) -> Substrate:
    return Substrate(cli_workspace)


def _build_vocabulary() -> Vocabulary:
    return Vocabulary(
        name="cli-test-vocab",
        version="0.1.0",
        entries=[
            VocabularyEntry(
                predicate="asserts_obligation",
                aliases=["asserts_shall"],
                operand_types=[
                    OperandTypeSchema(name="subject", kind="entity", required=True),
                ],
                qualifier_required=False,
                notes="cli-test entry",
            ),
        ],
    )


@pytest.fixture
def cli_vocabulary() -> Vocabulary:
    return _build_vocabulary()


def _planted_atom_substrate(
    substrate: Substrate, *, source_id: str = SOURCE_ID
) -> tuple[Atom, ProvenanceRecord]:
    """Plant one atom + its provenance + a vocabulary snapshot under ``source_id``.

    Reused by atom / clarification / vocabulary / status tests that
    need a non-empty substrate to validate against. Returns the planted
    atom + its PROV record so callers can assert against the planted ids.
    """
    vocab = _build_vocabulary()
    substrate.snapshot_vocabulary(source_id, vocab)

    agent = AgentAttribution(kind="llm", identifier="test-model", role="extractor")
    role_attribution = RoleAttribution(
        agent=agent,
        activity="proposed",
        at=datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC),
    )
    operand = OperandRef(role="subject", kind="entity", value="ent-acme", type_hint=None)

    atom_payload: dict[str, Any] = {
        "source_id": source_id,
        "section_path": ["Part I", "§1"],
        "paragraph_index": 0,
        "sentence_index": None,
        "char_span": (0, 30),
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": "asserts_obligation",
        "operands": [operand],
        "narrative": "ACME shall pay within 30 days.",
        "qualifier_level": None,
        "qualifier_basis": None,
        "provenance_id": "p-" + "0" * 16,  # placeholder; rewritten below
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    # Build the atom first with a placeholder provenance_id; provenance_id
    # is volatile for atom hashing so the id is stable.
    atom_payload["id"] = "a-" + "0" * 16
    atom_draft = Atom(**atom_payload)
    atom_id = compute_id(atom_draft)

    # PROV record whose entity_id == atom_id.
    prov_payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": "atom",
        "entity_id": atom_id,
        "activity": "extract_v1",
        "activity_started_at": datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC),
        "activity_ended_at": datetime(2026, 5, 30, 12, 0, 1, tzinfo=UTC),
        "used_entity_ids": [source_id],
        "was_attributed_to": agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    prov_draft = ProvenanceRecord(**prov_payload)
    prov_id = compute_id(prov_draft)
    prov_payload["id"] = prov_id
    prov = ProvenanceRecord(**prov_payload)
    substrate.add_provenance(source_id, prov)

    # Final atom with the real provenance_id; id is unchanged.
    atom_payload["id"] = atom_id
    atom_payload["provenance_id"] = prov_id
    atom = Atom(**atom_payload)
    substrate.add_atom(source_id, atom)
    return atom, prov


@pytest.fixture
def planted_atom(cli_substrate: Substrate) -> tuple[Atom, ProvenanceRecord]:
    return _planted_atom_substrate(cli_substrate)


@pytest.fixture
def planted_clarification(
    cli_substrate: Substrate, planted_atom: tuple[Atom, ProvenanceRecord]
) -> Clarification:
    """Plant one open clarification under SOURCE_ID."""
    atom, prov = planted_atom
    agent = AgentAttribution(kind="llm", identifier="auditor-test", role="auditor")
    payload: dict[str, Any] = {
        "id": "c-" + "0" * 16,
        "status": "open",
        "raised_at": datetime(2026, 5, 30, 12, 5, 0, tzinfo=UTC),
        "raised_by": agent,
        "raised_by_activity": "audit_v1",
        "context_refs": [atom.id],
        "question": "Is ACME the parent or a subsidiary?",
        "options": ["parent", "subsidiary"],
        "resolved_at": None,
        "resolved_by": None,
        "resolution": None,
        "raised_provenance_id": prov.id,
        "resolved_provenance_id": None,
        "schema_version": 1,
    }
    draft = Clarification(**payload)
    payload["id"] = compute_id(draft)
    clar = Clarification(**payload)
    cli_substrate.add_clarification(SOURCE_ID, clar)
    return clar
