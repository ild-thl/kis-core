import { test, expect, type Page } from "@playwright/test";

/**
 * A note, chat answer or tool can still cite a source that was removed since.
 * Its chip must not open the viewer, and the viewer itself must never offer
 * the library's own "open a file" screen.
 */

const WORKSPACE = process.env.E2E_WORKSPACE ?? "1ea7b2fa-b237-4bbd-801b-c9793d388984";
const GONE_UUID = "deadbeefdeadbeefdeadbeefdeadbeef";
const PDF_NAME = "01_Einführung_WissenschaftlichesSeminar2.pdf";
const API = `/api/ai-assistant/workspaces/${WORKSPACE}`;

test.use({ viewport: { width: 1600, height: 900 }, locale: "de-DE" });

async function openWorkspace(page: Page, studioTab = "tools") {
  await page.addInitScript(({ uuid, tab }) => {
    localStorage.setItem(`ki-assistent-panels-${uuid}`, JSON.stringify({ quellen: true, chat: true, studio: true }));
    sessionStorage.setItem("askf-studio-tab", tab);
  }, { uuid: WORKSPACE, tab: studioTab });
  await page.goto(`/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
  await expect(page.locator('[data-tour="chat-panel"]')).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1_500);
  await page.keyboard.press("Escape");
}

test("ein Chip auf eine entfernte Quelle oeffnet den Viewer nicht", async ({ page }) => {
  const marker = `Verwaiste Notiz ${Date.now()}`;
  const res = await page.request.post(`${API}/notes`, {
    data: {
      content: `${marker} [Q1:${GONE_UUID}, S. 1]`,
      source_uuids: [GONE_UUID],
      popup_selection: { uuid: GONE_UUID, page: 1, text: marker },
      auto_title: false,
    },
  });
  expect(res.ok()).toBeTruthy();
  const note = await res.json();

  try {
    await openWorkspace(page, "notes");
    const studio = page.locator('[data-tour="studio-panel"]');
    await studio.getByText(marker).first().click();
    const chip = studio.locator(".chip-cite").first();
    await expect(chip).toBeVisible();
    await expect(chip).toHaveAttribute("aria-disabled", "true");

    await chip.dispatchEvent("pointerdown", { button: 0 });
    // The material list below the note names the source as removed and opens nothing either.
    await studio.getByText("1 Material").click();
    const entry = studio.locator('[aria-disabled="true"]').filter({ hasText: "Quelle entfernt" });
    await expect(entry).toBeVisible();
    await entry.click({ force: true });
    await page.waitForTimeout(1_500);
    await expect(page.locator("embedpdf-container")).toHaveCount(0);
    await expect(page.locator('[data-tour="pdf-viewer"]')).toHaveCount(0);
  } finally {
    await page.request.delete(`${API}/notes/${note.id}`);
  }
});

test("laesst sich eine Datei nicht laden, bietet der Viewer kein eigenes Oeffnen an", async ({ page }) => {
  await page.route("**/sources/*/file", (route) => route.fulfill({ status: 404, body: "not found" }));
  await openWorkspace(page);

  await page.locator('[data-tour="sources-panel"]').getByText(PDF_NAME).first().click();
  const viewer = page.locator('[data-tour="pdf-viewer"]');
  await expect(viewer).toBeVisible();

  await expect(viewer.getByTestId("pdf-load-failed")).toBeVisible({ timeout: 15_000 });
  // Neither the library's error screen nor its empty state may show up.
  await expect(viewer.getByRole("button", { name: /Datei öffnen|Open File|Schließen|Close/ })).toHaveCount(0);
});
