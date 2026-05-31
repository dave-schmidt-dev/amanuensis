# Invariants Charter

Foundational properties that every plan must uphold. Entries are added by
plans that establish or modify an invariant (per `~/.agent/prompts/plan.md`).

Status legend: `active` (gate enforced) | `near-threshold` (warn) | `waived` (explicit waiver recorded inline).

---

## INV-1 — `amanuensis.yaml` marker is required at the project root

- **Status:** active (gated at substrate-construction + CLI surface)
- **Established:** 2026-05-29 (Phase 1 plan)
- **Property:** Every amanuensis project has an `amanuensis.yaml` at its root.
  Skills check for this marker before activating; CLI commands refuse to operate
  outside a marked directory.
- **Gate test:** `tests/fs/test_marker_required.py` (M1 — refuses
  `Substrate(root)` construction without the marker; raises
  `SubstrateMarkerMissing`) and `tests/cli/test_marker_required.py` (M4.1 —
  parametric over every marker-protected command; exit code 2 on preflight).
  The original plan placed a single gate under
  `tests/invariants/`; M11.3 consolidated it into the two
  surface-specific tests rather than re-asserting in the invariants
  directory (closer to the surface being enforced makes diagnosis
  faster when the gate trips).
- **Rationale:** Establishes a deterministic activation rule independent of the
  agent harness. Mirrors `git`, `npm`, `cargo`, `uv` conventions.

## INV-2 — No harness-specific files at project root

- **Status:** active (gated)
- **Established:** 2026-05-29
- **Property:** No `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, or `README.md` at the
  amanuensis project root. Documentation lives in `docs/` (human-facing,
  build-step-derived).
- **Gate test:** `tests/invariants/test_no_harness_files.py` — four cases:
  (1) clean workspace passes; (2) a hand-authored `mappings/README.md` lacking
  the generator marker is flagged; (3) a generator-written marker README passes;
  (4) the `no-harness-files` pre-commit hook in `.pre-commit-config.yaml` lists
  every forbidden filename (shell gate and pytest gate stay in sync).
- **Rationale:** Keeps amanuensis harness-agnostic. Agent-facing instructions
  live in skills (loaded JIT via each harness's skill mechanism); the project
  marker (INV-1) provides activation; per-harness skill discovery is handled
  by `amanuensis install-skills`.

## INV-3 — Provenance by construction

- **Status:** active
- **Established:** 2026-05-29
- **Property:** Every substrate artifact (atom, relation, finding, prose span,
  clarification resolution, iteration directive) has a PROV-O record recording
  who created it, what activity, what it used, and (for LLM contributions)
  which model. Retrofitted provenance is rejected.
- **Gate test:** `tests/invariants/test_provenance_completeness.py`
  — walks the substrate's atoms; fails if any atom's `provenance_id` is empty,
  the corresponding PROV-O record is missing, the file fails to parse, or the
  record's `entity_id` does not match the atom's id. Scoped to atoms in M2.5;
  extends to relations / clarifications / iterations in later milestones as
  those substrate paths come online (TODO documented in the test module).
  Supplementary read/write provenance is also exercised by the M5.2
  `tests/llm/test_replay_and_prov.py` writer tests and the M7.4
  reconciliation gate (`tests/dispatch/test_reconciliation.py`).
- **Rationale:** Documented reasoning is the artifact (Heuer inheritance);
  every cross-boundary action (LLM call, human clarification, iteration) is
  captured structurally so the supervisor can trace any output back to its
  source spans and authors.

## INV-4 — Determinism boundary is named, gated, and audited

- **Status:** active (both read-only and mutating sides gated)
- **Established:** 2026-05-29
- **Property:** Non-deterministic actions (LLM calls, human judgments) are
  permitted only at named events. Each event has: input content hash, output
  content hash, role attribution, model identifier (for LLM events), timestamp,
  and a deterministic validation gate that rejects malformed output before it
  enters the substrate. All other operations are pure functions over substrate
  state.
- **Gate test:** `tests/invariants/test_determinism_boundary.py` —
  11 parametric cases over read-only CLI commands (M4.4: substrate unchanged,
  stdout byte-deterministic across runs, second run reconfirms invariance)
  plus 3 mutating-side cases (M5.3: every LLM call routes through the
  `cached_call` + `append_replay_entry` + `write_llm_provenance` triple;
  cache hits short-circuit subprocess invocation; replay-log seq counter
  monotonic under contended writes).
- **Rationale:** The system's correctness rests on this boundary being explicit
  and small.

## INV-5 — Closed predicate vocabulary at extraction

- **Status:** active
- **Established:** 2026-05-29
- **Property:** Atoms must use predicates from the project's vocabulary
  registry. Open-vocabulary extraction is rejected by the auditor. Adding
  new predicates requires a governance event (human-proposed, test-suite
  validated, version-bumped registry commit).
- **Gate test:** `tests/invariants/test_closed_vocabulary.py` —
  certifies that the `closed_vocabulary` validator rejects atoms whose
  predicate is not in the per-distillation snapshot. Exercises canonical
  predicates, aliases (alias-aware resolution via `Vocabulary.has_predicate`),
  unknown predicates, and the snapshot-vs-global boundary (a predicate that
  is in the global registry but not in the snapshot is correctly rejected).
- **Rationale:** Open-vocabulary "pretty much guarantees drift across long
  matters" (D5 production survey). The closed-vocabulary floor is what makes
  cross-engagement reasoning tractable.

## INV-6 — `scale_anchor` is mandatory on every atom

- **Status:** active (gated at schema + validator surface)
- **Established:** 2026-05-29
- **Property:** Every atom declares `scale_anchor ∈ {sentence, paragraph,
  section, document}`. The auditor refuses atoms without it.
- **Gate test:** `tests/validators/test_scale_anchor.py` (M2.4 — parametric
  over each canonical anchor + rejection cases). Schema-level enforcement
  is additionally exercised by `tests/schemas/test_atom.py`. The
  original plan placed a single gate under `tests/invariants/`; M11.3
  consolidated it into the per-validator test suite rather than
  re-asserting in the invariants directory.
- **Rationale:** Multi-scale querying is a first-class concern; without a
  scale anchor, "atoms in §3.2" or "atoms at sentence grain" become heuristic
  filters rather than deterministic queries.

## INV-7 — `source_id`, `section_path`, `paragraph_index`, `char_span` mandatory

- **Status:** active (gated at validator surface)
- **Established:** 2026-05-29
- **Property:** Every atom resolves to a precise source span via the four-tuple
  `(source_id, section_path, paragraph_index, char_span)`. The citation-ledger
  gate rejects atoms missing any of these.
- **Gate test:** `tests/validators/test_citation_ledger.py` (M2.4 —
  pass case + one rejection case per missing four-tuple field). Schema-level
  shape enforcement is additionally exercised by `tests/schemas/test_atom.py`
  (`char_span` ordering + non-negative integer ranges). The original plan
  placed a single gate under `tests/invariants/`; M11.3 consolidated it
  into the per-validator test suite rather than re-asserting in the
  invariants directory.
- **Rationale:** Provenance by construction (INV-3) requires precise source
  addressing. The four-tuple is the deterministic citation identity.

## INV-8 — Substrate is the source of truth

- **Status:** active (gate via render smoke + atomic-write discipline)
- **Established:** 2026-05-29
- **Property:** All renderings (live web app, static export, prose report) are
  pure functions over substrate state. Renderings carry no state the substrate
  doesn't carry. Caches (e.g., SQLite query acceleration) are rebuildable
  from the substrate and never authoritative.
- **Gate test (partial):** `tests/export/test_static_export_smoke.py` (M9.1 —
  self-contained HTML output: no CDN URLs, deterministic structure given
  fixed substrate, `</script` injection defense) covers the static-HTML
  surface. Web-app renderings under `tests/web/` exercise read-only routes
  against in-memory `TestClient` instances. A dedicated invariants-
  directory render-purity gate (re-render the same substrate twice and
  assert byte-identical output across all surfaces) is planned for
  Phase 2 when the prose-report surface lands and a single shared
  surface-list exists to parametrize over.
- **Rationale:** Filesystem-as-truth keeps git-friendly, JIT-loadable,
  agent-direct-writable, and survives loss of cache/db.
- **Known escape hatch:** hand-edits to paragraph `.md` files in
  `source-mirror/paragraphs/` are not currently re-verified against the
  manifest's `content_sha256` hashes; a future verifier (post-M3.1) will
  close this. INV-8's atomic-write guarantee covers the write path, not
  post-write tampering.

## INV-10 — Vocabulary is pinned per distillation

- **Status:** active
- **Established:** 2026-05-29 (Phase 1 plan, via external review CR-5 + CV-4)
- **Property:** On ingest, the active vocabulary registry is snapshotted into
  `distillations/<source-id>/vocabulary-snapshot.yaml` (content-addressed; snapshot
  hash recorded in `source-mirror/manifest.yaml`). All validators read the
  per-distillation snapshot, never the global `~/.amanuensis/vocabularies/` registry.
  The global registry is a starting template, not a runtime dependency.
- **Gate test:** `tests/invariants/test_vocabulary_pinned.py`
  — verifies every distillation has a vocabulary snapshot; verifies write-once
  semantics (a snapshot for distillation A is independent of subsequent
  registry edits or of snapshots written for distillation B); verifies the
  auditor signal for "no snapshot" (`SubstrateNotFound`) vs "corrupt snapshot"
  (`SubstrateSnapshotCorrupt`) are distinct typed exceptions; verifies the
  M3.1 manifest's `vocabulary_snapshot_sha256` matches the SHA-256 of the
  on-disk snapshot bytes (closing the previously-deferred manifest-hash
  clause).
- **Rationale:** Vocabulary registry edits between distillations (Phase 1.5, second
  engagement, or unrelated tinkering) would otherwise silently retroactively change
  what existing atoms mean. The snapshot makes substrate-as-truth (INV-8) hold across
  vocabulary evolution; cross-machine and time-shifted reproducibility require the
  vocabulary to live next to the atoms it describes.

## INV-9 — Cross-document reasoning is Phase 2's job, not Phase 1's

- **Status:** active (gated)
- **Established:** 2026-05-29
- **Property:** Phase 1 emits intra-document relations only. Cross-document
  entity resolution, support/attack edges spanning documents, probandum
  hierarchies spanning sources are Phase 2 (Map) outputs. Phase 1 atoms
  carry normalized entity references so Phase 2 can join on them without
  re-extraction.
- **Gate test:** `tests/invariants/test_intra_doc_only.py` — three cases:
  (1) all relations in a clean fixture substrate have `source_id` matching
  their distillation and both endpoint atoms belong to the same source;
  (2) no Phase-2 cross-doc directories (`probanda/`, `cross-doc/`) exist
  at the workspace root; (3) a deliberately planted cross-source violation
  (relation filed under `src1` but claiming `source_id=src2`) is caught.
- **Rationale:** Single-doc Phase 1 keeps the multi-agent loop's context bounded
  and the checkpointing boundary clean. Concentrates cross-source complexity in
  Phase 2.

## INV-11 — Dispatched roles write only under their assigned subtree

- **Status:** active
- **Established:** 2026-05-30 (M6.3, lifted from CV-5 to INV during M11.3)
- **Property:** When the dispatch driver invokes a role's harness CLI, the
  subprocess MUST only write under
  `dispatch/outputs/<role>-<inputs_hash>/`. Any mutation to a file outside
  that subtree (excluding the documented skip set: `.venv`, `__pycache__`,
  `.git`) is a write-isolation violation. Deletions inside the workspace are
  not policed by this gate (per the M6.3 module docstring); the guarantee is
  about novel writes, not housekeeping.
- **Gate test:** `tests/dispatch/test_role_write_isolation.py` (M6.3) —
  five contracts: writes inside the allowed subtree pass; writes outside
  trip a violation; mtime-only bumps trip a violation; deletions do not
  trip a violation; the snapshot ignores skip directories.
- **Rationale:** Foundational for the multi-agent loop. Without write-
  isolation, a misbehaving (or compromised) role can clobber another role's
  outputs, the substrate, or the dispatch queue itself — defeating PROV-O's
  attribution chain (INV-3) and the determinism boundary (INV-4). Lifted
  from a contributing-violation (CV-5) to an invariant because the rest of
  the dispatch architecture (queue protocol, reconciliation gate, replay
  log) presumes role writes are scoped.

## INV-12 — `mappings/` is the home for all cross-document artifacts

- **Status:** active (gated)
- **Established:** 2026-05-31 (Phase 2a M10)
- **Property:** No cross-source artifact (`Entity` record, `Resolution` record,
  cross-doc relation [Phase 2b], probandum hierarchy [Phase 2c]) is permitted
  outside `mappings/`. Per-distillation directories under `distillations/`
  remain strictly intra-document. A relation filed under `distillations/<src>/`
  whose endpoint atoms belong to a different source is a violation. A
  `Resolution` record whose `source_id` names a non-existent distillation is
  a violation.
- **Gate test:** `tests/invariants/test_mappings_namespace_scoped.py` — three
  cases: (1) a clean workspace with entity, resolution, and matching distillation
  passes; (2) a relation filed under `src1` whose `from_atom_id` belongs to `src2`
  is caught by a cross-source atom-to-source index walk; (3) a resolution whose
  `source_id` has no matching distillation directory is caught as an orphan
  resolution.
- **Rationale:** Keeps the boundary between intra-document Phase 1 work and
  cross-document Phase 2 work structurally enforced at the filesystem level.
  Prevents Phase 1 roles from accidentally writing cross-source artifacts into
  per-distillation directories where INV-3 provenance scoping and INV-9 intra-doc
  guarantees would be violated.

## INV-13 — Entity and Resolution records are immutable once written

- **Status:** active (gated)
- **Established:** 2026-05-31 (Phase 2a M10)
- **Property:** Once written, `Entity` and `Resolution` records are not rewritten
  in place. Corrections are carried by `EntitySupersede` and `ResolutionSupersede`
  records, each with their own PROV-O record. Attempting to write a record whose
  content-addressable id already exists on disk with different non-volatile content
  raises `MutationOfImmutableRecord`. Idempotent re-writes (identical content) are
  silently accepted.
- **Gate test:** `tests/invariants/test_mappings_immutability.py` — four cases:
  (1) `add_entity` is idempotent for identical content; (2) `add_entity` raises
  `MutationOfImmutableRecord` when on-disk content diverges from incoming content
  at the same id; (3) `add_resolution` is idempotent for identical content;
  (4) a `ResolutionSupersede` chain allows corrections without triggering the
  immutability guard, and `latest_resolution_for` returns the replacement.
- **Rationale:** Content-addressable immutability is the basis for PROV-O audit
  trails (INV-3). If records could be silently overwritten, provenance attribution
  would be unreliable and replay would produce different results from the original
  run, violating INV-4 (determinism).

## INV-14 — Resolution records key off the normalized triple

- **Status:** active (gated)
- **Established:** 2026-05-31 (Phase 2a M10)
- **Property:** A `Resolution` record's identity is determined by what it resolves
  (the triple `(source_id, atom_id, operand_index)`) plus what it resolves to (the
  entity). Two non-superseded resolutions for the same triple cannot coexist.
  Attempting to add a second non-superseded resolution for an already-resolved
  triple raises `ResolutionDuplicateTriple`. Once a supersede record exists pointing
  from the first resolution to a replacement, `latest_resolution_for` returns `None`
  (chain terminal not yet written) and the replacement may be added without raising.
- **Gate test:** `tests/invariants/test_resolution_uniqueness.py` — three cases:
  (1) a single resolution for a triple is accepted and queryable via
  `latest_resolution_for`; (2) a second distinct non-superseded resolution for the
  same triple raises `ResolutionDuplicateTriple`; (3) after superseding v1 to v2
  without v2 on disk, `latest_resolution_for` returns `None` and `add_resolution(v2)`
  succeeds.
- **Rationale:** Without uniqueness enforcement, the reconciliation phase could
  accumulate conflicting resolutions silently. The supersede protocol provides a
  structured correction path while the duplicate guard makes concurrent or
  replayed writes safe.
