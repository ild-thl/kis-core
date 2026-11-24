import { test, expect } from "@playwright/test";

/** The info assistant answers with sources and keeps the chat in the history. */
test.describe("Infoassistent", () => {
  test("Beispielfrage bringt Antwort mit Quellen und legt einen Chat an", async ({ page }) => {
    await page.goto("/tools/info", { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="campus-examples"]', { timeout: 30_000 });

    await page.locator('[data-testid="campus-examples"] button').nth(3).click();
    const answer = page.locator('[data-testid="assistant-message"]').first();
    await expect(answer).toBeVisible({ timeout: 30_000 });
    await expect(answer.locator('[data-testid="campus-sources"]')).toBeVisible({ timeout: 90_000 });

    // The question became the title of a new chat in the history.
    await expect(page.locator('[data-testid="campus-history"] li').first()).toBeVisible();
  });

  test("ein neuer Chat startet leer", async ({ page }) => {
    await page.goto("/tools/info", { waitUntil: "domcontentloaded" });
    await page.locator('[data-testid="campus-new-chat"]').click();
    await expect(page.locator('[data-testid="campus-examples"]')).toBeVisible();
    await expect(page.locator('[data-testid="assistant-message"]')).toHaveCount(0);
  });

  test("Logo fuehrt zu den Workspaces, die Leiste klappt ein", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto("/tools/info", { waitUntil: "domcontentloaded" });
    const leiste = page.locator('[data-testid="campus-history"]');
    await expect(leiste).toBeVisible({ timeout: 30_000 });

    await expect(leiste.locator('[data-testid="campus-home"]')).toHaveAttribute("href", /\/workspace$/);
    await expect(page.locator('a[href$="/workspace"]:visible')).toHaveCount(1);

    await page.locator('[data-testid="campus-sidebar-toggle"]').click();
    const streifen = page.locator('[data-testid="campus-history-collapsed"]');
    await expect(streifen).toBeVisible();
    await expect(streifen.locator('img[src*="askfrancis-icon"]')).toBeVisible();
    await expect(streifen.locator("button, a")).toHaveCount(2);
    await streifen.locator('[data-testid="campus-new-chat"]').click();
    await expect(page.locator('[data-testid="campus-examples"]')).toBeVisible();

    // The choice survives a reload.
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator('[data-testid="campus-history-collapsed"]')).toBeVisible({ timeout: 30_000 });
    await page.locator('[data-testid="campus-sidebar-toggle"]').click();
    await expect(page.locator('[data-testid="campus-history"]')).toBeVisible();
  });

  test("am Handy oeffnet das Leistensymbol den Verlauf", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/tools/info", { waitUntil: "domcontentloaded" });
    await page.locator('[data-testid="campus-menu"]').click();
    const leiste = page.locator('[data-testid="campus-history"]:visible');
    await expect(leiste).toBeVisible();
    const breite = (await leiste.boundingBox())?.width ?? 0;
    expect(breite).toBeGreaterThan(300);
    expect(breite).toBeLessThan(390);
    await leiste.locator('[data-testid="campus-sidebar-toggle"]').click();
    await expect(leiste).toHaveCount(0);
  });
});
