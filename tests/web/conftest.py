"""Shared fixtures for ``tests/web/`` — workspace + planted-substrate builders.

Mirrors ``tests/cli/conftest.py``'s ``_planted_atom_substrate`` helper
but exposes it via fixtures suited to TestClient-driven web tests:

- ``web_workspace`` — empty tmpdir with INV-1 marker.
- ``web_substrate`` — Substrate bound to that workspace.
- ``planted_atom_workspace`` — workspace + one atom + its provenance +
  vocabulary snapshot, so the dashboard renders a non-empty table.
- ``planted_manifest_workspace`` — workspace + one source-mirror
  manifest, so the source-overview page renders the manifest summary.

Tests use ``monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))``
to point the FastAPI app at the fixture workspace per test.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import Substrate
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import (
    serialize_atom_md,
    serialize_entity_md,
    serialize_resolution_yaml,
    serialize_yaml,
)
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    Clarification,
    CrossDocRelation,
    CrossDocRelationSupersede,
    Entity,
    EntitySupersede,
    OperandRef,
    OperandTypeSchema,
    ParagraphEntry,
    Probandum,
    ProbandumEdge,
    ProvenanceRecord,
    Resolution,
    RoleAttribution,
    SourceMirrorManifest,
    Vocabulary,
    VocabularyEntry,
    compute_id,
)

SOURCE_ID = "web-fixture-src"


@pytest.fixture
def web_workspace(tmp_path: Path) -> Path:
    """An empty tmpdir with the INV-1 marker."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: web-test\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def web_substrate(web_workspace: Path) -> Substrate:
    return Substrate(web_workspace)


def _build_vocabulary() -> Vocabulary:
    return Vocabulary(
        name="web-test-vocab",
        version="0.1.0",
        entries=[
            VocabularyEntry(
                predicate="asserts_obligation",
                aliases=["asserts_shall"],
                operand_types=[
                    OperandTypeSchema(name="subject", kind="entity", required=True),
                ],
                qualifier_required=False,
                notes="web-test entry",
            ),
        ],
    )


def _plant_atom(substrate: Substrate, source_id: str) -> tuple[Atom, ProvenanceRecord]:
    """Plant one atom + provenance + vocabulary snapshot under ``source_id``."""
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


@pytest.fixture
def planted_atom_workspace(
    web_workspace: Path, web_substrate: Substrate
) -> tuple[Path, Atom, ProvenanceRecord]:
    """Workspace with one planted atom; returns (workspace_path, atom, prov)."""
    atom, prov = _plant_atom(web_substrate, SOURCE_ID)
    return web_workspace, atom, prov


def _plant_manifest(substrate: Substrate, source_id: str) -> SourceMirrorManifest:
    """Plant a minimal valid SourceMirrorManifest under ``source_id``.

    Source-mirror manifests are content-addressable like every other
    substrate artifact: the helper computes the id from a draft, then
    rebuilds the final model with the real id so ``add_source_mirror_manifest``
    accepts it. Uses deterministic placeholder hashes so the planted state
    is stable across runs.
    """
    deterministic_hex = "0" * 64
    prov_id = "p-" + "1" * 16
    paragraphs = [
        ParagraphEntry(
            paragraph_id="p-0001",
            paragraph_index=0,
            section_path=["Preamble"],
            label="text",
            page_no=1,
            char_count=42,
            content_sha256=deterministic_hex,
        ),
        ParagraphEntry(
            paragraph_id="p-0002",
            paragraph_index=1,
            section_path=["Preamble"],
            label="text",
            page_no=1,
            char_count=58,
            content_sha256=deterministic_hex,
        ),
    ]
    common_fields: dict[str, Any] = {
        "source_id": source_id,
        "source_filename": "example.pdf",
        "source_sha256": deterministic_hex,
        "source_bytes_len": 1024,
        "ingest_engine": "docling",
        "ingest_engine_version": "9.9.9",
        "vocabulary_snapshot_sha256": deterministic_hex,
        "provenance_id": prov_id,
        "paragraphs": paragraphs,
        "schema_version": 1,
    }
    draft = SourceMirrorManifest(id="m-" + "0" * 16, **common_fields)
    manifest = SourceMirrorManifest(id=compute_id(draft), **common_fields)
    substrate.add_source_mirror_manifest(source_id, manifest)
    return manifest


@pytest.fixture
def planted_manifest_workspace(
    web_workspace: Path, web_substrate: Substrate
) -> tuple[Path, SourceMirrorManifest]:
    """Workspace with one planted source-mirror manifest."""
    manifest = _plant_manifest(web_substrate, SOURCE_ID)
    return web_workspace, manifest


def _plant_clarification(
    substrate: Substrate, *, atom: Atom, prov: ProvenanceRecord, source_id: str
) -> Clarification:
    """Plant one open clarification under ``source_id``.

    Mirrors ``tests/cli/conftest._planted_atom_substrate``'s clarification
    helper but exposes the fixture flavor the web POST tests want: an
    open clarification whose id can be looked up across distillations
    without a CLI shim.
    """
    raising_agent = AgentAttribution(kind="llm", identifier="auditor-test", role="auditor")
    payload: dict[str, Any] = {
        "id": "c-" + "0" * 16,
        "status": "open",
        "kind": "warrant-defensibility-contested",
        "raised_at": datetime(2026, 5, 30, 12, 5, 0, tzinfo=UTC),
        "raised_by": raising_agent,
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
    substrate.add_clarification(source_id, clar)
    return clar


@pytest.fixture
def planted_clarification_workspace(
    web_workspace: Path, web_substrate: Substrate
) -> tuple[Path, Clarification, Atom, ProvenanceRecord]:
    """Workspace with one atom + one open clarification.

    Returns ``(workspace_path, clarification, atom, atom_prov)``. The
    atom + its provenance are also returned so a test can build a
    plausible context-ref payload without re-walking the substrate.
    """
    atom, prov = _plant_atom(web_substrate, SOURCE_ID)
    clar = _plant_clarification(web_substrate, atom=atom, prov=prov, source_id=SOURCE_ID)
    return web_workspace, clar, atom, prov


# ---------------------------------------------------------------------------
# Entity + Resolution fixture helpers (T8.1 - T8.3)
# ---------------------------------------------------------------------------


def _plant_entity(
    substrate: Substrate,
    *,
    kind: str,
    canonical_name: str,
    aliases: list[str] | None = None,
    notes: str | None = None,
) -> tuple[Entity, ProvenanceRecord]:
    """Plant one Entity + its mappings-layer ProvenanceRecord.

    Builds a content-addressable Entity via the standard compute_id
    pattern, then persists it to ``mappings/entities/`` and its prov
    to ``mappings/provenance/``.
    """
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
        notes=notes,
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
    # Write prov to mappings/provenance/ (no substrate helper; write directly).
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
) -> tuple[Resolution, ProvenanceRecord]:
    """Plant one Resolution + its mappings-layer ProvenanceRecord."""
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
        operand_index=0,
        entity_id=entity.id,
        confidence="high",
        basis="exact-name-match in fixture",
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
    # Write prov to mappings/provenance/ (no substrate helper; write directly).
    prov_path = substrate.mappings_provenance_path(prov.id)
    prov_path.parent.mkdir(parents=True, exist_ok=True)
    prov_path.write_text(prov.model_dump_json(indent=2), encoding="utf-8")
    substrate.add_resolution(resolution)
    return resolution, prov


@pytest.fixture
def planted_entities_workspace(web_workspace: Path, web_substrate: Substrate) -> Path:
    """Workspace with 2 entities of different kinds.

    Plants:
    - ``ACME Corp`` (kind=``organization``) with alias ``Acme``
    - ``Alice Smith`` (kind=``person``)

    Returns the workspace path (use ``monkeypatch.setenv`` in tests).
    """
    _plant_entity(
        web_substrate,
        kind="organization",
        canonical_name="ACME Corp",
        aliases=["Acme"],
    )
    _plant_entity(
        web_substrate,
        kind="person",
        canonical_name="Alice Smith",
    )
    return web_workspace


@pytest.fixture
def planted_resolutions_workspace(web_workspace: Path, web_substrate: Substrate) -> Path:
    """Workspace with 1 entity + 1 atom + 1 resolution.

    Plants the atom under ``SOURCE_ID``, an entity, and a resolution
    linking the atom's first operand to the entity.

    Returns the workspace path.
    """
    atom, _atom_prov = _plant_atom(web_substrate, SOURCE_ID)
    entity, _entity_prov = _plant_entity(
        web_substrate,
        kind="organization",
        canonical_name="ACME Corp",
        aliases=["Acme"],
    )
    _plant_resolution(web_substrate, entity=entity, atom=atom, source_id=SOURCE_ID)
    return web_workspace


# ---------------------------------------------------------------------------
# Merged-entity fixture (T8.8 — CV-9 supersede-chain walking)
# ---------------------------------------------------------------------------

_MERGE_SOURCE_ID = "src-merge"


@pytest.fixture
def merged_entity_workspace(
    web_workspace: Path, web_substrate: Substrate
) -> tuple[Path, str, str, str]:
    """Workspace with 2 entities + 1 resolution + 1 EntitySupersede.

    Plants:
    - ``entity_A`` (kind=``organization``, superseded by entity_B)
    - ``entity_B`` (kind=``organization``, canonical)
    - ``resolution_R`` targeting entity_A's id (on-disk entity_id == A)
    - ``EntitySupersede(A → B)``

    Also plants the atom that resolution_R anchors to, so that the
    atom-entity-index endpoint has something to index.

    Returns ``(workspace_path, entity_A_id, entity_B_id, resolution_R_id)``.
    """
    now = datetime(2026, 5, 31, 10, 0, 0, tzinfo=UTC)
    agent = AgentAttribution(kind="human", identifier="test-supervisor", role="human_supervisor")
    role_attr = RoleAttribution(agent=agent, activity="merged", at=now)

    # Plant the atom that resolution_R will anchor to.
    atom, _atom_prov = _plant_atom(web_substrate, _MERGE_SOURCE_ID)

    # Plant entity_A and entity_B.
    entity_a, _prov_a = _plant_entity(
        web_substrate,
        kind="organization",
        canonical_name="Old Corp",
    )
    entity_b, _prov_b = _plant_entity(
        web_substrate,
        kind="organization",
        canonical_name="New Corp",
    )

    # Plant resolution_R pointing to entity_A (the superseded entity).
    resolution_r, _prov_r = _plant_resolution(
        web_substrate, entity=entity_a, atom=atom, source_id=_MERGE_SOURCE_ID
    )

    # Build an EntitySupersede(A → B) and write it.
    es_draft = EntitySupersede(
        id="t-" + "0" * 16,
        kind="entity",
        superseded_entity_id=entity_a.id,
        replacement_entity_id=entity_b.id,
        reason="fixture merge for T8.8 CV-9 test",
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

    prov_es_path = web_substrate.mappings_provenance_path(prov_es.id)
    prov_es_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(prov_es_path, serialize_yaml(prov_es))
    web_substrate.add_entity_supersede(es)

    return web_workspace, entity_a.id, entity_b.id, resolution_r.id


# ---------------------------------------------------------------------------
# Phase 2b M8 — cross-doc relation web fixtures
# ---------------------------------------------------------------------------
#
# Mirror of ``tests/cli/conftest.py``'s
# ``tmp_workspace_with_two_cross_doc_relations``. Plants:
#
#   * The INV-1 marker.
#   * Two empty distillation directories (``src-A`` / ``src-B``).
#   * A shared canonical Entity (``e-smith``) + bilateral Resolutions so
#     ``Substrate.add_cross_doc_relation``'s INV-15 gate passes.
#   * Two CrossDocRelation records — one ``supports`` and one
#     ``attacks`` — committed via the substrate so all write-time gates
#     have run.
#
# The two relations differ only in ``kind`` + ``warrant`` so their
# content-addressable ids diverge.

_M8_FROM_SOURCE = "src-A"
_M8_FROM_ATOM = "a-fixture0001"
_M8_TO_SOURCE = "src-B"
_M8_TO_ATOM = "a-fixture0002"
_M8_SHARED_ENTITY = "e-smith"
_M8_STABLE_AT = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)


def _m8_plant_distillation_dir(workspace: Path, source_id: str) -> None:
    (workspace / "distillations" / source_id).mkdir(parents=True, exist_ok=True)


def _m8_plant_entity_literal(workspace: Path, entity: Entity) -> None:
    """Write an Entity to ``mappings/entities/<id>.md`` bypassing add_entity.

    Phase 2b's CrossDocRelation INV-15 gate looks up entities through
    ``latest_entity_for`` and accepts any id whose terminal record exists,
    so we plant a literal-id entity (``e-smith``) rather than a
    content-addressable one to keep the bilateral-resolution scaffolding
    short and stable across runs.
    """
    path = workspace / "mappings" / "entities" / f"{entity.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, serialize_entity_md(entity))


def _m8_plant_resolution_literal(workspace: Path, resolution: Resolution) -> None:
    """Write a Resolution to ``mappings/resolutions/<id>.yaml`` bypassing add_resolution."""
    path = workspace / "mappings" / "resolutions" / f"{resolution.id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, serialize_resolution_yaml(resolution))


def _m8_role_attribution() -> RoleAttribution:
    return RoleAttribution(
        agent=AgentAttribution(kind="llm", identifier="claude-opus-4-7", role="connect"),
        activity="proposed",
        at=_M8_STABLE_AT,
    )


def _m8_build_cross_doc_relation(
    *,
    kind: str,
    warrant: str,
    role_attribution: RoleAttribution,
) -> CrossDocRelation:
    """Build a CrossDocRelation whose id matches ``compute_id`` for its content."""
    payload: dict[str, Any] = {
        "id": "x-" + "0" * 16,
        "from_atom_id": _M8_FROM_ATOM,
        "from_source_id": _M8_FROM_SOURCE,
        "to_atom_id": _M8_TO_ATOM,
        "to_source_id": _M8_TO_SOURCE,
        "kind": kind,
        "warrant": warrant,
        "warrant_defensibility": "conventional",
        "warrant_basis": "Both atoms reference the same canonical Smith entity.",
        "confidence": "medium",
        "shared_entities": [_M8_SHARED_ENTITY],
        "provenance_id": "p-m8-cdr00000001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    draft = CrossDocRelation(**payload)
    payload["id"] = compute_id(draft)
    return CrossDocRelation(**payload)


def _m8_plant_shared_scaffold(workspace: Path) -> RoleAttribution:
    """Plant marker, distillation dirs, shared Entity, bilateral Resolutions."""
    marker = workspace / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: m8-cross-doc-fixture\n",
        encoding="utf-8",
    )
    _m8_plant_distillation_dir(workspace, _M8_FROM_SOURCE)
    _m8_plant_distillation_dir(workspace, _M8_TO_SOURCE)

    role_attr = _m8_role_attribution()

    # Shared Entity (literal id; INV-15 walks via latest_entity_for).
    entity = Entity(
        id=_M8_SHARED_ENTITY,
        kind="party",
        canonical_name="Smith",
        aliases=[],
        notes=None,
        provenance_id="p-m8-ent00000001",
        role_attributions=[role_attr],
        schema_version=1,
    )
    _m8_plant_entity_literal(workspace, entity)

    # Bilateral Resolutions.
    for slug, source_id, atom_id in (
        ("from", _M8_FROM_SOURCE, _M8_FROM_ATOM),
        ("to", _M8_TO_SOURCE, _M8_TO_ATOM),
    ):
        res = Resolution(
            id=f"j-m8-fixture-{slug}",
            source_id=source_id,
            atom_id=atom_id,
            operand_index=0,
            entity_id=_M8_SHARED_ENTITY,
            confidence="high",
            basis="fixture-planted for M8 web tests",
            provenance_id="p-m8-res00000001",
            role_attributions=[role_attr],
            schema_version=1,
        )
        _m8_plant_resolution_literal(workspace, res)
    return role_attr


@pytest.fixture
def tmp_workspace_with_two_cross_doc_relations(tmp_path: Path) -> Path:
    """Workspace with two committed CrossDocRelation records (supports + attacks).

    Same shape as the CLI M7 fixture of the same name (see
    ``tests/cli/conftest.py``). Lives here too so web tests can stay
    self-contained.
    """
    role_attr = _m8_plant_shared_scaffold(tmp_path)
    substrate = Substrate(tmp_path)
    rel_supports = _m8_build_cross_doc_relation(
        kind="supports",
        warrant="Both endpoints attest the Smith role in matching positions.",
        role_attribution=role_attr,
    )
    rel_attacks = _m8_build_cross_doc_relation(
        kind="attacks",
        warrant="The two endpoints describe the Smith role in contradictory ways.",
        role_attribution=role_attr,
    )
    substrate.add_cross_doc_relation(rel_supports)
    substrate.add_cross_doc_relation(rel_attacks)
    return tmp_path


@pytest.fixture
def tmp_workspace_with_cross_doc_supersede_chain(
    tmp_path: Path,
) -> tuple[Path, str, str]:
    """Workspace with two CrossDocRelations + one CrossDocRelationSupersede.

    Plants the same shared scaffold as
    ``tmp_workspace_with_two_cross_doc_relations``, two cross-doc
    relations (an ``old`` ``supports`` relation and a ``new`` ``attacks``
    relation), then a ``CrossDocRelationSupersede`` record pointing
    ``old → new``.

    Returns ``(workspace_path, old_relation_id, new_relation_id)``.
    """
    role_attr = _m8_plant_shared_scaffold(tmp_path)
    substrate = Substrate(tmp_path)
    rel_old = _m8_build_cross_doc_relation(
        kind="supports",
        warrant="Initial reading: the Smith role aligns across both atoms.",
        role_attribution=role_attr,
    )
    rel_new = _m8_build_cross_doc_relation(
        kind="attacks",
        warrant="Supervisor revision: closer reading flips the warrant.",
        role_attribution=role_attr,
    )
    substrate.add_cross_doc_relation(rel_old)
    substrate.add_cross_doc_relation(rel_new)

    sup_payload: dict[str, Any] = {
        "id": "v-" + "0" * 16,
        "supersedes_id": rel_old.id,
        "superseded_by_id": rel_new.id,
        "kind": "cross-doc-relation",
        "reason": "fixture supersede for M8 T8.3",
        "provenance_id": "p-m8-sup00000001",
        "role_attributions": [role_attr],
        "at": _M8_STABLE_AT,
        "schema_version": 1,
    }
    sup_draft = CrossDocRelationSupersede(**sup_payload)
    sup_payload["id"] = compute_id(sup_draft)
    sup = CrossDocRelationSupersede(**sup_payload)
    substrate.add_cross_doc_relation_supersede(sup)
    return tmp_path, rel_old.id, rel_new.id


@pytest.fixture
def web_app() -> object:
    """A fresh FastAPI app instance for cross-doc-relation tests.

    The spec for M8's tests uses ``web_app`` as a parameter directly.
    Tests still set ``AMANUENSIS_WORKSPACE`` via ``monkeypatch`` so the
    request-scoped ``get_substrate`` dependency picks up the planted
    workspace at request time.
    """
    from amanuensis.web.app import create_app

    return create_app()


# ---------------------------------------------------------------------------
# Phase 2c M10 — probandum tree web fixtures
# ---------------------------------------------------------------------------
#
# Mirror of ``tests/dispatch/conftest.py``'s
# ``tmp_workspace_with_probandum_tree`` but shaped per the M10 spec: one
# ``ultimate`` + one ``penultimate`` + one ``interim`` + two edges. The
# Walton snapshot is pinned so ``Substrate.add_probandum``'s INV-18 gate
# passes. The fixture returns a dict mapping role labels to substrate ids
# so route tests can build URLs without re-deriving content-addressable
# hashes.

_M10_STABLE_AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
_M10_SOURCE_ID = "src-tree"


def _m10_role_attribution() -> RoleAttribution:
    return RoleAttribution(
        agent=AgentAttribution(kind="llm", identifier="hierarchize", role="hierarchize"),
        activity="proposed",
        at=_M10_STABLE_AT,
    )


def _m10_build_atom(
    *,
    atom_id: str,
    source_id: str,
    narrative: str,
    char_offset: int,
) -> Atom:
    return Atom(
        id=atom_id,
        source_id=source_id,
        section_path=["body"],
        paragraph_index=0,
        sentence_index=None,
        char_span=(char_offset, char_offset + 30),
        scale_anchor="paragraph",
        kind="claim",
        predicate="alleges",
        operands=[OperandRef(role="subject", kind="entity", value="e-x", type_hint=None)],
        narrative=narrative,
        qualifier_level=None,
        qualifier_basis=None,
        provenance_id="p-m10fixture00001",
        role_attributions=[_m10_role_attribution()],
        schema_version=1,
    )


def _m10_plant_atom(workspace: Path, atom: Atom) -> None:
    path = workspace / "distillations" / atom.source_id / "atoms" / f"{atom.id}.md"
    atomic_write_text(path, serialize_atom_md(atom))


def _m10_build_probandum(
    *,
    statement: str,
    kind: str,
    scheme: str,
    alternatives_considered: list[str],
    confidence: str = "high",
) -> Probandum:
    """Build a Probandum with a content-addressable id."""
    role_attr = _m10_role_attribution()
    draft = Probandum(
        id="p-placeholder0001",
        statement=statement,
        kind=kind,  # pyright: ignore[reportArgumentType]
        scheme=scheme,
        alternatives_considered=alternatives_considered,
        confidence=confidence,  # pyright: ignore[reportArgumentType]
        provenance_id="p-m10fixture00001",
        role_attributions=[role_attr],
        schema_version=1,
    )
    return draft.model_copy(update={"id": compute_id(draft)})


def _m10_build_edge(
    *,
    parent_probandum_id: str,
    child_id: str,
    child_kind: str,
    child_source_id: str | None,
    warrant_suffix: str,
    kind: str = "supports",
) -> ProbandumEdge:
    role_attr = _m10_role_attribution()
    draft = ProbandumEdge(
        id="q-placeholder0001",
        parent_probandum_id=parent_probandum_id,
        child_id=child_id,
        child_kind=child_kind,  # pyright: ignore[reportArgumentType]
        child_source_id=child_source_id,
        kind=kind,  # pyright: ignore[reportArgumentType]
        warrant=f"Decomposition warrant for {warrant_suffix}.",
        warrant_defensibility="methodology-derived",
        warrant_basis="Wigmore §III decomposition.",
        confidence="high",
        provenance_id="p-m10fixture00001",
        role_attributions=[role_attr],
        schema_version=1,
    )
    return draft.model_copy(update={"id": compute_id(draft)})


@pytest.fixture
def tmp_workspace_with_probandum_tree(tmp_path: Path) -> dict[str, str]:
    """Workspace with 1 ultimate + 1 penultimate + 1 interim + 2 edges.

    Layout (top-to-bottom):
        ultimate  --supports-->  penultimate  --supports-->  interim

    Walton-scheme snapshot is pinned so INV-18 passes. Returns a dict
    mapping role labels (``workspace``, ``ultimate``, ``penultimate``,
    ``interim``, ``edge_ult_pen``, ``edge_pen_int``) to real substrate
    ids.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: m10-probandum-tree\n",
        encoding="utf-8",
    )
    (tmp_path / "distillations" / _M10_SOURCE_ID).mkdir(parents=True, exist_ok=True)

    sub = Substrate(tmp_path)
    sub.snapshot_walton_schemes()

    ultimate = _m10_build_probandum(
        statement="ACME prevails on its breach claim against Smith.",
        kind="ultimate",
        scheme="argument-from-expert-opinion",
        alternatives_considered=[],
    )
    sub.add_probandum(ultimate)

    penultimate = _m10_build_probandum(
        statement="Smith breached §3 by failing to deliver the April 2024 shipment.",
        kind="penultimate",
        scheme="argument-from-sign",
        alternatives_considered=[
            "Smith tendered but ACME rejected for unrelated quality reasons.",
            "Smith and ACME mutually deferred the April 2024 delivery.",
        ],
    )
    sub.add_probandum(penultimate)

    interim = _m10_build_probandum(
        statement="Smith never tendered the April 2024 shipment under §3.",
        kind="interim",
        scheme="argument-from-sign",
        alternatives_considered=[
            "Smith tendered late but ACME's records mis-dated the receipt.",
        ],
        confidence="medium",
    )
    sub.add_probandum(interim)

    edge_ult_pen = _m10_build_edge(
        parent_probandum_id=ultimate.id,
        child_id=penultimate.id,
        child_kind="probandum",
        child_source_id=None,
        warrant_suffix="ultimate to penultimate",
    )
    sub.add_probandum_edge(edge_ult_pen)

    edge_pen_int = _m10_build_edge(
        parent_probandum_id=penultimate.id,
        child_id=interim.id,
        child_kind="probandum",
        child_source_id=None,
        warrant_suffix="penultimate to interim",
    )
    sub.add_probandum_edge(edge_pen_int)

    return {
        "workspace": str(tmp_path),
        "ultimate": ultimate.id,
        "penultimate": penultimate.id,
        "interim": interim.id,
        "edge_ult_pen": edge_ult_pen.id,
        "edge_pen_int": edge_pen_int.id,
        "source_id": _M10_SOURCE_ID,
    }


@pytest.fixture
def tmp_workspace_probandum_tree_with_entity(
    tmp_workspace_with_probandum_tree: dict[str, str],
) -> dict[str, str]:
    """The M10 probandum tree plus a canonical Entity named ``Smith``.

    Used by the T10.5 test that verifies the entity-detail page's
    "Probanda referencing this entity" section. The Smith entity is
    planted with a literal id (``e-smith-m10``) for deterministic URL
    construction; its provenance is written via the direct path
    because the entity probandum-scan heuristic does not need a
    fully-canonical id.
    """
    workspace_path = Path(tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(workspace_path)

    role_attr = _m10_role_attribution()
    entity = Entity(
        id="e-smith-m10",
        kind="party",
        canonical_name="Smith",
        aliases=[],
        notes=None,
        provenance_id="p-m10ent00000001",
        role_attributions=[role_attr],
        schema_version=1,
    )
    # Use the literal-id planting helper used by the M8 fixtures so
    # we don't have to thread provenance hashing through here. The
    # detail route walks the supersede chain via
    # ``latest_entity_for``, and a single canonical record is enough.
    path = workspace_path / "mappings" / "entities" / f"{entity.id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, serialize_entity_md(entity))
    _ = sub  # quiet unused-arg lint; substrate is implicitly active above

    enriched = dict(tmp_workspace_with_probandum_tree)
    enriched["entity_id"] = entity.id
    enriched["entity_canonical_name"] = entity.canonical_name
    return enriched
