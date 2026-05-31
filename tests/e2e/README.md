# Playwright E2E suite (M8.9)

End-to-end browser tests for the amanuensis web app. Uses
`@playwright/test` (Node/TypeScript) per project policy.

## One-time setup

```bash
cd tests/e2e
npm install
npx playwright install chromium
```

`npm install` pulls `@playwright/test` and `typescript` into a local
`tests/e2e/node_modules/`. `npx playwright install chromium` downloads
the chromium build Playwright drives (gets cached at
`~/Library/Caches/ms-playwright/` on macOS, `~/.cache/ms-playwright/`
on Linux).

Both `node_modules/` and the playwright-report/test-results
directories are git-ignored.

## Running the suite

### Via pytest (preferred — single CLI surface)

```bash
uv run --no-sync pytest -m e2e
```

`tests/e2e/test_playwright_runs.py` is the pytest hook. It shells out
to `npx playwright test` from this directory and asserts exit 0.
Skips cleanly (with a hint message) when Node, `node_modules`, or
chromium are missing — so the e2e marker is safe to leave selectable
even on hosts without the full toolchain.

### Via Playwright directly

```bash
cd tests/e2e
npx playwright test                  # all specs, all workers
npx playwright test --headed         # show the browser
npx playwright test --ui             # interactive UI mode
npx playwright show-report           # open the last HTML report
```

## Specs

| File | Purpose |
| --- | --- |
| `test_phase1_smoke.spec.ts` | Dashboard → source overview → atoms → atom detail (`<mark>` highlight) → relations (Cytoscape mount + JSON payload). |
| `test_graph_state_persistence.spec.ts` | PM-6 mitigation: relation-graph survives reload + Alpine binding is wired. **Degraded** from full state-persistence per spec — see file docstring. |
| `test_phase1_graph_stress.spec.ts` | PM-5 mitigation: ~250 atoms / ~750 relations renders within 8s budget. **Downgraded** from the 1000/3000 target — see docstring + below. |

## Fixture workspace

`globalSetup.ts` runs once per `playwright test` invocation and
shells out to `_fixture_builder.py` to populate
`fixtures/workspace/`. Two distillations are planted:

- **`phase1-smoke`** — 1 atom, 1 self-loop relation, 1 source-mirror
  paragraph. Drives the smoke spec.
- **`phase1-stress`** — 250 atoms, 750 chained relations. Drives the
  stress spec.

`fixtures/workspace/` is git-ignored (regenerated on demand). The
generated state is cached under `fixtures/workspace/.built`; deleting
that sentinel forces a rebuild on the next run.

### Why 250 / 750 instead of 1000 / 3000?

Three reasons (all documented in `_fixture_builder.py` and the stress
spec):

1. **Soft-cap is 750 atoms / 2000 edges** (M8.4 plan). 250/750 sits
   under the cap, exercising the path the supervisor sees on every
   realistic distillation.
2. **Build time.** Substrate does one atomic file write per atom +
   per provenance + per relation. 1000/3000 takes ~60s; 250/750
   takes ~10s. The globalSetup budget matters more than the absolute
   stress numbers when this lane runs on every pre-push.
3. **Soft-cap fallback was deferred.** M8.4 ships the structural
   separation (`#cy` stable, `#cy-data` swappable) but NOT a
   view-by-section fallback. There's nothing for an over-the-cap
   fixture to assert that an under-the-cap fixture doesn't already
   cover.

If a future milestone adds the section-fallback UI, bump
`N_STRESS_ATOMS` / `N_STRESS_RELATIONS` in `_fixture_builder.py` to
exercise it.

## Known gaps / degradations

- **State-persistence is a smoke check, not exhaustive.** The cy
  instance is closed over inside the Alpine component (no `window.cy`
  export), so the spec asserts the wiring is intact but cannot
  introspect cy state directly. Lifting the closure is a future
  milestone.
- **Stress spec asserts render time, not memory.** A heap-profile
  capture lives in the chrome-devtools MCP world; M8.9 keeps the
  pytest hook self-contained.
- **`webServer.command` uses `cd ../..`.** This is fragile if the
  Playwright config is ever moved. The path resolution happens
  relative to where Playwright spawns the shell; if you move this
  file, fix the command.
