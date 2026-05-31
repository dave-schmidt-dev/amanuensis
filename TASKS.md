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

- [in progress] **Phase 2a (Resolve) — M1+M2+M3+M4+M5+M6 SHIPPED 2026-05-31;
  M7–M11 remain (38 tasks).** M1 (12 tasks, schema foundation) +
  M2 (5 tasks, entity-kind vocabulary) + M3 (11 tasks, substrate
  API extensions) + M4 (3 tasks, INV-9+INV-2 executable gates) +
  M5 (5 tasks, map_resolve/map_audit skills) + M6 (8 tasks,
  dispatch+reconcile extension for map roles) = 44 of 82 tasks done.
  Heavy parallelism via subagent waves; combined spec+code-quality
  reviewer per task. Real defects caught in review and fixed
  inline across milestones: T1.8 hash-corrupting v1 `kind` injection
  in `_serialize.py`; T1.10 frontmatter `find("---")` mid-content
  bug; M3 implementer's `from conftest import`; M6 nested-lock
  deadlock in `ReplayLog.append`; M6 over-strict `_MAP_ROLE_RE`
  regex; M6 missing `_non_empty_kind` validator on Entity; M6
  `role_attribution.at` timestamp drift breaking idempotency
  (fixed via deterministic `_stable_role_attribution_at` derived
  from `inputs_hash`). 633 fast tests + 3 integration tests pass;
  pyright strict + ruff clean. Next action: continue with M7 (CLI
  map family — `amanuensis map ...` Typer sub-app, 13 tasks).
- [pending] Phase 2b (Connect) — cross-doc support/attack edges built
  on Phase 2a's resolved entities. Full brainstorm cycle required;
  blocked on 2a implementation.
- [pending] Phase 2c (Hierarchize) — probandum hierarchies built on
  Phase 2b's cross-doc edges. Full brainstorm cycle required; blocked
  on 2b implementation.
- [pending] Phase 3 (Extend) — full brainstorm cycle (blocked on
  Phase 2 implementation).
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
