// Phase-1 smoke spec — exercises the full read surface end-to-end via Playwright.
//
// Scope (per M8.9):
//   1. Load the dashboard (/) and assert it renders.
//   2. Click into a distillation; assert the source overview renders.
//   3. Click into atoms; assert the atom table renders at least one row.
//   4. Click into an atom-detail page; assert the source-paragraph
//      <mark> highlight is present.
//   5. Navigate to the relations page; assert the Cytoscape <div id="cy">
//      mount is present AND the JSON payload <script id="cy-data"> is
//      parseable JSON with a non-empty `elements` array.
//
// Fixture: planted by globalSetup.ts at fixtures/workspace/. Distillation
// `phase1-smoke` is the small one with 1 atom + 1 relation + 1 paragraph.

import { expect, test } from "@playwright/test";

const SMOKE_SOURCE = "phase1-smoke";

test.describe("phase-1 smoke: dashboard → overview → atoms → detail → relations", () => {
  test("dashboard renders and links into the smoke distillation", async ({ page }) => {
    await page.goto("/");
    // Title from base.html should mention "amanuensis"; the dashboard h1 says "distillations".
    await expect(page).toHaveTitle(/amanuensis|dashboard/i);
    await expect(page.getByRole("heading", { name: "distillations" })).toBeVisible();
    // Smoke source id should appear as a link.
    const smokeLink = page.getByRole("link", { name: SMOKE_SOURCE });
    await expect(smokeLink).toBeVisible();
  });

  test("source overview renders with manifest summary", async ({ page }) => {
    await page.goto(`/distillations/${SMOKE_SOURCE}`);
    // The source-overview template renders the source-id in the page h1
    // AND a "source-mirror manifest" section.
    await expect(page.locator("h1")).toContainText(SMOKE_SOURCE);
    await expect(page.getByRole("heading", { name: "source-mirror manifest" })).toBeVisible();
  });

  test("atom browser renders at least one atom row", async ({ page }) => {
    await page.goto(`/distillations/${SMOKE_SOURCE}/atoms`);
    // The fragment template renders a table whose <tbody> rows are the atoms.
    // We assert >= 1 tbody row exists; the smoke fixture has exactly 1.
    const rows = page.locator("table tbody tr");
    await expect(rows).toHaveCount(1);
    // The single row should link to atom detail.
    const atomLink = rows.first().locator(`a[href^="/distillations/${SMOKE_SOURCE}/atoms/a-"]`);
    await expect(atomLink).toBeVisible();
  });

  test("atom detail renders the <mark> highlight from the source paragraph", async ({ page }) => {
    await page.goto(`/distillations/${SMOKE_SOURCE}/atoms`);
    const atomLink = page
      .locator(`a[href^="/distillations/${SMOKE_SOURCE}/atoms/a-"]`)
      .first();
    await atomLink.click();
    // Atom detail page: the <mark> tag is the source-paragraph highlight.
    const highlight = page.locator("mark");
    await expect(highlight).toBeVisible();
    // Char-span 0..30 of the fixture paragraph body covers "ACME shall pay within 30 days".
    await expect(highlight).toContainText("ACME shall pay within 30 days");
  });

  test("relations page renders #cy mount AND parseable #cy-data JSON", async ({ page }) => {
    await page.goto(`/distillations/${SMOKE_SOURCE}/relations`);
    // The Cytoscape mount div MUST exist and MUST NOT be the swap target.
    const cyDiv = page.locator("#cy");
    await expect(cyDiv).toBeVisible();
    // The JSON payload block is a <script type="application/json" id="cy-data">.
    // Its textContent must parse as JSON with an `elements` array.
    const cyDataText = await page.locator("#cy-data").textContent();
    expect(cyDataText, "#cy-data textContent must not be null").not.toBeNull();
    const parsed: unknown = JSON.parse(cyDataText ?? "");
    expect(parsed).toHaveProperty("elements");
    const elements = (parsed as { elements: unknown[] }).elements;
    expect(Array.isArray(elements)).toBe(true);
    // Smoke fixture has 1 atom + 1 self-loop relation → 2 elements (node + edge).
    expect(elements.length).toBeGreaterThanOrEqual(2);
  });
});
