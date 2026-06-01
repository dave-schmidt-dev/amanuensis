// Phase 2b M11 — supervisor exercises the cross-doc overlay flow.
//
// Fixture dependency: ``_fixture_builder.py`` plants a CrossDocRelation
// connecting ``phase1-smoke`` to ``phase2b-cross-doc`` with shared
// canonical entity ``ACME``. The supervisor:
//
//   1. Opens the relation-graph page for the smoke distillation.
//   2. Confirms the ``#cross-doc-toggle`` checkbox is rendered.
//   3. Toggles the overlay on and confirms the
//      ``/distillations/<src>/relations/atom-entity-index?include_cross_doc=1``
//      fetch fires (visible via the network event) AND the response
//      payload carries at least one ``cross_doc_edges`` entry.
//   4. Navigates to ``/cross-doc-relations`` (the list page) and confirms
//      the planted relation row is visible.
//   5. Clicks through to the detail page (``/cross-doc-relations/<id>``)
//      and confirms the warrant text + kind badge render.
//
// The Cytoscape edge-click → navigation handler is exercised in unit
// tests against the JS module (out of scope here); this spec confirms
// the URL surface + the HTTP surface that the overlay JS consumes.

import { expect, test } from "@playwright/test";

test.describe("phase-2b: cross-doc overlay flow", () => {
  test("graph view exposes the cross-doc toggle", async ({ page }) => {
    await page.goto("/distillations/phase1-smoke/relations");
    const toggle = page.locator("#cross-doc-toggle");
    await expect(toggle).toBeVisible();
    await expect(toggle).not.toBeChecked();
  });

  test("cross-doc atom-entity-index fragment serves overlay payload", async ({
    page,
  }) => {
    // Direct probe of the route the overlay JS consumes. We GET the
    // same URL ``cross_doc_overlay.js`` builds when the toggle is
    // checked and assert the response shape. This bypasses the
    // Cytoscape ``init()`` path (which depends on ``cose-bilkent``
    // and is exercised separately by the phase-1 smoke spec) and
    // pins down the HTTP contract that the overlay JS depends on.
    await page.goto("/distillations/phase1-smoke/relations");
    const overlayUrl =
      "/distillations/phase1-smoke/relations/atom-entity-index?include_cross_doc=1";
    const response = await page.request.get(overlayUrl);
    expect(response.status()).toBe(200);
    const payload = (await response.json()) as {
      cross_doc_edges?: Array<{
        id: string;
        kind: string;
        from_source_id: string;
        to_source_id: string;
      }>;
    };
    expect(Array.isArray(payload.cross_doc_edges)).toBe(true);
    expect((payload.cross_doc_edges ?? []).length).toBeGreaterThanOrEqual(1);
    // The planted edge connects phase1-smoke to phase2b-cross-doc; the
    // fragment is filtered via ``touching_source`` so phase1-smoke must
    // appear on one endpoint.
    const edge = (payload.cross_doc_edges ?? [])[0];
    expect(
      edge.from_source_id === "phase1-smoke" ||
        edge.to_source_id === "phase1-smoke",
    ).toBe(true);
  });

  test("supervisor opens the cross-doc relations list and detail page", async ({
    page,
  }) => {
    await page.goto("/cross-doc-relations");

    // The list page links every row's id to /cross-doc-relations/<id>.
    // Confirm the planted relation row is present and pick the first
    // such link, follow it, and assert the detail page renders the
    // warrant text from the fixture.
    const detailLink = page
      .locator('a[href^="/cross-doc-relations/x-"]')
      .first();
    await expect(detailLink).toBeVisible();

    // The planted relation kind is "supports"; assert it shows in the
    // table body (the kind dropdown also contains the option, so scope
    // to the tbody to disambiguate).
    await expect(
      page.locator("tbody >> text=supports").first(),
    ).toBeVisible();

    await detailLink.click();

    // URL is now /cross-doc-relations/x-<hash> — assert the page exposes
    // the warrant block. The fixture warrant text starts with the phrase
    // "Both atoms describe ACME's payment obligation".
    await expect(
      page.getByRole("heading", { name: /^warrant$/i }),
    ).toBeVisible();
    await expect(
      page.getByText("Both atoms describe ACME's payment obligation"),
    ).toBeVisible();
  });
});
