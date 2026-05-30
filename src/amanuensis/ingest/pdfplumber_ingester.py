"""pdfplumber-based PDF ingestion (M3.2 — fallback engine).

Public surface: :func:`ingest_pdf_pdfplumber`. Library-only — the
``--engine pdfplumber`` CLI flag is M4's concern; auto-fallback from
docling is M3.3's concern. This module ONLY provides a structurally
identical alternative to ``docling_ingester.ingest_pdf`` that records
``ingest_engine="pdfplumber"`` in the manifest.

Why a fallback at all
---------------------
Docling is the M3.1 default because it gives us a structured document
tree (heading hierarchy, classified body items, per-item provenance).
pdfplumber is the fallback because it is dramatically lighter (pure-
Python + pdfminer.six; no torch / no ML models), has zero
platform-specific accelerator caveats, and is the right tool when
Docling fails, when Docling's model download is impractical (CI cold
caches, air-gapped environments), or when the document is so simple
that the layout-model overhead is not worth it.

The trade-off paid for that lightness is **no section_path**:
pdfplumber does not classify regions and does not expose heading
hierarchy. Every paragraph emitted by this ingester has
``section_path=[]`` and ``label="text"``. INV-7's four-tuple
(source_id, section_path, paragraph_index, char_span) is still
materialized — just with an empty section component. Atom extraction
running over a pdfplumber-ingested source-mirror therefore loses one
dimension of structural context; downstream consumers that need
section grouping should prefer Docling when it works.

Pipeline (mirrors ``docling_ingester.ingest_pdf`` step-for-step)
-----------------------------------------------------------------
0. Write-once guard via ``SourceMirrorExists`` (manifest path check
   BEFORE any state writes).
1. Pin vocabulary via ``Substrate.snapshot_vocabulary`` (INV-10);
   re-read on-disk bytes and sha256 them for
   ``vocabulary_snapshot_sha256``.
2. Hash the PDF bytes (``source_sha256``, ``source_bytes_len``).
3. Open the PDF with pdfplumber bracketed by
   ``activity_started_at`` / ``activity_ended_at``; iterate pages and
   split each page's extracted text on blank-line boundaries to yield
   paragraph candidates (see "Paragraph splitting heuristic" below).
4. Emit ``ParagraphEntry`` models + write per-paragraph ``.md`` files
   atomically.
5. Build + persist the ingest PROV record with
   ``activity="pdfplumber-ingest"`` and the same derived ``entity_id``
   shape as docling (``source-mirror:<sha>:<iso-ts>``) — the cycle-
   breaking rationale in ``docling_ingester``'s "Content-id cycle"
   docstring applies identically here.
6. Build + persist the manifest with ``ingest_engine="pdfplumber"``
   and ``ingest_engine_version=<installed pdfplumber version>``.

Paragraph splitting heuristic
-----------------------------
``page.extract_text()`` returns a single string per page. We split
each page on one-or-more blank lines (regex ``\\n\\s*\\n``). Each
non-empty stripped chunk becomes one paragraph in document (page)
order.
This is deliberately simple — pdfplumber gives no semantic regions,
so a richer heuristic (e.g., heading detection by font size via
``page.extract_words()``) would be guesswork prone to silent
regressions. The fallback's job is to produce a usable source-mirror,
not to reconstruct Docling's output. M3.3's determinism gate will
re-run this pipeline and assert byte-identical paragraph output.

Determinism
-----------
Same as the docling pipeline: only ``activity_started_at`` /
``activity_ended_at`` are non-deterministic per run; every other
manifest field is a pure function of
(pdf_bytes, vocabulary_snapshot_bytes, pdfplumber_version). M3.3 will
verify byte-identical paragraphs across re-runs for this engine too.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

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

# Width of the zero-padded paragraph counter. Matches docling's discipline
# so on-disk lex-sort ordering is identical across engines.
_PARAGRAPH_ID_WIDTH = 4
_PARAGRAPH_ID_MAX = 10**_PARAGRAPH_ID_WIDTH - 1

_INGEST_ACTIVITY = "pdfplumber-ingest"

# Constant label for every pdfplumber paragraph. pdfplumber does not
# classify regions; the manifest schema requires a non-empty label
# string and "text" matches Docling's DocItemLabel.TEXT.value so the
# two engines' outputs are comparable for downstream tooling that
# groups paragraphs by label.
_PARAGRAPH_LABEL = "text"

# Split paragraphs on one-or-more blank lines (a newline, then optional
# whitespace, then another newline). Pre-compiled so the inner loop
# does not pay the re.compile cost on every page.
_BLANK_LINE_RE = re.compile(r"\n\s*\n")


def _pdfplumber_version() -> str:
    """Return the installed pdfplumber distribution version, or ``"unknown"``.

    Recorded in the manifest so M3.3 / M3.4 can detect re-ingest under
    a different ingester version (which is allowed to change paragraph
    output — determinism is per-version).
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("pdfplumber")
    except PackageNotFoundError:  # pragma: no cover - environment glitch
        return "unknown"


def _iso_utc(dt: datetime) -> str:
    """Stable ISO-8601 UTC encoding (microsecond + ``Z`` suffix)."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _derived_entity_id(source_sha256: str, activity_ended_at: datetime) -> str:
    """Deterministic ``entity_id`` for the ingest PROV record.

    Same shape as the docling pipeline so the manifest.id <-> prov.id
    cycle is broken identically (see ``docling_ingester`` module
    docstring, "Content-id cycle"). The engine string is NOT embedded
    in the entity_id because the entity (the source-mirror document)
    is the same regardless of which engine produced it — engine is a
    manifest property, not an identity component.
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


def _extract_paragraphs(pdf_path: Path) -> tuple[list[tuple[str, int]], datetime, datetime]:
    """Open ``pdf_path`` with pdfplumber and return paragraph + timing tuples.

    Returns ``([(text, page_no), ...], started, ended)``. The activity
    timestamps bracket the entire pdfplumber call (open + extract for
    every page) so the PROV record reflects the actual wall time the
    ingest engine held the file.

    Paragraphs are 1-indexed by page (matching Docling's convention)
    and emitted in document order: page 1 paragraphs first, then page
    2, etc. Within a page, paragraphs preserve top-to-bottom reading
    order as ``page.extract_text()`` delivers it.

    Empty pages and whitespace-only paragraph chunks are skipped — a
    silent drop is preferable to writing empty paragraph files that
    would never carry an atom.
    """
    # Lazy import: keeps the schema/substrate unit tests free of the
    # pdfminer.six load cost, mirrors the docling ingester's pattern.
    import pdfplumber

    out: list[tuple[str, int]] = []
    started = datetime.now(UTC)
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            page_no = page_index + 1  # 1-indexed, matching Docling
            text = page.extract_text() or ""
            if not text.strip():
                continue
            for chunk in _BLANK_LINE_RE.split(text):
                stripped = chunk.strip()
                if not stripped:
                    continue
                out.append((stripped, page_no))
    ended = datetime.now(UTC)
    return out, started, ended


def ingest_pdf_pdfplumber(
    *,
    substrate: Substrate,
    source_id: str,
    pdf_path: Path,
    vocabulary: Vocabulary,
    agent_attribution: AgentAttribution,
) -> SourceMirrorManifest:
    """Run the pdfplumber source-mirror pipeline end-to-end for one PDF.

    Args:
        substrate: Workspace substrate (already validates INV-1).
        source_id: Per-distillation identifier (path-safe).
        pdf_path: Filesystem path to the PDF.
        vocabulary: The in-memory ``Vocabulary`` to pin as the snapshot.
        agent_attribution: The agent (typically an LLM with role
            ``"extractor"``) on whose behalf this ingest is happening.
            Recorded as the PROV record's ``was_attributed_to``.

    Returns:
        The persisted ``SourceMirrorManifest`` with
        ``ingest_engine="pdfplumber"``.

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
    # 0. Write-once guard (symmetric with the docling ingester and with
    #    INV-10's SubstrateSnapshotConflict): refuse to re-ingest a
    #    source_id whose manifest already exists, to avoid orphan
    #    paragraph files from a shorter re-ingest or mixed-engine bodies.
    #    Check BEFORE any state writes so a tripped guard leaves the
    #    substrate untouched.
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

    # 3. Run pdfplumber; capture activity timestamps.
    paragraph_tuples, activity_started_at, activity_ended_at = _extract_paragraphs(pdf_path)

    # 4. Emit ParagraphEntry models + write per-paragraph .md files.
    #    section_path is uniformly empty (pdfplumber has no heading
    #    hierarchy); label is uniformly "text" (no region classifier).
    entries: list[ParagraphEntry] = []
    for index, (text, page_no) in enumerate(paragraph_tuples):
        paragraph_id = _paragraph_id(index)
        content_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        entry = ParagraphEntry(
            paragraph_id=paragraph_id,
            paragraph_index=index,
            section_path=[],
            label=_PARAGRAPH_LABEL,
            page_no=page_no,
            char_count=len(text),
            content_sha256=content_sha256,
        )
        entries.append(entry)
        paragraph_path = substrate.paragraph_path(source_id, paragraph_id)
        atomic_write_text(paragraph_path, serialize_paragraph_md(entry, text))

    # 5. Build + persist the ingest PROV record. ``entity_id`` is derived
    #    from source_sha256 + activity_ended_at to break the manifest.id
    #    <-> prov.id cycle (see docling_ingester module docstring
    #    "Content-id cycle"; the same rationale applies here).
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

    # 6. Build + persist the manifest with provenance_id = prov.id.
    #    Capture the pdfplumber version once so the draft and final
    #    manifest cannot disagree if the metadata changes between calls.
    pdfplumber_version = _pdfplumber_version()
    manifest_draft = SourceMirrorManifest(
        id="m-" + "0" * 16,
        source_id=source_id,
        source_filename=pdf_path.name,
        source_sha256=source_sha256,
        source_bytes_len=source_bytes_len,
        ingest_engine="pdfplumber",
        ingest_engine_version=pdfplumber_version,
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
        ingest_engine="pdfplumber",
        ingest_engine_version=pdfplumber_version,
        vocabulary_snapshot_sha256=vocabulary_snapshot_sha256,
        provenance_id=prov.id,
        paragraphs=entries,
        schema_version=1,
    )
    substrate.add_source_mirror_manifest(source_id, manifest)
    return manifest
