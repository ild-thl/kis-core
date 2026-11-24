import { test, expect, request as playwrightRequest } from "@playwright/test";

/**
 * A brand new account never faces an empty module list.
 *
 * Two things are checked in one run: the demo modules land in the account on
 * its own, whichever way that account came to be, and once the list does run
 * empty the card offers them back. The dialog behind the card opens on the
 * button and never on its own, an empty list must not throw a window at anybody.
 *
 * The demo flag is deliberately left alone here. Whoever carries it keeps it,
 * so a test run never turns somebody else's modules into demo modules.
 */

const ADMIN = { username: process.env.E2E_USER ?? "a", password: process.env.E2E_PASS ?? "a" };
const SUFFIX = Date.now().toString(36);

test.use({ storageState: { cookies: [], origins: [] } });

test("Leere Modulliste bietet die Demo-Module an", async ({ page, baseURL }) => {
  const admin = await playwrightRequest.newContext({ baseURL });
  expect((await admin.post("/auth/login", { data: ADMIN })).ok()).toBeTruthy();

  const code = await (await admin.post("/api/admin/access-codes", {
    data: {
      label: `E2E Demo Hinweis ${SUFFIX}`,
      max_uses: 2,
      valid_days: 1,
      access_hours: 24,
      askf_role: "staff",
      custom_role_id: null,
    },
  })).json();

  try {
    // Needs "load", not "domcontentloaded", or fills land in the DOM before hydration.
    await page.goto("/de/redeem", { waitUntil: "load" });
    await page.getByTestId("access-code-form").locator("#access-code").fill(code.code);
    await page.getByTestId("access-code-form").locator('button[type="submit"]').click();
    await page.getByTestId("access-code-continue").click();

    await page.goto("/de/workspace", { waitUntil: "domcontentloaded" });

    const demoKurse = await (await page.request.get("/api/ai-assistant/demo/workspaces")).json();
    test.skip(demoKurse.length === 0, "Ohne Demo-Konto gibt es nichts zuzuweisen");

    // They are all there without anybody asking for them.
    await expect(page.locator("tbody tr")).toHaveCount(demoKurse.length);

    // A first login can carry the welcome dialog, and it covers the whole page.
    // It arrives late, after its own request, so counting right away would miss it.
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Los geht's" })
      .click({ timeout: 10_000 })
      .catch(() => { /* not switched on, nothing in the way */ });

    // Now empty the list again, from here on the card is the only way back in.
    for (const m of demoKurse) {
      const weg = await page.request.post("/api/ai-assistant/demo/leave", {
        data: { workspace_uuid: m.uuid },
      });
      expect(weg.ok()).toBeTruthy();
    }
    await page.reload({ waitUntil: "domcontentloaded" });

    // The card stands there, the dialog stays shut until somebody asks for it.
    await expect(page.getByTestId("demo-invite")).toBeVisible();
    await expect(page.getByTestId("demo-hint")).toHaveCount(0);

    await page.getByTestId("demo-hint-open").click();
    await expect(page.getByTestId("demo-hint")).toBeVisible();

    await page.getByTestId("demo-hint-join").click();
    await expect(page.locator("tbody tr")).toHaveCount(demoKurse.length);
    await expect(page.getByTestId("demo-invite")).toHaveCount(0);
  } finally {
    await admin.delete(`/api/admin/access-codes/${code.id}`);
    await admin.dispose();
  }
});
