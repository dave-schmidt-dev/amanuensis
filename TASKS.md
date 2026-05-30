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
  - M3 (Ingestion) — **NEXT**. M3.1 (Docling integration via
    `amanuensis ingest`) is blocked by M2.3 — done. Will need to
    emit the `source-mirror/manifest.yaml` that lights up INV-10's
    deferred hash gate.
  - M4-M11 — pending, downstream of M3.

## Upcoming phases

- [pending] Phase 2 (Map) — full brainstorm cycle (blocked on Phase 1 implementation)
- [pending] Phase 3 (Extend) — full brainstorm cycle (blocked on Phase 2 implementation)
- [pending] Phase 4 (Synthesize) — packaging into agent-usable product

## Standing tasks

- [pending] When second engagement starts: instantiate domain config for that engagement
  (vocabulary, scheme catalogue, probandum template). Phase 1's substrate schema
  designed to absorb this without rewrite.
