import { test, expect, request as playwrightRequest } from "@playwright/test";

/** A stranger redeems an access code and lands inside the app, the admin side runs through the API. */

const ADMIN = { username: process.env.E2E_USER ?? "a", password: process.env.E2E_PASS ?? "a" };
// A per-run suffix keeps the name free across runs.
const SUFFIX = Date.now().toString(36);

test.use({ storageState: { cookies: [], origins: [] } });

test("Zugangscode: ein Konto einlösen und die Startseite erreichen", async ({ page, baseURL }) => {
  const admin = await playwrightRequest.newContext({ baseURL });
  const anmeldung = await admin.post("/auth/login", { data: ADMIN });
  expect(anmeldung.ok()).toBeTruthy();

  const erstellt = await admin.post("/api/admin/access-codes", {
    data: {
      label: `E2E Zugangscode ${SUFFIX}`,
      max_uses: 2,
      valid_days: 7,
      access_hours: 168,
      askf_role: "staff",
      custom_role_id: null,
    },
  });
  expect(erstellt.ok()).toBeTruthy();
  const code = await erstellt.json();

  let username = "";
  try {
    // Needs "load", not "domcontentloaded", or fills land in the DOM before hydration and never reach React state.
    await page.goto("/de/redeem", { waitUntil: "load" });
    const formular = page.getByTestId("access-code-form");
    await formular.locator("#access-code").fill(code.code);

    const [einloesung] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/access-codes/redeem") && r.request().method() === "POST"),
      formular.locator('button[type="submit"]').click(),
    ]);
    expect(einloesung.ok()).toBeTruthy();
    const antwort = await einloesung.json();
    username = antwort.username;
    expect(username).toBeTruthy();
    expect(antwort.password).toBeTruthy();

    const fertig = page.getByTestId("access-code-done");
    await expect(fertig).toBeVisible();
    await expect(fertig.getByTestId("access-code-username")).toHaveText(username);
    await expect(fertig.getByTestId("access-code-password")).toHaveText(antwort.password);

    // The card also carries two copy buttons, so address the continue one directly.
    const [kurse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/api/ai-assistant/workspaces") && r.request().method() === "GET"),
      fertig.getByTestId("access-code-continue").click(),
    ]);
    expect(kurse.ok()).toBeTruthy();
    await expect(page).toHaveURL((url) => !url.pathname.includes("redeem") && !url.pathname.includes("login"));
    await expect(page.locator("h1").filter({ hasText: username })).toBeVisible();
  } finally {
    await admin.delete(`/api/admin/access-codes/${code.id}`);
    if (username) {
      const liste = await (await admin.get(`/api/admin/users?limit=100&q=${encodeURIComponent(username)}`)).json();
      const konto = liste.users.find((u: { username: string }) => u.username === username);
      if (konto) await admin.delete(`/api/admin/users/${konto.id}`);
    }
    await admin.dispose();
  }
});

test("Zugangscode ohne Zugangsdaten: Link allein meldet an, ganz ohne Klick", async ({ page, baseURL }) => {
  const admin = await playwrightRequest.newContext({ baseURL });
  await admin.post("/auth/login", { data: ADMIN });

  const erstellt = await admin.post("/api/admin/access-codes", {
    data: {
      label: `E2E Veranstaltung ${SUFFIX}`,
      max_uses: 2,
      valid_days: 1,
      access_hours: 12,
      show_credentials: false,
      askf_role: "user",
      custom_role_id: null,
    },
  });
  expect(erstellt.ok()).toBeTruthy();
  const code = await erstellt.json();

  try {
    // The code comes from the URL as with a scanned QR code, no click needed.
    const [einloesung] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/access-codes/redeem") && r.request().method() === "POST"),
      page.goto(`/de/redeem?code=${code.code}`, { waitUntil: "load" }),
    ]);
    expect(einloesung.ok()).toBeTruthy();

    // No username/password step in between, straight to the start page.
    await expect(page).toHaveURL((url) => !url.pathname.includes("redeem"), { timeout: 10_000 });
    await expect(page.getByTestId("access-code-done")).toHaveCount(0);
  } finally {
    await admin.delete(`/api/admin/access-codes/${code.id}`);
    await admin.dispose();
  }
});

test.describe("Zugangscode anlegen im Formular", () => {
  test.use({ storageState: "e2e/.auth/state.json" });

  test("eine eigene Platzzahl eintippen", async ({ page, baseURL }) => {
    await page.goto("/de/admin/users/access-codes", { waitUntil: "load" });
    await page.getByTestId("access-code-create").click();

    await page.locator("#access-code-label").fill(`E2E Eigene Zahl ${SUFFIX}`);
    await page.locator("#access-code-seats-choice").click();
    await page.getByRole("option", { name: "Eigene Zahl" }).click();
    await page.getByTestId("access-code-seats").fill("37");

    const [antwort] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/api/admin/access-codes") && r.request().method() === "POST"),
      page.getByTestId("access-code-submit").click(),
    ]);
    expect(antwort.ok()).toBeTruthy();
    const code = await antwort.json();
    expect(code.max_uses).toBe(37);
    await expect(page.getByTestId("access-code-value")).toHaveText(code.code);

    const admin = await playwrightRequest.newContext({ baseURL });
    await admin.post("/auth/login", { data: ADMIN });
    await admin.delete(`/api/admin/access-codes/${code.id}`);
    await admin.dispose();
  });

  test("Evaluation-Haken bleibt am Code und laesst sich nachtraeglich setzen", async ({ page, baseURL }) => {
    await page.goto("/de/admin/users/access-codes", { waitUntil: "load" });
    await page.getByTestId("access-code-create").click();

    await page.locator("#access-code-label").fill(`E2E Evaluation ${SUFFIX}`);
    await page.getByRole("checkbox", { name: "Evaluation anzeigen" }).click();

    const [antwort] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/api/admin/access-codes") && r.request().method() === "POST"),
      page.getByTestId("access-code-submit").click(),
    ]);
    const code = await antwort.json();
    expect(code.show_evaluation).toBe(true);
    await page.getByRole("button", { name: "Schließen" }).click();

    // The dialog must restore the checkbox, otherwise the next save silently flips it.
    const zeile = page.locator("tr", { hasText: code.code });
    await zeile.getByRole("button", { name: "Bearbeiten" }).click();
    const haken = page.getByRole("checkbox", { name: "Evaluation anzeigen" });
    await expect(haken).toBeChecked();

    await haken.click();
    const [gespeichert] = await Promise.all([
      page.waitForResponse((r) => r.url().includes(`/api/admin/access-codes/${code.id}`) && r.request().method() === "PATCH"),
      page.getByTestId("access-code-edit-submit").click(),
    ]);
    expect(gespeichert.ok()).toBeTruthy();

    const admin = await playwrightRequest.newContext({ baseURL });
    await admin.post("/auth/login", { data: ADMIN });
    const liste = await (await admin.get("/api/admin/access-codes")).json();
    const frisch = liste.codes.find((c: { id: number }) => c.id === code.id);
    expect(frisch.show_evaluation).toBe(false);
    await admin.delete(`/api/admin/access-codes/${code.id}`);
    await admin.dispose();
  });

  test("QR-Code anzeigen und als PNG herunterladen", async ({ page, baseURL }) => {
    const admin = await playwrightRequest.newContext({ baseURL });
    await admin.post("/auth/login", { data: ADMIN });
    const erstellt = await admin.post("/api/admin/access-codes", {
      data: {
        label: `E2E QR ${SUFFIX}`,
        max_uses: 5,
        valid_days: 7,
        access_hours: 12,
        askf_role: "user",
        custom_role_id: null,
      },
    });
    const code = await erstellt.json();

    try {
      await page.goto("/de/admin/users/access-codes", { waitUntil: "load" });
      const zeile = page.locator("tr", { hasText: code.code });
      await zeile.getByRole("button", { name: "QR-Code" }).click();

      const modal = page.getByRole("dialog");
      await expect(modal.locator("img")).toBeVisible();
      await expect(modal.getByText(`/redeem?code=${code.code}`)).toBeVisible();

      const [download] = await Promise.all([
        page.waitForEvent("download"),
        modal.getByRole("link", { name: "Als PNG herunterladen" }).click(),
      ]);
      expect(download.suggestedFilename()).toBe(`zugangscode-${code.code}.png`);
    } finally {
      await admin.delete(`/api/admin/access-codes/${code.id}`);
      await admin.dispose();
    }
  });
});
