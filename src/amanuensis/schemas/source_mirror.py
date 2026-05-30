"""SourceMirrorManifest — manifest for a distillation's source-mirror.

A ``SourceMirrorManifest`` records the per-paragraph output of running a
PDF ingestor (M3.1 = Docling; M3.2 will add a pdfplumber fallback) over a
source document, together with the supporting integrity hashes:

- ``source_sha256`` pins the input PDF bytes so the ingest is reproducible
  against a specific file revision.
- ``vocabulary_snapshot_sha256`` closes INV-10's deferred manifest-hash
  check by recording the per-distillation vocabulary snapshot's content
  hash next to the paragraphs that were extracted under it.
- ``provenance_id`` references the one ``source-mirror-document`` PROV
  record (INV-3) that captures the ingest activity. Per-paragraph PROV
  records are out of scope for M3.1; future milestones can extend
  INV-3's gate to walk source-mirror paragraphs.

The manifest is content-addressable like every other substrate artifact
(``id`` is dropped from the canonical-form hash; see ``_hashing.py``).
There are no per-class volatile fields: every field — including the
non-deterministic ``activity_*`` timestamps that flow into
``provenance_id`` — is identity content. Re-ingesting the same PDF with
the same vocabulary snapshot and the same Docling version produces a
bytewise-identical manifest EXCEPT for the activity timestamps and the
ids they feed; M3.3 codifies that determinism boundary.

Notes
-----
- ``paragraph_id`` is formatted ``p-NNNN`` (zero-padded to width 4) so
  lexicographic sort of files in ``paragraphs/`` recovers reading order
  without parsing the manifest. Width 4 supports up to 9999 paragraphs
  per source-mirror; the manifest construction path raises a clear error
  if a fixture exceeds that.
- ``label`` stores the Docling ``DocItemLabel`` enum's ``.value`` string,
  not the enum itself, so the on-disk YAML stays clean and human-readable.
- ``section_path`` is the running stack of SECTION_HEADER text from the
  document root down to (but not including) the paragraph itself. An
  empty list means "before any heading was seen."
- ``page_no`` is the first page on which the paragraph appears (from
  ``item.prov[0].page_no`` when Docling supplies it; ``None`` otherwise).
- ``content_sha256`` is the SHA-256 of the paragraph's TEXT body — not
  the on-disk ``.md`` file (which includes YAML frontmatter); that is so
  re-rendering the file with different frontmatter formatting does not
  invalidate the content hash.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict


class ParagraphEntry(BaseModel):
    """One paragraph emitted by the source-mirror ingest.

    Carries enough provenance to reconstruct the four-tuple
    ``(source_id, section_path, paragraph_index, char_span)`` that
    INV-7 requires of every Atom: three are direct fields here; the
    fourth (``char_span``) is derived per-atom from the paragraph body
    when atoms are extracted in later milestones.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    paragraph_id: str
    paragraph_index: int
    section_path: list[str]
    label: str
    page_no: int | None
    char_count: int
    content_sha256: str


class SourceMirrorManifest(BaseModel):
    """Manifest for one distillation's source-mirror (M3.1 deliverable).

    See module docstring for the content-id discipline (id depends on
    every other field including the non-deterministic ``provenance_id``)
    and INV-10 / INV-3 interactions.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    # No per-class volatile fields. ``id`` is universally dropped by the
    # hasher (see ``_hashing.py``); every other field is identity content,
    # including ``provenance_id`` — re-running ingest writes a different
    # PROV (different timestamps) and therefore a different manifest id.
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset()

    id: str
    source_id: str
    source_filename: str
    source_sha256: str
    source_bytes_len: int

    ingest_engine: Literal["docling", "pdfplumber"]
    ingest_engine_version: str

    vocabulary_snapshot_sha256: str
    provenance_id: str

    paragraphs: list[ParagraphEntry]

    schema_version: int = 1
