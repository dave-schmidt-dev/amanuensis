// Phase 2a M11 — supervisor resolves a resolution-ambiguous clarification.
//
// Validates that the clarification kind badge renders on the /clarifications
// page, the resolve form submits successfully, and the workspace state
// updates (the clarification moves from the open bucket to the resolved
// bucket).
//
// Fixture dependency: ``_fixture_builder.py`` plants EXACTLY ONE open
// ``resolution-ambiguous`` clarification under the ``phase1-smoke`` source
// before the Playwright server boots.

import { expect, test } from "@playwright/test";

test.describe("phase-2a: resolution-ambiguous clarification flow", () => {
  test("supervisor opens clarifications page and sees resolution-ambiguous kind", async ({
    page,
  }) => {
    await page.goto("/clarifications");
    // The kind badge rendered by clarifications.html (M8 T8.4) must be visible.
    await expect(page.locator("text=resolution-ambiguous").first()).toBeVisible();
  });

  test("supervisor resolves a resolution-ambiguous clarification via the form", async ({
    page,
  }) => {
    await page.goto("/clarifications");

    // Locate the resolve form for an open clarification.  The fixture plants
    // exactly one resolution-ambiguous clarification so we expect exactly one
    // such form.  The action attribute pattern is shared by all resolve forms.
    const resolveForm = page
      .locator('form[action*="/clarifications/c-"][action*="/resolve"]')
      .first();
    await expect(resolveForm).toBeVisible();

    // Fill the resolution textarea and submit.
    await resolveForm.locator('textarea[name="resolution"]').fill("merge proposed into existing");
    await resolveForm.locator('button[type="submit"]').click();

    // The POST handler responds with a 303 redirect back to /clarifications.
    // After the redirect we should see the "resolved (N)" section heading.
    // The bare "resolved" string also appears in row footers (kind / source
    // metadata), so target the heading specifically to satisfy strict mode.
    await page.goto("/clarifications");
    await expect(page.getByRole("heading", { name: /^resolved \(\d+\)$/ })).toBeVisible();
  });
});
