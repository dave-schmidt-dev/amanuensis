# Tasks

Per-project task and work-in-progress tracking across sessions and agents.

Status key: `pending` | `in progress` | `done` | `blocked`.

Active plan: `~/Documents/Projects/.plans/amanuensis/phase2a-resolve-2026-05-31.md`
Active tasks: `~/Documents/Projects/.plans/amanuensis/phase2a-resolve-2026-05-31-tasks.md`
Synthesis record: `~/Documents/Projects/.plans/amanuensis/phase2a-resolve-2026-05-31-synthesis.md`
Spec: `docs/superpowers/specs/2026-05-31-phase2a-resolve-design.md` (committed)

Prior plan: `~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29.md` (shipped)

---

## Current focus

- [done] Phase 1 (Distill) — **SHIPPED 2026-05-30.** All 11 milestones
  (M1 schema/fs foundation, M2 validators/vocabulary, M3 ingestion,
  M4 CLI surface, M5 LLM-call wrapper, M6 dispatch driver, M7 active
  roles + orchestrator, M8 web app, M9 static export stub, M10 docs
  polish, M11 INVARIANT CI gate + final validation) complete.
  Final gates: 501 pytest + 26 invariant + 10 Playwright E2E pass;
  pyright strict + ruff + vulture clean; structural smoke on the
  DOJ post-trial brief produced 483 paragraphs + 589KB HTML.
  M11.2 (real-LLM dispatch on the DOJ brief) tactically deferred
  to first engagement; no acceptance loss (M7.5 already exercises
  the full code path with mocked role outputs). See `HISTORY.md`
  2026-05-30 entry for the per-milestone breakdown, open
  follow-ups, and the full validation transcript.

## Upcoming phases

- [done] **Phase 2a (Resolve) — SHIPPED 2026-05-31.** All 82 tasks
  complete across 11 milestones. 874 fast pytest cases + 50
  invariants + 3 integration pass; pyright strict + ruff + vulture
  clean; 11 Playwright specs authored (1 new T11.3); 9 new map CLI
  verbs; 3 new web routes; 4 new content-addressable schemas
  (Entity / Resolution / EntitySupersede / ResolutionSupersede); 3
  new invariants (INV-12/13/14) active with executable gate tests.
  See HISTORY.md 2026-05-31 entry for the per-milestone breakdown,
  defects caught + remediated, and full validation transcript.
- [done] **Phase 2b (Connect) — SHIPPED 2026-06-01.** All ~58 tasks
  complete across 11 milestones. 1019 fast pytest cases + 64
  invariants + 9 integration + 15 Playwright specs pass; pyright
  strict (0 NEW errors) + ruff + vulture clean. 2 new schemas
  (CrossDocRelation, CrossDocRelationSupersede); 1 new role
  (`amanuensis:map:connect`); new CLI verbs (map relation
  list/show/supersede, map --connect-only, export
  --workspace-appendix); 2 new web routes (`/cross-doc-relations`
  list + detail) plus Cytoscape overlay; 1 new invariant (INV-15
  shared-entity gate) active with executable gate tests. See
  HISTORY.md 2026-06-01 entry for the per-milestone breakdown,
  defects caught + remediated, and full validation transcript.
- [done] **Phase 2c (Hierarchize) — SHIPPED 2026-06-01.** All ~85
  tasks complete across 13 milestones. 1274 fast pytest cases +
  64+ invariants (INV-1..19, INV-19 charter row added in cleanup
  pass) + integration + 18 Playwright specs pass; pyright strict
  (0 NEW errors) + ruff + vulture clean. 4 new schemas (Probandum,
  ProbandumEdge, ProbandumSupersede, ProbandumEdgeSupersede); new
  role (``amanuensis:map:hierarchize``); 9 new CLI sub-commands (map
  probandum + map walton-scheme + --hierarchize-only flag); 3 new
  web routes (/probanda list + detail + tree) with Cytoscape dagre
  visualization; static export probandum-tree.html appendix +
  per-probandum lineage pages; 4 new invariants (INV-16
  tree-not-DAG, INV-17 lineage-to-ultimate, INV-18 closed Walton-
  scheme vocabulary, INV-19 ACH alternatives required on non-
  ultimate probanda). See HISTORY.md 2026-06-01 entry for the
  per-milestone breakdown, defects caught + remediated, and full
  validation transcript.
- [done] **Phase 2c cleanup pass — SHIPPED 2026-06-01.** Two
  follow-ups closed: (1) INV-19 charter entry retrofitted with new
  parametric on-disk gate test at
  ``tests/invariants/test_probandum_alternatives.py``; (2)
  clarification id plumbed through ``_build_probandum`` /
  ``_build_probandum_edge`` returns via new ``ProbandumBuildResult``
  + ``ProbandumEdgeBuildResult`` dataclasses (mirrors Phase 2b
  cleanup-2's ``CrossDocBuildResult``); ``_recover_latest_clarification_id``
  deleted; regression test added for the two-probanda-one-drain race.
  See HISTORY.md 2026-06-01 entry "Phase 2c cleanup pass" for the
  bullet-level breakdown.
- [pending] Phase 3 (Extend) — not blocked; full brainstorm cycle
  required. Phase 2 complete (Phase 2a/2b/2c all shipped).
- [pending] Phase 4 (Synthesize) — packaging into agent-usable
  product.

## Standing tasks

- [pending] When second engagement starts: instantiate domain config
  for that engagement (vocabulary, scheme catalogue, probandum
  template). Phase 1's substrate schema designed to absorb this
  without rewrite.
- [done] Lockfile commit — `uv.lock` committed 2026-05-31;
  `.gitignore` entry removed; inline CI-workflow notice removed.
  Standing task closed (CI subsequently removed entirely; see
  HISTORY 2026-05-31).
- [done] CI removed — verification is now local-only via
  pre-commit (fast: ruff, vulture, INV-1+INV-2 markers, hygiene)
  + pre-push (heavy: pyright strict + full pytest suite).
  GitHub Actions workflow deleted 2026-05-31.
