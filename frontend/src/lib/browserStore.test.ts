import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MAX_WORKSPACES,
  PREFS_KEY,
  USER_KEY,
  WORKSPACES_KEY,
  _resetMigrationForTests,
  clearUserData,
  readPrefs,
  readUserData,
  readWorkspaceUi,
  updatePrefs,
  updateUserData,
  updateWorkspaceUi,
} from "./browserStore";

// A localStorage stub backed by a plain map, returned so tests can look inside.
function stubStorage(initial: Record<string, string> = {}) {
  const store = new Map<string, string>(Object.entries(initial));
  vi.stubGlobal("window", {});
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => { store.set(key, value); },
    removeItem: (key: string) => { store.delete(key); },
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() { return store.size; },
  });
  return store;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  _resetMigrationForTests();
});

describe("prefs", () => {
  it("merges patches and drops undefined fields", () => {
    const store = stubStorage();
    updatePrefs({ theme: "dark", homeNoticeDismissed: "Hallo" });
    updatePrefs({ homeNoticeDismissed: undefined });
    expect(readPrefs()).toEqual({ theme: "dark" });
    expect([...store.keys()]).toEqual([PREFS_KEY]);
  });

  it("reads broken JSON as empty", () => {
    stubStorage({ [PREFS_KEY]: "{kaputt" });
    expect(readPrefs()).toEqual({});
  });

  it("is empty outside the browser", () => {
    expect(readPrefs()).toEqual({});
  });
});

describe("workspaces", () => {
  it("keeps only the most recently written workspaces", () => {
    vi.useFakeTimers();
    stubStorage();
    for (let i = 0; i <= MAX_WORKSPACES; i++) {
      vi.setSystemTime(1000 + i);
      updateWorkspaceUi(`ws-${i}`, { closedChapters: ["a"] });
    }
    expect(readWorkspaceUi("ws-0")).toEqual({});
    expect(readWorkspaceUi(`ws-${MAX_WORKSPACES}`).closedChapters).toEqual(["a"]);
  });
});

describe("user data", () => {
  it("is gone after clearUserData, prefs stay", () => {
    const store = stubStorage();
    updatePrefs({ theme: "dark" });
    updateUserData((d) => ({ ...d, translations: { src: { ts: 1, lang: "EN-US" } } }));
    expect(readUserData().translations?.src.lang).toBe("EN-US");
    clearUserData();
    expect(readUserData()).toEqual({});
    expect(store.has(PREFS_KEY)).toBe(true);
  });
});

describe("migrateLegacyKeys", () => {
  it("moves the former single keys into the three bundles", () => {
    const store = stubStorage({
      "kis.theme": "dark",
      "kis.pdf-theme": "dark",
      "ki-assistent-mascot": "francis",
      "kis.youtube-consent": "granted",
      "kis.kalender.ausgeblendet": "[3,4]",
      "kis-jobs-last-seen": "1700",
      "kis.home-notice.dismissed-text": "Hinweis",
      "kis-evaluation-dismissed": "2",
      "kis_thl_glossaries_migrated": "1",
      "kis.welcome-modal.seen.7": "1",
      "ki-assistent-panels-abc": '{"quellen":false,"chat":true,"studio":true}',
      "kis-chapters-closed-abc": '["k1"]',
      "kis-diagnosis-chat-7": '[{"role":"assistant","content":"?"}]',
      "kis:transcript-translate:src1": '{"ts":5,"lang":"DE"}',
      "fremder-schluessel": "bleibt",
    });

    expect(readPrefs()).toEqual({
      theme: "dark",
      mascot: "francis",
      youtubeConsent: true,
      calendarHidden: [3, 4],
      jobsLastSeen: 1700,
      homeNoticeDismissed: "Hinweis",
      evaluationDismissed: "2",
      welcomeSeen: [7],
    });
    expect(readWorkspaceUi("abc")).toMatchObject({
      panels: { quellen: false, chat: true, studio: true },
      closedChapters: ["k1"],
    });
    expect(readUserData()).toEqual({
      diagnosis: { "7": [{ role: "assistant", content: "?" }] },
      translations: { src1: { ts: 5, lang: "DE" } },
    });
    expect([...store.keys()].sort()).toEqual(
      ["fremder-schluessel", PREFS_KEY, USER_KEY, WORKSPACES_KEY].sort(),
    );
  });

  it("does not overwrite a value already in the bundle", () => {
    stubStorage({ [PREFS_KEY]: '{"theme":"light"}', "kis.theme": "dark" });
    expect(readPrefs().theme).toBe("light");
  });

  it("takes over the bundle keys from before the rename", () => {
    const store = stubStorage({
      "kis.prefs": '{"theme":"dark","jobsLastSeen":5}',
      "kis.workspaces": '{"abc":{"at":1,"closedChapters":["k1"]}}',
      [PREFS_KEY]: '{"jobsLastSeen":9}',
    });
    expect(readPrefs()).toMatchObject({ theme: "dark", jobsLastSeen: 9 });
    expect(readWorkspaceUi("abc").closedChapters).toEqual(["k1"]);
    expect(store.has("kis.prefs")).toBe(false);
  });
});
