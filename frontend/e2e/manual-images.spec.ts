import { test, expect, type Page } from "@playwright/test";

/**
 * Takes the screenshots the manual articles use, in both UI languages. Run it again
 * whenever the interface changes: E2E_BASE_URL=http://localhost:3010 npx playwright test manual-images
 */
const LOCALES = ["de", "en"] as const;
const SIZE = { width: 1440, height: 900 };
const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3000";
// The demo module "Projektmanagement", so no real course data ends up in the pictures.
const WORKSPACE = process.env.E2E_WORKSPACE ?? "6f2d916b-94a3-403a-ab4d-9000699e5ef0";
/**
 * The demo module is owned by "demo", everyone else only sees the preview. Shots that need
 * ownership (share, module stats) use the logged-in session's own module, else the backend returns 403.
 */
const OWNED = process.env.E2E_OWNED_WORKSPACE ?? "1ea7b2fa-b237-4bbd-801b-c9793d388984";
const OWNED_TITLE = process.env.E2E_OWNED_TITLE ?? "Wiss. Seminar";
/**
 * The stored session has all rights and answered both start page invitations long ago, so that
 * shot logs in as a student who has not. If the cards are gone, this SQL brings them back:
 * UPDATE users SET tour_seen_at = NULL, language_training_asked_at = NULL WHERE username = 'b'
 */
const STUDENT = {
  user: process.env.E2E_STUDENT_USER ?? "b",
  pass: process.env.E2E_STUDENT_PASS ?? "b",
};

/** One picture per page that needs nothing but its address. */
const PAGES: { name: string; path: string }[] = [
  { name: "start-page", path: "/services" },
  { name: "module-list", path: "/workspace" },
  { name: "tool-translation", path: "/tools/translate" },
  { name: "tool-text-to-speech", path: "/tools/tts" },
  { name: "tool-speech-to-text", path: "/tools/stt" },
  { name: "tool-summary", path: "/tools/summarize" },
  { name: "tool-pages", path: "/tools/pages-demo" },
  { name: "tool-image", path: "/tools/image" },
  { name: "tool-screencast", path: "/tools/screencast" },
  { name: "tool-podcast", path: "/tools/podcast" },
  { name: "tool-praesentation", path: "/tools/praesentation" },
  { name: "tool-interpreter", path: "/tools/interpreter" },
  { name: "tool-glossary", path: "/tools/glossary" },
  { name: "my-jobs", path: "/my-jobs" },
];

/** Labels that differ per language, needed to click the right thing. */
const LABELS = {
  de: {
    tabSchedule: "Zeitplan",
    tabNotes: "Notizen",
    tabGlossary: "Glossar",
    tabStats: "Statistik",
    tileVocabCards: "Lernkarten",
    tileGrammar: "Grammatikübung",
    tileVocabulary: "Wortschatzübung",
    tileFlashcards: "Karteikarten",
    tileQuiz: "Quiz",
    tileMindmap: "Mindmap",
    tileTable: "Datentabelle",
    mindmapExpand: "Alle ausklappen",
    mindmapFull: "Vollbild",
    nextMonth: "Nächster Monat",
    allMoods: "Alle Stimmungen nebeneinander",
    showAllCitations: "Alle Belege einblenden",
    profileTakeTest: "Sprachtest starten",
    diagSkip: "Überspringen",
    diagContinue: "Weiter",
  },
  en: {
    tabSchedule: "Schedule",
    tabNotes: "Notes",
    tabGlossary: "Glossary",
    tabStats: "Stats",
    tileVocabCards: "Vocab cards",
    tileGrammar: "Grammar exercises",
    tileVocabulary: "Vocabulary exercises",
    tileFlashcards: "Flashcards",
    tileQuiz: "Quiz",
    tileMindmap: "Mind map",
    tileTable: "Data table",
    mindmapExpand: "Expand all",
    mindmapFull: "Fullscreen",
    nextMonth: "Next month",
    allMoods: "All moods side by side",
    showAllCitations: "Show all citations",
    profileTakeTest: "Start the language test",
    diagSkip: "Skip",
    diagContinue: "Continue",
  },
} as const;

/** Only the harmless admin page: user list and providers show personal data and endpoints. */
const ADMIN_PAGES: { name: string; path: string }[] = [
  { name: "admin-tool-release", path: "/admin/tools/release" },
];

/** German is the default locale and carries no prefix. */
function prefix(locale: string) {
  return locale === "de" ? "" : `/${locale}`;
}

function shot(locale: string, name: string) {
  return `public/manual/${locale}/${name}.png`;
}

/** The saved session carries a language cookie, without this every shot comes out English. */
async function useLocale(page: Page, locale: string) {
  await page.context().addCookies([{ name: "NEXT_LOCALE", value: locale, url: BASE }]);
}

/** Shown once per browser profile and would otherwise sit on top of every start page picture. */
async function closeWelcome(page: Page) {
  const willkommen = page
    .locator("[role=dialog]")
    .filter({ hasText: /Willkommen bei askFrancis|Welcome to askFrancis/ });
  if (await willkommen.count()) {
    await willkommen.locator("button[aria-label]").first().click();
    await expect(willkommen).toHaveCount(0);
  }
}

async function settle(page: Page) {
  await expect(page.locator("header")).toBeVisible();
  // The dialog only opens after its own fetch, so waiting has to come first.
  await page.waitForTimeout(2000);
  await closeWelcome(page);
}

/** Opens the module, then a studio tile, then the first set inside it. */
async function openFirstSet(page: Page, locale: string, tile: string) {
  await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(4000);
  await page.getByText(tile, { exact: true }).first().click();
  await page.waitForTimeout(2500);
  // The set cards are the only clickable boxes in the list.
  await page.locator(".bg-background.rounded-xl").first().click();
  await page.waitForTimeout(3500);
}

test.describe("Handbuch-Bilder", () => {
  // Twice the pixels, so the pictures stay sharp when the article scales them.
  test.use({ viewport: SIZE, deviceScaleFactor: 2 });

  test.describe("ohne Anmeldung", () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    for (const locale of LOCALES) {
      test(`anmeldung ${locale}`, async ({ page }) => {
        await useLocale(page, locale);
        await page.goto(`${prefix(locale)}/login`, { waitUntil: "domcontentloaded" });
        await page.waitForSelector("#username");
        // The sign-in column alone, without Francis on the left and its empty space.
        await page.locator("form").first().locator("xpath=..").screenshot({ path: shot(locale, "sign-in") });
      });
    }
  });

  // Both invitations only show for a person who has not answered yet.
  test.describe("als Studierende", () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    for (const locale of LOCALES) {
      test(`erster-besuch ${locale}`, async ({ page }) => {
        await useLocale(page, locale);
        await page.goto("/login", { waitUntil: "domcontentloaded" });
        await page.waitForSelector("#username");
        await page.fill("#username", STUDENT.user);
        await page.fill("#password", STUDENT.pass);
        await page.locator('button[type="submit"]').click();
        await page.waitForURL((url) => !url.pathname.includes("login"), { timeout: 30_000 });
        // The login lands on "/services", the student is sent on to the module list, the English version needs its address back.
        await page.goto(`${prefix(locale)}/workspace`, { waitUntil: "domcontentloaded" });
        await settle(page);

        const karten = page.locator('[data-tour="tour-invite"]').locator("..");
        await expect(karten).toBeVisible();
        const box = (await karten.boundingBox())!;
        // Header, greeting and both cards; the module list below has its own picture.
        await page.screenshot({
          path: shot(locale, "first-login"),
          clip: { x: 0, y: 0, width: SIZE.width, height: Math.ceil(box.y + box.height + 24) },
        });
      });
    }
  });

  for (const locale of LOCALES) {
    for (const entry of PAGES) {
      test(`${entry.name} ${locale}`, async ({ page }) => {
        await useLocale(page, locale);
        await page.goto(`${prefix(locale)}${entry.path}`, { waitUntil: "domcontentloaded" });
        await settle(page);
        await page.screenshot({ path: shot(locale, entry.name) });
      });
    }

    test(`kalender ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/kalender`, { waitUntil: "domcontentloaded" });
      await settle(page);
      // The current month is empty, the course dates are in the winter semester.
      for (let i = 0; i < 4; i++) {
        await page.getByRole("button", { name: LABELS[locale].nextMonth }).click();
        await page.waitForTimeout(400);
      }
      await page.waitForTimeout(1500);
      await page.screenshot({ path: shot(locale, "calendar") });
    });

    test(`kopfleiste ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/`, { waitUntil: "domcontentloaded" });
      await settle(page);
      await page.locator('header button[aria-haspopup="menu"]').last().click();
      await page.waitForTimeout(500);
      await page.screenshot({ path: shot(locale, "header-menu") });
    });

    test(`feedback ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/feedback`, { waitUntil: "domcontentloaded" });
      await settle(page);
      await page.screenshot({ path: shot(locale, "feedback-form") });
    });

    test(`evaluation-frage ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/evaluation`, { waitUntil: "domcontentloaded" });
      await settle(page);
      // The intro screen always opens first, for the anonymity notice if nothing else.
      const start = page.getByRole("button", { name: /Los geht's|Get started|Weiter|Next/ }).first();
      if (await start.count()) await start.click();
      await page.waitForTimeout(800);
      // The card alone, the rest of the page is empty background and footer.
      const box = (await page.locator(".max-w-md").first().boundingBox())!;
      await page.screenshot({
        path: shot(locale, "evaluation-question"),
        clip: { x: box.x - 16, y: box.y - 16, width: box.width + 32, height: box.height + 32 },
      });
    });

    test(`schnittstellen ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/interfaces`, { waitUntil: "domcontentloaded" });
      await settle(page);
      await expect(page.getByText("Fish Audio", { exact: true })).toBeVisible();
      // Only the narrow column, at full width the empty margins shrink the text in the article.
      const box = (await page.locator(".max-w-2xl").last().boundingBox())!;
      await page.screenshot({
        path: shot(locale, "interfaces"),
        fullPage: true,
        clip: { x: box.x - 24, y: box.y - 24, width: box.width + 48, height: box.height + 48 },
      });
    });

    test(`schnittstelle-schluessel ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      // The recording account has its keys connected, the picture needs a card before that.
      await page.route("**/api/me/interfaces", async (route) => {
        const response = await route.fetch();
        await route.fulfill({ response, json: { ...(await response.json()), interfaces: [] } });
      });
      await page.goto(`${prefix(locale)}/interfaces`, { waitUntil: "domcontentloaded" });
      await settle(page);
      await page.locator("#key-elevenlabs").fill("sk_beispiel_1234567890");
      // The connect button fades in once the key is long enough.
      await page.waitForTimeout(800);
      await page.locator("section").filter({ has: page.locator("#key-elevenlabs") })
        .screenshot({ path: shot(locale, "interfaces-key") });
    });

    for (const entry of ADMIN_PAGES) {
      test(`${entry.name} ${locale}`, async ({ page }) => {
        await useLocale(page, locale);
        await page.goto(`${prefix(locale)}${entry.path}`, { waitUntil: "domcontentloaded" });
        await settle(page);
        await page.screenshot({ path: shot(locale, entry.name) });
      });
    }

    test(`modul-beitreten ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace`, { waitUntil: "domcontentloaded" });
      await settle(page);
      await page.getByTestId("join-open").click();
      await page.waitForTimeout(800);
      await page.screenshot({ path: shot(locale, "join-module") });
    });

    test(`modul-statistik ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace`, { waitUntil: "domcontentloaded" });
      await settle(page);
      await page.locator("tr", { hasText: OWNED_TITLE }).first()
        .getByTestId("workspace-stats").click();
      // The numbers load late, otherwise the spinner ends up in the picture.
      await expect(page.getByText(/Teilnehmer|Participants/).first()).toBeVisible({ timeout: 30_000 });
      await page.waitForTimeout(1500);
      await page.screenshot({ path: shot(locale, "module-stats") });
    });

    test(`modul-anlegen ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace`, { waitUntil: "domcontentloaded" });
      await settle(page);
      await page.locator('button:has-text("+")').last().click();
      await page.waitForTimeout(800);
      await page.screenshot({ path: shot(locale, "create-module") });
    });

    for (const [name, key] of [
      ["schedule-tab", "tabSchedule"],
      ["notes-tab", "tabNotes"],
      ["glossary-tab", "tabGlossary"],
      ["statistics-tab", "tabStats"],
    ] as const) {
      test(`${name} ${locale}`, async ({ page }) => {
        await useLocale(page, locale);
        await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
        await page.waitForTimeout(4000);
        await page.getByRole("button", { name: LABELS[locale][key], exact: true }).click();
        await page.waitForTimeout(2500);
        await page.screenshot({ path: shot(locale, name) });
      });
    }

    for (const [name, key] of [
      ["vocabulary-card-sets", "tileVocabCards"],
      ["grammar-sets", "tileGrammar"],
      ["vocabulary-exercise-sets", "tileVocabulary"],
    ] as const) {
      test(`${name} ${locale}`, async ({ page }) => {
        await useLocale(page, locale);
        await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
        await page.waitForTimeout(4000);
        await page.getByText(LABELS[locale][key], { exact: true }).first().click();
        await page.waitForTimeout(2500);
        await page.screenshot({ path: shot(locale, name) });
      });
    }

    test(`modul-viewer ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);
      // Any PDF, whatever the files in the module are called.
      await page.locator('[title$=".pdf"]').first().click();
      // The PDF renders only after loading, otherwise "Loading document" ends up in the picture.
      await expect(page.getByText(/Loading document/i)).toHaveCount(0, { timeout: 60_000 });
      await page.waitForTimeout(3000);
      await page.screenshot({ path: shot(locale, "viewer") });
    });

    test(`modul-studio ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);
      // By index it would grab a chat bubble, the tab strip identifies the panel.
      const studio = page
        .locator(".rounded-2xl")
        .filter({ hasText: LABELS[locale].tabSchedule })
        .last();
      await studio.screenshot({ path: shot(locale, "studio") });
    });

    test(`modul-chat ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);
      // The middle panel alone, the other two belong to other articles.
      await page.locator(".rounded-2xl").nth(1).screenshot({ path: shot(locale, "chat") });
    });


    for (const [name, key] of [
      ["flashcard", "tileFlashcards"],
      ["quiz-question", "tileQuiz"],
      ["vocabulary-card", "tileVocabCards"],
      ["vocabulary-exercise", "tileVocabulary"],
      ["grammar-exercise", "tileGrammar"],
      ["data-table", "tileTable"],
    ] as const) {
      test(`${name} ${locale}`, async ({ page }) => {
        await useLocale(page, locale);
        await openFirstSet(page, locale, LABELS[locale][key]);
        await page.screenshot({ path: shot(locale, name) });
      });
    }

    test(`modul-mindmap ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await openFirstSet(page, locale, LABELS[locale].tileMindmap);
      // In the narrow panel only the root node is visible, so unfold and go fullscreen.
      await page.locator(`button[title="${LABELS[locale].mindmapExpand}"]`).first().click();
      await page.waitForTimeout(1200);
      await page.locator(`button[title="${LABELS[locale].mindmapFull}"]`).first().click();
      await page.waitForTimeout(2000);
      await page.screenshot({ path: shot(locale, "mind-map") });
    });

    test(`modul-erstellen ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);
      await page.getByText(LABELS[locale].tileFlashcards, { exact: true }).first().click();
      await page.waitForTimeout(2500);
      await page.getByRole("button", { name: /Erstellen|Create/ }).first().click();
      await page.waitForTimeout(1500);
      await page.screenshot({ path: shot(locale, "create-set") });
    });

    test(`modul-freigeben ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace/${OWNED}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);
      await page.locator('[data-tour="share"]').first().click();
      // The links are fetched only on opening.
      await page.waitForTimeout(2500);
      // The enrolment link and its code stay unreadable in the picture, so no address shows.
      await page.evaluate(() => {
        for (const el of document.querySelectorAll("*")) {
          const text = el.children.length === 0 ? (el.textContent ?? "").trim() : "";
          if (/^https?:\/\//.test(text) || /^[0-9a-f]{8}$/.test(text)) (el as HTMLElement).style.filter = "blur(6px)";
        }
      });
      await page.screenshot({ path: shot(locale, "share-module") });
    });

    test(`modul-einstellungen ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);
      // The small gear of the module, not the one in the header.
      await page.locator('button[title="Einstellungen"].w-7, button[title="Settings"].w-7').first().click();
      await page.waitForTimeout(1500);
      await page.screenshot({ path: shot(locale, "module-settings") });
    });


    // The round marks are toggles, the citations only unfold after a click.
    test(`modul-video ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);
      await page.locator('[title$=".mp4"]').first().click();
      // The transcript loads late, otherwise only the player is in the picture.
      await expect(page.getByText(/Transkript|Transcript/i).first()).toBeVisible({ timeout: 60_000 });
      await page.waitForTimeout(4000);
      await page.screenshot({ path: shot(locale, "video") });
    });

    test(`modul-belege ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);
      await page.locator('[data-testid="assistant-message"] .chip-toggle').first().click();
      await expect(page.locator(".chip-cite").first()).toBeVisible();
      await page.waitForTimeout(500);
      await page.screenshot({ path: shot(locale, "citations") });
    });

    test(`modul-beleg-sprung ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);
      await page.locator('[data-testid="assistant-message"] .chip-toggle').first().click();
      const chip = page.locator(".chip-cite").first();
      await expect(chip).toBeVisible();
      await chip.click();
      await page.waitForTimeout(5000);
      await page.screenshot({ path: shot(locale, "citation-jump") });
    });

    test(`modul-ansicht ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(5000);
      await page.screenshot({ path: shot(locale, "module-view") });
    });

    // The selection bar only appears on a real text selection. EmbedPDF draws onto a canvas
    // with no text layer to click, so the pointer drags across the bullet list in the demo slides.
    test(`auswahlleiste ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);
      await page.locator('[title$=".pdf"]').first().click();
      await expect(page.getByText(/Loading document/i)).toHaveCount(0, { timeout: 60_000 });
      await page.waitForTimeout(6000);
      const panel = (await page.locator("[data-tour=\"pdf-viewer\"]").first().boundingBox())!;
      await page.mouse.move(panel.x + 44, panel.y + 400);
      await page.mouse.down();
      await page.mouse.move(panel.x + 282, panel.y + 428, { steps: 20 });
      await page.mouse.up();
      await page.waitForTimeout(1800);
      await page.screenshot({
        path: shot(locale, "selection-bar"),
        clip: { x: panel.x + 6, y: panel.y + 358, width: 400, height: 140 },
      });
    });

    // The button shows only on hover, once toggled on it stays visible.
    test(`belege-knopf ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(5000);
      const answer = page.locator('[data-testid="assistant-message"]').last();
      await answer.hover();
      await answer.getByTitle(LABELS[locale].showAllCitations).click();
      await page.waitForTimeout(800);
      // The row below the answer: buttons left, source count right.
      await answer.locator("button[aria-pressed]").locator("xpath=../..").screenshot({
        path: shot(locale, "citations-toggle"),
      });
    });

    // Both buttons at the highlight, the arrow only appears after scrolling on.
    test(`markierung-knoepfe ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      await page.goto(`${prefix(locale)}/workspace/${WORKSPACE}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(5000);
      const answer = page.locator('[data-testid="assistant-message"]').last();
      await answer.locator(".chip-toggle").first().click();
      const chip = answer.locator(".chip-cite").first();
      await expect(chip).toBeVisible();
      await chip.click();
      await page.waitForTimeout(6000);
      const bar = page.locator("div.absolute.bottom-6.right-4").first();
      await expect(bar).toBeVisible();
      const panel = (await page.locator("[data-tour=\"pdf-viewer\"]").first().boundingBox())!;
      // Scroll on, otherwise the back-to-highlight arrow is missing.
      for (let i = 0; i < 6 && (await bar.locator("button").count()) < 2; i++) {
        await page.mouse.move(panel.x + panel.width / 2, panel.y + panel.height / 2);
        await page.mouse.wheel(0, 1200);
        await page.waitForTimeout(1200);
      }
      const box = (await bar.boundingBox())!;
      // Some surroundings in the shot, otherwise two buttons float in nothing.
      await page.screenshot({
        path: shot(locale, "highlight-controls"),
        clip: { x: box.x - 200, y: box.y - 80, width: box.width + 220, height: box.height + 110 },
      });
    });

    // Only the grid with the five moods, the rest of the page is workshop.
    // Shot in German only, the English article shows the same pictures.
    for (const mascot of ["hilde", "francis"] as const) {
      test(`maskottchen-zustaende ${mascot} ${locale}`, async ({ page }) => {
        test.skip(locale !== "de", "ein Bild fuer beide Sprachen");
        await useLocale(page, locale);
        const url = `${prefix(locale)}/admin/mascots/${mascot}`;
        await page.goto(url, { waitUntil: "domcontentloaded" });
        await settle(page);
        const section = page.locator("section").filter({ hasText: LABELS[locale].allMoods }).last();
        // Only the boxes, the heading above belongs to the admin page.
        const grid = section.locator("div.grid").first();
        await expect(grid).toBeVisible();
        // The figures animate on appearing.
        await page.waitForTimeout(3000);
        // The box border is workshop noise in the manual; transparent, not none, or the boxes shrink by the border width.
        await page.addStyleTag({ content: ".grid > div { border-color: transparent }" });
        await grid.screenshot({ path: shot(locale, `mascot-states-${mascot}`) });
      });
    }

    // Turns the demo user's own switch on, drops an existing level, starts a fresh test,
    // skips every question, and lands back on the level page with a level set.
    // The questions themselves are always German, so language-test.png is shot once, while
    // the level page is fully translated and gets its own picture per language.
    test(`sprachtest ${locale}`, async ({ page }) => {
      await useLocale(page, locale);
      // The admin switch is already on, only the person's own switch needs flipping.
      await page.request.patch("/api/me/language-training", { data: { active: true } });
      // Without a level the page offers the test, so an old level is dropped first.
      await page.request.delete("/api/ai-assistant/language-diagnosis/me");
      await page.goto(`${prefix(locale)}/language-level`, { waitUntil: "domcontentloaded" });
      await settle(page);

      await page.getByRole("button", { name: LABELS[locale].profileTakeTest }).click();
      await page.waitForURL(new RegExp(`${prefix(locale)}/language-level/test`));

      const skip = page.getByRole("button", { name: LABELS[locale].diagSkip });
      await expect(skip.first()).toBeVisible({ timeout: 15_000 });
      await page.waitForTimeout(1000);
      if (locale === "de") await page.screenshot({ path: shot(locale, "language-test") });
      for (let i = 0; i < 12 && (await skip.count()); i++) {
        await skip.first().click();
        await page.waitForTimeout(1200);
      }

      await page.getByRole("button", { name: LABELS[locale].diagContinue }).click();
      await page.waitForURL(new RegExp(`${prefix(locale)}/language-level$`));
      await settle(page);
      await page.screenshot({ path: shot(locale, "language-level") });
    });
  }
});
