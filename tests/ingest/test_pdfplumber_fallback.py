"""Smoke test for the M3.2 pdfplumber fallback ingest pipeline.

Mirrors ``tests/ingest/test_simple_pdf.py`` (the M3.1 docling smoke
test) over the same 3-page CUAD fixture, but exercises
``ingest_pdf_pdfplumber`` and asserts the engine-specific differences:

- ``manifest.ingest_engine == "pdfplumber"``
- PROV ``activity == "pdfplumber-ingest"``
- No assertion that ``section_path`` is ever populated — pdfplumber
  has no heading hierarchy, so every paragraph ships with
  ``section_path=[]``. This is the documented fallback trade-off
  (see ``pdfplumber_ingester`` module docstring).

The same write-once guard (``SourceMirrorExists``) and content-
addressable id discipline applied by the docling pipeline are
re-verified here so the two engines stay structurally interchangeable.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from amanuensis.fs import SourceMirrorExists, Substrate
from amanuensis.fs._serialize import parse_paragraph_md
from amanuensis.ingest import ingest_pdf_pdfplumber
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
# Distinct from the docling test's source_id so the two ingester tests
# never collide if (hypothetically) run against the same workspace. In
# practice each test uses a fresh tmp_path, so this is defensive.
SOURCE_ID = "simple-contract-pdfplumber-test"


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

    Same shape as the docling test's vocabulary so the two snapshots
    have comparable byte sizes and any cross-engine debugging stays
    easy.
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


def test_ingest_simple_pdf_pdfplumber_end_to_end(tmp_path: Path) -> None:
    """Run the full pdfplumber source-mirror pipeline and verify every output."""
    workspace = _tmp_workspace(tmp_path)
    substrate = Substrate(workspace)
    vocab = _generic_vocabulary()
    agent = _agent()

    manifest = ingest_pdf_pdfplumber(
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
    assert manifest.ingest_engine == "pdfplumber"
    assert manifest.ingest_engine_version  # non-empty
    assert manifest.schema_version == 1

    # source_sha256 / source_bytes_len match the on-disk PDF.
    pdf_bytes = FIXTURE_PDF.read_bytes()
    assert manifest.source_sha256 == hashlib.sha256(pdf_bytes).hexdigest()
    assert manifest.source_bytes_len == len(pdf_bytes)

    # --- 2. Paragraph count + ordering. The blank-line heuristic can
    #     yield very different paragraph boundaries from Docling
    #     (pdfplumber doesn't reflow text and many PDFs have no blank
    #     lines), so we only assert >= 1 — the docling test's >= 5
    #     was tuned to Docling's segmentation, not pdfplumber's.
    assert len(manifest.paragraphs) >= 1, (
        f"expected at least 1 paragraph from the 3-page CUAD fixture; "
        f"got {len(manifest.paragraphs)}"
    )
    for index, entry in enumerate(manifest.paragraphs):
        assert entry.paragraph_index == index
        assert entry.paragraph_id == f"p-{index:04d}"
        assert entry.char_count >= 0
        # Every pdfplumber paragraph ships with the constant label /
        # empty section_path documented in the module docstring.
        assert entry.label == "text"
        assert entry.section_path == []
        # page_no should be 1-indexed and within fixture page range.
        assert entry.page_no is not None
        assert 1 <= entry.page_no <= 3

    # --- 3. Every paragraph file exists at the canonical path and
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

    # --- 4. PROV record exists, parses, and matches the manifest.
    prov_path = substrate.provenance_path(SOURCE_ID, manifest.provenance_id)
    assert prov_path.is_file(), f"provenance record missing: {prov_path}"
    prov_data = yaml.safe_load(prov_path.read_text(encoding="utf-8"))
    prov = ProvenanceRecord.model_validate(prov_data)
    assert prov.id == manifest.provenance_id
    assert prov.entity_type == "source-mirror-document"
    # M3.2 uses the same derived entity_id shape as M3.1 — engine is
    # NOT embedded (the entity is the same source-mirror document
    # regardless of which engine produced it; engine is a manifest
    # property, not an identity component).
    assert prov.entity_id.startswith(f"source-mirror:{manifest.source_sha256}:")
    assert prov.activity == "pdfplumber-ingest"
    assert prov.activity_started_at <= prov.activity_ended_at
    assert prov.used_entity_ids == []
    assert prov.was_attributed_to == agent

    # --- 5. Manifest file exists at canonical path and round-trips.
    manifest_path = substrate.manifest_path(SOURCE_ID)
    assert manifest_path.is_file(), f"manifest missing: {manifest_path}"
    manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    rehydrated = SourceMirrorManifest.model_validate(manifest_data)
    assert rehydrated.model_dump() == manifest.model_dump()

    # --- 6. Vocabulary snapshot pin matches the manifest hash.
    snapshot_path = substrate.vocabulary_snapshot_path(SOURCE_ID)
    assert snapshot_path.is_file()
    snapshot_bytes = snapshot_path.read_bytes()
    assert manifest.vocabulary_snapshot_sha256 == hashlib.sha256(snapshot_bytes).hexdigest()

    # --- 7. Sanity: the manifest's id is content-addressable (m- prefix);
    #     prov.id is p-prefixed.
    assert manifest.id.startswith("m-")
    assert prov.id.startswith("p-")


def test_pdfplumber_paragraph_entries_are_ordered_and_unique(tmp_path: Path) -> None:
    """Reading paragraphs in lex-order by filename matches manifest order."""
    workspace = _tmp_workspace(tmp_path)
    substrate = Substrate(workspace)
    vocab = _generic_vocabulary()
    agent = _agent()
    manifest = ingest_pdf_pdfplumber(
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


def test_pdfplumber_paragraph_entry_models_have_required_fields(tmp_path: Path) -> None:
    """Every entry in the manifest is a fully-populated ParagraphEntry."""
    workspace = _tmp_workspace(tmp_path)
    substrate = Substrate(workspace)
    vocab = _generic_vocabulary()
    agent = _agent()
    manifest = ingest_pdf_pdfplumber(
        substrate=substrate,
        source_id=SOURCE_ID,
        pdf_path=FIXTURE_PDF,
        vocabulary=vocab,
        agent_attribution=agent,
    )
    for entry in manifest.paragraphs:
        assert isinstance(entry, ParagraphEntry)
        assert entry.label == "text"  # constant for pdfplumber
        assert entry.char_count > 0
        assert len(entry.content_sha256) == 64  # hex sha256


def test_pdfplumber_reingest_refuses_when_manifest_exists(tmp_path: Path) -> None:
    """Second ingest call against the same source_id raises SourceMirrorExists.

    Symmetric with the docling ingester's write-once guard and with
    INV-10's ``SubstrateSnapshotConflict`` semantics: a source-mirror
    distillation is write-once. Re-ingest into an existing distillation
    could leave orphan paragraph files (shorter re-ingest) or mix
    old + new paragraph bodies (different pdfplumber version /
    different vocabulary). The pipeline refuses rather than corrupting
    on-disk state. Also verifies the first ingest's manifest is
    unchanged on disk after the failed second call.
    """
    workspace = _tmp_workspace(tmp_path)
    substrate = Substrate(workspace)
    vocab = _generic_vocabulary()
    agent = _agent()

    first_manifest = ingest_pdf_pdfplumber(
        substrate=substrate,
        source_id=SOURCE_ID,
        pdf_path=FIXTURE_PDF,
        vocabulary=vocab,
        agent_attribution=agent,
    )

    with pytest.raises(SourceMirrorExists, match="manifest already exists"):
        ingest_pdf_pdfplumber(
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
