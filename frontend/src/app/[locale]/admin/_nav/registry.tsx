"use client";

/** The admin navigation tree in one place, a new page is one entry. */

import type { ComponentType } from "react";
import { PERM } from "@/lib/permissions";
import {
  Bird,
  ChartBar,
  GearSix,
  Notebook,
  Ruler,
  Signpost,
  Sparkle,
  SquaresFour,
  Stamp,
  Users,
  type Icon,
} from "@phosphor-icons/react";

import ToolReleasePage from "../_pages/werkzeuge/release";
import ToolJobsPage from "../_pages/werkzeuge/jobs";
import GrenzenMaterialPage from "../_pages/grenzen/material";
import GrenzenKontextPage from "../_pages/grenzen/kontext";

import SourcesPage from "../_pages/assistent/sources";
import LanguageLevelPage from "../_pages/assistent/language-level";
import AiBehaviourPage from "../_pages/assistent/behaviour";

import StatistikNutzerPage from "../_pages/statistik/nutzer";
import StatistikWerkzeugePage from "../_pages/statistik/werkzeuge";
import StatistikAssistentPage from "../_pages/statistik/assistent";
import StatistikModellePage from "../_pages/statistik/modelle";
import StatistikEvaluationPage from "../_pages/statistik/evaluation";

import ProviderListPage from "../_pages/anbieter/list";
import ProviderRoutesPage from "../_pages/anbieter/routes";

import PendingPage from "../_pages/nutzer/pending";
import WhitelistPage from "../_pages/nutzer/whitelist";
import InvitesPage from "../_pages/nutzer/einladungen";
import AccessCodesPage from "../_pages/nutzer/zugangscodes";
import UsersPage from "../_pages/nutzer/users";
import RolesPage from "../_pages/nutzer/roles";
import ImpersonationPage from "../_pages/nutzer/impersonation";
import QuotaPage from "../_pages/nutzer/quota";
import FeedbackPage from "../_pages/nutzer/feedback";
import FeedbackDetailPage from "../_pages/nutzer/feedback-detail";
import EvaluationPage from "../_pages/nutzer/evaluation";

import EventStationsPage from "../_pages/event/stations";
import EventLandingPage from "../_pages/event/landing";
import EventBlockPage from "../_pages/event/block";
import EventStatsPage from "../_pages/event/stats";
import EventTasksPage from "../_pages/event/tasks";
import EventRafflePage from "../_pages/event/raffle";
import SystemOperationPage from "../_pages/system/operation";
import SystemLegalPage from "../_pages/system/legal";
import SystemMapPage from "../_pages/system/map";
import CampusAdminPage from "../_pages/campus";
import HildePage from "../_pages/mascot/hilde";
import FrancisPage from "../_pages/mascot/francis";

/** Which product a page concerns. */
type World = "tools" | "aia" | "both" | "dev";

/** Rank of an area, the sidebar draws a line between two ranks. */
type Rank = "product" | "admin" | "dev";

/** Order of the ranks in the sidebar. */
export const RANKS: Rank[] = ["product", "admin", "dev"];

/** Tabs only where one subject splits into two views. */
interface AdminTab {
  slug: string;
  /** Key under admin.sections.<area>.<page>.tabs */
  labelKey: string;
  Component: ComponentType;
  /** Permission of the tab, empty means the permission of its page. */
  perm?: string;
}

/** Second level: a subpage, expands in the sidebar. */
export interface AdminPage {
  slug: string;
  /** Key under admin.sections.<area> */
  key: string;
  world: World;
  /** Without this permission the page is neither in the sidebar nor reachable. */
  perm: string;
  Component?: ComponentType;
  tabs?: AdminTab[];
  /** The landing page of /admin, exactly one page carries this. */
  home?: true;
  /** Do not show in the sidebar, the URL stays valid. */
  hidden?: true;
  /** A red dot in the sidebar while something here still waits. */
  notice?: "openFeedback";
}

/** First level, without subpages the area itself is the page. */
export interface AdminSection {
  slug: string;
  /** Key under admin.sections */
  key: string;
  Icon: Icon;
  world: World;
  rank: Rank;
  /** Only for areas without subpages. */
  perm?: string;
  pages?: AdminPage[];
  Component?: ComponentType;
  /** Key under admin.sections.<area>.tabs */
  tabs?: AdminTab[];
}

export const SECTIONS: AdminSection[] = [
  // The two products on top, everything else is support work.
  {
    slug: "tools",
    key: "werkzeuge",
    Icon: SquaresFour,
    world: "tools",
    rank: "product",
    pages: [
      { slug: "release", key: "release", world: "tools", perm: PERM.toolsRelease, Component: ToolReleasePage },
      { slug: "jobs", key: "jobs", world: "tools", perm: PERM.toolsJobs, Component: ToolJobsPage, home: true },
    ],
  },
  {
    slug: "ai-assistant",
    key: "assistent",
    Icon: Notebook,
    world: "aia",
    rank: "product",
    pages: [
      // Only how material is processed, how much may come is set under Grenzen.
      { slug: "sources", key: "sources", world: "aia", perm: PERM.aiaSources, Component: SourcesPage },
      // Assessment and AI behaviour are one subject in two tabs.
      {
        slug: "level",
        key: "level",
        world: "aia",
        // Both tabs hang off one permission, their values live in the same record.
        perm: PERM.aiaLevel,
        tabs: [
          { slug: "assessment", labelKey: "assessment", Component: LanguageLevelPage },
          { slug: "behaviour", labelKey: "behaviour", Component: AiBehaviourPage },
        ],
      },
    ],
  },
  // The third product, sits with the other assistant instead of among the admin work.
  {
    slug: "campus",
    key: "campus",
    Icon: Signpost,
    world: "tools",
    rank: "product",
    perm: PERM.campus,
    Component: CampusAdminPage,
  },
  // Below both products, because a limit belongs to no single one of them.
  {
    slug: "limits",
    key: "grenzen",
    Icon: Ruler,
    world: "both",
    rank: "product",
    perm: PERM.toolsLimits,
    tabs: [
      { slug: "material", labelKey: "material", Component: GrenzenMaterialPage },
      { slug: "context", labelKey: "kontext", Component: GrenzenKontextPage },
    ],
  },
  // Read-only numbers sit together, every tab carries its own permission.
  {
    slug: "stats",
    key: "statistik",
    Icon: ChartBar,
    world: "both",
    rank: "admin",
    tabs: [
      { slug: "users", labelKey: "nutzer", perm: PERM.statsUsers, Component: StatistikNutzerPage },
      { slug: "tools", labelKey: "werkzeuge", perm: PERM.toolsStats, Component: StatistikWerkzeugePage },
      { slug: "ai-assistant", labelKey: "assistent", perm: PERM.aiaUsage, Component: StatistikAssistentPage },
      { slug: "models", labelKey: "modelle", perm: PERM.statsModels, Component: StatistikModellePage },
      // Hangs off the same right as creating the evaluation, no second one needed.
      { slug: "evaluation", labelKey: "evaluation", perm: PERM.usersEvaluation, Component: StatistikEvaluationPage },
    ],
  },
  // Providers and features are two views of the same thing.
  {
    slug: "providers",
    key: "anbieter",
    Icon: Sparkle,
    world: "both",
    rank: "admin",
    perm: PERM.providers,
    tabs: [
      { slug: "list", labelKey: "list", Component: ProviderListPage },
      { slug: "routes", labelKey: "routes", Component: ProviderRoutesPage },
    ],
  },
  {
    slug: "users",
    key: "nutzer",
    Icon: Users,
    world: "both",
    rank: "admin",
    pages: [
      { slug: "pending", key: "pending", world: "both", perm: PERM.usersPending, Component: PendingPage },
      { slug: "whitelist", key: "whitelist", world: "both", perm: PERM.usersWhitelist, Component: WhitelistPage },
      // Without the server switch the page stays empty instead of gone.
      { slug: "invites", key: "invites", world: "both", perm: PERM.usersAll, Component: InvitesPage },
      { slug: "access-codes", key: "accessCodes", world: "both", perm: PERM.usersAll, Component: AccessCodesPage },
      { slug: "all", key: "users", world: "both", perm: PERM.usersAll, Component: UsersPage },
      { slug: "roles", key: "roles", world: "both", perm: PERM.usersRoles, Component: RolesPage },
      { slug: "impersonation", key: "impersonation", world: "both", perm: PERM.usersImpersonate, Component: ImpersonationPage },
      { slug: "feedback", key: "feedback", world: "both", perm: PERM.usersFeedback, Component: FeedbackPage, notice: "openFeedback" },
      // No entry of its own, the page is a jump-off from the feedback list.
      { slug: "feedback-detail", key: "feedbackDetail", world: "both", perm: PERM.usersFeedback, Component: FeedbackDetailPage, hidden: true },
      { slug: "evaluation", key: "evaluation", world: "both", perm: PERM.usersEvaluation, Component: EvaluationPage },
      // No entry of its own, the page is a jump-off from the user list.
      { slug: "quotas", key: "quota", world: "both", perm: PERM.usersAll, Component: QuotaPage, hidden: true },
    ],
  },
  // Stands, event block and numbers of the stamp card, one subject in three views.
  {
    slug: "event",
    key: "event",
    Icon: Stamp,
    world: "both",
    rank: "admin",
    perm: PERM.event,
    tabs: [
      { slug: "stations", labelKey: "stations", Component: EventStationsPage },
      { slug: "raffle", labelKey: "raffle", Component: EventRafflePage },
      { slug: "block", labelKey: "block", Component: EventBlockPage },
      { slug: "tasks", labelKey: "tasks", Component: EventTasksPage },
      { slug: "stats", labelKey: "stats", Component: EventStatsPage },
      { slug: "landing", labelKey: "landing", Component: EventLandingPage },
    ],
  },
  // What holds for the whole installation, split by subject.
  {
    slug: "system",
    key: "system",
    Icon: GearSix,
    world: "both",
    rank: "admin",
    perm: PERM.system,
    tabs: [
      { slug: "operation", labelKey: "betrieb", Component: SystemOperationPage },
      { slug: "legal", labelKey: "rechtliches", Component: SystemLegalPage },
      { slug: "map", labelKey: "karte", Component: SystemMapPage },
    ],
  },
  {
    slug: "mascots",
    key: "mascot",
    Icon: Bird,
    world: "dev",
    rank: "dev",
    pages: [
      { slug: "francis", key: "francis", world: "dev", perm: PERM.mascot, Component: FrancisPage },
      { slug: "hilde", key: "hilde", world: "dev", perm: PERM.mascot, Component: HildePage },
    ],
  },
];

interface Resolved {
  section: AdminSection;
  page?: AdminPage;
  /** Path without the /admin prefix, always complete, for redirects. */
  path: string;
}

/** Maps path segments onto an entry, unknown ones yield null. */
export function resolve(segments: string[]): Resolved | null {
  if (!segments[0]) {
    const start = home();
    if (start) return start;
  }
  const section = segments[0]
    ? SECTIONS.find((s) => s.slug === segments[0])
    : SECTIONS[0];
  if (!section) return null;

  if (!section.pages) {
    return { section, path: section.slug };
  }

  const page = segments[1]
    ? section.pages.find((p) => p.slug === segments[1])
    : section.pages[0];
  if (!page) return null;

  return { section, page, path: `${section.slug}/${page.slug}` };
}

/** The marked landing page of /admin. */
function home(): Resolved | null {
  for (const section of SECTIONS) {
    const page = section.pages?.find((p) => p.home);
    if (page) return { section, page, path: `${section.slug}/${page.slug}` };
  }
  return null;
}

/** The sidebar filters itself so nobody sees a door behind a 403. */
function pageAllowed(page: AdminPage, keys: string[]): boolean {
  return keys.includes(page.perm);
}

/** Tabs without a permission of their own hang off their carrier's permission. */
function tabAllowed(tab: AdminTab, ownerPerm: string | undefined, keys: string[]): boolean {
  if (tab.perm) return keys.includes(tab.perm);
  return !!ownerPerm && keys.includes(ownerPerm);
}

/** The visible tabs of an area or a page. */
export function allowedTabs(
  tabs: AdminTab[] | undefined,
  ownerPerm: string | undefined,
  keys: string[],
): AdminTab[] {
  return (tabs ?? []).filter((t) => tabAllowed(t, ownerPerm, keys));
}

function sectionAllowed(section: AdminSection, keys: string[]): boolean {
  if (section.pages) return section.pages.some((p) => pageAllowed(p, keys));
  if (section.tabs?.some((t) => t.perm)) return allowedTabs(section.tabs, section.perm, keys).length > 0;
  return !!section.perm && keys.includes(section.perm);
}

/** The areas with their permitted pages and tabs, empty ones drop out. */
export function allowedSections(keys: string[]): AdminSection[] {
  return SECTIONS.filter((s) => sectionAllowed(s, keys)).map((s) => {
    if (s.pages) return { ...s, pages: s.pages.filter((p) => pageAllowed(p, keys)) };
    if (s.tabs?.some((t) => t.perm)) return { ...s, tabs: allowedTabs(s.tabs, s.perm, keys) };
    return s;
  });
}

/** May this URL be opened? */
export function allowed(found: Resolved, keys: string[]): boolean {
  return found.page
    ? pageAllowed(found.page, keys)
    : sectionAllowed(found.section, keys);
}

/** The first permitted page, the target of every redirect. */
export function firstAllowed(keys: string[]): Resolved | null {
  const start = home();
  if (start && allowed(start, keys)) return start;
  for (const section of allowedSections(keys)) {
    if (!section.pages) return { section, path: section.slug };
    const page = section.pages.find((p) => !p.hidden) ?? section.pages[0];
    if (page) return { section, page, path: `${section.slug}/${page.slug}` };
  }
  return null;
}
