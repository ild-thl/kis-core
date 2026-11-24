import type { UserPermissions } from "@/types";

/** Mirror of the server's permission keys so the sidebar offers no 403. */
export const PERM = {
  generalWelcome: "general.welcome",
  manual: "general.manual",
  // Own account at an outside voice service, at one's own responsibility.
  interfaces: "general.interfaces",

  aiaUse: "aia.use",
  aiaWorkspaceCreate: "aia.workspace.create",
  // Own language level and test, no system role holds it, only a custom role.
  aiaLanguageLevel: "aia.language_level",

  toolsRelease: "settings.werkzeuge.release",
  toolsJobs: "settings.werkzeuge.jobs",
  toolsStats: "settings.werkzeuge.stats",
  toolsLimits: "settings.werkzeuge.limits",
  aiaSources: "settings.assistent.sources",
  aiaLevel: "settings.assistent.level",
  aiaUsage: "settings.assistent.usage",
  providers: "settings.anbieter",
  usersPending: "settings.nutzer.pending",
  usersWhitelist: "settings.nutzer.whitelist",
  usersAll: "settings.nutzer.users",
  usersRoles: "settings.nutzer.roles",
  // Log in as somebody else to see a reported problem first-hand.
  usersImpersonate: "settings.nutzer.impersonate",
  usersFeedback: "settings.nutzer.feedback",
  usersEvaluation: "settings.nutzer.evaluation",
  system: "settings.system",
  mascot: "settings.mascot",
  // Stands, event block and the numbers of the stamp card.
  event: "settings.event",
  // Crawl, map link and retention of the campus assistant.
  campus: "settings.campus",
  // Two tabs keep their old key so existing roles lose nothing.
  statsUsers: "settings.statistik.nutzer",
  statsModels: "settings.statistik.modelle",
  // Not a settings right but the right to keep working while everything is shut.
  maintenanceAccess: "settings.wartung.zugang",
} as const;

/** The four statistics tabs, the only settings rights that read without changing anything. */
export const STATS_PERMS: string[] = [
  PERM.statsUsers,
  PERM.toolsStats,
  PERM.aiaUsage,
  PERM.statsModels,
];

/** The settings group, everything that unlocks a page of the area. */
export const SETTINGS_PERMS: string[] = [
  PERM.toolsRelease,
  PERM.toolsJobs,
  PERM.toolsStats,
  PERM.toolsLimits,
  PERM.aiaSources,
  PERM.aiaLevel,
  PERM.aiaUsage,
  PERM.providers,
  PERM.usersPending,
  PERM.usersWhitelist,
  PERM.usersAll,
  PERM.usersRoles,
  PERM.usersImpersonate,
  PERM.usersFeedback,
  PERM.usersEvaluation,
  PERM.system,
  PERM.mascot,
  PERM.event,
  PERM.statsUsers,
  PERM.statsModels,
  PERM.maintenanceAccess,
];

export const EMPTY_PERMS: UserPermissions = {
  allow_admin_panel: false,
  allow_aia: false,
  allow_workspace_create: false,
  tools: [],
  keys: [],
  allow_account_create: false,
};

/** Whether the permissions contain one of the named keys. */
export function hasPerm(perms: UserPermissions | undefined, ...keys: string[]): boolean {
  if (!perms?.keys) return false;
  return keys.some((k) => perms.keys.includes(k));
}

/** Whoever holds every settings permission is effectively an administrator, measured by the permissions. */
export function isFullAdmin(perms: UserPermissions | undefined): boolean {
  if (!perms?.keys) return false;
  return SETTINGS_PERMS.every((k) => perms.keys.includes(k));
}

/** The name of the area behind the gear menu, a key under `header`. */
export type AreaKey = "admin" | "settings" | "stats";

/** Whoever may only read numbers gets a link called statistics, not administration. */
export function areaLabelKey(perms: UserPermissions | undefined): AreaKey {
  if (isFullAdmin(perms)) return "admin";
  // Maintenance access opens no page, so it does not make the area an administration.
  const pages = (perms?.keys ?? []).filter((k) => SETTINGS_PERMS.includes(k) && k !== PERM.maintenanceAccess);
  if (pages.length > 0 && pages.every((k) => STATS_PERMS.includes(k))) return "stats";
  return "settings";
}
