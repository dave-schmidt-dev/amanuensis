# History

Meaningful changes to amanuensis, regardless of git. Bugs, remediation,
regression tests are recorded here per project convention.

Format: dated entries, newest first. Bug entries cite the area touched:
`[bug] <description> | files: path/a.py, path/b.ts`.

---

## 2026-05-29

- Project initialized. Conceptual foundation imported from a prior
  architecture-research session (2026-05-28) covering the five
  intellectual-tradition surveys (D1 Toulmin, D2 Wigmore, D3 Heuer/ACH,
  D4 argument mining, D5 production-extraction-systems) and the
  verified-deliverable workflow work. The distilled rationale lives in
  `docs/architecture.md` and `INVARIANTS.md`; the raw research artifacts
  are kept locally and gitignored.
- Foundational architectural frames resolved through brainstorming:
  agent-doer + human-on-the-loop; three-surface model (substrate +
  live web app + static export); harness-agnostic; multi-agent per
  level (Extractor + Auditor active in Phase 1 launch); single-doc per
  Phase 1 run; hierarchical aggregation with scale-anchored atoms.
- Scaffolded project skeleton: `amanuensis.yaml` marker, `HISTORY.md`,
  `TASKS.md`, `INVARIANTS.md`, `pyproject.toml` stub, `.gitignore`,
  `.pre-commit-config.yaml`, `.env.example`, `docs/`.
- No `README.md`, `CLAUDE.md`, `AGENTS.md`, or `GEMINI.md` at root —
  intentional, to keep the project harness-agnostic.
- Phase 1 plan written at warp tier under `~/.agent/prompts/plan.md`
  discipline. Draft → self-contrarian (6 PW + 1 WR inline fixes,
  1 WR deferred) → external dispatch (contrarian via codex/GPT 5.5,
  auditor via gemini/Gemini 3.1 Pro, constructive via claude/Claude
  Opus). 28 findings (10H/13M/5L); 22 accepted, 7 acknowledged, 0
  rejected/escalated. Major reshapes folded in: substrate layout
  reconciled with `amanuensis.yaml`; content-addressable ID hash cycle
  resolved (provenance_id volatile); per-distillation vocabulary
  snapshot (INV-10 added); read-only commands no longer write
  replay-log; dispatch driver write-isolation enforced; contested
  warrants auto-raise clarifications.
- Skeleton updates from review: dropped `substrate_root` and
  reframed supervision paths in `amanuensis.yaml`; added INV-10 to
  the charter; removed stale `replay-log/local-*/` from `.gitignore`;
  added pytailwindcss to pyproject deps comment. Plan + synthesis
  record live at `~/Documents/Projects/.plans/amanuensis/`.
- Fresh-eyes premortem (Kimi K2.5 via cursor-agent) returned 7
  failure modes + 4 systemic risks. 4 MITIGATE applied: vocabulary
  validated against three fixtures (pleading/contract/expert report);
  ingest determinism test (re-ingest x3, byte-identical assertion);
  Cytoscape stress fixture + view-by-section graceful degradation
  above 750 atoms / 2000 edges; web-form lock acquisition with 5s
  timeout. 7 ACKNOWLEDGE (mostly already-addressed by external
  review). 0 ESCALATE. Total warp-tier inputs across self-contrarian
  + external + premortem: 47; total fixes applied: 40.
- 56-task implementation breakdown at
  `~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29-tasks.md`
  across 11 milestone phases. Implementation runs in a separate
  session per plan.md ("planning and implementation are separate").
- Session pause point: plan + synthesis + tasks complete and
  user-approved; project skeleton committed (956e4d8); ready for a
  fresh implementation session.
- M1.2 — runtime + dev deps added (pydantic, typer, pyyaml, structlog;
  hypothesis to dev) | files: pyproject.toml, src/amanuensis/__init__.py.
  Created minimal package source so hatchling wheel target resolves.
  Lockfile reproducibility verified via `uv sync --frozen`; ruff clean.
- M1.3 — Atom + Relation + shared types schemas added. | files:
  src/amanuensis/schemas/{atom,relation,_shared,__init__}.py,
  tests/schemas/{conftest,test_atom,test_relation}.py. Pydantic v2
  strict mode + `extra="forbid"`; tz-aware datetimes enforced via
  `AwareDatetime` (rejects naive timestamps with `timezone_aware`
  error); `char_span` ordering validator. RoleAttribution and
  OperandRef designed per task's suggested minimal shapes (no
  deviation). 11 tests passing; pyright strict clean; ruff clean.
- M1.4 — Provenance, Clarification, IterationDirective, ReplayLogEntry, Vocabulary schemas added. | files: src/amanuensis/schemas/provenance.py, src/amanuensis/schemas/clarification.py, src/amanuensis/schemas/iteration.py, src/amanuensis/schemas/replay_log.py, src/amanuensis/schemas/vocabulary.py, src/amanuensis/schemas/__init__.py, tests/schemas/conftest.py, tests/schemas/test_provenance.py, tests/schemas/test_clarification.py, tests/schemas/test_iteration.py, tests/schemas/test_replay_log.py, tests/schemas/test_vocabulary.py
  Pydantic v2 strict + `extra="forbid"`; `AwareDatetime` across all tz-aware
  fields. ProvenanceRecord `entity_type` carries all 9 plan §4 values
  including the three `source-mirror-*` variants. Clarification's
  raised/resolved provenance pair and IterationDirective's issued/applied
  pair both implemented as required-on-create + optional-on-completion.
  ReplayLogEntry's `tokens_input`/`tokens_output`/`cost_estimate_cents`
  are optional (default `None`) so cost telemetry can land later without
  a schema-version bump. OperandTypeSchema designed per task's suggested
  minimal shape (no deviation); placed in `vocabulary.py` as a
  vocabulary-domain concept (not in `_shared.py`). 47 new + 11 prior = 58
  tests passing; pyright strict clean on schemas/; ruff clean.
- M1.5 — content-addressable hashing with canonical-form spec added.
  | files: src/amanuensis/schemas/_hashing.py,
  src/amanuensis/schemas/atom.py, src/amanuensis/schemas/relation.py,
  src/amanuensis/schemas/provenance.py,
  src/amanuensis/schemas/clarification.py,
  src/amanuensis/schemas/iteration.py,
  src/amanuensis/schemas/__init__.py,
  tests/schemas/test_content_addressing.py, docs/schema-reference.md
  `compute_id(model)` returns `"<kind-letter>-<16 hex chars>"` where the
  16 hex chars are the first 8 bytes of SHA-256 over the canonical form.
  Canonical form drops `id` universally plus each class's
  `_VOLATILE_FIELDS: ClassVar[frozenset[str]]`; recursively sorts mapping
  keys; encodes datetimes as ISO-8601 UTC microsecond + `Z` suffix;
  encodes floats via `repr()` (rejecting NaN/Inf); encodes as canonical
  JSON (`sort_keys=True`, `ensure_ascii=True`, `separators=(",", ":")`,
  `allow_nan=False`). Volatile sets per type: `Atom`/`Relation` →
  `{provenance_id}`; `ProvenanceRecord` → empty; `Clarification` →
  `{status, resolved_at, resolved_by, resolution,
  raised_provenance_id, resolved_provenance_id}`; `IterationDirective`
  → `{applied_at, applied_by, applied_outcome, issued_provenance_id,
  applied_provenance_id}` — so lifecycle completion does NOT change the
  artifact's id, matching the spec's intent that paired
  raised/resolved and issued/applied provenance records record the
  transition. 31 new + 58 prior = 89 tests passing. Hypothesis property
  test runs 500 examples in ~1.4s. pyright strict clean on `src/` and
  `tests/`; ruff clean.
- [bug] Python 3.14's `site.py` skips `.pth` files whose stem starts with
  `_`, which breaks hatchling's editable install (`_editable_impl_amanuensis.pth`).
  M1.4 tests passed only by exporting `PYTHONPATH=src/`; under default `uv run`
  the package was not importable. Pinned project to Python 3.12 via
  `.python-version` (gitignored, local) and tightened `requires-python` to
  `">=3.12,<3.14"` to document the upstream incompatibility until hatchling
  ships a non-`_`-prefixed editable shim. After rebuild, `import amanuensis`
  resolves natively, all 58 schema tests pass without PYTHONPATH overrides,
  `uv sync --frozen` is clean. | files: pyproject.toml, .python-version
- M1.6 — Substrate filesystem class with atomic writes + marker
  enforcement. | files: src/amanuensis/fs/__init__.py,
  src/amanuensis/fs/_errors.py, src/amanuensis/fs/_atomic.py,
  src/amanuensis/fs/_serialize.py, src/amanuensis/fs/substrate.py,
  tests/fs/__init__.py, tests/fs/conftest.py,
  tests/fs/test_marker_required.py, tests/fs/test_substrate_paths.py,
  tests/fs/test_atomic_writes.py
  `Substrate(workspace_root)` enforces INV-1 at construction (rejects
  missing marker, marker-as-directory, nonexistent workspace, file-instead-
  of-dir). Path resolvers (`atom_path`, `relation_path`, `provenance_path`,
  `clarification_path`, `iteration_path`) are pure path computation —
  no filesystem access. Mutating methods (`add_atom`, `add_relation`,
  `add_provenance`, `add_clarification`, `add_iteration`) assert
  `model.id == compute_id(model)` before writing and use atomic
  write-to-tmp-then-rename via `atomic_write_text` (POSIX `os.replace`).
  `get_atom` / `list_atoms` parse on read; `list_atoms` is a generator
  and skips writer `.tmp.*` leftovers. On-disk format: markdown with
  YAML frontmatter for narrative-bearing artifacts (Atom narrative,
  Clarification question, IterationDirective directive) and plain YAML
  for record-only artifacts (Relation, ProvenanceRecord). YAML
  round-trip for `char_span` coerces list→tuple before Pydantic strict
  validation (YAML has no tuple type).
  Decision: provenance filenames are keyed by the provenance record's
  own id (`provenance/<prov-id>.yaml`), not the `entity_id` per plan §5,
  because a Clarification's raised+resolved pair would otherwise
  collide on the same `entity_id`. Inverse lookup is via the
  `entity_id` field on the ProvenanceRecord. Documented in
  `Substrate` docstring and substrate.py module docstring.
  Decision: source_id and other id components are validated against
  `^[A-Za-z0-9_.-]+$` (rejects empty, `.`, `..`, slashes, backslashes,
  whitespace, NUL) to keep path discipline tight by default.
  Crash semantics tested via `multiprocessing.Process` (spawn context)
  that writes a `.tmp.*` sibling then exits abruptly via `os._exit(1)`
  before rename — used in place of self-SIGKILL for cross-platform
  reliability; the invariant under test ("canonical path never sees a
  torn write") holds under any abrupt exit, not just SIGKILL. 47 new
  + 89 prior = 136 tests passing; pyright strict clean on `src/` and
  `tests/`; ruff clean (check + format); vulture clean.
- M1.8 — workspace flock context manager with timeout. | files:
  src/amanuensis/fs/lock.py, src/amanuensis/fs/_errors.py,
  src/amanuensis/fs/__init__.py,
  tests/fs/test_concurrent_distill_blocked.py
  `acquire_workspace_lock(workspace_root, *, timeout=5.0)` is the
  serialization primitive named in plan §5: mutating CLI commands
  (`distill`, `dispatch`, clarification-resolve) and web POST endpoints
  hold an exclusive `fcntl.flock` on `<workspace>/.amanuensis-lock`
  for the duration of substrate writes; read-only commands DO NOT
  acquire the lock (they're already safe against the
  write-to-tmp-then-rename snapshots from M1.6). The lock module
  refuses to flock a directory that lacks the `amanuensis.yaml`
  marker — INV-1 defense in depth so a caller can't accidentally
  flock the wrong tree before any `Substrate` is constructed. The
  sentinel file is created at mode 0o644 if missing and is NOT
  deleted on release (concurrent waiters may have already opened
  it; unlinking would not affect their inherited flock and creates
  filesystem-cleanup noise). New `WorkspaceLockTimeout`
  (`SubstrateError` subclass) raised with a message naming the lock
  path and elapsed timeout for user-facing CLI/web error output.
  Polling strategy: non-blocking `flock(LOCK_EX|LOCK_NB)` against a
  `time.monotonic()` deadline with a 100ms poll interval, clamped to
  the remaining deadline so small `timeout` values stay precise;
  `timeout=0` performs a single attempt and fast-fails;
  `timeout<0` is rejected with `ValueError`. SIGKILL-recovery
  property exercised: a spawn child acquires the lock and calls
  `os._exit(1)` while holding it — Python's contextmanager finally
  block is bypassed, so only the POSIX kernel's fd-table teardown
  releases the flock; the parent's subsequent acquire succeeds.
  Decision: chose `fcntl.flock` over `fcntl.lockf` for clearer
  whole-file semantics (`flock` is per-open-file-description with
  predictable auto-release at fd close) — both are POSIX-advisory
  and equivalent for cooperative locking, but `flock` matches the
  plan §5 language ("workspace flock") and reads more obviously in
  the source. POSIX-only by design — Windows is out of scope for
  Phase 1. 9 new + 136 prior = 145 tests passing; pyright strict
  clean on `src/` and `tests/`; ruff clean (check + format);
  vulture clean.
- M1.7 — Replay-log seq counter with workspace-flock-serialized
  increments. | files: src/amanuensis/fs/replay_log.py,
  src/amanuensis/fs/__init__.py,
  tests/fs/test_replay_log_concurrent.py
  `ReplayLog(workspace_root, source_id)` is the per-distillation
  append-only activity log. `append(...)` assigns a monotonic, gap-free
  `seq` under the workspace flock from M1.8 and returns a finalized
  `ReplayLogEntry`; read paths (`read_seq`, `list_entries`,
  `get_entry`) are lock-free per plan §5. Layout matches plan §5:
  `distillations/<source-id>/replay-log/.next-seq` plus
  `<yyyy-mm-dd>/<padded-seq-12>.yaml` (zero-padded width-12 so
  lexicographic file sort within a day directory equals numeric seq
  order). Day subdirectory is derived from the entry's UTC date
  regardless of the timestamp's original timezone offset.
  Decision: counter is per-distillation (not per-workspace) per
  plan §5 layout, BUT the increment is serialized by the workspace-
  wide flock from M1.8 — two writers targeting different distillations
  still take the same lock. Cheap, correct, and matches the plan's
  "workspace flock" wording (the flock scope is workspace; the counter
  scope is distillation).
  Crash discipline (plan §5): the entry file is written via
  `atomic_write_text` BEFORE the counter is bumped. A crash between
  those two steps leaves the counter at N and the next writer
  overwrites the orphan entry at seq N, then bumps to N+1 — gap-free
  and duplicate-free on retry. Verified by an explicit orphan-entry
  test that fabricates the post-crash state and confirms the recovery
  writer's content lands at the orphan's path.
  Concurrent race test: 10 spawn-context children with a parent-side
  barrier (per-child ready-files + a single go-file) all attempt to
  append at roughly the same instant; assertions check
  set(seqs)==range(10), counter advances to 10, and each child's
  uniquely-named activity is present. The barrier matters — without
  it slow process startup could quietly serialize the appends and
  hide a real concurrency bug.
  Decision: cross-module access to package-private helpers
  (`_safe_dump`/`_safe_load` from `_serialize.py`,
  `_validate_id_component` from `substrate.py`) is annotated with
  per-import `# pyright: ignore[reportPrivateUsage]` rather than
  promoted to public names — the underscore convention still reads
  as "package-internal, not part of the published API" to a reviewer
  and the annotation makes the intent explicit. 18 new + 145 prior
  = 163 tests passing; pyright strict clean on `src/` and `tests/`;
  ruff clean (check + format); vulture clean.
- [bug] M1.7 replay-log left cross-day orphan files after SIGKILL near UTC midnight, breaking plan §5 "no duplicates". Fixed by scanning all day-dirs for the claimed seq inside the held workspace flock and unlinking stale matches before writing the new entry. | files: src/amanuensis/fs/replay_log.py, tests/fs/test_replay_log_concurrent.py
- M1.9 — first-draft `docs/architecture.md` and extended
  `docs/schema-reference.md`. | files: docs/architecture.md,
  docs/schema-reference.md
  New `architecture.md` (411 lines) covers purpose, substrate-as-truth
  (INV-8), the three-surface model (substrate / live web app / static
  export), the determinism boundary (INV-4) and the LLM-call wrapper's
  six-step recipe, the harness-aware `dispatch` module as the only
  harness-knowing layer, substrate layout summary, concurrency model
  (workspace flock + atomic writes + lock-free reads), module
  decomposition with public surfaces, and Phase 1 known limitations
  (single-doc, single-supervisor, POSIX-only, Python <3.14, replay-log
  cross-day window, vocabulary scope, role stubs, Cytoscape soft cap).
  Cross-links to `schema-reference.md`, `INVARIANTS.md`, `amanuensis.yaml`.
  `schema-reference.md` (593 lines, was 194) gains a per-model schema
  reference (all twelve Phase 1 types with required/optional/notes
  tables and on-disk-shape notes), a filesystem-layout section
  mirroring plan §5 with the `prov-id`-not-`entity-id` decision and
  the replay-log layout, and an "Invariants enforcement" section
  documenting INV-3 / INV-4 / INV-5 / INV-6 / INV-7 / INV-10 schema-
  layer enforcement points with planned gate-test references. The
  pre-existing "Content-addressable IDs" section moved after the new
  per-model reference (IDs are derived from the schemas; reads more
  naturally that way). The worked-example canonical JSON's `§`
  escape was preserved verbatim from the M1.5 commit. Docs-only
  change; no code touched.
- Phase 1 milestone M1 complete (HEAD `5023f4a`). Final gate: 164 tests
  pass; pyright strict, ruff, vulture all clean. Substrate foundation is
  shippable: 12 Pydantic schemas + content-addressable hashing
  (`compute_id`) + `Substrate` filesystem class with atomic writes +
  workspace `flock` context manager + per-distillation `ReplayLog`
  append-only writer with crash-resilient seq counter + first-draft
  architecture + schema reference. Two real bugs surfaced and remediated
  via two-stage review (Python 3.14 site.py editable-shim skip; cross-day
  orphan in replay-log recovery); both documented in the `[bug]` entries
  above with `files:` citations. Session pause point: ready for fresh
  session to start M2 (Validators + vocabulary, 5 tasks) per handoff.md.
- M2.1 — three vocabulary-design fixtures acquired for M2.2 predicate-
  vocabulary design. | files: tests/fixtures/vocabulary-design/SOURCES.md,
  tests/fixtures/vocabulary-design/us-v-google-plaintiffs-post-trial-brief-2024.pdf,
  tests/fixtures/vocabulary-design/cuad-verizon-abs-service-agreement-2020.pdf,
  tests/fixtures/vocabulary-design/ntsb-aar2101-calabasas-helicopter-crash-2021.pdf,
  .pre-commit-config.yaml
  Three publicly-available PDFs covering three distinct domains and three
  distinct postures: (1) DOJ Antitrust Division *Plaintiffs' Post-Trial Brief*
  in *US v. Google LLC* (1:20-cv-03010-APM, Doc. 837; PD under 17 U.S.C. § 105)
  — adversarial advocacy with full claim/evidence/qualifier/rebuttal density;
  (2) *Verizon Owner Trust 2020-A Transfer and Servicing Agreement* (SEC
  EDGAR EX-10.4; CC-BY-4.0 via the CUAD v1 dataset) — transactional drafting
  with extensive jurisdiction, dated-trigger, and obligation-modal language;
  (3) NTSB *Aircraft Accident Report AAR-21/01* on the Calabasas Sikorsky
  S-76B crash (PD under 17 U.S.C. § 105; NTSB is a federal agency) — neutral
  expert determination with an unusually rich certainty-modifier vein and
  formal probable-cause language. Each fixture has 2-3 representative PDF
  pages flagged in `SOURCES.md` for M2.2's manual annotation pass. SOURCES.md
  also documents three known limitations for M2.2 annotators: (a) the
  `denies_*`/`contests_*` predicate family is exercised richly only by
  fixture 1 (rebuttal monoculture — design that sub-vocabulary primarily
  off the DOJ brief and treat it as a known under-fit risk for Phase 2
  expansion fixtures to stress-test); (b) annotation page numbers are PDF
  page indices, not the printed page numbers stamped on the documents;
  (c) bracketed/redacted figures in the DOJ brief render as stray short
  tokens under `pdftotext` — intentional redactions, not extraction errors.
  Editorial review (APPROVE WITH NOTES) and spec-compliance review (9/9
  PASS) both performed via the implement.md two-stage subagent pattern;
  three editorial notes folded back into SOURCES.md before commit. One
  plumbing change: `check-added-large-files` in `.pre-commit-config.yaml`
  now excludes `^tests/fixtures/vocabulary-design/.*\.pdf$` so that
  intentionally-large fixture PDFs (the NTSB report is ~6 MB) clear the
  hook without raising the 2 MB cap globally — the cap stays protective
  for code and config files.
- M2.2 — generic predicate vocabulary v0.1 hand-designed against the
  three M2.1 fixtures. | files: vocabularies/generic/predicates.yaml,
  vocabularies/generic/COVERAGE.md, vocabularies/generic/TODO.md
  58 predicates (within the 30-60 target) covering claim types
  (`asserts_*`, `alleges_*`), data/evidence types (`cites_*`,
  `references_*`, `quotes_*`, `exhibits_data`), qualifier types
  (`applies_*`, `concludes_*`, `declares_*`, `designates_*`,
  `recommends_*`, `waives_*`), and rebuttal types (`denies_*`,
  `contests_*`, `disputes_*`, `rejects_*`). Each entry conforms to
  `src/amanuensis/schemas/vocabulary.py` (strict Pydantic v2,
  extra=forbid) with `predicate` + `aliases` + `operand_types` +
  `qualifier_required` + `notes`. Manual annotation pass on the 9
  M2.1 fixture pages (Google brief 8/60/75, Verizon contract 8/12/49,
  NTSB report 15/55/66) yielded 100% coverage per fixture (32/32,
  33/33, 30/30); editorial reviewer spot-checked one page per
  fixture and confirmed the assignments are honest though the
  denominator is conservative (minor restatements covered by the
  same predicate as a neighbor were not separately enumerated — a
  COVERAGE.md note now documents this counting convention). Phase 5
  workflow followed end-to-end: implementer (general-purpose, full
  research + design + annotation) → spec-compliance (haiku, 13/13
  PASS, Pydantic schema gate clears) → editorial quality (default,
  APPROVE WITH NOTES, 10 small issues across naming/operand-types/
  consistency) → fix subagent (9 surgical edits across predicates.yaml
  + COVERAGE.md + TODO.md; schema re-validated) → orchestrator commit.
  Vendored under `vocabularies/generic/` rather than installed at
  `~/.amanuensis/vocabularies/generic`; bootstrap-path comment at the
  top of `predicates.yaml` documents the `cp -R` or
  `amanuensis.yaml` override paths. INV-10 makes the global registry
  a starting template (not a runtime dependency), so the location of
  the source-of-truth copy is editorial. Known limitations carrying
  forward into M2.3+: (a) the rebuttal predicate family (8 entries)
  is grounded entirely in one page of one fixture (Google brief
  p.75), inheriting the rebuttal-monoculture risk first disclosed
  in M2.1's SOURCES.md — Phase 2 expansion fixtures (an answer brief
  or opposition pleading) must stress-test it; (b) TODO.md now
  explicitly enumerates blank predicate space for tort liability,
  criminal charges, environmental enforcement, damages/remedy/quantum,
  fraud-with-scienter, and discovery/metadata — Phase 2 expansion
  must add fixtures targeting each blank category before vocabulary
  v0.2 lands; (c) `asserts_regulatory_classification` currently does
  dual duty (classifying a subject under a rule AND stating a
  general regulatory rule) — flagged in both the YAML notes and
  TODO.md for a future `asserts_regulatory_rule` sibling split.
- [bug] M1.7 concurrent-replay-log test seeded entries with `datetime.now(UTC)` while orphan + recovery used a hardcoded `datetime(2026, 5, 29, ...)`. Past UTC midnight the seeded entries landed in a different day-dir than the orphan, scrambling the lex-ordered list returned by `list_entries` and failing the test. Fixed by pinning the 5 seed timestamps to the same fixed 2026-05-29 datetime so all 7 entries (5 seeds + orphan + recovery) share one day-dir. Production code untouched (`src/amanuensis/fs/replay_log.py` was always correct; only the test was wrong). Cross-day orphan recovery remains covered by the dedicated `test_orphan_in_different_day_directory_is_removed_by_recovery` in the same file. Surfaced by M2.3's full-suite gate check. | files: tests/fs/test_replay_log_concurrent.py
- M2.3 — vocabulary registry loader + per-distillation snapshot
  mechanism. | files: src/amanuensis/vocabulary/__init__.py,
  src/amanuensis/vocabulary/registry.py,
  src/amanuensis/schemas/vocabulary.py,
  src/amanuensis/fs/substrate.py, src/amanuensis/fs/_errors.py,
  src/amanuensis/fs/__init__.py,
  tests/vocabulary/__init__.py,
  tests/vocabulary/test_generic_predicates.py,
  tests/vocabulary/test_alias_resolution.py,
  tests/vocabulary/test_snapshot_on_ingest.py
  New `vocabulary` package with `load_vocabulary(path)` reading the
  M2.2 YAML, validating against the strict-Pydantic Vocabulary schema,
  detecting duplicate predicates, within-entry alias duplication, and
  cross-entry alias collisions (alias=other-canonical OR alias=other-alias).
  `Vocabulary.has_predicate(name)` and `Vocabulary.resolve(name)` answer
  predicate-or-alias lookups in O(1) via a `cached_property` table —
  these are the building blocks M2.4 validators and M2.5's INV-5 gate
  test will call. New typed exception `VocabularyLoadError` defined in
  `vocabulary/registry.py`. Substrate gains `vocabulary_snapshot_path`,
  `snapshot_vocabulary(source_id, vocabulary)`, and
  `get_vocabulary_snapshot(source_id)`. Snapshot writes go through
  `atomic_write_text`; write-once semantics use semantic equality
  (`Vocabulary.model_dump() == ...`) rather than byte equality so a
  future PyYAML version drift or schema additive default doesn't
  false-trip the conflict guard. Two new typed exceptions in
  `fs/_errors.py`: `SubstrateSnapshotConflict` (write-time pin
  violation — existing snapshot has different content) and
  `SubstrateSnapshotCorrupt` (read-time integrity failure — snapshot
  fails to deserialize). Both inherit from `SubstrateError`. Source-
  mirror manifest hash-recording is deferred to M3.1 (the manifest
  file itself is M3.1's deliverable); a `TODO(M3.1)` seam is left in
  the `snapshot_vocabulary` docstring. Implements INV-10 enforcement:
  validators read the snapshot, never the global registry; the global
  is a starting template. Phase 5 workflow followed: implementer
  (general-purpose, full surface) → spec-compliance (haiku, all
  checklist items PASS, 36/36 new tests PASS, 200/200 overall) →
  code quality (default, APPROVE WITH NOTES, 10 issues across
  semantic-vs-byte conflict comparison / typed exception coverage /
  within-entry alias dedup / byte-stability test rigor / minor
  documentation gaps) → fix subagent (4 substantive fixes: semantic
  equality for snapshot conflict, typed exceptions for read failures
  including the new `SubstrateSnapshotCorrupt`, per-entry alias
  dedup, real byte-stability assertion in the test; remaining 6
  issues deferred to a future polish sweep) → orchestrator commit.
  Final gate: 200/200 tests pass, pyright strict + ruff + ruff-format
  + vulture all clean. The pre-existing M1.7 cross-day-flake bug
  exposed by the gate check was fixed in a separate `fix:` commit
  (912c3aa) before this one.
- Repository made public on GitHub at https://github.com/dave-schmidt-dev/amanuensis.
  Pre-publish hygiene: untracked + gitignored `research-transcripts/`,
  `synthesis/`, and `MANIFEST.md` (client-matter context kept locally);
  changed author email in `pyproject.toml` to `dave@zdelta.dev` for
  consistency with git commit attribution and to use the consulting
  email for open-source attribution; added MIT `LICENSE` at root. After
  the initial push, a full-history audit found that the deleted files
  still lived in past commit objects (text-readable), so all 25 commits
  were squashed into a single `feat: initial public release` orphan
  commit (`4e2e40f`) and force-pushed to `main`. The squash preserves
  the milestone-by-milestone narrative in this file while giving the
  public repo a clean baseline. Pre-commit + pre-push hooks installed
  via `uv run pre-commit install --hook-type pre-commit --hook-type
  pre-push`; tool versions aligned with the project's actual
  installed versions (pre-commit-hooks v6.0.0, ruff v0.15.15, vulture
  v2.16). Fixed a latent YAML-syntax bug in the existing
  invariant-marker pre-commit hooks (unquoted `colon-space` sequences
  in bash-c entries were being parsed as nested mappings).
- M2.4 — seven canonical validators. | files:
  src/amanuensis/validators/__init__.py,
  src/amanuensis/validators/_result.py,
  src/amanuensis/validators/schema_check.py,
  src/amanuensis/validators/citation_ledger.py,
  src/amanuensis/validators/universe_check.py,
  src/amanuensis/validators/scale_anchor.py,
  src/amanuensis/validators/closed_vocabulary.py,
  src/amanuensis/validators/provenance_completeness.py,
  src/amanuensis/validators/lineage_closure.py,
  src/amanuensis/fs/substrate.py,
  tests/validators/__init__.py,
  tests/validators/_types.py,
  tests/validators/conftest.py,
  tests/validators/test_schema_check.py,
  tests/validators/test_citation_ledger.py,
  tests/validators/test_universe_check.py,
  tests/validators/test_scale_anchor.py,
  tests/validators/test_closed_vocabulary.py,
  tests/validators/test_provenance_completeness.py,
  tests/validators/test_lineage_closure.py,
  tests/fs/test_provenance_io.py
  Seven canonical validators as pure functions in
  `src/amanuensis/validators/`, each returning a typed
  `ValidationResult` (`passed` + `validator` name + human-readable
  `reason` + optional `subject_id`). Validators: `schema_check`
  (Pydantic model_validate routing); `citation_ledger` (INV-7 —
  `source_id` non-empty, `section_path` non-empty list of non-empty
  strings, `paragraph_index ≥ 0`, `char_span` start non-negative
  AND start < end); `universe_check` (atom.source_id ∈ supplied
  known-source set); `scale_anchor` (INV-6 — named restatement
  with post-construction-mutation defense); `closed_vocabulary`
  (INV-5 — delegates to `Vocabulary.has_predicate`, alias-aware,
  caller supplies snapshot per INV-10); `provenance_completeness`
  (INV-3 — atom.provenance_id non-empty + file present + parseable
  YAML + valid ProvenanceRecord schema + entity_id matches atom.id;
  catches `SubstrateNotFound`, `SubstrateInvalidId`,
  `yaml.YAMLError`, and `pydantic.ValidationError` to keep the
  validator total over its type); `lineage_closure` (relation's
  `from_atom_id` and `to_atom_id` resolve to atoms on substrate).
  `Substrate.get_provenance(source_id, prov_id)` added (mirrors
  `get_atom`/`get_relation` pattern) to support `provenance_completeness`.
  Workflow: implementer → spec-compliance (haiku, all checks PASS)
  → code quality (default, APPROVE WITH NOTES — 8 issues, 1 medium-
  severity bug: `provenance_completeness` was crashing on corrupt
  prov YAML instead of returning fail) → fix subagent (3 substantive
  fixes: corrupt-YAML/schema-violation exception handling,
  defense-in-depth `start < end` check in `citation_ledger` to
  match `scale_anchor`'s posture, branch-coverage tests for
  paragraph_index < 0 / negative char_span / inverted char_span)
  → orchestrator. Final gate: 238/238 tests pass; pyright strict
  + ruff + ruff-format + vulture all clean. 38 new tests.
- M2.5 — invariant gate tests for INV-3, INV-5, INV-10. | files:
  tests/invariants/__init__.py, tests/invariants/_types.py,
  tests/invariants/conftest.py,
  tests/invariants/test_provenance_completeness.py,
  tests/invariants/test_closed_vocabulary.py,
  tests/invariants/test_vocabulary_pinned.py, INVARIANTS.md
  Three gate-test modules under `tests/invariants/`, all marked
  `@pytest.mark.invariants` so `uv run pytest -m invariants` selects
  exactly these. Each module quotes the INVARIANTS.md entry it
  certifies in its docstring. **INV-3** (3 tests): walks the
  substrate's atoms via `list_atoms`, runs `provenance_completeness`
  on each; positive case (5 atoms + matching PROV records all pass);
  negative cases (missing provenance file; provenance record's
  entity_id mismatches atom.id). Scoped to atoms in M2.5 with
  `TODO(M3-M9)` to extend to relations / clarifications / iterations
  once those substrate paths come online. **INV-5** (4 tests):
  canonical predicate passes; alias passes (alias-aware lookup
  through `Vocabulary.has_predicate`); unknown predicate fails with
  reason naming the predicate AND the vocabulary; snapshot-vs-global
  distinction (a hand-rolled 3-entry subset Vocabulary is snapshotted;
  an atom whose predicate is in the global registry but NOT in the
  snapshot is correctly rejected — certifying INV-10's "validators
  read snapshot, not global" property). **INV-10** (4 tests): every
  distillation has a snapshot file; snapshot for source A is
  independent of subsequent registry edits or of snapshots written
  for source B; no-snapshot raises `SubstrateNotFound`;
  corrupt-snapshot raises `SubstrateSnapshotCorrupt` (typed-
  exception distinction matters because the remediation paths
  diverge — auditor surface). The "snapshot hash matches manifest"
  half of INV-10's charter is deferred to M3.1 (manifest doesn't
  exist yet); `TODO(M3.1)` seam in the test module. INVARIANTS.md
  updated: INV-3, INV-5, INV-10 graduated from "Gate test (planned)"
  to "Gate test (active)" with scope notes describing what each
  gate covers and what is deferred. Workflow: implementer
  (general-purpose) → spec-compliance (haiku, full PASS) →
  code quality (default, APPROVE WITH NOTES — 7 issues, all
  minor/nit; one worth folding in: corrupt-snapshot test for
  INV-10) → orchestrator added the corrupt-snapshot test inline.
  Final gate: 249/249 tests pass (238 + 11 new — 10 from the
  implementer + 1 orchestrator-added); pyright strict + ruff +
  ruff-format + vulture all clean. **M2 (Validators + vocabulary,
  5 tasks) COMPLETE.**

## 2026-05-30

- [bug] Editable install silently disappeared between sessions: `uv run pytest`
  failed with `ModuleNotFoundError: No module named 'amanuensis'` despite
  `uv sync` reporting the package installed. Root cause is a CPython 3.12.13
  regression on macOS: 3.12.13 backported a `site.py` change that skips `.pth`
  files carrying `UF_HIDDEN`, and pytest's own Python startup ends up marking
  the editable-install `.pth` as hidden between invocations — so a standalone
  "unhide" hook before pytest does not stick (something between hooks re-hides
  the file). The one-line manual repair is `find .venv -name "*.pth" -exec
  chflags nohidden {} +`. Permanent fix: inline the chflags sweep INSIDE each
  Python-invoking pre-push hook entry (one `bash -c` that runs `chflags
  nohidden` immediately before `uv run pyright …` and again immediately before
  `uv run pytest …`), so no other process can re-hide in the gap. Pre-push
  hooks now self-heal on every push. Linux runners skip silently (chflags is
  macOS-only; `2>/dev/null || true` keeps the entry portable). Pin to Python
  3.12.12 or lower if you need to dodge the site.py change entirely. | files:
  .pre-commit-config.yaml
- Session-end handoff: refreshed `handoff.md` to the canonical
  `~/.agent/prompts/handoff.md` structure (active plan + current task +
  critical files + 2-3 sentence strategic momentum + active subagents).
  M2 fully shipped; next session entry point is M3.1 (Docling ingestion).
  | files: handoff.md
- M3.1 — Docling source-mirror ingest landed. Added `docling` runtime
  dependency (uv-resolved, no version pin); new `amanuensis.ingest`
  package with the library-only `ingest_pdf(...)` function (no CLI
  subcommand yet); new `SourceMirrorManifest` + `ParagraphEntry`
  schemas under `amanuensis.schemas.source_mirror`, registered as the
  sixth content-addressable type (kind prefix `m-`). The ingest
  pipeline pins the vocabulary (INV-10), hashes the PDF bytes, runs
  Docling end-to-end (CPU accelerator forced — macOS MPS hits a
  float64 incompatibility in rt-detr layout), walks `iterate_items()`
  while maintaining a heading stack keyed by `SectionHeaderItem.level`,
  writes one `.md` per paragraph with YAML-frontmatter + body under
  `distillations/<source-id>/source-mirror/paragraphs/`, persists one
  `source-mirror-document` PROV record (entity_id derived from
  `source_sha256` + `activity_ended_at` to break the manifest.id ↔
  prov.id content-id cycle), and writes the canonical YAML manifest at
  `source-mirror/manifest.yaml`. New `Substrate` resolvers:
  `source_mirror_root`, `paragraph_path`, `manifest_path`; new writer
  `Substrate.add_source_mirror_manifest`. New paragraph-md serializer
  helpers (`serialize_paragraph_md` / `parse_paragraph_md`) following
  the existing per-artifact serializer pattern. Test fixture:
  3-page extract of the CUAD Verizon contract via `pypdfium2`
  (transitive dep — no new dependency for fixture creation);
  `tests/fixtures/ingest/SOURCES.md` documents the extraction recipe
  and CC-BY-4.0 license inheritance. INV-10 graduates from "active
  (partial)" to fully "active" — new gate test
  `test_inv10_manifest_records_snapshot_hash` runs `ingest_pdf` and
  asserts `manifest.vocabulary_snapshot_sha256 ==
  sha256(snapshot_bytes).hexdigest()`. | files: pyproject.toml,
  src/amanuensis/schemas/source_mirror.py,
  src/amanuensis/schemas/_hashing.py,
  src/amanuensis/schemas/__init__.py,
  src/amanuensis/fs/substrate.py, src/amanuensis/fs/_serialize.py,
  src/amanuensis/ingest/__init__.py,
  src/amanuensis/ingest/docling_ingester.py,
  tests/fixtures/ingest/simple-contract.pdf,
  tests/fixtures/ingest/SOURCES.md,
  tests/ingest/__init__.py, tests/ingest/test_simple_pdf.py,
  tests/invariants/test_vocabulary_pinned.py, INVARIANTS.md
- M3.1 code-review fixes: heading-stack underflow padding for
  documents opening at non-H1 depth (preserves INV-7 depth signal);
  whitespace-only SECTION_HEADER / paragraph text now silently skipped
  rather than pushed onto the stack or emitted as a zero-content
  paragraph; new typed exception `SourceMirrorExists` (symmetric with
  INV-10's `SubstrateSnapshotConflict`) guards `ingest_pdf` against
  re-ingest into an existing distillation (orphan-paragraph-file risk
  + mixed-version body risk); docstring's "macOS / MPS note" rewritten
  as "CPU accelerator (unconditional)" to acknowledge the dual
  motivation (MPS float64 bug avoidance + cross-platform determinism);
  `_docling_version()` captured once instead of called twice in
  manifest construction; collision-sweep test extended to cover the
  `m-` prefix (six kinds, all prefixes distinct). New test
  `test_reingest_refuses_when_manifest_exists` asserts the guard fires
  and the first-ingest manifest is unchanged on disk. | files:
  src/amanuensis/ingest/docling_ingester.py,
  src/amanuensis/fs/_errors.py, src/amanuensis/fs/__init__.py,
  tests/ingest/test_simple_pdf.py,
  tests/schemas/test_content_addressing.py
- [followup] M3.1 review surfaced field-validator gap (sha256 / non-negative
  integer ranges absent on SourceMirrorManifest — matches pre-existing
  project convention across all schemas); track for a cross-schema
  validator pass in a future milestone. Also: no paragraph-body
  re-verification path yet; hand-edits to paragraph .md files diverge
  silently from manifest hashes — document in INVARIANTS.md INV-8 as a
  known escape hatch when a future milestone introduces the verifier.
  | files: HISTORY.md
- M3.2 — pdfplumber fallback ingester landed. New
  `ingest_pdf_pdfplumber(...)` mirrors `ingest_pdf` step-for-step but
  emits `ingest_engine="pdfplumber"` and `activity="pdfplumber-ingest"`.
  pdfplumber moved from a stale comment in `pyproject.toml` into the
  active dependencies list. Paragraph splitting heuristic: per page
  `extract_text()` split on `\n\s*\n` blank-line boundaries; each
  non-empty stripped chunk becomes one paragraph. Documented trade-off:
  `section_path=[]` and `label="text"` uniformly (no heading hierarchy
  available from pdfplumber). The derived `entity_id` shape is shared
  with the docling pipeline — engine is a manifest property, not an
  identity component, so the source-mirror document's PROV identity is
  engine-agnostic. Same write-once `SourceMirrorExists` guard. New
  smoke test mirrors the docling smoke test against the same 3-page
  CUAD fixture (4 tests). | files: pyproject.toml,
  src/amanuensis/ingest/__init__.py,
  src/amanuensis/ingest/pdfplumber_ingester.py,
  tests/ingest/test_pdfplumber_fallback.py
- M3.3 — re-ingest determinism test (PM-3 mitigation) landed. New
  `tests/ingest/test_ingest_determinism.py` parametrizes over both
  ingest engines; each parametrize case runs the engine three times
  against the same CUAD fixture into three independent tmp_path
  workspaces and asserts byte-identical output across runs on every
  field EXCEPT the documented non-deterministic set (`activity_*`
  timestamps and the ids that derive from them — `prov.id`,
  `prov.entity_id`, `manifest.id`). The on-disk paragraph `.md` files
  are also compared as full bytes (frontmatter + body) so a future
  serializer drift would be caught. Sanity-asserts that timestamps DO
  differ across runs (so the test isn't accidentally caching). Also
  added `tests/fixtures/INGEST_FALLBACKS.md` — a structured
  documentation file (no parser, no tests) for logging fixtures that
  prove non-deterministic under Docling and need the pdfplumber
  fallback. Both engines hold determinism on CUAD; INGEST_FALLBACKS.md
  starts with `(none yet)`. | files:
  tests/ingest/test_ingest_determinism.py,
  tests/fixtures/INGEST_FALLBACKS.md
- M3.4 — legal-pleading fixture + fidelity test landed. The DOJ
  Antitrust Division's *Plaintiffs' Post-Trial Brief* in *United
  States v. Google LLC* (Case 1:20-cv-03010-APM, Doc. 837) was copied
  from `tests/fixtures/vocabulary-design/` (where it had been vetted
  for M2.1) to `tests/fixtures/legal-pleading/` to clarify its role
  as the M3.4 fidelity fixture. Git deduplicates the blob by content
  SHA so the copy is effectively free at the repo level; the
  fixture's `SOURCES.md` cross-references the shared blob and
  re-cites the 17 USC §105 public-domain basis. New
  `tests/ingest/test_legal_pdf_fidelity.py` runs `ingest_pdf` over
  the brief and asserts three fidelity properties: (1) paragraph
  boundaries (483 non-empty paragraphs observed against `>= 50`
  threshold; median `char_count` 225 against `> 100` threshold),
  (2) citation references preserved (Sherman Act 13 occurrences;
  Microsoft `253 F.3d` 11 occurrences; PFOF cites in 138 paragraphs
  via regex `r"PFOF\s*¶?\s*\d+"`), (3) footnote linkage preserved
  (18 paragraphs labeled `"footnote"` against `>= 1` threshold).
  Every fidelity threshold landed as the plan specified — no
  adaptation needed. The determinism test was extended to also
  parametrize over the legal-pleading fixture; both engines hold
  byte-identical output across three docling runs (~150 s) and
  three pdfplumber runs (sub-second), so no fallback recording
  required. | files:
  tests/fixtures/legal-pleading/us-v-google-plaintiffs-post-trial-brief-2024.pdf,
  tests/fixtures/legal-pleading/SOURCES.md,
  tests/ingest/test_legal_pdf_fidelity.py,
  tests/ingest/test_ingest_determinism.py
- Phase M3 (Ingestion) complete: M3.1+M3.2+M3.3+M3.4 all shipped.
  266 tests pass; pyright strict, ruff (check + format), vulture all
  clean. Full pytest walltime ~6:40 (dominated by the four 50 s
  docling runs in the fidelity test and the three runs each in the
  determinism gate). Next session entry point is M4.1 (Typer CLI
  skeleton + INV-1 marker decorator) — the surface area that exposes
  the M3 library functions to supervisors via `amanuensis ingest`.
- M4.1+M4.2+M4.3 — full CLI surface landed. `amanuensis` registered
  in `[project.scripts]` (script entry resolves to the Typer root app
  at `amanuensis.cli:app`). `@require_marker` decorator (per PEP 695
  type-parameter syntax) enforces INV-1 on every command except
  `init`; failure emits a clear stderr error and exits with code 2
  (preflight failure, distinct from command-body failures). Mutating
  commands acquire the workspace flock; read-only commands do not.
  Twelve commands ship in this batch: `init`, `ingest`, `status`,
  `install-skills` (top-level); `atom {list,show,validate}`,
  `clarification {list,resolve}`, `iteration {list,add}`,
  `vocabulary {list,show,snapshot}` (subcommand groups). `init`
  bootstraps the workspace (marker + `docs/` + sensible `.gitignore`);
  `ingest` wires the M3 ingester(s) with engine selector; `status`
  prints workspace summary with `--json` option; `atom` exposes the
  M2 validators via `atom validate`; `clarification resolve` writes
  the paired resolved-PROV record; `iteration add` writes the issued
  PROV + the directive; `vocabulary snapshot` echoes the INV-10 pin.
  `install-skills` is intentionally STUB-LEVEL (M4.3): detects
  installed harness CLIs via `shutil.which` and emits placeholder
  install messages; M7.6 finalises the actual file installation
  once M7.1 ships the skill files. Pyright strict mode globally
  downgrades `reportUnknownMemberType` + `reportUnknownVariableType`
  to "none" — Typer's overloaded `Argument`/`Option` signatures
  collapse to `Any` in strict mode and the rule is unusable
  per-call; trade-off documented inline in `pyproject.toml`. All
  4 Click-8.4-incompatible (str, Enum) classes migrated to StrEnum
  per `UP042`. 48 new CLI tests (250 + 48 + 16 prior fixed = 314
  pass; pyright strict + ruff + ruff-format + vulture all clean).
  | files: pyproject.toml, src/amanuensis/cli/__init__.py,
  src/amanuensis/cli/_marker.py, src/amanuensis/cli/_common.py,
  src/amanuensis/cli/init.py, src/amanuensis/cli/ingest.py,
  src/amanuensis/cli/status.py, src/amanuensis/cli/atom.py,
  src/amanuensis/cli/clarification.py, src/amanuensis/cli/iteration.py,
  src/amanuensis/cli/vocabulary.py, src/amanuensis/cli/install_skills.py,
  tests/cli/__init__.py, tests/cli/conftest.py,
  tests/cli/test_marker_required.py, tests/cli/test_init.py,
  tests/cli/test_ingest_cli.py, tests/cli/test_status.py,
  tests/cli/test_atom_cli.py, tests/cli/test_clarification.py,
  tests/cli/test_iteration.py, tests/cli/test_vocabulary.py,
  tests/cli/test_install_skills.py
- [bug] Click 8.4 removed the `CliRunner(mix_stderr=False)` kwarg;
  five CLI test files used it and collection failed with
  `TypeError`. Replaced with default `CliRunner()` (stderr now merges
  into `result.output`) and rewired assertions to read `result.output`
  instead of `result.stderr`. | files: tests/cli/test_init.py,
  tests/cli/test_ingest_cli.py, tests/cli/test_status.py,
  tests/cli/test_atom_cli.py, tests/cli/test_marker_required.py
- M4.4+M4.5 — INV-4 read-only-side gate test + docs/cli-reference.md.
  `tests/invariants/test_determinism_boundary.py` exercises every
  read-only CLI command (11 cases: status, status --json, atom
  list/show/validate, clarification list, iteration list, vocabulary
  list/show/snapshot, install-skills) and asserts (a) substrate is
  byte-identical before/after, (b) two consecutive runs produce
  identical stdout, (c) substrate is still byte-identical after the
  second run. Marked `@pytest.mark.invariants`. The mutating-side gate
  (init/ingest/clarification resolve/iteration add) is explicitly
  deferred to M5.3 once the LLM-boundary mechanics (M5.1/M5.2) land
  — TODO(M5.3) comment in the module docstring names each mutating
  command and its specific idempotency contract.
  Fixture sharing: `tests/invariants/conftest.py` re-exports four
  fixtures from `tests/cli/conftest.py` (cli_workspace, cli_substrate,
  planted_atom, planted_clarification) — the conventional pytest
  mechanism for sharing across directories without duplication
  (pytest_plugins= conflicted with already-registered names).
  `docs/cli-reference.md` documents every command with classification
  (read-only / mutating), idempotency semantics, notable flags,
  one example invocation, exit-code table, and a Known Limitations
  section covering install-skills' M4.3 stub status, the absent
  distill/dispatch/export commands, the absent web UI, and the M5.3
  mutating-side gate. 325 tests pass (314 + 11); pytest -m invariants
  -q reports 23 passed. Pyright + ruff + ruff-format + vulture all
  clean. | files: tests/invariants/test_determinism_boundary.py,
  tests/invariants/conftest.py, docs/cli-reference.md
- Phase M4 (CLI surface) complete: M4.1-M4.5 all shipped. 325 tests
  pass; pyright strict + ruff + ruff-format + vulture all clean.
  Next session entry point is M5.1 (cached LLM call wrapper).
- M5.1+M5.2+M5.3 — LLM-call boundary mechanics landed in one batch.
  New `amanuensis.llm` package:
  - `cached_call(...)` (M5.1) computes a canonical `inputs_hash` over
    `(role, prompt, inputs, model_id)` using the same canonical-form
    pattern as `schemas/_hashing.py`. Cache hit copies
    `cache/<hash>.yaml` to `dispatch/outputs/<role>-<hash>/output.yaml`;
    cache miss writes a `DispatchQueueEntry` at
    `dispatch/queue/<role>-<hash>.yaml` for the M6 dispatch driver to
    pick up. Cache file mode 0600 per CV-15 (sensitive prompt/output
    material); queue mode 0644 (short-lived coordination).
  - `DispatchQueueEntry` (M5.1 → re-used by M6.1) is a Pydantic v2
    strict + `extra="forbid"` model — `role`, `prompt`, `inputs`,
    `model_id`, `inputs_hash`, `enqueued_at: AwareDatetime`,
    `schema_version`.
  - `append_replay_entry(...)` (M5.2) is a thin facade over the M1.7
    `ReplayLog.append` infrastructure — takes a pre-built
    `ReplayLogEntry`, acquires the workspace flock, increments the
    seq counter, writes to `replay-log/<date>/seq-NNNN.yaml`. Caller's
    `seq` is overwritten by the appender (the appender owns seq
    allocation).
  - `write_llm_provenance(...)` (M5.2) writes a PROV-O record with
    `was_attributed_to.identifier = model_id` and
    `was_attributed_to.kind = "llm"`. Closed entity-type set
    (`{"atom", "relation", "clarification-raised"}`) and role set
    (`{"extractor", "auditor", "contrarian", "constructive",
    "premortem"}`) reject misuse (e.g. `"iteration-issued"` is human-
    attributed; `"human_supervisor"` role on an LLM-call PROV record
    is a bug).
  - **Design call:** `inputs_hash` is NOT a new field on
    `ProvenanceRecord` (the schema's `_VOLATILE_FIELDS` is empty —
    every field is identity content, and adding one would churn every
    existing content-addressable PROV id). Instead the cross-reference
    PROV ↔ replay-log ↔ cache lives in the replay-log entry's
    `inputs_hash` field. PROV is locatable from replay-log by
    `(activity, actor, timestamp)`.
  - **M5.3 INV-4 mutating-side gate** — three new
    `@pytest.mark.invariants` cases under
    `tests/invariants/test_determinism_boundary.py`'s new "Mutating
    side (M5.3)" section: (a) every LLM-call boundary writes a
    replay-log entry AND a PROV-O record AND a cache entry,
    (b) cache-hit replays produce byte-identical outputs,
    (c) `inputs_hash` is deterministic across re-invocations. The
    M4.4 TODO(M5.3) block is reframed to note M5.3 has landed.
  - 16 new tests (6 cache + 7 replay/PROV + 3 mutating-side gate);
    341 total pass (325 + 16); 26 invariants pass (23 + 3). Pyright
    strict + ruff + ruff-format + vulture all clean. | files:
    src/amanuensis/llm/__init__.py, src/amanuensis/llm/cached_call.py,
    src/amanuensis/llm/queue.py, src/amanuensis/llm/replay_log.py,
    src/amanuensis/llm/provenance.py, tests/llm/__init__.py,
    tests/llm/conftest.py, tests/llm/test_cache.py,
    tests/llm/test_replay_and_prov.py,
    tests/invariants/test_determinism_boundary.py
- M6.1+M6.2+M6.3+M6.4+M6.5 — dispatch driver shipped in one batch.
  New `amanuensis.dispatch` package:
  - `dispatch/queue.py` (M6.1): enqueue/dequeue/list_queue/
    move_to_failures/move_to_outputs with atomic-rename semantics
    (`os.replace`); failures get a sibling `.failure.yaml` with
    `reason` + `detail` + `failed_at_iso`.
  - `dispatch/driver.py` (M6.2): `detect_harnesses()` via shutil.which
    for {claude, codex, cursor-agent, gemini}; `invoke_role(...)` runs
    the harness subprocess with `stdin=DEVNULL`, `text=True`,
    `capture_output=True`, `timeout=…`; `InvokeResult` carries
    stdout/stderr/exit/walltime/timed_out/parse_error/output_payload.
    Successful stdout is parsed as YAML/JSON; parse failure → typed
    `parse_error` field, not a re-raise. Test-only harness override
    via module-level `TEST_HARNESS_OVERRIDES` + `harness_binary_path=`
    kwarg on `invoke_role` (clean injection seam for M6.4's echo-role
    fixture; production passes `None`).
  - `dispatch/isolation.py` (M6.3 / CV-5): snapshot the workspace
    mtime tree before role invocation; re-walk after; reject any
    file added/modified outside the allowed `dispatch/outputs/…/`
    subtree. Skips `.venv/`, `__pycache__/`, `.git/`. Driver routes
    violations to `dispatch/failures/` with
    `reason="write-isolation-violation"`.
  - Echo-role fixture (M6.4 / CV-7): inline shell-script fixtures
    written outside the dispatch workspace (so the isolation check
    doesn't flag the script's own marker files). Tests cover the
    happy path, cache-hit no-subprocess, and malformed-stdout
    routing to `failures/`.
  - `amanuensis dispatch` CLI (M6.5) with `--check` (prints JSON
    harness probe), `--once` (drain once), `--max-iterations N`
    (safety cap for the continuous loop). The drain loop: peek
    queue → cache hit shortcuts to `move_to_outputs` → cache miss
    snapshots mtime tree → invokes harness → checks write
    isolation → on success writes cache (mode 0600) + moves to
    outputs + appends replay-log + writes PROV-O.
  - **Design calls:**
    - Driver does NOT delegate cache lookup to `cached_call` (it
      would re-hash inputs; some entries have pinned hashes for
      test/recovery). Driver reads `cache/<entry.inputs_hash>.yaml`
      directly, honoring the pinned contract.
    - Driver does NOT hold the workspace flock around the drain —
      `ReplayLog.append` takes the lock itself; re-entering would
      deadlock. Each helper's individual atomicity covers the gap;
      future cross-writer mutual exclusion can use a dedicated
      sentinel.
    - Role→harness mapping is a hardcoded default for Phase 1
      (extractor → claude, auditor → claude); a future
      `dispatch/role_routes.yaml` is M7.x's concern. Unmapped role
      → `failures/` with `reason="role-unmapped"` (driver never
      crashes).
    - PROV-O written only on cache miss (cache hits are
      deterministic re-plays of the original miss's PROV).
  - Detected all four harnesses on the supervisor machine
    (claude, codex, cursor-agent, gemini); `amanuensis dispatch
    --check` returns valid JSON.
  - 41 new tests (10 queue + 3 harness detection + 9 retry/parse +
    7 isolation + 4 echo-role + 3 cache-integration + 5 dispatch-CLI);
    382 total pass (341 + 41); pyright strict + ruff + ruff-format
    + vulture all clean. | files: src/amanuensis/dispatch/__init__.py,
    src/amanuensis/dispatch/queue.py, src/amanuensis/dispatch/driver.py,
    src/amanuensis/dispatch/isolation.py, src/amanuensis/cli/dispatch.py,
    src/amanuensis/cli/__init__.py, tests/dispatch/__init__.py,
    tests/dispatch/conftest.py, tests/dispatch/test_queue_protocol.py,
    tests/dispatch/test_harness_detection.py,
    tests/dispatch/test_retry_policy.py,
    tests/dispatch/test_role_write_isolation.py,
    tests/dispatch/test_echo_role_fixture.py,
    tests/dispatch/test_cache_integration.py,
    tests/cli/test_dispatch_cli.py
- Phase M6 (Dispatch driver) complete: M6.1-M6.5 all shipped. 382
  tests pass; pyright strict + ruff + ruff-format + vulture all
  clean. Next session entry point is M7.1 (skill files for
  orchestrator + Extractor + Auditor + 3 stubs).
- M7.1 — six skill files landed under `src/amanuensis/skills/`:
  `distill.md` (orchestrator, active), `distill_extract.md`
  (Extractor, active), `distill_audit.md` (Auditor, active), plus
  three stubs `distill_contrarian.md` / `distill_constructive.md` /
  `distill_premortem.md` (Phase 2 work). Each file is YAML-frontmatter
  + markdown body with required fields: `name`, `description`, `role`,
  `version`, `active`, `stub`, `expects_substrate`, `phase`,
  `cli_commands_invoked`. Stubs carry `stub: true` + `stub_reason`.
  Orchestrator body walks the supervisor through the six-step distill
  workflow; Extractor body specifies the structured-YAML output
  contract and the INV-5/6/7 atom requirements; Auditor body
  specifies the contested-warrant clarification trigger (CR-7) the
  M7.4 reconciliation gate will action.
  Wheel packaging: hatchling's existing `packages = ["src/amanuensis"]`
  ships every `.md` under `skills/` (verified by `uv build --wheel`
  + `unzip -l`).
  `tests/skills/test_skill_frontmatter.py` (11 tests) parametrically
  validates each file's frontmatter shape and asserts the
  orchestrator-plus-two-actives-plus-three-stubs ledger. | files:
  src/amanuensis/skills/__init__.py,
  src/amanuensis/skills/distill.md,
  src/amanuensis/skills/distill_extract.md,
  src/amanuensis/skills/distill_audit.md,
  src/amanuensis/skills/distill_contrarian.md,
  src/amanuensis/skills/distill_constructive.md,
  src/amanuensis/skills/distill_premortem.md,
  tests/skills/__init__.py,
  tests/skills/test_skill_frontmatter.py
- M8.1 — local web app skeleton (FastAPI + Jinja2 + HTMX + Tailwind).
  Runtime deps added: `fastapi`, `uvicorn[standard]`, `jinja2`,
  `pytailwindcss` (ships the Tailwind binary in a Python package — no
  Node toolchain). `src/amanuensis/web/app.py` exposes `create_app()`
  + module-level `app` (uvicorn entry `amanuensis.web.app:app`) with
  `GET /healthz` JSON route, static mount at `/static`, Jinja2
  templates at `/src/amanuensis/web/templates/`, async lifespan
  context manager (no-op for now but plumbed for M5/M6 wiring later).
  `WebConfig` (frozen dataclass) defaults `bind_host=127.0.0.1` +
  `bind_port=8723`; `load_config()` reads `AMANUENSIS_HOST` /
  `AMANUENSIS_PORT` (with `AMANUENSIS_BIND_HOST` / `_PORT` fallback)
  so both the `.env.example` convention and the M8.8 binding-refusal
  semantics are honoured.
  `build_css.py` is a `python -m amanuensis.web.build_css` entry that
  invokes `pytailwindcss.run(...)` with `auto_install=True` — first
  run downloads the standalone Tailwind binary (~16MB); subsequent
  runs are local. Output is `src/amanuensis/web/static/tailwind.css`
  (2773 bytes for the M8.1 minimal template surface).
  HTMX 1.9.12 vendored at `static/vendor/htmx.min.js` (48101 bytes)
  with a `vendor/README.md` recording the upstream URL.
  `tests/web/test_app_boots.py` (3 tests) covers `/healthz` JSON,
  vendored HTMX served correctly, and `create_app()` returning a
  FastAPI instance. Wheel build verified (`uv build --wheel` packages
  templates + vendored HTMX + built CSS).
  Pyright strict: pytailwindcss has no type stubs, so the build_css
  module carries a targeted `# pyright: ignore` for that import.
  396 tests pass (393 from M7.1 + 3 from M8.1; 382 baseline + 14
  new); pyright strict + ruff + ruff-format + vulture all clean.
  | files: pyproject.toml, src/amanuensis/web/__init__.py,
  src/amanuensis/web/app.py, src/amanuensis/web/config.py,
  src/amanuensis/web/build_css.py,
  src/amanuensis/web/tailwind.config.js,
  src/amanuensis/web/tailwind.input.css,
  src/amanuensis/web/templates/base.html,
  src/amanuensis/web/templates/healthz.html,
  src/amanuensis/web/static/tailwind.css,
  src/amanuensis/web/static/vendor/htmx.min.js,
  src/amanuensis/web/static/vendor/README.md,
  tests/web/__init__.py, tests/web/test_app_boots.py
