import { expect, test, type Page } from "@playwright/test";

/** Smoke checks for the flows the HTML comparison of the cleanup could not reach. */

const WORKSPACE = process.env.E2E_WORKSPACE ?? "1ea7b2fa-b237-4bbd-801b-c9793d388984";
const PDF_NAME = "01_Einführung_WissenschaftlichesSeminar2.pdf";
const VIDEO_NAME = "VL1_25-03-2026.webm";

function fehlerSammeln(page: Page): string[] {
  const fehler: string[] = [];
  page.on("pageerror", (e) => fehler.push(e.message));
  return fehler;
}

async function openWorkspace(page: Page) {
  await page.addInitScript((uuid) => {
    localStorage.setItem(`ki-assistent-panels-${uuid}`, JSON.stringify({ quellen: true, chat: true, studio: true }));
  }, WORKSPACE);
  await page.goto(`/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-tour="chat-panel"]')).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(1_500);
  await page.keyboard.press("Escape");
}

test.describe("angemeldet", () => {
  test.use({ viewport: { width: 1600, height: 900 } });

  test("PDF-Viewer zeigt die erste Seite", async ({ page }) => {
    const fehler = fehlerSammeln(page);
    await openWorkspace(page);
    await page.locator('[data-tour="sources-panel"]').getByText(PDF_NAME).first().click();
    const viewer = page.locator('[data-tour="pdf-viewer"]');
    await expect(viewer).toBeVisible();
    await expect(viewer.locator("canvas, img").first()).toBeVisible({ timeout: 30_000 });
    await expect(viewer.getByTestId("pdf-load-failed")).toHaveCount(0);
    await page.screenshot({ path: "e2e/screens/klick-pdf.png" });
    expect(fehler).toEqual([]);
  });

  test("Video öffnet mit Transkript", async ({ page }) => {
    const fehler = fehlerSammeln(page);
    await openWorkspace(page);
    await page.locator('[data-tour="sources-panel"]').getByText(VIDEO_NAME).first().click();
    const transkript = page.locator('[data-tour="transcript-panel"]');
    await expect(transkript).toBeVisible({ timeout: 30_000 });
    await expect.poll(async () => (await transkript.innerText()).length, { timeout: 30_000 }).toBeGreaterThan(200);
    await expect(page.locator("video").first()).toBeVisible();
    await page.screenshot({ path: "e2e/screens/klick-transkript.png" });
    expect(fehler).toEqual([]);
  });

  test("Meine Jobs listet Aufträge", async ({ page }) => {
    const fehler = fehlerSammeln(page);
    await page.goto("/my-jobs", { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: /^(Meine Jobs|My jobs)$/ })).toBeVisible({ timeout: 30_000 });
        await page.screenshot({ path: "e2e/screens/klick-my-jobs.png" });
    expect(fehler).toEqual([]);
  });

  test("Dolmetscher übersetzt einen getippten Satz", async ({ page }) => {
    test.setTimeout(120_000);
    const fehler = fehlerSammeln(page);
    await page.goto("/tools/interpreter", { waitUntil: "domcontentloaded" });
    const feld = page.getByRole("textbox", { name: /^(Dein Text|Your text)$/ }).first();
    await expect(feld).toBeVisible({ timeout: 30_000 });
    await feld.fill("Guten Morgen, wie geht es dir heute?");
    await feld.press("Enter");
    await expect.poll(async () => {
      for (const f of await page.getByRole("textbox", { name: /Übersetzung|Translation/ }).all()) {
        if ((await f.inputValue()).trim()) return true;
      }
      return false;
    }, { timeout: 90_000 }).toBe(true);
    await page.screenshot({ path: "e2e/screens/klick-dolmetscher.png" });
    expect(fehler).toEqual([]);
  });
});

test.describe("abgemeldet", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("Login: Reiter Zugangscode meldet einen falschen Code", async ({ page }) => {
    const fehler = fehlerSammeln(page);
    await page.goto("/login", { waitUntil: "domcontentloaded" });
    await page.waitForSelector("#username");
    const reiter = page.getByRole("tab", { name: /Mit Zugangscode|With access code/ }).or(page.getByRole("button", { name: /Mit Zugangscode|With access code/ }));
    test.skip(await reiter.count() === 0, "access codes are switched off on this instance");
    await reiter.first().click();
    await page.locator("#access-code").fill("ASKF-ZZZZ-0000");
    await page.getByTestId("access-code-form").locator('button[type="submit"]').click();
    await expect(page.getByTestId("access-code-form").getByRole("alert")).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: "e2e/screens/klick-login-code.png" });
    expect(fehler).toEqual([]);
  });

  test("Redeem: falscher Code zeigt eine Meldung", async ({ page }) => {
    const fehler = fehlerSammeln(page);
    await page.goto("/redeem", { waitUntil: "load" });
    await expect(page.getByRole("heading", { name: /Zugang einlösen|Redeem access/ })).toBeVisible({ timeout: 30_000 });
    await page.locator("#access-code").fill("ASKF-ZZZZ-0000");
    await page.getByTestId("access-code-form").locator('button[type="submit"]').click();
    await expect(page.getByTestId("access-code-form").getByRole("alert")).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: "e2e/screens/klick-redeem.png" });
    expect(fehler).toEqual([]);
  });
});
