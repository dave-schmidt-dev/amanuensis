# Invariants Charter

Foundational properties that every plan must uphold. Entries are added by
plans that establish or modify an invariant (per `~/.agent/prompts/plan.md`).

Status legend: `active` (gate enforced) | `near-threshold` (warn) | `waived` (explicit waiver recorded inline).

---

## INV-1 — `amanuensis.yaml` marker is required at the project root

- **Status:** active
- **Established:** 2026-05-29 (Phase 1 plan)
- **Property:** Every amanuensis project has an `amanuensis.yaml` at its root.
  Skills check for this marker before activating; CLI commands refuse to operate
  outside a marked directory.
- **Gate test (planned):** `tests/invariants/test_marker_required.py` — verifies
  CLI commands and skills exit with a clear error when invoked outside a marked
  directory.
- **Rationale:** Establishes a deterministic activation rule independent of the
  agent harness. Mirrors `git`, `npm`, `cargo`, `uv` conventions.

## INV-2 — No harness-specific files at project root

- **Status:** active
- **Established:** 2026-05-29
- **Property:** No `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, or `README.md` at the
  amanuensis project root. Documentation lives in `docs/` (human-facing,
  build-step-derived).
- **Gate test (planned):** `tests/invariants/test_no_harness_files.py` —
  scans for forbidden filenames at the project root.
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
- **Gate test (active, scoped to atoms):** `tests/invariants/test_provenance_completeness.py`
  — walks the substrate's atoms; fails if any atom's `provenance_id` is empty,
  the corresponding PROV-O record is missing, the file fails to parse, or the
  record's `entity_id` does not match the atom's id. Scoped to atoms in M2.5;
  extends to relations / clarifications / iterations in later milestones as
  those substrate paths come online (TODO documented in the test module).
- **Rationale:** Documented reasoning is the artifact (Heuer inheritance);
  every cross-boundary action (LLM call, human clarification, iteration) is
  captured structurally so the supervisor can trace any output back to its
  source spans and authors.

## INV-4 — Determinism boundary is named, gated, and audited

- **Status:** active
- **Established:** 2026-05-29
- **Property:** Non-deterministic actions (LLM calls, human judgments) are
  permitted only at named events. Each event has: input content hash, output
  content hash, role attribution, model identifier (for LLM events), timestamp,
  and a deterministic validation gate that rejects malformed output before it
  enters the substrate. All other operations are pure functions over substrate
  state.
- **Gate test (planned):** `tests/invariants/test_determinism_boundary.py` —
  verifies every LLM call goes through the cache+log wrapper; verifies CLI
  commands are idempotent given a fixed substrate state.
- **Rationale:** The system's correctness rests on this boundary being explicit
  and small.

## INV-5 — Closed predicate vocabulary at extraction

- **Status:** active
- **Established:** 2026-05-29
- **Property:** Atoms must use predicates from the project's vocabulary
  registry. Open-vocabulary extraction is rejected by the auditor. Adding
  new predicates requires a governance event (human-proposed, test-suite
  validated, version-bumped registry commit).
- **Gate test (active):** `tests/invariants/test_closed_vocabulary.py` —
  certifies that the `closed_vocabulary` validator rejects atoms whose
  predicate is not in the per-distillation snapshot. Exercises canonical
  predicates, aliases (alias-aware resolution via `Vocabulary.has_predicate`),
  unknown predicates, and the snapshot-vs-global boundary (a predicate that
  is in the global registry but not in the snapshot is correctly rejected).
- **Rationale:** Open-vocabulary "pretty much guarantees drift across long
  matters" (D5 production survey). The closed-vocabulary floor is what makes
  cross-engagement reasoning tractable.

## INV-6 — `scale_anchor` is mandatory on every atom

- **Status:** active
- **Established:** 2026-05-29
- **Property:** Every atom declares `scale_anchor ∈ {sentence, paragraph,
  section, document}`. The auditor refuses atoms without it.
- **Gate test (planned):** `tests/invariants/test_scale_anchor_required.py`.
- **Rationale:** Multi-scale querying is a first-class concern; without a
  scale anchor, "atoms in §3.2" or "atoms at sentence grain" become heuristic
  filters rather than deterministic queries.

## INV-7 — `source_id`, `section_path`, `paragraph_index`, `char_span` mandatory

- **Status:** active
- **Established:** 2026-05-29
- **Property:** Every atom resolves to a precise source span via the four-tuple
  `(source_id, section_path, paragraph_index, char_span)`. The citation-ledger
  gate rejects atoms missing any of these.
- **Gate test (planned):** `tests/invariants/test_citation_ledger.py`.
- **Rationale:** Provenance by construction (INV-3) requires precise source
  addressing. The four-tuple is the deterministic citation identity.

## INV-8 — Substrate is the source of truth

- **Status:** active
- **Established:** 2026-05-29
- **Property:** All renderings (live web app, static export, prose report) are
  pure functions over substrate state. Renderings carry no state the substrate
  doesn't carry. Caches (e.g., SQLite query acceleration) are rebuildable
  from the substrate and never authoritative.
- **Gate test (planned):** `tests/invariants/test_render_purity.py` — verifies
  renderings are deterministic given fixed substrate.
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
- **Gate test (active):** `tests/invariants/test_vocabulary_pinned.py`
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

- **Status:** active
- **Established:** 2026-05-29
- **Property:** Phase 1 emits intra-document relations only. Cross-document
  entity resolution, support/attack edges spanning documents, probandum
  hierarchies spanning sources are Phase 2 (Map) outputs. Phase 1 atoms
  carry normalized entity references so Phase 2 can join on them without
  re-extraction.
- **Gate test (planned):** `tests/invariants/test_intra_doc_only.py` — verifies
  Phase 1 outputs contain no cross-source edges.
- **Rationale:** Single-doc Phase 1 keeps the multi-agent loop's context bounded
  and the checkpointing boundary clean. Concentrates cross-source complexity in
  Phase 2.
