# Tasks

Per-project task and work-in-progress tracking across sessions and agents.

Status key: `pending` | `in progress` | `done` | `blocked`.

Active plan: `~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29.md`
Active tasks: `~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29-tasks.md`
Synthesis record: `~/Documents/Projects/.plans/amanuensis/phase1-distill-foundation-2026-05-29-synthesis.md`

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

- [pending] Phase 2 (Map) — full brainstorm cycle required before
  planning. Standing pattern: brainstorm → plan → synthesis → 56-task
  breakdown → fresh implementation session, mirroring the Phase 1
  cycle. Phase 2 scope (per INV-9): cross-document entity resolution,
  support/attack edges spanning documents, probandum hierarchies
  spanning sources. Inputs to the brainstorm: Phase 1 ship's open
  follow-ups (see HISTORY 2026-05-30), the standing INV-2/INV-8
  gate gaps, and any real-engagement findings if Phase 1 has been
  exercised on a live matter.
- [pending] Phase 3 (Extend) — full brainstorm cycle (blocked on
  Phase 2 implementation).
- [pending] Phase 4 (Synthesize) — packaging into agent-usable
  product.

## Standing tasks

- [pending] When second engagement starts: instantiate domain config
  for that engagement (vocabulary, scheme catalogue, probandum
  template). Phase 1's substrate schema designed to absorb this
  without rewrite.
- [pending] Lockfile commit — `uv.lock` currently gitignored;
  first CI run will fail at `uv sync --frozen` until `uv lock &&
  git add -f uv.lock && git commit` + removal from `.gitignore`
  lands. Documented inline at the top of
  `.github/workflows/ci.yml`.
