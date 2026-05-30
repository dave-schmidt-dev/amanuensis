# Tasks

Per-project task and work-in-progress tracking across sessions and agents.

Status key: `pending` | `in progress` | `done` | `blocked`.

Active plan: `~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29.md`
Active tasks: `~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29-tasks.md`
Synthesis record: `~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29-synthesis.md`

---

## Current focus

- [in progress] Phase 1 (Distill) — implementation per the 56-task breakdown
  - M1 (Schema + filesystem foundation, 9 tasks): **DONE** (HEAD `5023f4a`).
    164 tests passing; pyright strict, ruff, vulture all clean. Two bugs surfaced
    and fixed via review: Python 3.14 site.py editable-shim skip (pinned to 3.12);
    cross-day orphan in replay-log recovery (scan-and-unlink under flock). See
    HISTORY.md 2026-05-29 entries for M1.2-M1.9 + the two `[bug]` lines.
  - M2 (Validators + vocabulary, 5 tasks): **DONE** (249 tests
    pass, INV-3 / INV-5 / INV-10 gate tests active).
    - M2.1 (acquire three vocabulary fixtures): **DONE**. Three PDFs
      committed under `tests/fixtures/vocabulary-design/` (DOJ post-trial
      brief in US v. Google + CUAD Verizon ABS transfer & servicing
      agreement + NTSB AAR-21/01 Calabasas helicopter crash report);
      `SOURCES.md` cites source + URL + license per fixture and flags
      2-3 representative annotation pages per PDF. Known limitation
      documented: rebuttal monoculture (rich `denies_*`/`contests_*`
      material only in fixture 1).
    - M2.2 (design 30-60 generic predicates): **DONE**. 58 predicates
      vendored under `vocabularies/generic/predicates.yaml` (conforms
      to `src/amanuensis/schemas/vocabulary.py`; bootstrap path
      documented at top of YAML — `cp -R` to `~/.amanuensis/` OR
      override `amanuensis.yaml` `vocabulary_registry`). Manual
      annotation pass on the 9 M2.1 fixture pages yielded 100%
      coverage per fixture (32/32, 33/33, 30/30); the editorial
      reviewer spot-checked one page per fixture and confirmed the
      assignments are honest. Forward gaps tabulated in
      `vocabularies/generic/TODO.md` (rebuttal monoculture +
      tort/criminal/environmental/damages/fraud/discovery blank
      space for Phase 2). HEAD on commit close-out.
    - M2.3 (registry loader + per-distillation snapshot mechanism):
      **DONE**. `src/amanuensis/vocabulary/registry.py` with
      `load_vocabulary` + `Vocabulary.load` + `has_predicate` +
      `resolve`; `Substrate.snapshot_vocabulary` + `get_vocabulary_snapshot`
      with semantic write-once semantics; new typed exceptions
      (`VocabularyLoadError`, `SubstrateSnapshotConflict`,
      `SubstrateSnapshotCorrupt`). 36 new tests, 200/200 overall.
      Manifest-hash recording deferred to M3.1 (manifest doesn't
      exist yet); `TODO(M3.1)` seam in snapshot_vocabulary docstring.
    - M2.4 (seven validators): **DONE**. `schema_check`,
      `citation_ledger` (INV-7), `universe_check`, `scale_anchor`
      (INV-6), `closed_vocabulary` (INV-5), `provenance_completeness`
      (INV-3), `lineage_closure`. Each returns a typed
      `ValidationResult`. `Substrate.get_provenance` added to
      support `provenance_completeness`. 38 new tests.
    - M2.5 (INV-3 / INV-5 / INV-10 gate tests): **DONE**. 11 gate
      tests under `tests/invariants/`, all `@pytest.mark.invariants`.
      INVARIANTS.md updated to graduate the three invariants from
      "planned" to "active". M3.1 seams left for the manifest-hash
      check (INV-10) and for extending INV-3 to relations /
      clarifications / iterations.
  - M3 (Ingestion, 4 tasks) — **IN PROGRESS**.
    - M3.1 (Docling integration via `amanuensis ingest` library
      function): **DONE**. New `amanuensis.ingest` package with
      `ingest_pdf(...)`; new `SourceMirrorManifest` + `ParagraphEntry`
      schemas (sixth content-addressable type, `m-` prefix); new
      Substrate resolvers (`source_mirror_root`, `paragraph_path`,
      `manifest_path`) and writer (`add_source_mirror_manifest`); new
      typed exception `SourceMirrorExists` (re-ingest refuses to
      clobber, symmetric with `SubstrateSnapshotConflict`); paragraph
      .md frontmatter+body serializer pair. INV-10 graduated to fully
      "active" — manifest-hash gate test live. 254 tests pass; pyright
      strict + ruff + ruff-format + vulture all clean. Test fixture:
      3-page CUAD excerpt (519K source → 107K excerpt via pypdfium2;
      already a docling transitive). Followups tracked: cross-schema
      field-validator pass (sha256 / non-negative integer ranges
      currently unvalidated across all schemas, not just
      SourceMirrorManifest); paragraph-body re-verification path
      (hand-edits to paragraph .md diverge silently from manifest
      content_sha256 — INVARIANTS.md INV-8 documents as a known escape
      hatch).
    - M3.2 (pdfplumber fallback): **DONE**. `ingest_pdf_pdfplumber`
      mirrors the docling pipeline step-for-step; emits
      `ingest_engine="pdfplumber"` with `section_path=[]` and
      `label="text"` uniformly (no heading hierarchy from pdfplumber).
      pdfplumber added to active runtime dependencies. 4 new tests.
    - M3.3 (re-ingest determinism test, PM-3 mitigation): **DONE**.
      `test_ingest_determinism.py` parametrizes over both engines;
      three independent re-ingests asserted byte-identical except for
      the documented non-deterministic set (timestamps + ids derived
      from them). New `tests/fixtures/INGEST_FALLBACKS.md`
      documentation file (no fallbacks recorded — both engines hold
      determinism on CUAD).
    - M3.4 (legal-pleading fixture + fidelity test): **DONE**. DOJ
      *US v. Google* post-trial brief copied to
      `tests/fixtures/legal-pleading/`; fidelity test asserts
      paragraph boundaries (483 paragraphs; median char_count 225),
      citation preservation (Sherman Act 13×, 253 F.3d 11×, PFOF
      cites in 138 paragraphs), and footnote linkage (18 paragraphs
      labeled `"footnote"`). Determinism gate extended to legal-
      pleading fixture; both engines hold byte-identical output.
  - **Phase M3 complete**: 266 tests pass; pyright strict, ruff, ruff-
    format, vulture all clean. Walltime ~6:40 (docling × 4 fidelity
    runs + docling × 3 determinism runs dominate).
  - M4 (CLI surface, 5 tasks) — **IN PROGRESS** (3/5 done).
    - M4.1 (Typer skeleton + INV-1 marker decorator): **DONE**.
      `[project.scripts]` registers `amanuensis = "amanuensis.cli:app"`;
      `@require_marker` enforces INV-1 with PEP 695 type-parameter
      syntax; exit code 2 on preflight failure.
    - M4.2 (init / ingest / status / atom CLI commands): **DONE**.
      Workspace bootstrap, M3-ingester wiring with engine selector,
      substrate summary, atom list/show/validate.
    - M4.3 (clarification / iteration / vocabulary / install-skills):
      **DONE**. Mutating commands acquire workspace flock; resolve
      writes paired resolved-PROV; iteration add writes issued-PROV;
      install-skills is M4.3 STUB level (detects harness CLIs via
      `shutil.which`; M7.6 finalises actual file installation).
    - M4.4 (INV-4 read-only / mutating gate): pending.
    - M4.5 (docs/cli-reference.md): pending.
  - M5-M11 — pending, downstream of M4.

## Upcoming phases

- [pending] Phase 2 (Map) — full brainstorm cycle (blocked on Phase 1 implementation)
- [pending] Phase 3 (Extend) — full brainstorm cycle (blocked on Phase 2 implementation)
- [pending] Phase 4 (Synthesize) — packaging into agent-usable product

## Standing tasks

- [pending] When second engagement starts: instantiate domain config for that engagement
  (vocabulary, scheme catalogue, probandum template). Phase 1's substrate schema
  designed to absorb this without rewrite.
