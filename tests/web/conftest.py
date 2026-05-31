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
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    Clarification,
    Entity,
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
