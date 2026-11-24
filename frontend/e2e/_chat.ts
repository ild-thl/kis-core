import { Page, Locator, expect } from "@playwright/test";

/** Seeded dev workspace (owner = account `a`) with 3 PDFs + 3 lecture videos. */
export const WS =
  process.env.E2E_WORKSPACE ??
  "/en/workspace/1ea7b2fa-b237-4bbd-801b-c9793d388984";

/** Open the workspace and wait until the chat input + source list are ready. */
export async function openWorkspace(page: Page): Promise<void> {
  await page.goto(WS, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("textarea", { timeout: 30_000 });
  // The sources are only ticked after the layout settles, so wait briefly.
  await page.waitForTimeout(2_500);
}

/** Type a question and submit it (Enter, matching the real keybinding). */
export async function ask(page: Page, question: string): Promise<void> {
  const ta = page.locator("textarea").first();
  await ta.fill(question);
  await ta.press("Enter");
}

/** Asks a question and returns exactly the new answer bubble. */
export async function askAndGetAnswer(page: Page, question: string): Promise<Locator> {
  const answers = page.locator('[data-testid="assistant-message"]');
  const before = await answers.count();
  await ask(page, question);
  await expect(answers).toHaveCount(before + 1, { timeout: 60_000 });
  return answers.last();
}

/** Citation chips inside a specific message bubble (optionally further filtered). */
export function chipsIn(answer: Locator, suffix = ""): Locator {
  return answer.locator(`.chip-cite${suffix}`);
}

/** Expands every chip position of the answer so the chips become clickable. */
export async function revealChipsIn(answer: Locator, timeout = 90_000): Promise<void> {
  await expect(answer.locator(".chip-toggle").first()).toBeVisible({ timeout });
  const closed = answer.locator('.chip-toggle[aria-label^="+"]');
  const deadline = Date.now() + timeout;
  while ((await closed.count()) > 0 && Date.now() < deadline) {
    await closed.first().click();
  }
}

/** Wait for the first citation chip within a given answer bubble. */
export async function waitForChipIn(answer: Locator): Promise<Locator> {
  await revealChipsIn(answer);
  const chip = chipsIn(answer).first();
  await expect(chip).toBeVisible({ timeout: 90_000 });
  return chip;
}

/** Narrows the active sources down to exactly one. */
export async function selectOnlySourceByName(page: Page, namePart: string): Promise<void> {
  // Untick everything instead of relying on a translated label.
  const ticked = page.locator("button.source-checkbox:has(svg)");
  for (let guard = 0; (await ticked.count()) > 0 && guard < 20; guard++) {
    await ticked.first().click();
    await page.waitForTimeout(150);
  }
  const row = page.locator("div.group.relative").filter({ hasText: namePart }).first();
  await row.locator("button.source-checkbox").click();
  await page.waitForTimeout(300);
  // Self-verify: exactly one source is now active (else the scoping is a lie).
  await expect(page.locator("button.source-checkbox:has(svg)")).toHaveCount(1);
}

/** Counts the yellow highlights in the PDF, chips highlight nothing. */
export async function highlightRectCount(page: Page): Promise<number> {
  return page.evaluate(() => {
    const host = document.querySelector("embedpdf-container") as Element | null;
    const root = (host && (host as unknown as { shadowRoot: ShadowRoot }).shadowRoot) || null;
    if (!root) return 0;
    let n = 0;
    for (const el of Array.from(root.querySelectorAll<HTMLElement>("*"))) {
      const bg = getComputedStyle(el).backgroundColor || "";
      if (bg.includes("255, 225, 77")) n++; // CITATION_HL_COLOR (#FFE14D) fill
    }
    return n;
  });
}

/** Current playback position of the media player (-1 if no player mounted). */
export async function mediaCurrentTime(page: Page): Promise<number> {
  return page.evaluate(() => {
    const m = document.querySelector<HTMLMediaElement>("video, audio");
    return m ? m.currentTime : -1;
  });
}

