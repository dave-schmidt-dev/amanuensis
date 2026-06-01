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

## INV-15 — Cross-doc edges are grounded in shared resolved entities

- **Status:** active (gated)
- **Established:** 2026-05-31 (Phase 2b M3)
- **Property:** Every `CrossDocRelation` written to `mappings/relations/` must
  declare a non-empty `shared_entities` list, and every listed entity id must
  (a) exist as an `Entity` record under `mappings/entities/` (chain-walked to
  its terminus via `latest_entity_for`) AND (b) be resolved by BOTH endpoint
  atoms via Phase 2a `Resolution` records. Substrate `add_cross_doc_relation`
  enforces this at write-time; the invariant gate test re-runs the check
  against every on-disk cross-doc relation to catch records that bypassed the
  substrate (e.g., manually authored YAML). Violations raise
  `SharedEntityGateViolation`.
- **Gate test:** `tests/invariants/test_cross_doc_shared_entity.py` — five
  cases: (1) a workspace with bilateral resolutions and one valid edge passes;
  (2) a relation with `shared_entities: []` is caught; (3) a relation
  referencing an entity id with no on-disk Entity record is caught;
  (4) a relation whose from-endpoint lacks a Resolution to the shared entity
  is caught; (5) the to-endpoint mirror is caught.
- **Rationale:** Cross-doc edges with no shared resolved entity are
  ungrounded — there is no evidence in the substrate that the two atoms refer
  to the same real-world thing, so any warrant connecting them is hollow.
  Enforcing the gate at write-time AND at audit-time keeps every cross-doc
  relation traceable from atoms through resolutions through entities, which
  is the structural backbone of cross-document reasoning.

## INV-16 — Probandum hierarchy is a tree (no cycles, no multi-parent)

- **Status:** active (gated)
- **Established:** 2026-06-01 (Phase 2c M4)
- **Property:** The directed graph induced by `ProbandumEdge` records with
  `child_kind == "probandum"` MUST be a tree. Concretely: (a) the graph is
  acyclic — walking parent-to-child via probandum-only edges from any node
  reaches a leaf set (atoms / cross-doc relations / probanda with no
  outgoing edges) in finite steps; and (b) every non-root probandum has
  exactly one PARENT (the set of parents of any given child is a
  singleton). Parallel edges from the SAME parent to the SAME child
  (different `kind` / `warrant`) remain legal because the parent set is
  still a singleton. Attempting to write a `ProbandumEdge` whose
  parent-to-child relation would close a cycle, would self-loop, or would
  give the child a second distinct parent raises
  `ProbandumTreeViolation` at `Substrate.add_probandum_edge`.
  Superseded edges are excluded from both checks — they represent
  retracted state and cannot anchor or break tree-shape.
- **Gate test:** `tests/invariants/test_probandum_tree.py` — five cases:
  (1) a clean tree (`ult → pen → interim`) passes; (2) a planted
  self-loop edge (`p → p`) is caught; (3) a planted two-cycle
  (`ult → pen` AND `pen → ult`) is caught; (4) a planted three-cycle
  (`a → b → c → a`) is caught; (5) a clean 10-deep linear chain passes.
- **Rationale:** Wigmore trees are trees; cycles would make lineage
  walking non-terminating and provenance attribution ambiguous. The
  spec's "acyclic" wording (§INV-16) and "tree" risk language
  (§Risks #1) are reconciled by enforcing the stronger discipline
  (tree, not DAG), because Wigmore semantics rely on a single canonical
  lineage per probandum — DAG-with-duplicated-subtrees is the sanctioned
  way to express multi-lineage participation.

## INV-17 — Probandum lineage completes to an `ultimate`

- **Status:** active (gated)
- **Established:** 2026-06-01 (Phase 2c M4)
- **Property:** Every probandum-edge's `parent_probandum_id` MUST trace
  upward through INCOMING probandum-edges (where the parent is the
  `child_id` of some earlier edge with `child_kind == "probandum"`) to
  at least one `Probandum` with `kind == "ultimate"`. An `ultimate`
  probandum trivially satisfies the gate (it IS the lineage terminus).
  Substrate enforces this at write-time: a proposed edge whose parent
  is itself a non-ultimate with no path to an ultimate raises
  `LineageIncomplete` at `Substrate.add_probandum_edge`. The walk is
  depth-capped at 100 (defensive) and excludes superseded edges.
- **Gate test:** `tests/invariants/test_probandum_lineage.py` — four
  cases: (1) a clean tree with full lineage passes; (2) an orphan
  interim probandum (parent has no incoming edge) is caught;
  (3) a penultimate parent with no incoming edge from an ultimate is
  caught; (4) a chain whose top node is a `penultimate` rather than
  an `ultimate` is caught.
- **Rationale:** matches the synthesis-doc "probandum lineage check"
  verification step. Findings without an ultimate-rooted lineage are
  not part of the engagement's answer — they are unresolved sub-trees
  that the supervisor still owes a connection for. Enforcing the gate
  at write-time forces operators to author the tree top-down (ultimate
  first, then penultimates linking to it, then interim levels) rather
  than accumulating dangling sub-trees.

## INV-18 — Closed Walton-scheme vocabulary

- **Status:** active (gated)
- **Established:** 2026-06-01 (Phase 2c M3)
- **Property:** Every `Probandum`'s `scheme` field MUST appear in the
  per-engagement `mappings/walton-scheme-snapshot.yaml`. Unknown schemes are
  rejected by `Substrate.add_probandum`. The snapshot is pinned via
  `Substrate.snapshot_walton_schemes` (and the matching CLI `amanuensis map
  walton-scheme snapshot` once shipped) from the bundled generic catalogue at
  `vocabularies/generic/walton-schemes.yaml`; `--extend` archives the prior
  snapshot under `mappings/walton-scheme-archive/<hash>.yaml`. Substrate
  caches the loaded registry per instance; the cache is invalidated on every
  snapshot call. Violations raise `WaltonSchemeGateViolation`; absence of any
  snapshot raises `SubstrateNotFound`.
- **Gate test:** `tests/invariants/test_probandum_scheme.py` — three cases:
  (1) a workspace with a snapshot and a valid probandum passes; (2) a
  probandum whose `scheme` is absent from the snapshot raises
  `WaltonSchemeGateViolation`; (3) a workspace with a probandum but no
  pinned snapshot raises `SubstrateNotFound`.
- **Rationale:** matches INV-5 (closed predicate vocabulary) + INV-10
  (per-distillation snapshot) discipline for the synthesis layer's
  warrant-typology field. Without a closed-vocabulary gate at write-time,
  extracted argument schemes could miss their Walton critical-questions
  matrix and break downstream lookup; the per-engagement snapshot keeps
  vocabulary evolution from retroactively changing the meaning of probanda
  already on disk.

## INV-19 — ACH alternatives are required on non-ultimate probanda

- **Status:** active (gated at substrate-construction surface)
- **Established:** 2026-06-01 (Phase 2c M-cleanup; gate landed during
  Phase 2c, charter entry retrofitted in cleanup pass)
- **Property:** Every `Probandum` with `kind in ("penultimate", "interim")`
  MUST have a non-empty `alternatives_considered` list (Analysis of
  Competing Hypotheses discipline). `ultimate` probanda are exempt —
  they ARE the alternatives the corpus picks between, not nodes that
  pick between sub-alternatives. `Substrate.add_probandum` raises
  `AchAlternativesGateViolation` (defined in
  `src/amanuensis/fs/_errors.py`; inherits from both `SubstrateError`
  and `ValueError`) when the gate trips.
- **Gate test:** `tests/fs/test_probandum_io.py` —
  `test_rejects_empty_alternatives_on_penultimate` +
  `test_rejects_empty_alternatives_on_interim` +
  `test_accepts_empty_alternatives_on_ultimate` exercise the
  substrate write-time gate directly. `tests/invariants/test_probandum_alternatives.py`
  additionally walks every probandum on disk via
  `Substrate.list_probanda` and re-runs the gate through
  `Substrate.add_probandum`, catching records that bypass the substrate
  write path (e.g., manually authored YAML).
- **Rationale:** ACH (Analysis of Competing Hypotheses, Heuer) is the
  structural discipline that prevents single-hypothesis tunnel vision
  in the probandum tree. An interim or penultimate finding without
  enumerated alternatives is by construction an unfalsified claim — it
  has nowhere on disk to record what other hypotheses were considered
  and rejected. The gate forces the operator to record the comparison
  set at write-time. `ultimate` probanda are exempt because they sit
  at the top of the lineage and ARE the alternative set the engagement
  is choosing among.
