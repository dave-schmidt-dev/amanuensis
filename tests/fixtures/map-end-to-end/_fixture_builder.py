"""Fixture builder for Phase 2a M11 map-end-to-end tests.

Invoked from integration tests or as a CLI smoke-check::

    uv run python tests/fixtures/map-end-to-end/_fixture_builder.py <workspace-path>

Plants 3 distillations into the workspace (3 atoms each, 9 total):

1. ``contract-draft-1`` — atoms referencing "ACME Corp", "BetaCo Ltd",
   "Contract Draft 1" as entity-kind obligor operands.
2. ``contract-draft-2`` — atoms referencing "ACME Corporation" (alias
   variation), "BetaCo Ltd.", "Contract Draft 2".
3. ``settlement-instrument`` — atoms referencing "ACME Corp", "BetaCo",
   "Counsel for ACME".

Design rationale
----------------
T11.1 originally called for 3 synthetic PDFs (LaTeX/Typst/Pandoc).  No PDF
authoring tools are installed and adding one violates YAGNI.  The actual
purpose of T11.2 is testing the **mapping pipeline** end-to-end (entity
deduplication, cross-document resolution, idempotency), not testing PDF
ingestion — Phase 1's ``test_distill_tiny_fixture.py`` covers that.

This module plants distillations directly via project APIs (``Substrate``,
``add_atom``, ``add_provenance``, ``snapshot_vocabulary``) using
content-addressable ids computed by ``compute_id``.  The on-disk format
cannot drift from the production format because it is written by the same
code that the real ingest pipeline uses.

See ``SOURCES.md`` in this directory for the full design rationale and the
5 expected canonical entities produced by the mapping pipeline.

Mirrors the patterns in ``tests/e2e/_fixture_builder.py``:
deterministic ids, structured Atom/Provenance models, content-addressable
hashes via ``compute_id``, atomic writes through ``Substrate`` APIs.
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
    OperandRef,
    OperandTypeSchema,
    ParagraphEntry,
    ProvenanceRecord,
    RoleAttribution,
    SourceMirrorManifest,
    Vocabulary,
    VocabularyEntry,
    compute_id,
)

# ---------------------------------------------------------------------------
# Source ids for the 3 distillations
# ---------------------------------------------------------------------------

SOURCE_CONTRACT_1 = "contract-draft-1"
SOURCE_CONTRACT_2 = "contract-draft-2"
SOURCE_SETTLEMENT = "settlement-instrument"

# Deterministic SHA-256 placeholder (content-hash not under test here).
_DETERMINISTIC_SHA256 = "0" * 64


def _now() -> datetime:
    """Fixed timestamp keeps planted ids deterministic across runs."""
    return datetime(2026, 5, 31, 9, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Vocabulary helpers
# ---------------------------------------------------------------------------


def _build_vocabulary() -> Vocabulary:
    """Minimal vocabulary with ``asserts_obligation`` for the map-e2e fixture."""
    return Vocabulary(
        name="map-e2e-fixture-vocab",
        version="0.1.0",
        entries=[
            VocabularyEntry(
                predicate="asserts_obligation",
                aliases=["asserts_shall", "asserts_must"],
                operand_types=[
                    OperandTypeSchema(name="obligor", kind="entity", required=True),
                    OperandTypeSchema(name="action", kind="literal", required=True),
                ],
                qualifier_required=True,
                notes="map-e2e fixture obligation predicate",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Agent / attribution helpers
# ---------------------------------------------------------------------------


def _make_agent() -> AgentAttribution:
    return AgentAttribution(kind="llm", identifier="map-e2e-fixture", role="extractor")


def _make_role_attribution(agent: AgentAttribution) -> RoleAttribution:
    return RoleAttribution(agent=agent, activity="proposed", at=_now())


# ---------------------------------------------------------------------------
# Provenance builder
# ---------------------------------------------------------------------------


def _build_provenance(
    *,
    source_id: str,
    atom_id: str,
    agent: AgentAttribution,
    nonce: str = "",
) -> ProvenanceRecord:
    """Build a ProvenanceRecord with a content-addressable id."""
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


# ---------------------------------------------------------------------------
# Atom builder
# ---------------------------------------------------------------------------


def _build_atom(
    *,
    source_id: str,
    paragraph_index: int,
    char_span: tuple[int, int],
    narrative: str,
    entity_surface_form: str,
    provenance_id: str,
    role_attribution: RoleAttribution,
    nonce: str = "",
) -> Atom:
    """Build an Atom with a content-addressable id.

    Each atom carries one entity-kind operand (``obligor``) whose
    ``value`` is the surface form of the entity being referenced. The
    mapping pipeline uses this surface form to deduplicate across sources.

    A second ``action`` literal operand is required by the
    ``asserts_obligation`` predicate's vocabulary definition.

    ``nonce`` varies the identity content so atoms with the same surface
    form but different paragraph positions hash to distinct ids.
    """
    operand_obligor = OperandRef(
        role="obligor",
        kind="entity",
        value=entity_surface_form,
        type_hint="party",
    )
    operand_action = OperandRef(
        role="action",
        kind="literal",
        value=f"perform obligations under section 1{('-' + nonce) if nonce else ''}",
        type_hint="action_description",
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
        "operands": [operand_obligor, operand_action],
        "narrative": narrative,
        "qualifier_level": "high",
        "qualifier_basis": None,
        "provenance_id": provenance_id,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    draft = Atom(**base)
    base["id"] = compute_id(draft)
    return Atom(**base)


# ---------------------------------------------------------------------------
# Round-trip helper: plant one atom + its provenance
# ---------------------------------------------------------------------------


def _plant_atom(
    substrate: Substrate,
    source_id: str,
    *,
    paragraph_index: int,
    char_span: tuple[int, int],
    narrative: str,
    entity_surface_form: str,
    agent: AgentAttribution,
    role_attribution: RoleAttribution,
    nonce: str = "",
) -> Atom:
    """Build, round-trip prov/atom, and plant both onto the substrate."""
    # Round 1: build a stub provenance pointing at placeholder atom id;
    # compute the real atom id; rebuild prov against the real atom id.
    # This mirrors the pattern in tests/e2e/_fixture_builder.py.
    stub_prov = _build_provenance(
        source_id=source_id,
        atom_id="a-" + "0" * 16,
        agent=agent,
        nonce=nonce,
    )
    atom_stub = _build_atom(
        source_id=source_id,
        paragraph_index=paragraph_index,
        char_span=char_span,
        narrative=narrative,
        entity_surface_form=entity_surface_form,
        provenance_id=stub_prov.id,
        role_attribution=role_attribution,
        nonce=nonce,
    )
    final_prov = _build_provenance(
        source_id=source_id,
        atom_id=atom_stub.id,
        agent=agent,
        nonce=nonce,
    )
    atom = _build_atom(
        source_id=source_id,
        paragraph_index=paragraph_index,
        char_span=char_span,
        narrative=narrative,
        entity_surface_form=entity_surface_form,
        provenance_id=final_prov.id,
        role_attribution=role_attribution,
        nonce=nonce,
    )
    substrate.add_provenance(source_id, final_prov)
    substrate.add_atom(source_id, atom)
    return atom


# ---------------------------------------------------------------------------
# Paragraph + manifest helpers
# ---------------------------------------------------------------------------


def _plant_paragraph(
    substrate: Substrate, source_id: str, paragraph_id: str, body: str, paragraph_index: int
) -> ParagraphEntry:
    paragraph_dir = substrate.source_mirror_root(source_id) / "paragraphs"
    paragraph_dir.mkdir(parents=True, exist_ok=True)
    entry = ParagraphEntry(
        paragraph_id=paragraph_id,
        paragraph_index=paragraph_index,
        section_path=["Part I", "§1"],
        label="text",
        page_no=1,
        char_count=len(body),
        content_sha256=_DETERMINISTIC_SHA256,
    )
    paragraph_path = substrate.paragraph_path(source_id, paragraph_id)
    atomic_write_text(paragraph_path, serialize_paragraph_md(entry, body))
    return entry


def _plant_manifest(
    substrate: Substrate,
    source_id: str,
    filename: str,
    paragraph_entries: list[ParagraphEntry],
) -> None:
    manifest_payload: dict[str, Any] = {
        "source_id": source_id,
        "source_filename": filename,
        "source_sha256": _DETERMINISTIC_SHA256,
        "source_bytes_len": 2048,
        "ingest_engine": "docling",
        "ingest_engine_version": "0.1.0",
        "vocabulary_snapshot_sha256": _DETERMINISTIC_SHA256,
        "provenance_id": "p-" + "1" * 16,
        "paragraphs": paragraph_entries,
        "schema_version": 1,
    }
    draft_manifest = SourceMirrorManifest(id="m-" + "0" * 16, **manifest_payload)
    manifest = SourceMirrorManifest(id=compute_id(draft_manifest), **manifest_payload)
    substrate.add_source_mirror_manifest(source_id, manifest)


# ---------------------------------------------------------------------------
# Per-distillation planters
# ---------------------------------------------------------------------------


def _plant_contract_draft_1(substrate: Substrate) -> None:
    """Plant contract-draft-1: "ACME Corp", "BetaCo Ltd", "Contract Draft 1", "Signing 1"."""
    source_id = SOURCE_CONTRACT_1
    vocabulary = _build_vocabulary()
    substrate.snapshot_vocabulary(source_id, vocabulary)

    agent = _make_agent()
    role_attribution = _make_role_attribution(agent)

    bodies = [
        "ACME Corp shall deliver the widgets under Contract Draft 1 by the agreed date.",
        "BetaCo Ltd shall make payment to ACME Corp within 30 days of Signing 1.",
        "Contract Draft 1 governs all obligations between the parties until Signing 1.",
    ]
    paragraph_entries: list[ParagraphEntry] = []
    for i, body in enumerate(bodies):
        pid = f"p-{i:04d}"
        paragraph_entries.append(
            _plant_paragraph(substrate, source_id, pid, body, paragraph_index=i)
        )

    # 3 atoms: one per entity surface form used as obligor
    _plant_atom(
        substrate,
        source_id,
        paragraph_index=0,
        char_span=(0, len(bodies[0])),
        narrative=bodies[0],
        entity_surface_form="ACME Corp",
        agent=agent,
        role_attribution=role_attribution,
        nonce="cd1-a0",
    )
    _plant_atom(
        substrate,
        source_id,
        paragraph_index=1,
        char_span=(0, len(bodies[1])),
        narrative=bodies[1],
        entity_surface_form="BetaCo Ltd",
        agent=agent,
        role_attribution=role_attribution,
        nonce="cd1-a1",
    )
    _plant_atom(
        substrate,
        source_id,
        paragraph_index=2,
        char_span=(0, len(bodies[2])),
        narrative=bodies[2],
        entity_surface_form="Contract Draft 1",
        agent=agent,
        role_attribution=role_attribution,
        nonce="cd1-a2",
    )

    _plant_manifest(substrate, source_id, "contract-draft-1.pdf", paragraph_entries)


def _plant_contract_draft_2(substrate: Substrate) -> None:
    """Plant contract-draft-2.

    Surface forms: "ACME Corporation", "BetaCo Ltd.", "Contract Draft 2", "Signing 2".
    """
    source_id = SOURCE_CONTRACT_2
    vocabulary = _build_vocabulary()
    substrate.snapshot_vocabulary(source_id, vocabulary)

    agent = _make_agent()
    role_attribution = _make_role_attribution(agent)

    bodies = [
        "ACME Corporation shall complete all filings under Contract Draft 2 within 10 days.",
        "BetaCo Ltd. shall provide written notice to ACME Corporation before Signing 2.",
        "The parties shall execute Contract Draft 2 at Signing 2.",
    ]
    paragraph_entries: list[ParagraphEntry] = []
    for i, body in enumerate(bodies):
        pid = f"p-{i:04d}"
        paragraph_entries.append(
            _plant_paragraph(substrate, source_id, pid, body, paragraph_index=i)
        )

    _plant_atom(
        substrate,
        source_id,
        paragraph_index=0,
        char_span=(0, len(bodies[0])),
        narrative=bodies[0],
        entity_surface_form="ACME Corporation",
        agent=agent,
        role_attribution=role_attribution,
        nonce="cd2-a0",
    )
    _plant_atom(
        substrate,
        source_id,
        paragraph_index=1,
        char_span=(0, len(bodies[1])),
        narrative=bodies[1],
        entity_surface_form="BetaCo Ltd.",
        agent=agent,
        role_attribution=role_attribution,
        nonce="cd2-a1",
    )
    _plant_atom(
        substrate,
        source_id,
        paragraph_index=2,
        char_span=(0, len(bodies[2])),
        narrative=bodies[2],
        entity_surface_form="Contract Draft 2",
        agent=agent,
        role_attribution=role_attribution,
        nonce="cd2-a2",
    )

    _plant_manifest(substrate, source_id, "contract-draft-2.pdf", paragraph_entries)


def _plant_settlement_instrument(substrate: Substrate) -> None:
    """Plant settlement-instrument: "ACME Corp", "BetaCo", "Counsel for ACME",
    "Settlement Instrument", "Settlement Event"."""
    source_id = SOURCE_SETTLEMENT
    vocabulary = _build_vocabulary()
    substrate.snapshot_vocabulary(source_id, vocabulary)

    agent = _make_agent()
    role_attribution = _make_role_attribution(agent)

    bodies = [
        "ACME Corp shall pay the settlement amount pursuant to the Settlement Instrument.",
        "BetaCo shall release all claims against ACME Corp upon execution of the Settlement Event.",
        "Counsel for ACME shall file the Settlement Instrument with the court within 5 days.",
    ]
    paragraph_entries: list[ParagraphEntry] = []
    for i, body in enumerate(bodies):
        pid = f"p-{i:04d}"
        paragraph_entries.append(
            _plant_paragraph(substrate, source_id, pid, body, paragraph_index=i)
        )

    _plant_atom(
        substrate,
        source_id,
        paragraph_index=0,
        char_span=(0, len(bodies[0])),
        narrative=bodies[0],
        entity_surface_form="ACME Corp",
        agent=agent,
        role_attribution=role_attribution,
        nonce="si-a0",
    )
    _plant_atom(
        substrate,
        source_id,
        paragraph_index=1,
        char_span=(0, len(bodies[1])),
        narrative=bodies[1],
        entity_surface_form="BetaCo",
        agent=agent,
        role_attribution=role_attribution,
        nonce="si-a1",
    )
    _plant_atom(
        substrate,
        source_id,
        paragraph_index=2,
        char_span=(0, len(bodies[2])),
        narrative=bodies[2],
        entity_surface_form="Counsel for ACME",
        agent=agent,
        role_attribution=role_attribution,
        nonce="si-a2",
    )

    _plant_manifest(substrate, source_id, "settlement-instrument.pdf", paragraph_entries)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_map_end_to_end_workspace(workspace: Path) -> Path:
    """Plant 3 distillations into the workspace; return the workspace path.

    Writes the ``amanuensis.yaml`` marker if absent, then plants
    ``contract-draft-1``, ``contract-draft-2``, and
    ``settlement-instrument`` under ``distillations/``.

    Each distillation gets a vocabulary snapshot (``asserts_obligation``
    predicate), 3 paragraphs, 3 atoms each with one entity-kind obligor
    operand, provenance records, and a source-mirror manifest.  The 9 atom
    operand surface forms collapse to 5 canonical entities after map-resolve
    deduplication (see ``SOURCES.md``).

    Args:
        workspace: Path to the workspace root directory.  The directory
            is created if it does not exist.

    Returns:
        The resolved workspace path (same as the input, resolved).
    """
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    marker = workspace / "amanuensis.yaml"
    if not marker.is_file():
        marker.write_text(
            "schema_version: 1\nproject_name: map-end-to-end-fixture\n",
            encoding="utf-8",
        )

    substrate = Substrate(workspace)
    _plant_contract_draft_1(substrate)
    _plant_contract_draft_2(substrate)
    _plant_settlement_instrument(substrate)
    return workspace


# ---------------------------------------------------------------------------
# CLI smoke-check entry point
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: _fixture_builder.py <workspace-path>\n")
        sys.exit(2)
    workspace = Path(sys.argv[1]).resolve()
    build_map_end_to_end_workspace(workspace)
    sys.stdout.write(f"map-end-to-end fixture planted at {workspace}\n")


if __name__ == "__main__":
    main()
