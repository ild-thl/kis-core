/**
 * Everything the app keeps in localStorage, bundled into three keys:
 *
 * - `askf.prefs`      device-wide settings and "already seen" markers, kept for good
 * - `askf.workspaces` view state per workspace (panels, folded chapters), only the most recent ones
 * - `askf.user`       drafts and running jobs of the signed-in person, cleared on logout
 *
 * Every access is wrapped, private mode or a full quota just means nothing is remembered.
 */

export type Theme = "light" | "dark";

export interface Prefs {
  theme?: Theme;
  mascot?: string;
  youtubeConsent?: boolean;
  calendarHidden?: number[];
  /** Workspace uuids, private appointments under their own key, left out of the calendar. */
  calendarHiddenGroups?: string[];
  jobsLastSeen?: number;
  homeNoticeDismissed?: string;
  evaluationDismissed?: string;
  /** User ids that closed the welcome dialog, a shared browser tracks each account. */
  welcomeSeen?: number[];
}

interface WorkspaceUi {
  panels?: Record<string, boolean>;
  closedChapters?: string[];
  /** Last write, the oldest workspaces are dropped first. */
  at: number;
}

interface PendingTranslation {
  ts: number;
  lang: string;
}

interface UserData {
  /** Diagnosis chat draft per user id. */
  diagnosis?: Record<string, unknown[]>;
  /** Running transcript translation per source uuid. */
  translations?: Record<string, PendingTranslation>;
}

export const PREFS_KEY = "askf.prefs";
export const WORKSPACES_KEY = "askf.workspaces";
export const USER_KEY = "askf.user";

/** More workspaces than anyone has open in a term, older view state falls away. */
export const MAX_WORKSPACES = 30;

function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage;
  } catch {
    return null;
  }
}

function readJson<T extends object>(key: string): T {
  const s = storage();
  if (!s) return {} as T;
  try {
    const parsed = JSON.parse(s.getItem(key) ?? "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as T) : ({} as T);
  } catch {
    return {} as T;
  }
}

function writeJson(key: string, value: object) {
  const s = storage();
  if (!s) return;
  try {
    if (Object.keys(value).length === 0) s.removeItem(key);
    else s.setItem(key, JSON.stringify(value));
  } catch {
    /* quota or blocked storage */
  }
}

// ---------------------------------------------------------------- legacy keys

let migrated = false;

function parseOr<T>(raw: string, fallback: T): T {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

/** Moves the former single keys into the bundles, once per page load. */
export function migrateLegacyKeys() {
  if (migrated) return;
  const s = storage();
  if (!s) return;
  migrated = true;

  const legacy: string[] = [];
  try {
    for (let i = 0; i < s.length; i++) {
      const k = s.key(i);
      if (k && k !== PREFS_KEY && k !== WORKSPACES_KEY && k !== USER_KEY) legacy.push(k);
    }
  } catch {
    return;
  }
  if (legacy.length === 0) return;

  const prefs = readJson<Prefs>(PREFS_KEY);
  const workspaces = readJson<Record<string, WorkspaceUi>>(WORKSPACES_KEY);
  const user = readJson<UserData>(USER_KEY);
  const ws = (uuid: string) => (workspaces[uuid] ??= { at: 0 });
  const done: string[] = [];

  for (const k of legacy) {
    const raw = s.getItem(k);
    if (raw === null) continue;
    let handled = true;
    // The three bundle keys from before the rename to askFrancis, newer values win.
    if (k === "kis.prefs") Object.assign(prefs, { ...parseOr<Prefs>(raw, {}), ...prefs });
    else if (k === "kis.workspaces") Object.assign(workspaces, { ...parseOr<Record<string, WorkspaceUi>>(raw, {}), ...workspaces });
    else if (k === "kis.user") Object.assign(user, { ...parseOr<UserData>(raw, {}), ...user });
    else if (k === "kis.theme") prefs.theme ??= raw === "dark" ? "dark" : "light";
    else if (k === "kis.pdf-theme") { /* was never read, just dropped */ }
    else if (k === "ki-assistent-mascot") prefs.mascot ??= raw;
    else if (k === "kis.youtube-consent") prefs.youtubeConsent ??= raw === "granted";
    else if (k === "kis.kalender.ausgeblendet") prefs.calendarHidden ??= parseOr<number[]>(raw, []);
    else if (k === "kis-jobs-last-seen") prefs.jobsLastSeen ??= Number(raw) || undefined;
    else if (k === "kis.home-notice.dismissed-text") prefs.homeNoticeDismissed ??= raw;
    else if (k === "kis-evaluation-dismissed") prefs.evaluationDismissed ??= raw;
    else if (k === "kis_thl_glossaries_migrated") { /* the glossaries migrate on their own key */ }
    else if (k.startsWith("kis.welcome-modal.seen.")) {
      const id = Number(k.slice("kis.welcome-modal.seen.".length));
      if (id && !prefs.welcomeSeen?.includes(id)) prefs.welcomeSeen = [...(prefs.welcomeSeen ?? []), id];
    } else if (k.startsWith("ki-assistent-panels-")) {
      ws(k.slice("ki-assistent-panels-".length)).panels ??= parseOr(raw, undefined);
    } else if (k.startsWith("kis-chapters-closed-")) {
      ws(k.slice("kis-chapters-closed-".length)).closedChapters ??= parseOr(raw, undefined);
    } else if (k.startsWith("kis-diagnosis-chat-")) {
      const turns = parseOr<unknown[]>(raw, []);
      if (Array.isArray(turns) && turns.length) {
        user.diagnosis = { ...user.diagnosis, [k.slice("kis-diagnosis-chat-".length)]: turns };
      }
    } else if (k.startsWith("kis:transcript-translate:")) {
      const p = parseOr<PendingTranslation | null>(raw, null);
      if (p) user.translations = { ...user.translations, [k.slice("kis:transcript-translate:".length)]: p };
    } else handled = false;
    if (handled) done.push(k);
  }
  if (done.length === 0) return;

  writeJson(PREFS_KEY, prefs);
  writeJson(WORKSPACES_KEY, trimWorkspaces(workspaces));
  writeJson(USER_KEY, user);
  for (const k of done) {
    try { s.removeItem(k); } catch { /* ignore */ }
  }
}

/** Test hook, the migration otherwise runs once per page load. */
export function _resetMigrationForTests() {
  migrated = false;
}

// ---------------------------------------------------------------- prefs

export function readPrefs(): Prefs {
  migrateLegacyKeys();
  return readJson<Prefs>(PREFS_KEY);
}

export function updatePrefs(patch: Partial<Prefs>) {
  const next: Prefs = { ...readPrefs(), ...patch };
  for (const k of Object.keys(next) as (keyof Prefs)[]) {
    if (next[k] === undefined) delete next[k];
  }
  writeJson(PREFS_KEY, next);
}

// ---------------------------------------------------------------- workspaces

function trimWorkspaces(all: Record<string, WorkspaceUi>): Record<string, WorkspaceUi> {
  const entries = Object.entries(all);
  if (entries.length <= MAX_WORKSPACES) return all;
  entries.sort(([, a], [, b]) => (b.at ?? 0) - (a.at ?? 0));
  return Object.fromEntries(entries.slice(0, MAX_WORKSPACES));
}

export function readWorkspaceUi(uuid: string): Omit<WorkspaceUi, "at"> {
  migrateLegacyKeys();
  return readJson<Record<string, WorkspaceUi>>(WORKSPACES_KEY)[uuid] ?? {};
}

export function updateWorkspaceUi(uuid: string, patch: Partial<Omit<WorkspaceUi, "at">>) {
  migrateLegacyKeys();
  const all = readJson<Record<string, WorkspaceUi>>(WORKSPACES_KEY);
  all[uuid] = { ...all[uuid], ...patch, at: Date.now() };
  writeJson(WORKSPACES_KEY, trimWorkspaces(all));
}

// ---------------------------------------------------------------- per person

export function readUserData(): UserData {
  migrateLegacyKeys();
  return readJson<UserData>(USER_KEY);
}

export function updateUserData(change: (data: UserData) => UserData) {
  const next = change(readUserData());
  if (next.diagnosis && Object.keys(next.diagnosis).length === 0) delete next.diagnosis;
  if (next.translations && Object.keys(next.translations).length === 0) delete next.translations;
  writeJson(USER_KEY, next);
}

/** On logout, so the next person on a shared computer finds no drafts. */
export function clearUserData() {
  const s = storage();
  if (!s) return;
  try { s.removeItem(USER_KEY); } catch { /* ignore */ }
}
