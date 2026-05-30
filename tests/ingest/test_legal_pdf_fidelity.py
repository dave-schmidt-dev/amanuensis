"""Ingest-fidelity test for a representative legal pleading (M3.4).

Runs ``ingest_pdf`` (M3.1 Docling pipeline) over the DOJ post-trial brief in
``United States and Plaintiff States v. Google LLC`` and spot-checks that
three structural properties of the brief survive the source-mirror ingest:

1. **Paragraph segmentation** is logical, not shattered into single-line
   fragments.
2. **Citation references** are preserved at realistic density (statutory
   cites, case cites, PFOF paragraph cites).
3. **Footnote linkage** is preserved via ``DocItemLabel.FOOTNOTE`` carried
   through to the manifest's ``ParagraphEntry.label`` field.

All thresholds are deliberately defensive lower bounds (typically several
multiples below the observed values in M3.4's calibration run), so that
small drifts in Docling's word-level segmentation across versions do NOT
cause spurious failures — but a structural-ingest collapse (paragraphs
shattered, citations stripped, footnotes lost) WOULD trip them.

Why this is a fidelity test, not an invariant
---------------------------------------------
This file is intentionally **not** marked ``invariants``. The invariants
charter codifies behaviors the substrate refuses to violate at the type /
filesystem level (write-once, vocabulary-pinning, PROV completeness, etc.).
Fidelity to a specific PDF is an external-world property that depends on
Docling's heuristics; the right mitigation when it drifts is a Docling
upgrade or a per-fixture pdfplumber fallback (see
``tests/fixtures/INGEST_FALLBACKS.md``), not a substrate-level guard.

Cost notes
----------
One Docling run over the 80-page brief takes ~50 s on Apple Silicon
forced to CPU (the M3.1 pipeline pins ``AcceleratorDevice.CPU`` for
cross-platform determinism — see ``docling_ingester`` module docstring).
This test runs the pipeline once, so the walltime is roughly one minute.
"""

from __future__ import annotations

import hashlib
import re
import statistics
from pathlib import Path

from amanuensis.fs import Substrate
from amanuensis.fs._serialize import parse_paragraph_md
from amanuensis.ingest import ingest_pdf
from amanuensis.schemas import (
    AgentAttribution,
    OperandTypeSchema,
    SourceMirrorManifest,
    Vocabulary,
    VocabularyEntry,
)

FIXTURE_PDF = (
    Path(__file__).parent.parent
    / "fixtures"
    / "legal-pleading"
    / "us-v-google-plaintiffs-post-trial-brief-2024.pdf"
)
SOURCE_ID = "doj-google-post-trial-brief"


def _tmp_workspace(workspace_path: Path) -> Path:
    """Create the INV-1 marker so the ``Substrate`` constructor accepts the path."""
    workspace_path.mkdir(parents=True, exist_ok=True)
    marker = workspace_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: ingest-test\n",
        encoding="utf-8",
    )
    return workspace_path


def _generic_vocabulary() -> Vocabulary:
    """Same minimal-but-realistic vocabulary shape as the other ingest tests.

    The fidelity test doesn't exercise the vocabulary directly — it's
    pinned because every ingest run requires one (INV-10). Re-using the
    smoke tests' shape keeps cross-test debugging trivial.
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


def _ingest(workspace_path: Path) -> tuple[Substrate, SourceMirrorManifest]:
    """Run the Docling pipeline once over the legal-pleading fixture.

    Returns the substrate (for on-disk lookups) and the persisted manifest.
    """
    workspace = _tmp_workspace(workspace_path)
    substrate = Substrate(workspace)
    manifest = ingest_pdf(
        substrate=substrate,
        source_id=SOURCE_ID,
        pdf_path=FIXTURE_PDF,
        vocabulary=_generic_vocabulary(),
        agent_attribution=_agent(),
    )
    return substrate, manifest


def _paragraph_bodies(substrate: Substrate, manifest: SourceMirrorManifest) -> list[str]:
    """Read every paragraph's body text from disk in manifest order."""
    bodies: list[str] = []
    for entry in manifest.paragraphs:
        path = substrate.paragraph_path(SOURCE_ID, entry.paragraph_id)
        _, body = parse_paragraph_md(path.read_text(encoding="utf-8"))
        bodies.append(body)
    return bodies


def test_legal_pdf_structural_ingest_succeeds(tmp_path: Path) -> None:
    """Smoke gate: ingest completes, manifest is well-formed, hashes match.

    Cheap pre-check before the fidelity asserts: confirms the pipeline
    didn't silently swallow an error and that ``ingest_engine`` /
    ``source_sha256`` are what the rest of the file relies on.
    """
    _substrate, manifest = _ingest(tmp_path)

    assert isinstance(manifest, SourceMirrorManifest)
    assert manifest.source_id == SOURCE_ID
    assert manifest.source_filename == FIXTURE_PDF.name
    assert manifest.ingest_engine == "docling"
    assert manifest.ingest_engine_version  # non-empty
    assert manifest.schema_version == 1

    pdf_bytes = FIXTURE_PDF.read_bytes()
    assert manifest.source_sha256 == hashlib.sha256(pdf_bytes).hexdigest()
    assert manifest.source_bytes_len == len(pdf_bytes)


def test_legal_pdf_paragraph_boundaries_are_logical(tmp_path: Path) -> None:
    """Paragraph count and median size reject the shattered-segmentation failure.

    The brief is ~80 pages of dense prose. M3.4's calibration run produced
    483 paragraphs with a median ``char_count`` of 225 chars. We assert
    very defensive lower bounds — at least 50 non-empty paragraphs and a
    median > 100 chars — that would still pass under non-trivial Docling
    drift but would fail if the ingest collapsed the document into
    single-line fragments (the degenerate failure mode the M3.1 pipeline
    must avoid for downstream atom extraction to be feasible).
    """
    substrate, manifest = _ingest(tmp_path)
    bodies = _paragraph_bodies(substrate, manifest)

    non_empty_paragraphs = [b for b in bodies if b.strip()]
    assert len(non_empty_paragraphs) >= 50, (
        f"expected at least 50 non-empty paragraphs from the ~80-page brief; "
        f"got {len(non_empty_paragraphs)} — Docling may have collapsed the "
        f"document into oversized blocks or stripped most body text"
    )

    median_char_count = statistics.median(e.char_count for e in manifest.paragraphs)
    assert median_char_count > 100, (
        f"median paragraph char_count is {median_char_count}; expected > 100. "
        f"A low median signals Docling shattered the document into "
        f"single-line fragments, which would break downstream atom "
        f"extraction's four-tuple citation discipline (INV-7)."
    )


def test_legal_pdf_citation_references_are_preserved(tmp_path: Path) -> None:
    """Statutory, case, and PFOF cites survive ingest at realistic density.

    Calibrated against M3.4's run of the brief:
        - "Sherman Act" appeared 13 times across paragraph bodies
        - "253 F.3d" (the Microsoft cite) appeared 11 times
        - 138 paragraphs matched ``PFOF\\s*¶\\s*\\d+``; 145 matched either
          the pilcrow or whitespace variant

    We assert defensive lower bounds (3 / 1 / 5) — each is several
    multiples below the observed counts, so drift in Docling's
    word-level segmentation across versions won't trip them, but a
    citation-stripping ingest regression would.
    """
    substrate, manifest = _ingest(tmp_path)
    bodies = _paragraph_bodies(substrate, manifest)
    full_text = "\n".join(bodies)

    # 1. Statutory cite — the Sherman Act is the case's controlling statute
    #    and appears throughout the argument sections.
    sherman_count = full_text.count("Sherman Act")
    assert sherman_count >= 3, (
        f'expected "Sherman Act" to appear at least 3 times across all '
        f"paragraphs; got {sherman_count}. A complete stripping of "
        f"statutory cites is the failure mode this check guards against."
    )

    # 2. Case cite — Microsoft's reporter cite (253 F.3d 34) is the
    #    foundational antitrust precedent the brief leans on.
    microsoft_count = full_text.count("253 F.3d")
    assert microsoft_count >= 1, (
        f'expected "253 F.3d" to appear at least 1 time across all '
        f"paragraphs (the Microsoft cite); got {microsoft_count}."
    )

    # 3. PFOF paragraph cites — the brief cites its own Proposed Findings
    #    of Fact by paragraph number using the pilcrow form
    #    "PFOF ¶ NNN" (most common) or plain-whitespace "PFOF NNN".
    #    Either form is acceptable evidence of citation preservation.
    pfof_re = re.compile(r"PFOF\s*¶?\s*\d+")
    pfof_paragraph_hits = sum(1 for body in bodies if pfof_re.search(body))
    assert pfof_paragraph_hits >= 5, (
        f"expected at least 5 paragraphs to contain a PFOF cite "
        f'(regex r"PFOF\\s*¶?\\s*\\d+"); got {pfof_paragraph_hits}. '
        f"PFOF cites are the brief's primary intra-document reference "
        f"vehicle; absent density here would mean Docling has dropped "
        f"either the 'PFOF' tokens, the pilcrow, or the digit runs."
    )


def test_legal_pdf_footnote_linkage_is_preserved(tmp_path: Path) -> None:
    """At least one manifest entry carries the FOOTNOTE label.

    Docling's ``DocItemLabel.FOOTNOTE.value`` is the string ``"footnote"``;
    the docling ingester emits it directly into ``ParagraphEntry.label``
    when the underlying item is footnote-typed. M3.4's calibration run
    produced 18 footnote-labeled paragraphs in the brief — we assert a
    defensive lower bound of 1, which would still pass under most
    Docling drift but would fail if the FOOTNOTE label class were
    silently filtered out of the manifest.
    """
    # Match the docling label-class value rather than the literal string
    # so a future docling rename surfaces here clearly.
    from docling_core.types.doc.labels import DocItemLabel

    _substrate, manifest = _ingest(tmp_path)

    footnote_label = DocItemLabel.FOOTNOTE.value
    footnote_count = sum(1 for entry in manifest.paragraphs if entry.label == footnote_label)
    assert footnote_count >= 1, (
        f"expected at least 1 paragraph with label={footnote_label!r} from "
        f"the brief's numbered footnotes; got {footnote_count}. Docling's "
        f"FOOTNOTE classification appears to have been dropped — downstream "
        f"atom extraction would lose the ability to distinguish footnote "
        f"text from body text in this fixture."
    )
