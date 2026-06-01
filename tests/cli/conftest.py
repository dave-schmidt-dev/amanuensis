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
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import (
    serialize_entity_md,
    serialize_resolution_yaml,
)
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    Clarification,
    CrossDocRelation,
    Entity,
    OperandRef,
    OperandTypeSchema,
    ProvenanceRecord,
    Resolution,
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
        "kind": "warrant-defensibility-contested",
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
        "schema_version": 2,
    }
    draft = Clarification(**payload)
    payload["id"] = compute_id(draft)
    clar = Clarification(**payload)
    cli_substrate.add_clarification(SOURCE_ID, clar)
    return clar


# ---------------------------------------------------------------------------
# Phase 2b M7 — cross-doc relation CLI fixtures
# ---------------------------------------------------------------------------
#
# The M7 verbs operate against a workspace that already contains
# committed CrossDocRelation records. The fixture below mirrors the
# dispatch-test ``tmp_workspace_with_bilateral_resolutions`` pattern: it
# plants a shared canonical Entity + bilateral Resolutions so the INV-15
# gate inside ``Substrate.add_cross_doc_relation`` passes, then writes
# two distinct CrossDocRelations (one ``supports``, one ``attacks``) via
# the substrate gate.

_M7_FROM_SOURCE = "src-A"
_M7_FROM_ATOM = "a-fixture0001"
_M7_TO_SOURCE = "src-B"
_M7_TO_ATOM = "a-fixture0002"
_M7_SHARED_ENTITY = "e-smith"
_M7_STABLE_AT = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)


def _m7_plant_distillation_dir(workspace: Path, source_id: str) -> None:
    (workspace / "distillations" / source_id).mkdir(parents=True, exist_ok=True)


def _m7_plant_entity(workspace: Path, entity: Entity) -> None:
    path = workspace / "mappings" / "entities" / f"{entity.id}.md"
    atomic_write_text(path, serialize_entity_md(entity))


def _m7_plant_resolution(workspace: Path, resolution: Resolution) -> None:
    path = workspace / "mappings" / "resolutions" / f"{resolution.id}.yaml"
    atomic_write_text(path, serialize_resolution_yaml(resolution))


def _m7_role_attribution() -> RoleAttribution:
    return RoleAttribution(
        agent=AgentAttribution(kind="llm", identifier="claude-opus-4-7", role="connect"),
        activity="proposed",
        at=_M7_STABLE_AT,
    )


def _m7_build_cross_doc_relation(
    *,
    kind: str,
    warrant: str,
    role_attribution: RoleAttribution,
) -> CrossDocRelation:
    """Build a CrossDocRelation whose id matches ``compute_id`` for its content."""
    payload: dict[str, Any] = {
        "id": "x-" + "0" * 16,
        "from_atom_id": _M7_FROM_ATOM,
        "from_source_id": _M7_FROM_SOURCE,
        "to_atom_id": _M7_TO_ATOM,
        "to_source_id": _M7_TO_SOURCE,
        "kind": kind,
        "warrant": warrant,
        "warrant_defensibility": "conventional",
        "warrant_basis": "Both atoms reference the same canonical Smith entity.",
        "confidence": "medium",
        "shared_entities": [_M7_SHARED_ENTITY],
        "provenance_id": "p-m7-cdr00000001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    draft = CrossDocRelation(**payload)
    payload["id"] = compute_id(draft)
    return CrossDocRelation(**payload)


# ---------------------------------------------------------------------------
# Phase 2c M9 — Walton-scheme snapshot fixture for probandum CLI tests
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace_with_walton_snapshot(tmp_path: Path) -> Path:
    """Workspace with the INV-1 marker + a pinned generic Walton-scheme snapshot.

    Many Phase 2c (Hierarchize) CLI verbs touch ``add_probandum`` which
    enforces the INV-18 closed-vocabulary gate at write-time. This
    fixture pins the bundled generic catalogue (via
    ``Substrate.snapshot_walton_schemes``) so probandum writes that name
    a known scheme (e.g. ``argument-from-sign``) clear the gate.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: m9-walton-fixture\n",
        encoding="utf-8",
    )
    Substrate(tmp_path).snapshot_walton_schemes()
    return tmp_path


@pytest.fixture
def tmp_workspace_with_two_cross_doc_relations(tmp_path: Path) -> Path:
    """Workspace with two committed CrossDocRelation records.

    Plants:
      * The INV-1 marker.
      * Two empty distillation directories (``src-A`` / ``src-B``).
      * A shared canonical Entity (``e-smith``) + bilateral Resolutions
        so the INV-15 shared-entity gate accepts the relations.
      * Two CrossDocRelation records — one ``supports`` and one
        ``attacks`` — committed via ``Substrate.add_cross_doc_relation``
        so the INV-13 / INV-15 / id-discipline gates have all run.

    The two relations differ only in ``kind`` + ``warrant`` so their
    content-addressable ids diverge.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: m7-cross-doc-fixture\n",
        encoding="utf-8",
    )
    _m7_plant_distillation_dir(tmp_path, _M7_FROM_SOURCE)
    _m7_plant_distillation_dir(tmp_path, _M7_TO_SOURCE)

    role_attr = _m7_role_attribution()

    # Shared Entity (literal id; INV-15 walks via latest_entity_for).
    entity = Entity(
        id=_M7_SHARED_ENTITY,
        kind="party",
        canonical_name="Smith",
        aliases=[],
        notes=None,
        provenance_id="p-m7-ent00000001",
        role_attributions=[role_attr],
        schema_version=1,
    )
    _m7_plant_entity(tmp_path, entity)

    # Bilateral Resolutions.
    for slug, source_id, atom_id in (
        ("from", _M7_FROM_SOURCE, _M7_FROM_ATOM),
        ("to", _M7_TO_SOURCE, _M7_TO_ATOM),
    ):
        res = Resolution(
            id=f"j-m7-fixture-{slug}",
            source_id=source_id,
            atom_id=atom_id,
            operand_index=0,
            entity_id=_M7_SHARED_ENTITY,
            confidence="high",
            basis="fixture-planted for M7 CLI tests",
            provenance_id="p-m7-res00000001",
            role_attributions=[role_attr],
            schema_version=1,
        )
        _m7_plant_resolution(tmp_path, res)

    # Two CrossDocRelations through the gate.
    substrate = Substrate(tmp_path)
    rel_supports = _m7_build_cross_doc_relation(
        kind="supports",
        warrant="Both endpoints attest Smith's role in matching positions.",
        role_attribution=role_attr,
    )
    rel_attacks = _m7_build_cross_doc_relation(
        kind="attacks",
        warrant="The two endpoints describe Smith's role in contradictory ways.",
        role_attribution=role_attr,
    )
    substrate.add_cross_doc_relation(rel_supports)
    substrate.add_cross_doc_relation(rel_attacks)
    return tmp_path
