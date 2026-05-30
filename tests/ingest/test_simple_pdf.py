"""Smoke test for the M3.1 Docling ingest pipeline.

Runs ``ingest_pdf`` over the 3-page CUAD fixture and asserts the full
output shape: manifest fields, paragraph files on disk, the PROV record,
and the vocabulary-snapshot pin (INV-10's manifest-hash link is
exercised separately by ``tests/invariants/test_vocabulary_pinned.py``).

This test is not marked ``invariants`` — it is the M2.5-pattern
end-to-end exercise of the source-mirror pipeline. The invariants
charter for M3.1's manifest-hash gate is enforced under
``tests/invariants/``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from amanuensis.fs import SourceMirrorExists, Substrate
from amanuensis.fs._serialize import parse_paragraph_md
from amanuensis.ingest import ingest_pdf
from amanuensis.schemas import (
    AgentAttribution,
    OperandTypeSchema,
    ParagraphEntry,
    ProvenanceRecord,
    SourceMirrorManifest,
    Vocabulary,
    VocabularyEntry,
)

FIXTURE_PDF = Path(__file__).parent.parent / "fixtures" / "ingest" / "simple-contract.pdf"
SOURCE_ID = "simple-contract-test"


def _tmp_workspace(tmp_path: Path) -> Path:
    """Create the marker so ``Substrate`` constructor accepts the path."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: ingest-test\n",
        encoding="utf-8",
    )
    return tmp_path


def _generic_vocabulary() -> Vocabulary:
    """A minimal-but-realistic vocabulary for the ingest test.

    Two entries are enough to make the snapshot bytes non-trivial; the
    closed-vocabulary gate is exercised elsewhere.
    """
    return Vocabulary(
        name="ingest-test-vocab",
        version="0.1.0",
        entries=[
            VocabularyEntry(
                predicate="asserts_obligation",
                aliases=["asserts_shall"],
                operand_types=[
                    OperandTypeSchema(name="obligor", kind="entity", required=True),
                ],
                qualifier_required=False,
                notes="ingest-test entry 1",
            ),
            VocabularyEntry(
                predicate="cites_evidence",
                aliases=[],
                operand_types=[],
                qualifier_required=False,
                notes="ingest-test entry 2",
            ),
        ],
    )


def _agent() -> AgentAttribution:
    return AgentAttribution(
        kind="llm",
        identifier="claude-opus-4-7",
        role="extractor",
    )


def test_ingest_simple_pdf_end_to_end(tmp_path: Path) -> None:
    """Run the full Docling source-mirror pipeline and verify every output."""
    workspace = _tmp_workspace(tmp_path)
    substrate = Substrate(workspace)
    vocab = _generic_vocabulary()
    agent = _agent()

    manifest = ingest_pdf(
        substrate=substrate,
        source_id=SOURCE_ID,
        pdf_path=FIXTURE_PDF,
        vocabulary=vocab,
        agent_attribution=agent,
    )

    # --- 1. Return value is a SourceMirrorManifest with expected scalars.
    assert isinstance(manifest, SourceMirrorManifest)
    assert manifest.source_id == SOURCE_ID
    assert manifest.source_filename == "simple-contract.pdf"
    assert manifest.ingest_engine == "docling"
    assert manifest.ingest_engine_version  # non-empty
    assert manifest.schema_version == 1

    # source_sha256 / source_bytes_len match the on-disk PDF.
    pdf_bytes = FIXTURE_PDF.read_bytes()
    assert manifest.source_sha256 == hashlib.sha256(pdf_bytes).hexdigest()
    assert manifest.source_bytes_len == len(pdf_bytes)

    # --- 2. Paragraph count + ordering.
    assert len(manifest.paragraphs) >= 5, (
        f"expected at least 5 paragraphs from the 3-page CUAD fixture; "
        f"got {len(manifest.paragraphs)}"
    )
    for index, entry in enumerate(manifest.paragraphs):
        assert entry.paragraph_index == index
        assert entry.paragraph_id == f"p-{index:04d}"
        assert entry.char_count >= 0

    # --- 3. At least one paragraph has a non-empty section_path.
    #     The CUAD fixture has SECTION_HEADERs (ARTICLE I, ARTICLE II,
    #     TABLE OF CONTENTS) within the first 3 pages, so at least one
    #     following paragraph should have a populated stack.
    assert any(entry.section_path for entry in manifest.paragraphs), (
        "expected at least one paragraph with a non-empty section_path; the "
        "fixture's ARTICLE I / II / TOC headers should push onto the heading "
        "stack and leave following paragraphs with section_path != []"
    )

    # --- 4. Every paragraph file exists at the canonical path and
    #     round-trips back to a frontmatter+body pair whose content_sha256
    #     matches the manifest entry.
    for entry in manifest.paragraphs:
        path = substrate.paragraph_path(SOURCE_ID, entry.paragraph_id)
        assert path.is_file(), f"paragraph file missing: {path}"
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_paragraph_md(text)
        # Frontmatter shape: every ParagraphEntry field except content_sha256.
        assert frontmatter["paragraph_id"] == entry.paragraph_id
        assert frontmatter["paragraph_index"] == entry.paragraph_index
        assert frontmatter["section_path"] == entry.section_path
        assert frontmatter["label"] == entry.label
        assert frontmatter["page_no"] == entry.page_no
        assert frontmatter["char_count"] == entry.char_count
        assert "content_sha256" not in frontmatter
        # Body content hashes to the manifest's stored content_sha256.
        assert hashlib.sha256(body.encode("utf-8")).hexdigest() == entry.content_sha256
        assert len(body) == entry.char_count

    # --- 5. PROV record exists, parses, and matches the manifest.
    prov_path = substrate.provenance_path(SOURCE_ID, manifest.provenance_id)
    assert prov_path.is_file(), f"provenance record missing: {prov_path}"
    prov_data = yaml.safe_load(prov_path.read_text(encoding="utf-8"))
    prov = ProvenanceRecord.model_validate(prov_data)
    assert prov.id == manifest.provenance_id
    assert prov.entity_type == "source-mirror-document"
    # M3.1 uses a derived entity_id (see docling_ingester module docstring,
    # "Content-id cycle"). It encodes the source sha + activity end time.
    assert prov.entity_id.startswith(f"source-mirror:{manifest.source_sha256}:")
    assert prov.activity == "docling-ingest"
    assert prov.activity_started_at <= prov.activity_ended_at
    assert prov.used_entity_ids == []
    assert prov.was_attributed_to == agent

    # --- 6. Manifest file exists at canonical path and round-trips.
    manifest_path = substrate.manifest_path(SOURCE_ID)
    assert manifest_path.is_file(), f"manifest missing: {manifest_path}"
    manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    rehydrated = SourceMirrorManifest.model_validate(manifest_data)
    assert rehydrated.model_dump() == manifest.model_dump()

    # --- 7. Vocabulary snapshot pin matches the manifest hash.
    snapshot_path = substrate.vocabulary_snapshot_path(SOURCE_ID)
    assert snapshot_path.is_file()
    snapshot_bytes = snapshot_path.read_bytes()
    assert manifest.vocabulary_snapshot_sha256 == hashlib.sha256(snapshot_bytes).hexdigest()

    # --- 8. Sanity: the manifest's id is content-addressable (m- prefix).
    assert manifest.id.startswith("m-")
    assert prov.id.startswith("p-")


def test_paragraph_entries_are_ordered_and_unique(tmp_path: Path) -> None:
    """Reading paragraphs in lex-order by filename matches manifest order."""
    workspace = _tmp_workspace(tmp_path)
    substrate = Substrate(workspace)
    vocab = _generic_vocabulary()
    agent = _agent()
    manifest = ingest_pdf(
        substrate=substrate,
        source_id=SOURCE_ID,
        pdf_path=FIXTURE_PDF,
        vocabulary=vocab,
        agent_attribution=agent,
    )
    paragraphs_dir = substrate.source_mirror_root(SOURCE_ID) / "paragraphs"
    on_disk_ids = [p.stem for p in sorted(paragraphs_dir.iterdir()) if p.suffix == ".md"]
    manifest_ids = [entry.paragraph_id for entry in manifest.paragraphs]
    assert on_disk_ids == manifest_ids
    # Width-4 zero-padding ensures lex order == numeric order up to 9999.
    assert manifest_ids == sorted(manifest_ids)


def test_paragraph_entry_models_have_required_fields(tmp_path: Path) -> None:
    """Every entry in the manifest is a fully-populated ParagraphEntry."""
    workspace = _tmp_workspace(tmp_path)
    substrate = Substrate(workspace)
    vocab = _generic_vocabulary()
    agent = _agent()
    manifest = ingest_pdf(
        substrate=substrate,
        source_id=SOURCE_ID,
        pdf_path=FIXTURE_PDF,
        vocabulary=vocab,
        agent_attribution=agent,
    )
    for entry in manifest.paragraphs:
        assert isinstance(entry, ParagraphEntry)
        assert entry.label  # non-empty string
        assert entry.char_count > 0
        assert len(entry.content_sha256) == 64  # hex sha256


def test_reingest_refuses_when_manifest_exists(tmp_path: Path) -> None:
    """Second ingest call against the same source_id raises SourceMirrorExists.

    Symmetric with INV-10's ``SubstrateSnapshotConflict`` semantics: a
    source-mirror distillation is write-once. Re-ingest into an existing
    distillation could leave orphan paragraph files (shorter re-ingest)
    or mix old + new paragraph bodies (different Docling version /
    different vocabulary). The substrate refuses rather than corrupting
    on-disk state. Also verifies the first ingest's manifest is
    unchanged on disk after the failed second call.
    """
    workspace = _tmp_workspace(tmp_path)
    substrate = Substrate(workspace)
    vocab = _generic_vocabulary()
    agent = _agent()

    first_manifest = ingest_pdf(
        substrate=substrate,
        source_id=SOURCE_ID,
        pdf_path=FIXTURE_PDF,
        vocabulary=vocab,
        agent_attribution=agent,
    )

    with pytest.raises(SourceMirrorExists, match="manifest already exists"):
        ingest_pdf(
            substrate=substrate,
            source_id=SOURCE_ID,
            pdf_path=FIXTURE_PDF,
            vocabulary=vocab,
            agent_attribution=agent,
        )

    # First ingest's manifest is unchanged on disk: re-read and compare ids.
    manifest_path = substrate.manifest_path(SOURCE_ID)
    manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    on_disk_manifest = SourceMirrorManifest.model_validate(manifest_data)
    assert on_disk_manifest.id == first_manifest.id
    assert on_disk_manifest.provenance_id == first_manifest.provenance_id
