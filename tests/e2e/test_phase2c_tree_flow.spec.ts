// Phase 2c M13 — supervisor exercises the probandum-tree flow.
//
// Fixture dependency: ``_fixture_builder.py`` plants 1 ultimate +
// 1 penultimate + 1 interim probandum, linked top-to-bottom via
// supports edges. The supervisor:
//
//   1. Opens ``/probanda`` and confirms the planted probanda appear
//      in the browser table.
//   2. Clicks an ultimate-row link → ``/probanda/<id>`` and confirms
//      the detail page renders the statement, kind badge, scheme,
//      and the "tree view" link.
//   3. Clicks through to ``/probanda/<id>/tree`` and confirms the
//      Cytoscape container mounts.
//   4. Probes the sibling JSON endpoint ``/probanda/<id>/tree.json``
//      directly and confirms it returns a valid Cytoscape elements
//      shape (``nodes`` + ``edges`` arrays).
//
// Scope-down note (matches Phase 2b T11.2): Cytoscape's actual
// rendering in headless Chromium is brittle because the vendored
// dagre+cytoscape-dagre layout interacts poorly with the runner's
// JIT timing. We assert the canvas's container mounts (a stable
// data attribute on ``#probandum-tree-root``) AND the JSON endpoint's
// response shape — that's the substantive contract the page consumes.
// Pixel-level Cytoscape rendering is left to the unit tests in
// ``tests/web/test_probandum_tree_route_*.py``.

import { expect, test } from "@playwright/test";

test.describe("phase-2c: probandum tree flow", () => {
  test("probanda list renders the planted probanda", async ({ page }) => {
    await page.goto("/probanda");

    // The probanda browser is a <table> with one row per probandum.
    // The fixture plants 3 probanda (ultimate / penultimate / interim);
    // every row's id is rendered as a link to /probanda/<id>.
    const detailLinks = page.locator('a[href^="/probanda/p-"]');
    await expect(detailLinks.first()).toBeVisible();

    // Confirm all three kinds appear in the table body (the dropdown
    // also contains the words so we scope to tbody).
    await expect(
      page.locator("tbody >> text=ultimate").first(),
    ).toBeVisible();
    await expect(
      page.locator("tbody >> text=penultimate").first(),
    ).toBeVisible();
    await expect(
      page.locator("tbody >> text=interim").first(),
    ).toBeVisible();
  });

  test("probandum detail page renders statement + tree-view link", async ({
    page,
  }) => {
    await page.goto("/probanda");

    // Find the first ultimate row and follow its detail link. The list
    // page sorts by id-lex, so the first ultimate link is deterministic
    // across runs. Use a row-scoped locator so we land on the right link.
    const ultimateRow = page
      .locator("tbody tr")
      .filter({ has: page.locator("text=ultimate") })
      .first();
    const detailLink = ultimateRow
      .locator('a[href^="/probanda/p-"]')
      .first();
    await expect(detailLink).toBeVisible();
    await detailLink.click();

    // URL is now /probanda/p-<hash>. Confirm the detail-page sections
    // the template renders. ``statement`` / ``alternatives
    // considered`` / ``tree view`` are <h2> headings; ``scheme`` is a
    // <p> label inside a grid card, so it's scoped with text= instead
    // of getByRole("heading").
    await expect(
      page.getByRole("heading", { name: /^statement$/i }),
    ).toBeVisible();
    await expect(page.locator("text=scheme").first()).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /^alternatives considered$/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /^tree view$/i }),
    ).toBeVisible();

    // The "open Cytoscape subtree view" link points at the tree page.
    const treeLink = page.locator('a[href$="/tree"]').first();
    await expect(treeLink).toBeVisible();
    await treeLink.click();

    // Cytoscape mount target is on the page even if the rendering
    // itself is brittle in headless Chromium. The data-tree-url
    // attribute pins the JSON endpoint the JS consumes.
    const treeRoot = page.locator("#probandum-tree-root");
    await expect(treeRoot).toBeVisible();
    await expect(treeRoot).toHaveAttribute("data-probandum-id", /^p-/);
    await expect(treeRoot).toHaveAttribute(
      "data-tree-url",
      /^\/probanda\/p-[0-9a-f]+\/tree\.json$/,
    );
  });

  test("tree.json endpoint returns Cytoscape-compatible payload", async ({
    page,
  }) => {
    // Pick a probandum id off the list page (the first row's link).
    await page.goto("/probanda");
    const firstHref = await page
      .locator('a[href^="/probanda/p-"]')
      .first()
      .getAttribute("href");
    expect(firstHref).toMatch(/^\/probanda\/p-[0-9a-f]+$/);

    const probandumId = firstHref!.split("/").pop()!;
    const jsonUrl = `/probanda/${probandumId}/tree.json`;
    const response = await page.request.get(jsonUrl);
    expect(response.status()).toBe(200);

    const payload = (await response.json()) as {
      nodes?: Array<{ data: { id: string; kind?: string } }>;
      edges?: Array<{ data: { id: string; source: string; target: string } }>;
      truncated?: boolean;
    };
    // Cytoscape elements shape: nodes + edges arrays.
    expect(Array.isArray(payload.nodes)).toBe(true);
    expect(Array.isArray(payload.edges)).toBe(true);
    // The seed node (the probandum the page was opened on) is always
    // in the nodes array.
    const ids = (payload.nodes ?? []).map((n) => n.data.id);
    expect(ids).toContain(probandumId);
    // Untruncated for a 3-node tree.
    expect(payload.truncated).toBe(false);
  });
});
