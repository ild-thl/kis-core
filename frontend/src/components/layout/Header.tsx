"use client";

import Link from "next/link";
import LinkBusy from "@/components/ui/LinkBusy";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { CalendarBlank, Folders, SignIn, SquaresFour } from "@phosphor-icons/react";
import { Link as LocaleLink, usePathname } from "@/i18n/navigation";
import { checkAuthStatus, logout } from "@/lib/auth";
import { api } from "@/lib/api";
import { hasModule } from "@/lib/modules";
import { areaLabelKey, hasPerm, PERM, type AreaKey } from "@/lib/permissions";
import JobsPanel from "@/components/jobs/JobsPanel";
import HeaderMobileMenu from "@/components/layout/HeaderMobileMenu";
import HeaderPublicControls from "@/components/layout/HeaderPublicControls";
import HeaderSettingsMenu from "@/components/layout/HeaderSettingsMenu";
import type { HeaderAccount } from "@/components/layout/HeaderAccountRow";
import Wordmark from "@/components/layout/Wordmark";
import { useTourStart } from "@/app/[locale]/workspace/_components/useTourStart";
import { useOpenFeedback } from "@/hooks/useOpenFeedback";

interface HeaderProps {
  hasSession?: boolean;
  /** The login page is the way in itself, so the login button is left out there. */
  hideLogin?: boolean;
  showLogout?: boolean;
}

export default function Header({ hasSession = true, showLogout = false, hideLogin = false }: HeaderProps) {
  const t = useTranslations("header");
  const pathname = usePathname();
  // The URL says where you are, the button in the header shows it.
  const onCalendar = pathname === "/calendar" || pathname.startsWith("/calendar/");
  // The services page and every tool below it count as being on Dienste.
  const onTools = pathname === "/services" || pathname.startsWith("/tools/");
  const onWorkspaces = pathname === "/workspace" || pathname.startsWith("/workspace/");
  const [isAdmin, setIsAdmin] = useState(false);
  const [canViewManual, setCanViewManual] = useState(false);
  // Admin only for whoever may do everything, everyone else goes to their settings.
  const [areaKey, setAreaKey] = useState<AreaKey>("admin");
  const [isLocalMode, setIsLocalMode] = useState(false);
  const [hasTools, setHasTools] = useState(false);
  // A missing modules field means an older server, which always has both.
  const [hasAia, setHasAia] = useState(true);
  const [account, setAccount] = useState<HeaderAccount | null>(null);
  // The language level page hangs off its own permission, not off the role.
  const [mayLanguageLevel, setMayLanguageLevel] = useState(false);
  const [mayInterfaces, setMayInterfaces] = useState(false);
  const [mayFeedback, setMayFeedback] = useState(false);
  // Only true with an admin-enabled, non-empty text — otherwise the menu row would be a dead click.
  // The start-page card can be dismissed for good, the menu row is the way back to it.
  const [evaluationActive, setEvaluationActive] = useState(false);
  // The tour lives in the demo course, the menu only offers it while one exists.
  const tour = useTourStart(showLogout && hasSession);
  // Open feedback keeps a dot on the way into the admin area until someone deals with it.
  const feedbackNotice = useOpenFeedback(showLogout && hasSession && mayFeedback) > 0;

  useEffect(() => {
    if (!showLogout || !hasSession) return;
    checkAuthStatus().then((s) => {
      setIsAdmin(s.is_admin ?? false);
      setCanViewManual(hasPerm(s.permissions, PERM.manual));
      setAreaKey(areaLabelKey(s.permissions));
      setIsLocalMode(s.local_mode ?? false);
      // Jobs only come from tools, without a tool permission the list stays empty.
      setHasTools((s.permissions?.tools?.length ?? 0) > 0);
      setHasAia(hasModule(s.modules, "aia"));
      setMayLanguageLevel(hasPerm(s.permissions, PERM.aiaLanguageLevel));
      setMayInterfaces(hasPerm(s.permissions, PERM.interfaces));
      setMayFeedback(hasPerm(s.permissions, PERM.usersFeedback));
      setAccount({ name: s.display_name || s.username || "", email: s.email ?? "", expiresAt: s.access_expires_at ?? null });
    });
  }, [showLogout, hasSession]);

  useEffect(() => {
    if (!showLogout || !hasSession) return;
    let cancelled = false;
    api
      .fetch("/api/evaluation/active", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setEvaluationActive(data.active === true);
      })
      .catch(() => {
        /* ignore - menu row just stays hidden */
      });
    return () => {
      cancelled = true;
    };
  }, [showLogout, hasSession]);

  const handleLogout = async () => {
    await logout();
    // Hard nav so the server layout re-reads the cleared session cookie.
    window.location.assign("/login");
  };

  return (
    <header style={{ backgroundColor: "var(--header-bg)", borderBottom: "1px solid var(--border)" }} className="py-3 compact-on-short">
      <div className="px-4 sm:px-6 flex items-center justify-between">
        {/* The page title is the h1, the wordmark is only a link. */}
        <div className="flex items-center gap-2">
          {/* Signed in, the wordmark leads to the workspaces, the landing page is for visitors. */}
          <Link
            href={hasSession ? "/workspace" : "/"}
            aria-label={t("homeAria")}
            className="logo-link flex items-center"
          >
            <Wordmark className="logo-plate--fit" plate={false} />
          </Link>
        </div>

        {showLogout && (
          <div className="flex items-center gap-1.5">
            {/* Public pages have no session, so the two basic switches and the way in, last as the main action, replace the menus. */}
            {!hasSession && (
              <>
                <HeaderPublicControls />
                {!hideLogin && (
                  <LocaleLink href="/login" className="flex items-center justify-center h-9 px-3 sm:px-3.5 gap-1.5 rounded-full btn-on-dark" data-testid="header-login">
                    <SignIn size={17} weight="bold" aria-hidden="true" className="hidden sm:block" />
                    <span className="text-sm font-medium">{t("login")}</span>
                  </LocaleLink>
                )}
              </>
            )}
            {hasSession && (
              <div className="hidden sm:flex items-center gap-1.5">
                {hasAia && (
                  <Link
                    href="/workspace"
                    aria-label={t("workspaces")}
                    title={t("workspaces")}
                    aria-current={onWorkspaces ? "page" : undefined}
                    className={`flex items-center justify-center h-9 px-3 gap-1.5 rounded-full btn-on-dark${onWorkspaces ? " is-active" : ""}`}
                  >
                    <LinkBusy size="sm">
                      <Folders size={17} weight="bold" />
                    </LinkBusy>
                    <span className="text-sm font-medium">{t("workspaces")}</span>
                  </Link>
                )}
                {hasTools && (
                  <Link
                    href="/services"
                    aria-label={t("tools")}
                    title={t("tools")}
                    aria-current={onTools ? "page" : undefined}
                    className={`flex items-center justify-center h-9 px-3 gap-1.5 rounded-full btn-on-dark${onTools ? " is-active" : ""}`}
                  >
                    <LinkBusy size="sm">
                      <SquaresFour size={17} weight="bold" />
                    </LinkBusy>
                    <span className="text-sm font-medium">{t("tools")}</span>
                  </Link>
                )}
                {hasTools && <JobsPanel />}
                {hasAia && (
                  <Link
                    href="/calendar"
                    aria-label={t("calendar")}
                    title={t("calendar")}
                    aria-current={onCalendar ? "page" : undefined}
                    className={`flex items-center justify-center h-9 px-3 gap-1.5 rounded-full btn-on-dark${onCalendar ? " is-active" : ""}`}
                  >
                    <LinkBusy size="sm">
                      <CalendarBlank size={17} weight="bold" />
                    </LinkBusy>
                    <span className="text-sm font-medium">{t("calendar")}</span>
                  </Link>
                )}
                <HeaderSettingsMenu
                  account={account}
                  isAdmin={isAdmin}
                  canViewManual={canViewManual}
                  showLanguageLevel={mayLanguageLevel}
                  showInterfaces={mayInterfaces}
                  showTour={hasAia && tour.available}
                  onStartTour={tour.start}
                  showEvaluation={evaluationActive}
                  areaKey={areaKey}
                  showLogout={!isLocalMode}
                  showFaq
                  adminNotice={isAdmin && feedbackNotice}
                  onLogout={handleLogout}
                />
              </div>
            )}

            {hasSession && (
              <HeaderMobileMenu
                hasSession={hasSession}
                account={account}
                isAdmin={isAdmin}
                canViewManual={canViewManual}
                showLanguageLevel={mayLanguageLevel}
                showInterfaces={mayInterfaces}
                showTour={hasAia && tour.available}
                onStartTour={tour.start}
                showEvaluation={evaluationActive}
                areaKey={areaKey}
                hasTools={hasTools}
                hasAia={hasAia}
                isLocalMode={isLocalMode}
                adminNotice={isAdmin && feedbackNotice}
                onLogout={handleLogout}
              />
            )}
          </div>
        )}
      </div>
    </header>
  );
}
