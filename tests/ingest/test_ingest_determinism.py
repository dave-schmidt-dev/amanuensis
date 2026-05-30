"""Re-ingest determinism gate for the M3.1 / M3.2 source-mirror pipelines (M3.3 / M3.4).

Both ingesters document a per-run determinism boundary in their module
docstrings: only ``activity_started_at`` / ``activity_ended_at`` (and the
ids they transitively feed — ``prov.id``, ``prov.entity_id``, and
``manifest.id``) are non-deterministic across re-runs of the same
(pdf_bytes, vocabulary_snapshot_bytes, ingester_version). Every other
manifest field — paragraph count, paragraph ids/indices, section_path,
label, page_no, char_count, content_sha256, source_sha256,
source_bytes_len, vocabulary_snapshot_sha256, ingest_engine,
ingest_engine_version — and the on-disk paragraph ``.md`` body bytes
must be byte-identical across re-runs.

This test mitigates PM-3 (the Phase 1 plan's "ingest non-determinism"
risk) by codifying that boundary against the CUAD fixture (M3.3 baseline)
AND against the DOJ legal-pleading fixture (M3.4 extension), parametrized
across both engines for both fixtures. On a per-fixture non-determinism
observation for Docling, the project's documented response is to mark the
fixture in ``tests/fixtures/INGEST_FALLBACKS.md`` and route it through
the pdfplumber engine — the determinism test does not auto-switch
engines; it only *observes* determinism so the fallback decision is
informed by data.

Cost / scope notes
------------------
- CUAD fixture: three runs per engine x two engines = six full ingests
  over the small (3-page) fixture (Docling dominates at roughly 25 s per
  run on CPU; pdfplumber is sub-second).
- Legal-pleading fixture (M3.4 extension): the brief is ~80 pages, so
  Docling x 3 takes roughly 60-90 s per run x 3 = ~3-5 min; pdfplumber
  remains sub-second. Walltime budget is a few minutes total; the test
  is left unmarked because no ``slow`` marker is registered in
  ``pyproject.toml`` today. If a ``slow`` marker is added in a later
  milestone this test is a natural candidate.
- No ingester code is modified by M3.3 or M3.4. The test imports the
  public ``ingest_pdf`` / ``ingest_pdf_pdfplumber`` entrypoints and the
  ``Substrate`` API exactly as the smoke tests do.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from amanuensis.fs import Substrate
from amanuensis.ingest import ingest_pdf, ingest_pdf_pdfplumber
from amanuensis.schemas import (
    AgentAttribution,
    OperandTypeSchema,
    SourceMirrorManifest,
    Vocabulary,
    VocabularyEntry,
)

CUAD_FIXTURE_PDF = Path(__file__).parent.parent / "fixtures" / "ingest" / "simple-contract.pdf"
LEGAL_FIXTURE_PDF = (
    Path(__file__).parent.parent
    / "fixtures"
    / "legal-pleading"
    / "us-v-google-plaintiffs-post-trial-brief-2024.pdf"
)

# Source ids stay distinct per (fixture, engine) combination so a
# hypothetical shared workspace would never collide. Each parametrize
# case uses its own ``tmp_path`` subdirectory anyway, so this is
# defensive — but it also makes failure messages easier to read because
# the source_id encodes the case.
CUAD_SOURCE_ID = "simple-contract-determinism"
LEGAL_SOURCE_ID = "doj-google-post-trial-brief-determinism"

# Signature shared by both engine entrypoints. Re-declared locally (rather
# than imported from each ingester) because the public surface is the
# function alone — there is no exported ``IngestFn`` Protocol to lean on.
IngestFn = Callable[..., SourceMirrorManifest]


def _tmp_workspace(workspace_path: Path) -> Path:
    """Create the INV-1 marker so the ``Substrate`` constructor accepts ``workspace_path``.

    Mirrors the helper in ``test_simple_pdf.py`` /
    ``test_pdfplumber_fallback.py`` so all three ingest tests start from
    the same workspace shape.
    """
    workspace_path.mkdir(parents=True, exist_ok=True)
    marker = workspace_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: ingest-test\n",
        encoding="utf-8",
    )
    return workspace_path


def _generic_vocabulary() -> Vocabulary:
    """Minimal-but-realistic vocabulary; identical shape to the smoke tests.

    Re-snapshotting the same Vocabulary in a fresh workspace must yield
    byte-identical snapshot files (and therefore identical
    ``vocabulary_snapshot_sha256`` values across runs) — the
    ``_serialize_vocabulary_snapshot`` canonicalization in
    ``Substrate`` is the contract that makes that true.
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


def _ingest_into(
    workspace_path: Path,
    engine_fn: IngestFn,
    pdf_path: Path,
    source_id: str,
) -> SourceMirrorManifest:
    """Materialize a fresh workspace at ``workspace_path`` and run ``engine_fn`` once.

    Returns the persisted ``SourceMirrorManifest``. Each call uses a
    fresh substrate (new marker, no prior distillations) so the
    write-once guard in either ingester does not trip across runs.
    """
    workspace = _tmp_workspace(workspace_path)
    substrate = Substrate(workspace)
    return engine_fn(
        substrate=substrate,
        source_id=source_id,
        pdf_path=pdf_path,
        vocabulary=_generic_vocabulary(),
        agent_attribution=_agent(),
    )


def _paragraph_body_sha(substrate: Substrate, source_id: str, paragraph_id: str) -> str:
    """Hash the on-disk paragraph ``.md`` body bytes.

    Hashes the full file bytes — frontmatter included — because the
    determinism contract covers what an auditor would see on disk, not
    just the body field. Frontmatter is generated deterministically by
    ``serialize_paragraph_md`` from the entry's deterministic fields,
    so any drift here would signal a real regression.
    """
    path = substrate.paragraph_path(source_id, paragraph_id)
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("engine_fn", "pdf_path", "source_id"),
    [
        pytest.param(ingest_pdf, CUAD_FIXTURE_PDF, CUAD_SOURCE_ID, id="docling-cuad"),
        pytest.param(ingest_pdf_pdfplumber, CUAD_FIXTURE_PDF, CUAD_SOURCE_ID, id="pdfplumber-cuad"),
        pytest.param(
            ingest_pdf,
            LEGAL_FIXTURE_PDF,
            LEGAL_SOURCE_ID,
            id="docling-legal-pleading",
        ),
        pytest.param(
            ingest_pdf_pdfplumber,
            LEGAL_FIXTURE_PDF,
            LEGAL_SOURCE_ID,
            id="pdfplumber-legal-pleading",
        ),
    ],
)
def test_reingest_is_deterministic(
    tmp_path: Path, engine_fn: IngestFn, pdf_path: Path, source_id: str
) -> None:
    """Three fresh re-ingests of the same PDF produce byte-identical paragraphs.

    Parametrized over the cross-product of (engine, fixture):
        - docling x CUAD (small 3-page contract)
        - pdfplumber x CUAD
        - docling x legal-pleading (DOJ ~80-page post-trial brief — M3.4)
        - pdfplumber x legal-pleading

    The legal-pleading axis is the M3.4 extension of M3.3's CUAD-only
    determinism gate. Docling runs over the brief take ~50 s each on
    CPU, so the docling-legal-pleading case is the slowest (~2.5-3 min
    for three runs); pdfplumber over the brief remains sub-second.
    M3.4's calibration runs confirmed Docling is byte-identical across
    re-ingests of the brief, so no xfail markers are needed. If a
    future Docling upgrade breaks this on the brief, the documented
    response is in ``tests/fixtures/INGEST_FALLBACKS.md``: log the
    fixture, mark this specific parametrize case xfail, and route the
    fixture through the pdfplumber path at the call site.

    What is asserted equal across runs:
        - paragraph count
        - per-paragraph: paragraph_id, paragraph_index, section_path,
          label, page_no, char_count, content_sha256
        - on-disk paragraph ``.md`` body bytes (sha256)
        - manifest scalars: source_sha256, source_bytes_len,
          vocabulary_snapshot_sha256, ingest_engine,
          ingest_engine_version, source_id, source_filename

    What is asserted DIFFERENT across runs (sanity check that the test
    is exercising fresh ingests, not a cache):
        - ``activity_started_at`` / ``activity_ended_at`` on the PROV
          record (we read them indirectly via ``provenance_id``,
          which incorporates ``activity_ended_at`` into its derived
          ``entity_id``; differing provenance_ids implies differing
          timestamps)
        - ``manifest.id`` (depends on ``provenance_id``)
    """
    run_dirs = [tmp_path / f"run-{i}" for i in range(3)]
    manifests = [_ingest_into(run_dir, engine_fn, pdf_path, source_id) for run_dir in run_dirs]
    substrates = [Substrate(run_dir) for run_dir in run_dirs]

    first = manifests[0]

    # --- 1. Deterministic manifest scalars match across all three runs.
    for other in manifests[1:]:
        assert other.source_id == first.source_id
        assert other.source_filename == first.source_filename
        assert other.source_sha256 == first.source_sha256
        assert other.source_bytes_len == first.source_bytes_len
        assert other.ingest_engine == first.ingest_engine
        assert other.ingest_engine_version == first.ingest_engine_version
        assert other.vocabulary_snapshot_sha256 == first.vocabulary_snapshot_sha256
        assert other.schema_version == first.schema_version

    # --- 2. Paragraph count is stable.
    counts = [len(m.paragraphs) for m in manifests]
    assert counts[0] == counts[1] == counts[2], (
        f"paragraph count drifted across re-ingests: {counts}; this is "
        f"the PM-3 signal — record the fixture in tests/fixtures/"
        f"INGEST_FALLBACKS.md and route through the alternate engine"
    )

    # --- 3. Per-paragraph fields match index-by-index across runs.
    for index in range(counts[0]):
        e0 = first.paragraphs[index]
        for run_idx, other in enumerate(manifests[1:], start=1):
            ei = other.paragraphs[index]
            assert ei.paragraph_id == e0.paragraph_id, (
                f"run {run_idx} paragraph {index}: id drift "
                f"{ei.paragraph_id!r} vs {e0.paragraph_id!r}"
            )
            assert ei.paragraph_index == e0.paragraph_index
            assert ei.section_path == e0.section_path, (
                f"run {run_idx} paragraph {index}: section_path drift "
                f"{ei.section_path!r} vs {e0.section_path!r}"
            )
            assert ei.label == e0.label
            assert ei.page_no == e0.page_no
            assert ei.char_count == e0.char_count
            assert ei.content_sha256 == e0.content_sha256, (
                f"run {run_idx} paragraph {index} ({e0.paragraph_id}): "
                f"content_sha256 drift {ei.content_sha256} vs "
                f"{e0.content_sha256}"
            )

    # --- 4. On-disk paragraph .md files are byte-identical across runs.
    for entry in first.paragraphs:
        body_shas = [
            _paragraph_body_sha(substrate, source_id, entry.paragraph_id)
            for substrate in substrates
        ]
        assert body_shas[0] == body_shas[1] == body_shas[2], (
            f"paragraph {entry.paragraph_id} on-disk bytes drift across runs: {body_shas}"
        )

    # --- 5. Documented non-determinism: provenance_id (and therefore
    #     manifest.id) MUST differ across runs because they incorporate
    #     activity_ended_at. Sanity check that the three runs really
    #     executed independently — if all three matched, the test would
    #     be silently passing on cached state instead of exercising the
    #     ingest pipeline three times.
    prov_ids = {m.provenance_id for m in manifests}
    manifest_ids = {m.id for m in manifests}
    assert len(prov_ids) == 3, (
        f"expected three distinct provenance_ids (one per run); got "
        f"{prov_ids} — the test may be hitting cached state instead of "
        f"running the ingest pipeline three times"
    )
    assert len(manifest_ids) == 3, (
        f"expected three distinct manifest.ids (one per run); got "
        f"{manifest_ids} — manifest.id depends on provenance_id which "
        f"embeds activity_ended_at, so non-uniqueness here is a smell"
    )
