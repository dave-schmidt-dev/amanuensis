"""Build the Playwright E2E fixture workspace.

Invoked from ``globalSetup.ts`` as::

    uv run --no-sync python tests/e2e/_fixture_builder.py <workspace-path>

Plants two distillations under the workspace:

1. ``phase1-smoke`` — one atom + one relation + one source-mirror paragraph
   so the smoke spec can navigate the full read surface (dashboard ->
   source overview -> atom browser -> atom detail with ``<mark>`` highlight)
   and the relations page renders a non-empty graph.

2. ``phase1-stress`` — ``N_STRESS_ATOMS`` atoms + ``N_STRESS_RELATIONS``
   relations, all chained head-to-tail, exercising the relation-graph
   page under load (PM-5 mitigation).

The counts are deliberately lower than the original 1000/3000 target.
The relation-graph soft cap is 750 atoms / 2000 edges (per the M8.4
plan); 250 atoms / 750 relations sits under that cap, exercising the
"normal" render path while still being large enough to surface render
regressions. The downgrade is documented in ``README.md`` next to the
M8.9 quality gates.

This module mirrors the patterns used by ``tests/web/conftest.py`` —
deterministic ids, structured Atom/Relation/Provenance models, content-
addressable hashes computed via ``compute_id``. The point is to write
the same on-disk format the real ingest pipeline writes; using project
APIs (Substrate, schemas) guarantees the fixture cannot drift from the
production format.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amanuensis.fs import Substrate
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import serialize_paragraph_md
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    Clarification,
    CrossDocRelation,
    Entity,
    OperandRef,
    OperandTypeSchema,
    ParagraphEntry,
    Probandum,
    ProbandumEdge,
    ProvenanceRecord,
    Relation,
    Resolution,
    RoleAttribution,
    SourceMirrorManifest,
    Vocabulary,
    VocabularyEntry,
    compute_id,
)

# Fixture sizing — see module docstring for the 250/750 downgrade rationale.
SMOKE_SOURCE_ID = "phase1-smoke"
STRESS_SOURCE_ID = "phase1-stress"
# Phase 2b cross-doc fixture source. One atom + bilateral resolution joining
# back to the canonical entity shared with phase1-smoke, so the planted
# CrossDocRelation can satisfy INV-15.
CROSS_DOC_SOURCE_ID = "phase2b-cross-doc"
N_STRESS_ATOMS = 250
N_STRESS_RELATIONS = 750
DETERMINISTIC_SHA256 = "0" * 64
SMOKE_PARAGRAPH_BODY = "ACME shall pay within 30 days under section 3 of the contract."
# Char-span covers "ACME shall pay within 30 days" — the highlighted slice
# the smoke spec asserts is rendered inside the <mark>.
SMOKE_CHAR_SPAN: tuple[int, int] = (0, 30)
CROSS_DOC_PARAGRAPH_BODY = "ACME's payment obligation continues under the settlement letter."
CROSS_DOC_CHAR_SPAN: tuple[int, int] = (0, 30)


def _now() -> datetime:
    """Fixed timestamp keeps planted ids deterministic across runs."""
    return datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)


def _build_vocabulary() -> Vocabulary:
    return Vocabulary(
        name="e2e-fixture-vocab",
        version="0.1.0",
        entries=[
            VocabularyEntry(
                predicate="asserts_obligation",
                aliases=["asserts_shall"],
                operand_types=[
                    OperandTypeSchema(name="subject", kind="entity", required=True),
                ],
                qualifier_required=False,
                notes="e2e fixture entry",
            ),
        ],
    )


def _plant_marker(workspace: Path) -> None:
    marker = workspace / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: e2e-fixture\n",
        encoding="utf-8",
    )


def _make_agent() -> AgentAttribution:
    return AgentAttribution(kind="llm", identifier="e2e-fixture", role="extractor")


def _make_role_attribution(agent: AgentAttribution) -> RoleAttribution:
    return RoleAttribution(agent=agent, activity="proposed", at=_now())


def _build_atom(
    *,
    source_id: str,
    paragraph_index: int,
    char_span: tuple[int, int],
    narrative: str,
    provenance_id: str,
    role_attribution: RoleAttribution,
    nonce: str = "",
) -> Atom:
    """Build an Atom, compute its content-addressable id, return final model.

    ``nonce`` lets the stress builder vary identity content per-atom so each
    of the 250 atoms hashes to a distinct id even though everything else is
    structurally identical.
    """
    operand = OperandRef(
        role="subject", kind="entity", value=f"ent-{nonce or 'acme'}", type_hint=None
    )
    base: dict[str, Any] = {
        "id": "a-" + "0" * 16,
        "source_id": source_id,
        "section_path": ["Part I", "§1"],
        "paragraph_index": paragraph_index,
        "sentence_index": None,
        "char_span": char_span,
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": "asserts_obligation",
        "operands": [operand],
        "narrative": narrative,
        "qualifier_level": None,
        "qualifier_basis": None,
        "provenance_id": provenance_id,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    draft = Atom(**base)
    base["id"] = compute_id(draft)
    return Atom(**base)


def _build_provenance(
    *,
    source_id: str,
    atom_id: str,
    agent: AgentAttribution,
    nonce: str = "",
) -> ProvenanceRecord:
    """Build a ProvenanceRecord, compute its id, return final model."""
    base: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": "atom",
        "entity_id": atom_id,
        "activity": f"extract_v1{('-' + nonce) if nonce else ''}",
        "activity_started_at": _now(),
        "activity_ended_at": _now(),
        "used_entity_ids": [source_id],
        "was_attributed_to": agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    draft = ProvenanceRecord(**base)
    base["id"] = compute_id(draft)
    return ProvenanceRecord(**base)


def _build_relation(
    *,
    source_id: str,
    from_atom_id: str,
    to_atom_id: str,
    provenance_id: str,
    role_attribution: RoleAttribution,
    nonce: str = "",
) -> Relation:
    base: dict[str, Any] = {
        "id": "r-" + "0" * 16,
        "source_id": source_id,
        "from_atom_id": from_atom_id,
        "to_atom_id": to_atom_id,
        "kind": "supports",
        "warrant": f"warrant {nonce}".strip(),
        "warrant_defensibility": "conventional",
        "warrant_basis": "fixture",
        "confidence": "medium",
        "provenance_id": provenance_id,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    draft = Relation(**base)
    base["id"] = compute_id(draft)
    return Relation(**base)


def _plant_paragraph(substrate: Substrate, source_id: str, body: str) -> None:
    """Write paragraph p-0000 .md so the smoke spec can render the highlight.

    Goes through the same ``serialize_paragraph_md`` helper the real
    ingester uses. ``ParagraphEntry.char_count`` is set to the body
    length; ``content_sha256`` is the deterministic-placeholder hash
    because nothing in the e2e suite asserts content-hash correctness.
    """
    paragraph_dir = substrate.source_mirror_root(source_id) / "paragraphs"
    paragraph_dir.mkdir(parents=True, exist_ok=True)
    entry = ParagraphEntry(
        paragraph_id="p-0000",
        paragraph_index=0,
        section_path=["Part I", "§1"],
        label="text",
        page_no=1,
        char_count=len(body),
        content_sha256=DETERMINISTIC_SHA256,
    )
    paragraph_path = substrate.paragraph_path(source_id, "p-0000")
    atomic_write_text(paragraph_path, serialize_paragraph_md(entry, body))


def _plant_smoke(substrate: Substrate) -> None:
    """Plant the smoke distillation: 1 atom + 1 self-loop relation."""
    substrate.snapshot_vocabulary(SMOKE_SOURCE_ID, _build_vocabulary())
    agent = _make_agent()
    role_attribution = _make_role_attribution(agent)

    # Build provenance pointing at a stub atom id, then build the real
    # atom against that provenance, then re-build provenance against the
    # real atom id. The schema lets provenance_id be any id-shaped string;
    # for an honest content-addressable plant we round-trip once.
    stub_prov = _build_provenance(source_id=SMOKE_SOURCE_ID, atom_id="a-" + "0" * 16, agent=agent)
    atom = _build_atom(
        source_id=SMOKE_SOURCE_ID,
        paragraph_index=0,
        char_span=SMOKE_CHAR_SPAN,
        narrative=SMOKE_PARAGRAPH_BODY,
        provenance_id=stub_prov.id,
        role_attribution=role_attribution,
    )
    final_prov = _build_provenance(source_id=SMOKE_SOURCE_ID, atom_id=atom.id, agent=agent)
    # Rebuild atom with the real provenance pointer so substrate accepts both.
    atom = _build_atom(
        source_id=SMOKE_SOURCE_ID,
        paragraph_index=0,
        char_span=SMOKE_CHAR_SPAN,
        narrative=SMOKE_PARAGRAPH_BODY,
        provenance_id=final_prov.id,
        role_attribution=role_attribution,
    )
    substrate.add_provenance(SMOKE_SOURCE_ID, final_prov)
    substrate.add_atom(SMOKE_SOURCE_ID, atom)

    # One self-loop relation so the relations page renders both a node and an edge.
    rel_prov = _build_provenance(source_id=SMOKE_SOURCE_ID, atom_id=atom.id, agent=agent)
    relation = _build_relation(
        source_id=SMOKE_SOURCE_ID,
        from_atom_id=atom.id,
        to_atom_id=atom.id,
        provenance_id=rel_prov.id,
        role_attribution=role_attribution,
    )
    substrate.add_provenance(SMOKE_SOURCE_ID, rel_prov)
    substrate.add_relation(SMOKE_SOURCE_ID, relation)

    # Source-mirror manifest + the one paragraph file the atom highlights into.
    manifest_payload: dict[str, Any] = {
        "source_id": SMOKE_SOURCE_ID,
        "source_filename": "smoke.pdf",
        "source_sha256": DETERMINISTIC_SHA256,
        "source_bytes_len": 1024,
        "ingest_engine": "docling",
        "ingest_engine_version": "9.9.9",
        "vocabulary_snapshot_sha256": DETERMINISTIC_SHA256,
        "provenance_id": "p-" + "1" * 16,
        "paragraphs": [
            ParagraphEntry(
                paragraph_id="p-0000",
                paragraph_index=0,
                section_path=["Part I", "§1"],
                label="text",
                page_no=1,
                char_count=len(SMOKE_PARAGRAPH_BODY),
                content_sha256=DETERMINISTIC_SHA256,
            ),
        ],
        "schema_version": 1,
    }
    draft_manifest = SourceMirrorManifest(id="m-" + "0" * 16, **manifest_payload)
    manifest = SourceMirrorManifest(id=compute_id(draft_manifest), **manifest_payload)
    substrate.add_source_mirror_manifest(SMOKE_SOURCE_ID, manifest)
    _plant_paragraph(substrate, SMOKE_SOURCE_ID, SMOKE_PARAGRAPH_BODY)


def _plant_stress(substrate: Substrate) -> None:
    """Plant N_STRESS_ATOMS atoms + N_STRESS_RELATIONS chained relations."""
    substrate.snapshot_vocabulary(STRESS_SOURCE_ID, _build_vocabulary())
    agent = _make_agent()
    role_attribution = _make_role_attribution(agent)

    atoms: list[Atom] = []
    for i in range(N_STRESS_ATOMS):
        # Round-trip provenance/atom ids per the smoke-plant pattern, but
        # use the atom-index as a nonce so every atom hashes to a unique id.
        nonce = f"stress-{i:04d}"
        stub_prov = _build_provenance(
            source_id=STRESS_SOURCE_ID,
            atom_id="a-" + "0" * 16,
            agent=agent,
            nonce=nonce,
        )
        atom_stub = _build_atom(
            source_id=STRESS_SOURCE_ID,
            paragraph_index=i,
            char_span=(0, 30),
            narrative=f"stress atom {i:04d} narrative",
            provenance_id=stub_prov.id,
            role_attribution=role_attribution,
            nonce=nonce,
        )
        final_prov = _build_provenance(
            source_id=STRESS_SOURCE_ID,
            atom_id=atom_stub.id,
            agent=agent,
            nonce=nonce,
        )
        atom = _build_atom(
            source_id=STRESS_SOURCE_ID,
            paragraph_index=i,
            char_span=(0, 30),
            narrative=f"stress atom {i:04d} narrative",
            provenance_id=final_prov.id,
            role_attribution=role_attribution,
            nonce=nonce,
        )
        substrate.add_provenance(STRESS_SOURCE_ID, final_prov)
        substrate.add_atom(STRESS_SOURCE_ID, atom)
        atoms.append(atom)

    # Chain relations: edge i connects atoms[i % N] -> atoms[(i + 1) % N].
    # Mix the kind / nonce so each Relation hashes uniquely.
    for j in range(N_STRESS_RELATIONS):
        src = atoms[j % N_STRESS_ATOMS]
        dst = atoms[(j + 1) % N_STRESS_ATOMS]
        nonce = f"rel-{j:04d}"
        rel_prov = _build_provenance(
            source_id=STRESS_SOURCE_ID, atom_id=src.id, agent=agent, nonce=nonce
        )
        relation = _build_relation(
            source_id=STRESS_SOURCE_ID,
            from_atom_id=src.id,
            to_atom_id=dst.id,
            provenance_id=rel_prov.id,
            role_attribution=role_attribution,
            nonce=nonce,
        )
        substrate.add_provenance(STRESS_SOURCE_ID, rel_prov)
        substrate.add_relation(STRESS_SOURCE_ID, relation)


def _plant_resolution_ambiguous_clarification(substrate: Substrate, source_id: str) -> None:
    """Plant one open ``resolution-ambiguous`` clarification under ``source_id``.

    Mirrors the ``_plant_clarification`` helper in ``tests/web/conftest.py``
    but uses ``kind="resolution-ambiguous"`` so the Phase 2a T11.3 Playwright
    spec can assert the kind badge renders and the resolve form works.

    The clarification is anchored to the smoke atom (looked up from the
    substrate) so that ``context_refs`` contains a real atom id. The
    provenance round-trip follows the same content-addressable pattern as
    every other planted artifact in this builder.
    """
    raising_agent = AgentAttribution(kind="llm", identifier="auditor-e2e", role="auditor")

    # Build raised provenance record first (entity_id will be the clarification
    # id — we need a stub to bootstrap the compute_id round-trip).
    prov_payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": "clarification-raised",
        "entity_id": "c-" + "0" * 16,  # stub — replaced below
        "activity": "audit_v1",
        "activity_started_at": _now(),
        "activity_ended_at": _now(),
        "used_entity_ids": [source_id],
        "was_attributed_to": raising_agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    prov_draft = ProvenanceRecord(**prov_payload)
    prov_id = compute_id(prov_draft)
    prov_payload["id"] = prov_id
    prov = ProvenanceRecord(**prov_payload)

    clar_payload: dict[str, Any] = {
        "id": "c-" + "0" * 16,
        "status": "open",
        "kind": "resolution-ambiguous",
        "raised_at": _now(),
        "raised_by": raising_agent,
        "raised_by_activity": "audit_v1",
        "context_refs": [],
        "question": (
            "Two operands match entity 'ACME Corp.' with equal confidence — "
            "which resolution should take precedence?"
        ),
        "options": ["merge proposed into existing", "keep both as separate entities"],
        "resolved_at": None,
        "resolved_by": None,
        "resolution": None,
        "raised_provenance_id": prov_id,
        "resolved_provenance_id": None,
        "schema_version": 2,
    }
    clar_draft = Clarification(**clar_payload)
    clar_id = compute_id(clar_draft)
    clar_payload["id"] = clar_id
    clar = Clarification(**clar_payload)

    substrate.add_provenance(source_id, prov)
    substrate.add_clarification(source_id, clar)


def _plant_cross_doc_artifacts(substrate: Substrate) -> None:
    """Plant a CrossDocRelation between phase1-smoke and phase2b-cross-doc (Phase 2b M11 T11.2).

    The smoke distillation already has one atom. To exercise the Phase 2b
    cross-doc overlay flow in Playwright we need:

    1. A second source (``phase2b-cross-doc``) with at least one atom.
    2. A shared canonical ``Entity`` in ``mappings/entities/``.
    3. Bilateral ``Resolution`` records pointing each atom's first operand
       at the canonical entity (INV-15 precondition).
    4. A ``CrossDocRelation`` referencing both endpoints and the shared
       entity. This is what the overlay JS renders and what the
       ``/cross-doc-relations/<id>`` detail page displays.

    The atom in the smoke source uses surface form "ent-acme"; we mint a
    canonical "ACME" entity, plant a resolution for the smoke atom under
    that entity, plant a paired atom + resolution under the cross-doc
    source, then write the cross-doc edge.
    """
    agent = _make_agent()
    role_attribution = _make_role_attribution(agent)

    # --- Locate the smoke atom (already on disk from _plant_smoke) ---
    smoke_atoms = sorted(
        substrate.list_atoms(SMOKE_SOURCE_ID),
        key=lambda a: a.id,
    )
    assert smoke_atoms, "phase1-smoke must already have its atom planted"
    smoke_atom = smoke_atoms[0]

    # --- Plant the second source: 1 atom + 1 paragraph + 1 manifest ---
    substrate.snapshot_vocabulary(CROSS_DOC_SOURCE_ID, _build_vocabulary())

    stub_prov = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="atom",
        entity_id="a-" + "0" * 16,
        activity="extract_v1-cross-doc",
        activity_started_at=_now(),
        activity_ended_at=_now(),
        used_entity_ids=[CROSS_DOC_SOURCE_ID],
        was_attributed_to=agent,
        was_influenced_by=[],
        schema_version=1,
    )
    stub_prov = stub_prov.model_copy(update={"id": compute_id(stub_prov)})

    operand = OperandRef(role="subject", kind="entity", value="ent-acme", type_hint=None)
    cross_atom_draft = Atom(
        id="a-" + "0" * 16,
        source_id=CROSS_DOC_SOURCE_ID,
        section_path=["Part I", "§1"],
        paragraph_index=0,
        sentence_index=None,
        char_span=CROSS_DOC_CHAR_SPAN,
        scale_anchor="paragraph",
        kind="claim",
        predicate="asserts_obligation",
        operands=[operand],
        narrative=CROSS_DOC_PARAGRAPH_BODY,
        qualifier_level=None,
        qualifier_basis=None,
        provenance_id=stub_prov.id,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    cross_atom = cross_atom_draft.model_copy(update={"id": compute_id(cross_atom_draft)})

    # Rebuild prov against the real atom id.
    final_prov = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="atom",
        entity_id=cross_atom.id,
        activity="extract_v1-cross-doc",
        activity_started_at=_now(),
        activity_ended_at=_now(),
        used_entity_ids=[CROSS_DOC_SOURCE_ID],
        was_attributed_to=agent,
        was_influenced_by=[],
        schema_version=1,
    )
    final_prov = final_prov.model_copy(update={"id": compute_id(final_prov)})
    cross_atom = cross_atom.model_copy(update={"provenance_id": final_prov.id})
    # Re-hash after pointing at the real prov id (atom id is volatile w.r.t.
    # provenance_id? No — atom's provenance_id is identity, so recompute).
    cross_atom = cross_atom.model_copy(update={"id": compute_id(cross_atom)})

    substrate.add_provenance(CROSS_DOC_SOURCE_ID, final_prov)
    substrate.add_atom(CROSS_DOC_SOURCE_ID, cross_atom)

    # Paragraph + manifest so the source-overview surface renders.
    paragraph_dir = substrate.source_mirror_root(CROSS_DOC_SOURCE_ID) / "paragraphs"
    paragraph_dir.mkdir(parents=True, exist_ok=True)
    paragraph_entry = ParagraphEntry(
        paragraph_id="p-0000",
        paragraph_index=0,
        section_path=["Part I", "§1"],
        label="text",
        page_no=1,
        char_count=len(CROSS_DOC_PARAGRAPH_BODY),
        content_sha256=DETERMINISTIC_SHA256,
    )
    paragraph_path = substrate.paragraph_path(CROSS_DOC_SOURCE_ID, "p-0000")
    atomic_write_text(
        paragraph_path, serialize_paragraph_md(paragraph_entry, CROSS_DOC_PARAGRAPH_BODY)
    )

    manifest_payload: dict[str, Any] = {
        "source_id": CROSS_DOC_SOURCE_ID,
        "source_filename": "cross-doc.pdf",
        "source_sha256": DETERMINISTIC_SHA256,
        "source_bytes_len": 1024,
        "ingest_engine": "docling",
        "ingest_engine_version": "9.9.9",
        "vocabulary_snapshot_sha256": DETERMINISTIC_SHA256,
        "provenance_id": "p-" + "2" * 16,
        "paragraphs": [paragraph_entry],
        "schema_version": 1,
    }
    draft_manifest = SourceMirrorManifest(id="m-" + "0" * 16, **manifest_payload)
    manifest = SourceMirrorManifest(id=compute_id(draft_manifest), **manifest_payload)
    substrate.add_source_mirror_manifest(CROSS_DOC_SOURCE_ID, manifest)

    # --- Plant the canonical entity ---
    entity_payload: dict[str, Any] = {
        "id": "e-" + "0" * 16,
        "kind": "organization",
        "canonical_name": "ACME",
        "aliases": ["ACME Corp"],
        "notes": "cross-doc fixture entity",
        "provenance_id": final_prov.id,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    entity_draft = Entity(**entity_payload)
    entity_payload["id"] = compute_id(entity_draft)
    entity = Entity(**entity_payload)
    substrate.add_entity(entity)

    # --- Bilateral resolutions ---
    res_smoke_payload: dict[str, Any] = {
        "id": "j-" + "0" * 16,
        "source_id": SMOKE_SOURCE_ID,
        "atom_id": smoke_atom.id,
        "operand_index": 0,
        "entity_id": entity.id,
        "confidence": "high",
        "basis": "cross-doc fixture: smoke endpoint resolution",
        "provenance_id": final_prov.id,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    res_smoke_draft = Resolution(**res_smoke_payload)
    res_smoke_payload["id"] = compute_id(res_smoke_draft)
    substrate.add_resolution(Resolution(**res_smoke_payload))

    res_cross_payload: dict[str, Any] = {
        "id": "j-" + "1" * 16,
        "source_id": CROSS_DOC_SOURCE_ID,
        "atom_id": cross_atom.id,
        "operand_index": 0,
        "entity_id": entity.id,
        "confidence": "high",
        "basis": "cross-doc fixture: phase2b endpoint resolution",
        "provenance_id": final_prov.id,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    res_cross_draft = Resolution(**res_cross_payload)
    res_cross_payload["id"] = compute_id(res_cross_draft)
    substrate.add_resolution(Resolution(**res_cross_payload))

    # --- The CrossDocRelation itself ---
    rel_payload: dict[str, Any] = {
        "id": "x-" + "0" * 16,
        "from_atom_id": smoke_atom.id,
        "from_source_id": SMOKE_SOURCE_ID,
        "to_atom_id": cross_atom.id,
        "to_source_id": CROSS_DOC_SOURCE_ID,
        "kind": "supports",
        "warrant": (
            "Both atoms describe ACME's payment obligation; the cross-doc "
            "edge captures continuity of the obligation across the contract "
            "and the settlement letter."
        ),
        "warrant_defensibility": "conventional",
        "warrant_basis": "Two independent attestations of ACME's payment obligation.",
        "confidence": "medium",
        "shared_entities": [entity.id],
        "provenance_id": final_prov.id,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    rel_draft = CrossDocRelation(**rel_payload)
    rel_payload["id"] = compute_id(rel_draft)
    substrate.add_cross_doc_relation(CrossDocRelation(**rel_payload))


def plant_probandum_tree(substrate: Substrate) -> dict[str, str]:
    """Plant a minimal probandum tree for the Phase 2c T13.2 E2E spec.

    Shape produced:
      * Walton-scheme snapshot pinned from the bundled generic catalogue.
      * 1 ultimate probandum.
      * 1 penultimate probandum, linked upward to the ultimate via a
        ``supports`` edge.
      * 1 interim probandum, linked upward to the penultimate via a
        ``supports`` edge.

    Returns ``{"ultimate": <id>, "penultimate": <id>, "interim": <id>}``
    so the spec can navigate by id without re-deriving the
    content-addressable hashes.
    """
    # Pin the bundled Walton-scheme catalogue (idempotent across re-builds).
    substrate.snapshot_walton_schemes()

    agent = _make_agent()
    role_attribution = _make_role_attribution(agent)

    # Mappings-scope provenance for all three probanda + two edges.
    prov_draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="probandum",
        entity_id="p-placeholder",
        activity="e2e-fixture-plant-probandum-tree",
        activity_started_at=_now(),
        activity_ended_at=_now(),
        used_entity_ids=[],
        was_attributed_to=agent,
        was_influenced_by=[],
        schema_version=1,
    )
    prov = prov_draft.model_copy(update={"id": compute_id(prov_draft)})
    prov_path = substrate.mappings_provenance_path(prov.id)
    prov_path.parent.mkdir(parents=True, exist_ok=True)
    from amanuensis.fs._serialize import serialize_yaml

    atomic_write_text(prov_path, serialize_yaml(prov))

    # --- The three probanda ----------------------------------------------
    ultimate_draft = Probandum(
        id="p-placeholder",
        statement=("The claimant prevails on the contested obligation against the respondent."),
        kind="ultimate",
        scheme="argument-from-expert-opinion",
        alternatives_considered=[],
        confidence="high",
        provenance_id=prov.id,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    ultimate = ultimate_draft.model_copy(update={"id": compute_id(ultimate_draft)})
    substrate.add_probandum(ultimate)

    penultimate_draft = Probandum(
        id="p-placeholder",
        statement=("The respondent breached the §3 delivery obligation in April 2024."),
        kind="penultimate",
        scheme="argument-from-sign",
        alternatives_considered=[
            "The respondent tendered but the claimant rejected for unrelated reasons.",
            "The parties mutually deferred the April 2024 delivery date.",
        ],
        confidence="high",
        provenance_id=prov.id,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    penultimate = penultimate_draft.model_copy(update={"id": compute_id(penultimate_draft)})
    substrate.add_probandum(penultimate)

    interim_draft = Probandum(
        id="p-placeholder",
        statement=("The shipping log shows no April 2024 transit consistent with the §3 schedule."),
        kind="interim",
        scheme="argument-from-sign",
        alternatives_considered=[
            "The shipping log entry was suppressed for unrelated audit reasons.",
            "The shipping log records a non-§3 alternative-route delivery.",
        ],
        confidence="medium",
        provenance_id=prov.id,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    interim = interim_draft.model_copy(update={"id": compute_id(interim_draft)})
    substrate.add_probandum(interim)

    # --- The two linking edges -------------------------------------------
    def _edge(parent: Probandum, child: Probandum, basis: str) -> ProbandumEdge:
        draft = ProbandumEdge(
            id="q-placeholder",
            parent_probandum_id=parent.id,
            child_id=child.id,
            child_kind="probandum",
            child_source_id=None,
            kind="supports",
            warrant=f"Decomposition: {basis}",
            warrant_defensibility="methodology-derived",
            warrant_basis="Wigmore §III decomposition.",
            confidence="high",
            provenance_id=prov.id,
            role_attributions=[role_attribution],
            schema_version=1,
        )
        return draft.model_copy(update={"id": compute_id(draft)})

    substrate.add_probandum_edge(_edge(ultimate, penultimate, "breach -> ultimate"))
    substrate.add_probandum_edge(_edge(penultimate, interim, "shipping-log -> breach"))

    return {
        "ultimate": ultimate.id,
        "penultimate": penultimate.id,
        "interim": interim.id,
    }


def build(workspace: Path) -> None:
    """Plant both fixture distillations under ``workspace`` (idempotent-ish).

    ``Substrate`` writes are atomic; re-running this script over an
    already-populated workspace will overwrite the same content-addressed
    paths with identical bytes, so it's a no-op in practice. ``globalSetup.ts``
    wipes the workspace before invoking this script to keep things clean.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    _plant_marker(workspace)
    substrate = Substrate(workspace)
    _plant_smoke(substrate)
    _plant_stress(substrate)
    # Plant one open resolution-ambiguous clarification so the T11.3
    # Playwright spec has exactly one such clarification to navigate.
    _plant_resolution_ambiguous_clarification(substrate, SMOKE_SOURCE_ID)
    # Plant Phase 2b cross-doc fixture (T11.2 — overlay flow spec).
    _plant_cross_doc_artifacts(substrate)
    # Plant Phase 2c probandum tree fixture (T13.2 — tree flow spec).
    plant_probandum_tree(substrate)


def main() -> None:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: _fixture_builder.py <workspace-path>\n")
        sys.exit(2)
    workspace = Path(sys.argv[1]).resolve()
    build(workspace)
    sys.stdout.write(f"e2e fixture planted at {workspace}\n")


if __name__ == "__main__":
    main()
