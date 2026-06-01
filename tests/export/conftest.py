"""Shared fixtures for ``tests/export/`` — workspace builders for M9 tests.

Provides three workspace fixtures:

- ``populated_mappings_workspace`` — source + paragraph + atom + entity + resolution.
- ``empty_mappings_workspace`` — source + paragraph + atom, no entities/resolutions.
- ``resolved_atom_workspace`` — alias for ``populated_mappings_workspace`` (same shape).
- ``unresolved_atom_workspace`` — source + atom with kind=entity operand, no resolution.
- ``merged_entity_workspace`` — 2 entities (A superseded by B) + 1 atom + 1 resolution.
- ``tmp_workspace_with_two_cross_doc_relations`` — Phase 2b M9 fixture: 2
  distillation dirs + shared canonical Entity ``e-smith`` + bilateral
  Resolutions + 2 ``CrossDocRelation`` records (supports + attacks).
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
    serialize_paragraph_md,
    serialize_resolution_yaml,
    serialize_yaml,
)
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    CrossDocRelation,
    Entity,
    EntitySupersede,
    OperandRef,
    OperandTypeSchema,
    ParagraphEntry,
    ProvenanceRecord,
    Resolution,
    RoleAttribution,
    SourceMirrorManifest,
    Vocabulary,
    VocabularyEntry,
    compute_id,
)

_SOURCE_ID = "export-m9-src"
_MERGE_SOURCE_ID = "src-merge"


# ---------------------------------------------------------------------------
# Low-level helpers (mirrors tests/web/conftest.py)
# ---------------------------------------------------------------------------


def _make_marker(tmp_path: Path) -> Path:
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text("schema_version: 1\nproject_name: export-m9-test\n", encoding="utf-8")
    return tmp_path


def _build_vocabulary() -> Vocabulary:
    return Vocabulary(
        name="export-m9-vocab",
        version="0.1.0",
        entries=[
            VocabularyEntry(
                predicate="asserts_obligation",
                aliases=["asserts_shall"],
                operand_types=[
                    OperandTypeSchema(name="subject", kind="entity", required=True),
                ],
                qualifier_required=False,
                notes="export-m9 entry",
            ),
        ],
    )


def _plant_manifest(substrate: Substrate, source_id: str) -> SourceMirrorManifest:
    deterministic_hex = "0" * 64
    prov_id = "p-" + "1" * 16
    paragraphs = [
        ParagraphEntry(
            paragraph_id="p-0000",
            paragraph_index=0,
            section_path=["Section 1"],
            label="text",
            page_no=1,
            char_count=42,
            content_sha256=deterministic_hex,
        ),
    ]
    common: dict[str, Any] = {
        "source_id": source_id,
        "source_filename": "fixture.pdf",
        "source_sha256": deterministic_hex,
        "source_bytes_len": 512,
        "ingest_engine": "docling",
        "ingest_engine_version": "9.9.9",
        "vocabulary_snapshot_sha256": deterministic_hex,
        "provenance_id": prov_id,
        "paragraphs": paragraphs,
        "schema_version": 1,
    }
    draft = SourceMirrorManifest(id="m-" + "0" * 16, **common)
    manifest = SourceMirrorManifest(id=compute_id(draft), **common)
    substrate.add_source_mirror_manifest(source_id, manifest)
    # Plant paragraph .md
    for entry in paragraphs:
        path = substrate.paragraph_path(source_id, entry.paragraph_id)
        atomic_write_text(path, serialize_paragraph_md(entry, "ACME shall deliver on time."))
    return manifest


def _plant_atom(
    substrate: Substrate,
    source_id: str,
    *,
    operand_value: str = "ACME",
) -> tuple[Atom, ProvenanceRecord]:
    vocab = _build_vocabulary()
    substrate.snapshot_vocabulary(source_id, vocab)

    agent = AgentAttribution(kind="llm", identifier="test-model", role="extractor")
    role_attribution = RoleAttribution(
        agent=agent,
        activity="proposed",
        at=datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC),
    )
    operand = OperandRef(role="subject", kind="entity", value=operand_value, type_hint=None)

    atom_payload: dict[str, Any] = {
        "source_id": source_id,
        "section_path": ["Section 1"],
        "paragraph_index": 0,
        "sentence_index": None,
        "char_span": (0, 30),
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": "asserts_obligation",
        "operands": [operand],
        "narrative": f"{operand_value} shall deliver on time.",
        "qualifier_level": None,
        "qualifier_basis": None,
        "provenance_id": "p-" + "0" * 16,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    atom_payload["id"] = "a-" + "0" * 16
    atom_draft = Atom(**atom_payload)
    atom_id = compute_id(atom_draft)

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

    atom_payload["id"] = atom_id
    atom_payload["provenance_id"] = prov_id
    atom = Atom(**atom_payload)
    substrate.add_atom(source_id, atom)
    return atom, prov


def _plant_entity(
    substrate: Substrate,
    *,
    kind: str,
    canonical_name: str,
    aliases: list[str] | None = None,
) -> tuple[Entity, ProvenanceRecord]:
    agent = AgentAttribution(kind="llm", identifier="test-resolver", role="map-resolve")
    role_attribution = RoleAttribution(
        agent=agent,
        activity="proposed",
        at=datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC),
    )
    entity_draft = Entity(
        id="e-" + "0" * 16,
        kind=kind,
        canonical_name=canonical_name,
        aliases=aliases or [],
        notes=None,
        provenance_id="p-" + "0" * 16,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    entity_id = compute_id(entity_draft)

    prov_payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": "entity",
        "entity_id": entity_id,
        "activity": "reconcile_v1",
        "activity_started_at": datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC),
        "activity_ended_at": datetime(2026, 5, 30, 12, 0, 1, tzinfo=UTC),
        "used_entity_ids": [],
        "was_attributed_to": agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    prov_draft = ProvenanceRecord(**prov_payload)
    prov_id = compute_id(prov_draft)
    prov_payload["id"] = prov_id
    prov = ProvenanceRecord(**prov_payload)

    entity = entity_draft.model_copy(update={"id": entity_id, "provenance_id": prov_id})
    prov_path = substrate.mappings_provenance_path(prov.id)
    prov_path.parent.mkdir(parents=True, exist_ok=True)
    prov_path.write_text(prov.model_dump_json(indent=2), encoding="utf-8")
    substrate.add_entity(entity)
    return entity, prov


def _plant_resolution(
    substrate: Substrate,
    *,
    entity: Entity,
    atom: Atom,
    source_id: str,
    operand_index: int = 0,
) -> tuple[Resolution, ProvenanceRecord]:
    agent = AgentAttribution(kind="llm", identifier="test-resolver", role="map-resolve")
    role_attribution = RoleAttribution(
        agent=agent,
        activity="proposed",
        at=datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC),
    )
    resolution_draft = Resolution(
        id="j-" + "0" * 16,
        source_id=source_id,
        atom_id=atom.id,
        operand_index=operand_index,
        entity_id=entity.id,
        confidence="high",
        basis="exact-name-match in export fixture",
        provenance_id="p-" + "0" * 16,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    resolution_id = compute_id(resolution_draft)

    prov_payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": "resolution",
        "entity_id": resolution_id,
        "activity": "reconcile_v1",
        "activity_started_at": datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC),
        "activity_ended_at": datetime(2026, 5, 30, 12, 0, 1, tzinfo=UTC),
        "used_entity_ids": [entity.id],
        "was_attributed_to": agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    prov_draft = ProvenanceRecord(**prov_payload)
    prov_id = compute_id(prov_draft)
    prov_payload["id"] = prov_id
    prov = ProvenanceRecord(**prov_payload)

    resolution = resolution_draft.model_copy(update={"id": resolution_id, "provenance_id": prov_id})
    prov_path = substrate.mappings_provenance_path(prov.id)
    prov_path.parent.mkdir(parents=True, exist_ok=True)
    prov_path.write_text(prov.model_dump_json(indent=2), encoding="utf-8")
    substrate.add_resolution(resolution)
    return resolution, prov


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def populated_mappings_workspace(tmp_path: Path) -> Path:
    """Workspace with 1 source + 1 atom + 1 entity (ACME) + 1 resolution.

    The entity canonical_name is ``"ACME"`` — T9.2 tests assert on that.
    The resolution links the atom's operand 0 to the ACME entity.
    """
    workspace = _make_marker(tmp_path)
    substrate = Substrate(workspace)
    _plant_manifest(substrate, _SOURCE_ID)
    atom, _ = _plant_atom(substrate, _SOURCE_ID, operand_value="ACME")
    entity, _ = _plant_entity(substrate, kind="organization", canonical_name="ACME")
    _plant_resolution(substrate, entity=entity, atom=atom, source_id=_SOURCE_ID)
    return workspace


@pytest.fixture
def empty_mappings_workspace(tmp_path: Path) -> Path:
    """Workspace with 1 source + 1 atom but NO entities or resolutions."""
    workspace = _make_marker(tmp_path)
    substrate = Substrate(workspace)
    _plant_manifest(substrate, _SOURCE_ID)
    _plant_atom(substrate, _SOURCE_ID)
    return workspace


# resolved_atom_workspace is an alias for populated_mappings_workspace —
# same substrate shape (source + atom + entity + resolution).
@pytest.fixture
def resolved_atom_workspace(tmp_path: Path) -> Path:
    """Workspace with 1 atom that has a fully-resolved kind=entity operand."""
    workspace = _make_marker(tmp_path)
    substrate = Substrate(workspace)
    _plant_manifest(substrate, _SOURCE_ID)
    atom, _ = _plant_atom(substrate, _SOURCE_ID, operand_value="ACME")
    entity, _ = _plant_entity(substrate, kind="organization", canonical_name="ACME")
    _plant_resolution(substrate, entity=entity, atom=atom, source_id=_SOURCE_ID)
    return workspace


@pytest.fixture
def unresolved_atom_workspace(tmp_path: Path) -> Path:
    """Workspace with 1 atom (kind=entity operand) but NO resolution."""
    workspace = _make_marker(tmp_path)
    substrate = Substrate(workspace)
    _plant_manifest(substrate, _SOURCE_ID)
    _plant_atom(substrate, _SOURCE_ID, operand_value="ACME")
    # Plant the entity so it exists, but deliberately omit the resolution.
    _plant_entity(substrate, kind="organization", canonical_name="ACME")
    return workspace


@pytest.fixture
def merged_entity_workspace(tmp_path: Path) -> tuple[Path, str, str, str]:
    """Workspace with entity_A superseded by entity_B + 1 atom + 1 resolution.

    Plants:
    - ``entity_A`` (kind=``organization``, canonical_name=``"Old Corp"``)
    - ``entity_B`` (kind=``organization``, canonical_name=``"New Corp"``)
    - ``atom`` with kind=entity operand value ``"Old Corp"``
    - ``resolution_R`` targeting entity_A's id (on-disk entity_id == A)
    - ``EntitySupersede(A → B)``

    Returns ``(workspace_path, entity_A_id, entity_B_id, resolution_R_id)``.
    """
    workspace = _make_marker(tmp_path)
    substrate = Substrate(workspace)
    _plant_manifest(substrate, _MERGE_SOURCE_ID)
    atom, _ = _plant_atom(substrate, _MERGE_SOURCE_ID, operand_value="Old Corp")

    entity_a, _ = _plant_entity(substrate, kind="organization", canonical_name="Old Corp")
    entity_b, _ = _plant_entity(substrate, kind="organization", canonical_name="New Corp")

    resolution_r, _ = _plant_resolution(
        substrate, entity=entity_a, atom=atom, source_id=_MERGE_SOURCE_ID
    )

    # Build EntitySupersede(A → B)
    now = datetime(2026, 5, 31, 10, 0, 0, tzinfo=UTC)
    agent = AgentAttribution(kind="human", identifier="test-supervisor", role="human_supervisor")
    role_attr = RoleAttribution(agent=agent, activity="merged", at=now)

    es_draft = EntitySupersede(
        id="t-" + "0" * 16,
        kind="entity",
        superseded_entity_id=entity_a.id,
        replacement_entity_id=entity_b.id,
        reason="fixture merge for CV-9 export test",
        provenance_id="p-" + "0" * 16,
        role_attributions=[role_attr],
        schema_version=1,
    )
    es_id = compute_id(es_draft)

    prov_es_draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="entity-supersede",
        entity_id=es_id,
        activity="entity-merge",
        activity_started_at=now,
        activity_ended_at=now,
        used_entity_ids=[],
        was_attributed_to=agent,
        was_influenced_by=[],
        schema_version=1,
    )
    prov_es_id = compute_id(prov_es_draft)
    prov_es = prov_es_draft.model_copy(update={"id": prov_es_id})
    es = es_draft.model_copy(update={"id": es_id, "provenance_id": prov_es_id})

    prov_es_path = substrate.mappings_provenance_path(prov_es.id)
    prov_es_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(prov_es_path, serialize_yaml(prov_es))
    substrate.add_entity_supersede(es)

    return workspace, entity_a.id, entity_b.id, resolution_r.id


# ---------------------------------------------------------------------------
# Phase 2b M9 — cross-doc relation export fixtures
# ---------------------------------------------------------------------------
#
# Mirrors ``tests/web/conftest.py::tmp_workspace_with_two_cross_doc_relations``.
# Plants:
#   * The INV-1 marker.
#   * Two empty distillation directories (``src-A`` / ``src-B``).
#   * A shared canonical Entity (``e-smith``) + bilateral Resolutions so
#     ``Substrate.add_cross_doc_relation``'s INV-15 gate passes.
#   * Two CrossDocRelation records — one ``supports`` and one ``attacks`` —
#     committed via the substrate so all write-time gates have run.

_M9_FROM_SOURCE = "src-A"
_M9_FROM_ATOM = "a-fixture0001"
_M9_TO_SOURCE = "src-B"
_M9_TO_ATOM = "a-fixture0002"
_M9_SHARED_ENTITY = "e-smith"
_M9_STABLE_AT = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)


def _m9_plant_distillation_dir(workspace: Path, source_id: str) -> None:
    (workspace / "distillations" / source_id).mkdir(parents=True, exist_ok=True)


def _m9_plant_entity_literal(workspace: Path, entity: Entity) -> None:
    """Plant an Entity at its literal id (bypass content-addressable add_entity)."""
    path = workspace / "mappings" / "entities" / f"{entity.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, serialize_entity_md(entity))


def _m9_plant_resolution_literal(workspace: Path, resolution: Resolution) -> None:
    """Plant a Resolution at its literal id (bypass content-addressable add_resolution)."""
    path = workspace / "mappings" / "resolutions" / f"{resolution.id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, serialize_resolution_yaml(resolution))


def _m9_role_attribution() -> RoleAttribution:
    return RoleAttribution(
        agent=AgentAttribution(kind="llm", identifier="claude-opus-4-7", role="connect"),
        activity="proposed",
        at=_M9_STABLE_AT,
    )


def _m9_build_cross_doc_relation(
    *,
    kind: str,
    warrant: str,
    role_attribution: RoleAttribution,
) -> CrossDocRelation:
    """Build a CrossDocRelation whose id matches ``compute_id`` for its content."""
    payload: dict[str, Any] = {
        "id": "x-" + "0" * 16,
        "from_atom_id": _M9_FROM_ATOM,
        "from_source_id": _M9_FROM_SOURCE,
        "to_atom_id": _M9_TO_ATOM,
        "to_source_id": _M9_TO_SOURCE,
        "kind": kind,
        "warrant": warrant,
        "warrant_defensibility": "conventional",
        "warrant_basis": "Both atoms reference the same canonical Smith entity.",
        "confidence": "medium",
        "shared_entities": [_M9_SHARED_ENTITY],
        "provenance_id": "p-m9-cdr00000001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    draft = CrossDocRelation(**payload)
    payload["id"] = compute_id(draft)
    return CrossDocRelation(**payload)


def _m9_plant_shared_scaffold(workspace: Path) -> RoleAttribution:
    """Plant INV-1 marker + distillation dirs + shared Entity + bilateral Resolutions."""
    marker = workspace / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: m9-cross-doc-fixture\n",
        encoding="utf-8",
    )
    _m9_plant_distillation_dir(workspace, _M9_FROM_SOURCE)
    _m9_plant_distillation_dir(workspace, _M9_TO_SOURCE)

    role_attr = _m9_role_attribution()

    entity = Entity(
        id=_M9_SHARED_ENTITY,
        kind="party",
        canonical_name="Smith",
        aliases=[],
        notes=None,
        provenance_id="p-m9-ent00000001",
        role_attributions=[role_attr],
        schema_version=1,
    )
    _m9_plant_entity_literal(workspace, entity)

    for slug, source_id, atom_id in (
        ("from", _M9_FROM_SOURCE, _M9_FROM_ATOM),
        ("to", _M9_TO_SOURCE, _M9_TO_ATOM),
    ):
        res = Resolution(
            id=f"j-m9-fixture-{slug}",
            source_id=source_id,
            atom_id=atom_id,
            operand_index=0,
            entity_id=_M9_SHARED_ENTITY,
            confidence="high",
            basis="fixture-planted for M9 export tests",
            provenance_id="p-m9-res00000001",
            role_attributions=[role_attr],
            schema_version=1,
        )
        _m9_plant_resolution_literal(workspace, res)
    return role_attr


@pytest.fixture
def tmp_workspace_with_two_cross_doc_relations(tmp_path: Path) -> Path:
    """Workspace with two committed CrossDocRelation records (supports + attacks).

    Same shape as ``tests/web/conftest.py``'s fixture of the same name —
    duplicated here so the export tests stay self-contained.
    """
    role_attr = _m9_plant_shared_scaffold(tmp_path)
    substrate = Substrate(tmp_path)
    rel_supports = _m9_build_cross_doc_relation(
        kind="supports",
        warrant="Both endpoints attest the Smith role in matching positions.",
        role_attribution=role_attr,
    )
    rel_attacks = _m9_build_cross_doc_relation(
        kind="attacks",
        warrant="The two endpoints describe the Smith role in contradictory ways.",
        role_attribution=role_attr,
    )
    substrate.add_cross_doc_relation(rel_supports)
    substrate.add_cross_doc_relation(rel_attacks)
    return tmp_path
