"""Docling-based PDF ingestion for M3.1.

Public surface: :func:`ingest_pdf`. Library-only — no CLI subcommand
in M3.1.

The pipeline is deliberately small. Given a workspace ``Substrate``, a
``source_id``, a PDF path, a ``Vocabulary``, and an ``AgentAttribution``:

1. **Pin the vocabulary** via ``Substrate.snapshot_vocabulary`` (INV-10).
   Re-read the on-disk bytes and SHA-256 them — that hash is what the
   manifest stores. INV-10's deferred manifest-hash gate (M3.1) reads
   the snapshot file again at audit time and re-verifies.
2. **Hash the PDF**. ``source_sha256`` + ``source_bytes_len`` pin the
   input revision; re-ingesting the same file deterministically
   recomputes them.
3. **Run Docling**. ``activity_started_at`` and ``activity_ended_at``
   bracket the call — these are the only intentionally non-deterministic
   fields in the output (and the ids they feed into).
4. **Walk the document**. ``iterate_items`` yields ``(item, level)``
   tuples for the entire document tree. We maintain a heading stack
   keyed by ``SectionHeaderItem.level`` so the running ``section_path``
   for any paragraph is the list of ancestor headings.
5. **Write paragraphs** atomically to
   ``distillations/<source_id>/source-mirror/paragraphs/p-NNNN.md``.
6. **Persist the PROV record** for the ingest activity (one record,
   ``entity_type="source-mirror-document"``). Per-paragraph PROV is out
   of scope for M3.1 — INV-3's gate is scoped to atoms today; later
   milestones can extend it to walk source-mirror paragraphs.
7. **Persist the manifest** at
   ``distillations/<source_id>/source-mirror/manifest.yaml``.

INV-1 is upheld by ``Substrate.__init__`` (marker required); INV-8 by
every write going through ``atomic_write_text``; INV-7's four-tuple is
materialized in each ``ParagraphEntry``'s ``section_path`` +
``paragraph_index`` (the remaining ``char_span`` is derived per-atom in
later milestones).

Content-id cycle (Constraint 6)
-------------------------------
``SourceMirrorManifest.id`` depends on ``provenance_id``;
``ProvenanceRecord.entity_id`` would naively depend on ``manifest.id``.
We break the cycle the way the M3.1 spec's fallback suggests: the
ingest activity's ``entity_id`` is a deterministic derivation of the
PDF's content hash + the activity end timestamp
(``source-mirror:<source_sha256>:<activity_ended_at_iso>``). That
identifier is unique per ingest run (timestamp), points unambiguously
at this PDF (sha256), and does NOT require the manifest's id — so we
can compute prov first, then the manifest. The assertion approach
described in Constraint 6 (placeholder entity_id → recompute) would
fire because ``ProvenanceRecord._VOLATILE_FIELDS`` is empty (every
field including ``entity_id`` is identity content), so the fallback
is the right path. The manifest itself remains content-addressable;
auditors can still walk from any paragraph back to the manifest via
``provenance_id`` and from the manifest's PROV record to the source
bytes via ``entity_id``.

Determinism
-----------
M3.1 emits one PROV per ingest call. Per-run, only
``activity_started_at`` / ``activity_ended_at`` are non-deterministic;
they feed into ``prov.id`` and (transitively) ``manifest.id`` and
``prov.entity_id``. Every other manifest field is a pure function of
(pdf_bytes, vocabulary_snapshot_bytes, docling_version). M3.3 will
verify byte-identical paragraphs across re-runs.

CPU accelerator (unconditional)
-------------------------------
The pipeline forces ``AcceleratorDevice.CPU`` for two reasons: (1) macOS
Apple-Silicon hits an MPS float64 incompatibility in Docling 2.96's
rt-detr layout model, and (2) running CPU on every platform gives us
deterministic byte-identical paragraph output across Linux/macOS runs.
Throughput cost only; correctness and M3.3's determinism gate both
benefit.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from amanuensis.fs import SourceMirrorExists, Substrate
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import serialize_paragraph_md
from amanuensis.schemas import (
    AgentAttribution,
    ParagraphEntry,
    ProvenanceRecord,
    SourceMirrorManifest,
    Vocabulary,
    compute_id,
)

# Width of the zero-padded paragraph counter. Supports up to 9999 paragraphs
# per source-mirror — well above the M3.1 fixture's needs. Exceeding it
# raises a clear error so the on-disk lex-sort ordering invariant doesn't
# break silently.
_PARAGRAPH_ID_WIDTH = 4
_PARAGRAPH_ID_MAX = 10**_PARAGRAPH_ID_WIDTH - 1

_INGEST_ACTIVITY = "docling-ingest"


def _docling_version() -> str:
    """Return the installed Docling distribution version, or ``"unknown"``.

    Recorded in the manifest so M3.3 / M3.4 can detect re-ingest under a
    different ingester version (which is allowed to change paragraph
    output — determinism is per-version).
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("docling")
    except PackageNotFoundError:  # pragma: no cover - environment glitch
        return "unknown"


def _iso_utc(dt: datetime) -> str:
    """Stable ISO-8601 UTC encoding (microsecond + ``Z`` suffix)."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _derived_entity_id(source_sha256: str, activity_ended_at: datetime) -> str:
    """Deterministic ``entity_id`` for the ingest PROV record.

    Avoids the manifest.id <-> prov.id cycle (see module docstring,
    "Content-id cycle"). The format is human-readable so an auditor
    grep-finding ``source-mirror:<sha>:<ts>`` immediately sees which
    PDF revision and which run.
    """
    return f"source-mirror:{source_sha256}:{_iso_utc(activity_ended_at)}"


def _paragraph_id(index: int) -> str:
    """``p-NNNN`` zero-padded; raises if ``index`` overflows the width."""
    if index < 0:
        raise ValueError(f"paragraph_index must be non-negative; got {index}")
    if index > _PARAGRAPH_ID_MAX:
        raise ValueError(
            f"paragraph_index {index} exceeds width-{_PARAGRAPH_ID_WIDTH} "
            f"({_PARAGRAPH_ID_MAX} max); widen _PARAGRAPH_ID_WIDTH to ingest "
            "documents with more paragraphs"
        )
    return f"p-{index:0{_PARAGRAPH_ID_WIDTH}d}"


# Labels we emit as paragraphs (Docling-classified body content).
# SECTION_HEADER, TITLE — note: TITLE is body content (the document
# title is text the reader is meant to read), not structural.
# TABLE, PICTURE, CHART, PAGE_HEADER, PAGE_FOOTER, DOCUMENT_INDEX etc.
# are skipped — tables and pictures are future-milestone work.
def _paragraph_labels() -> frozenset[str]:
    """Closed set of DocItemLabel values that count as paragraph content.

    Computed lazily inside a function so the docling import does not run
    at module load time (the standalone schema/substrate paths must
    remain importable without Docling installed).
    """
    from docling_core.types.doc.labels import DocItemLabel

    return frozenset(
        {
            DocItemLabel.TEXT.value,
            DocItemLabel.TITLE.value,
            DocItemLabel.LIST_ITEM.value,
            DocItemLabel.CAPTION.value,
            DocItemLabel.FOOTNOTE.value,
            DocItemLabel.FORMULA.value,
            DocItemLabel.CODE.value,
        }
    )


def _section_header_label() -> str:
    from docling_core.types.doc.labels import DocItemLabel

    return DocItemLabel.SECTION_HEADER.value


def _run_docling(pdf_path: Path) -> tuple[object, datetime, datetime]:
    """Run Docling end-to-end on ``pdf_path``. Returns (result, started, ended).

    Forces CPU acceleration (see module docstring's "CPU accelerator"
    note); other pipeline options are left at defaults for M3.1.
    """
    # Imports kept inside the function so unit tests of the schema /
    # substrate paths do not pay the heavy docling import cost.
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    pipeline_options = PdfPipelineOptions()
    pipeline_options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU)
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )
    started = datetime.now(UTC)
    result = converter.convert(pdf_path)
    ended = datetime.now(UTC)
    return result, started, ended


def _iterate_paragraphs(
    document: Any,
) -> list[tuple[str, str, list[str], int | None]]:
    """Walk a Docling document; return ``[(label, text, section_path, page_no), ...]``.

    Maintains a heading stack keyed by ``SectionHeaderItem.level``. When
    a SECTION_HEADER at depth ``L`` is encountered, the stack is
    truncated to depth ``L - 1`` and the header text is pushed at depth
    ``L``; so deeper headings extend the path, sibling/shallower
    headings pop. The header item itself is not emitted as a
    paragraph (it is structure, not content).

    Returns the ordered list of paragraph tuples. Caller assigns indices
    and computes per-paragraph content hashes.
    """
    paragraph_labels = _paragraph_labels()
    section_header_label = _section_header_label()
    # heading_stack[i] = header text at depth (i + 1)
    heading_stack: list[str] = []
    out: list[tuple[str, str, list[str], int | None]] = []
    # Iterate the entire tree (no recursion needed; ``iterate_items`` is a
    # pre-order walk that yields every body item).
    for item, _iter_level in document.iterate_items():
        label_value = cast("str", item.label.value)
        text_raw = getattr(item, "text", "")
        text = text_raw if isinstance(text_raw, str) else ""
        if label_value == section_header_label:
            # Skip whitespace-only headers entirely — don't push them onto
            # the stack (silent garbage in the section_path is worse than
            # a quiet skip; Docling occasionally emits stray empty headers).
            if not text.strip():
                continue
            depth = cast("int", getattr(item, "level", 1))
            depth = max(depth, 1)
            # Truncate stack to depth - 1; then push at depth.
            del heading_stack[depth - 1 :]
            # Pad with empty strings if the document opens at a deeper level
            # than 1 (e.g., legal pleadings starting at "Argument II.A.1"
            # with no preceding H1/H2). This preserves heading depth
            # information for INV-7 four-tuple citation discipline —
            # downstream atom extraction needs to know the header is
            # depth-3 nested even when shallower ancestors are absent.
            while len(heading_stack) < depth - 1:
                heading_stack.append("")
            heading_stack.append(text)
            continue
        if label_value not in paragraph_labels:
            # tables, pictures, charts, page headers/footers, document
            # indexes, form regions, etc. — out of scope for M3.1.
            continue
        if not text.strip():
            # Skip empty / whitespace-only body items (defensive; Docling
            # occasionally emits zero-length placeholders for non-text
            # regions). Silent garbage is worse than a quiet skip.
            continue
        prov = getattr(item, "prov", None)
        page_no: int | None
        if prov:
            page_no_raw = getattr(prov[0], "page_no", None)
            page_no = cast("int | None", page_no_raw)
        else:
            page_no = None
        out.append((label_value, text, list(heading_stack), page_no))
    return out


def ingest_pdf(
    *,
    substrate: Substrate,
    source_id: str,
    pdf_path: Path,
    vocabulary: Vocabulary,
    agent_attribution: AgentAttribution,
) -> SourceMirrorManifest:
    """Run the Docling source-mirror pipeline end-to-end for one PDF.

    Args:
        substrate: Workspace substrate (already validates INV-1).
        source_id: Per-distillation identifier (path-safe).
        pdf_path: Filesystem path to the PDF.
        vocabulary: The in-memory ``Vocabulary`` to pin as the snapshot.
        agent_attribution: The agent (typically an LLM with role
            ``"extractor"``) on whose behalf this ingest is happening.
            Recorded as the PROV record's ``was_attributed_to``.

    Returns:
        The persisted ``SourceMirrorManifest``.

    Side effects:
        - Writes ``distillations/<source_id>/vocabulary-snapshot.yaml``
          (INV-10) if not already present.
        - Writes one ``.md`` file per paragraph under
          ``distillations/<source_id>/source-mirror/paragraphs/``.
        - Writes the ingest PROV record under
          ``distillations/<source_id>/provenance/<prov-id>.yaml``.
        - Writes the manifest at
          ``distillations/<source_id>/source-mirror/manifest.yaml``.
    """
    # 0. Write-once guard (symmetric with INV-10's SubstrateSnapshotConflict
    #    for the vocabulary snapshot): refuse to re-ingest a source_id whose
    #    manifest already exists, to avoid orphan paragraph files from a
    #    shorter re-ingest or mixed-version bodies. Check BEFORE any state
    #    writes so a tripped guard leaves the substrate untouched.
    manifest_path = substrate.manifest_path(source_id)
    if manifest_path.is_file():
        raise SourceMirrorExists(
            f"source-mirror manifest already exists at {manifest_path}; "
            f"refusing to re-ingest source_id={source_id!r}. Delete the "
            f"distillation's source-mirror/ directory if you want to "
            "re-ingest from scratch."
        )

    # 1. Pin the vocabulary (INV-10) and hash the snapshot bytes.
    snapshot_path = substrate.snapshot_vocabulary(source_id, vocabulary)
    snapshot_bytes = snapshot_path.read_bytes()
    vocabulary_snapshot_sha256 = hashlib.sha256(snapshot_bytes).hexdigest()

    # 2. Hash the PDF bytes.
    pdf_bytes = pdf_path.read_bytes()
    source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    source_bytes_len = len(pdf_bytes)

    # 3. Run Docling; capture activity timestamps.
    conv_result, activity_started_at, activity_ended_at = _run_docling(pdf_path)
    docling_document = cast("Any", conv_result).document  # pyright: ignore[reportUnknownMemberType]

    # 4. Walk the document into paragraph tuples.
    paragraph_tuples = _iterate_paragraphs(docling_document)

    # 5. Emit ParagraphEntry models + write per-paragraph .md files.
    entries: list[ParagraphEntry] = []
    for index, (label, text, section_path, page_no) in enumerate(paragraph_tuples):
        paragraph_id = _paragraph_id(index)
        content_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        entry = ParagraphEntry(
            paragraph_id=paragraph_id,
            paragraph_index=index,
            section_path=section_path,
            label=label,
            page_no=page_no,
            char_count=len(text),
            content_sha256=content_sha256,
        )
        entries.append(entry)
        paragraph_path = substrate.paragraph_path(source_id, paragraph_id)
        atomic_write_text(paragraph_path, serialize_paragraph_md(entry, text))

    # 6. Build + persist the ingest PROV record. ``entity_id`` is derived
    #    from source_sha256 + activity_ended_at to break the manifest.id
    #    <-> prov.id cycle (see module docstring "Content-id cycle").
    entity_id = _derived_entity_id(source_sha256, activity_ended_at)
    prov_draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type="source-mirror-document",
        entity_id=entity_id,
        activity=_INGEST_ACTIVITY,
        activity_started_at=activity_started_at,
        activity_ended_at=activity_ended_at,
        used_entity_ids=[],
        was_attributed_to=agent_attribution,
        was_influenced_by=[],
        schema_version=1,
    )
    prov_id = compute_id(prov_draft)
    prov = ProvenanceRecord(
        id=prov_id,
        entity_type="source-mirror-document",
        entity_id=entity_id,
        activity=_INGEST_ACTIVITY,
        activity_started_at=activity_started_at,
        activity_ended_at=activity_ended_at,
        used_entity_ids=[],
        was_attributed_to=agent_attribution,
        was_influenced_by=[],
        schema_version=1,
    )
    substrate.add_provenance(source_id, prov)

    # 7. Build + persist the manifest with provenance_id = prov.id.
    #    Capture the Docling version once so the draft and final manifest
    #    cannot disagree if the metadata changes between calls.
    docling_version = _docling_version()
    manifest_draft = SourceMirrorManifest(
        id="m-" + "0" * 16,
        source_id=source_id,
        source_filename=pdf_path.name,
        source_sha256=source_sha256,
        source_bytes_len=source_bytes_len,
        ingest_engine="docling",
        ingest_engine_version=docling_version,
        vocabulary_snapshot_sha256=vocabulary_snapshot_sha256,
        provenance_id=prov.id,
        paragraphs=entries,
        schema_version=1,
    )
    manifest = SourceMirrorManifest(
        id=compute_id(manifest_draft),
        source_id=source_id,
        source_filename=pdf_path.name,
        source_sha256=source_sha256,
        source_bytes_len=source_bytes_len,
        ingest_engine="docling",
        ingest_engine_version=docling_version,
        vocabulary_snapshot_sha256=vocabulary_snapshot_sha256,
        provenance_id=prov.id,
        paragraphs=entries,
        schema_version=1,
    )
    substrate.add_source_mirror_manifest(source_id, manifest)
    return manifest
