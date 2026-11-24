"use client";

import type { AreaKey } from "@/lib/permissions";
import Link from "next/link";
import LinkBusy from "@/components/ui/LinkBusy";
import NoticeDot from "@/components/ui/NoticeDot";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { CalendarBlank, Check, Compass, FileText, List, Medal, Moon, PencilSimple, Plugs, Question, SignOut, Stack, SquaresFour, Sun, UserCircleGear, X } from "@phosphor-icons/react";
import { usePathname } from "@/i18n/navigation";
import type { Locale } from "@/i18n/routing";
import { useTheme, type Theme } from "@/hooks/useTheme";
import { blockStartRows, LOCALES, THEMES, useLocaleSwitch } from "./_headerMenu";

interface HeaderMobileMenuProps {
  hasSession: boolean;
  isAdmin: boolean;
  canViewManual?: boolean;
  showLanguageLevel?: boolean;
  showInterfaces?: boolean;
  showTour?: boolean;
  onStartTour?: () => void;
  /** The start-page card can be dismissed for good, this is the way back to it. */
  showEvaluation?: boolean;
  areaKey?: AreaKey;
  hasTools?: boolean;
  hasAia?: boolean;
  isLocalMode?: boolean;
  /** Open feedback waits in the admin area. */
  adminNotice?: boolean;
  onLogout: () => void;
}

export default function HeaderMobileMenu({ hasSession, isAdmin, canViewManual = false, showLanguageLevel = false, showInterfaces = false, showTour = false, onStartTour, showEvaluation = false, areaKey = "admin", hasTools = false, hasAia = true, isLocalMode = false, adminNotice = false, onLogout }: HeaderMobileMenuProps) {
  const t = useTranslations("header");
  const tLang = useTranslations("languageSwitch");
  const tManual = useTranslations("manual");
  const pathname = usePathname();
  const { currentLocale, switchLocale } = useLocaleSwitch();
  const [open, setOpen] = useState(false);

  // The menu stays open while the page loads, so the row can show its spinner.
  useEffect(() => { setOpen(false); }, [pathname]);

  // Clicking the page you already stand on never changes the path, so close right away.
  const closeIfHere = (href: string) => () => {
    if (pathname === href || pathname.startsWith(`${href}/`)) setOpen(false);
  };

  const [sheetTop, setSheetTop] = useState(0);
  const { theme, setTheme } = useTheme();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    // The sheet hangs below the header, whose height is only known in the browser.
    const header = ref.current?.closest("header");
    setSheetTop(header ? Math.round(header.getBoundingClientRect().bottom) : 0);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    // The page behind must not scroll along while the sheet is open.
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", handler);
    return () => document.removeEventListener("pointerdown", handler);
  }, [open]);

  const chooseLocale = (next: Locale) => {
    setOpen(false);
    switchLocale(next);
  };

  const chooseTheme = (next: Theme) => {
    setOpen(false);
    if (next !== theme) setTheme(next);
  };

  const rowBase = "flex items-center gap-3 w-full px-4 py-3 text-sm font-medium transition-colors no-underline text-left";
  const rowClass = `${rowBase} hover:bg-[var(--surface-dim)]`;
  // Log out rests on a grey band, so hover has to go one step darker to stay visible.
  const logoutRowClass = `${rowBase} bg-[var(--border-soft)] hover:bg-[var(--border)]`;
  // The row of the page you are currently on stays highlighted.
  const activeRowStyle = { backgroundColor: "var(--surface-dim)", fontWeight: 600 };
  const onCalendar = pathname === "/calendar" || pathname.startsWith("/calendar/");
  // The services page and every tool below it count as being on Dienste.
  const onTools = pathname === "/services" || pathname.startsWith("/tools/");
  const onJobsPage = pathname.startsWith("/my-jobs");
  const headingClass = "px-4 pt-2.5 pb-1 text-2xs font-semibold uppercase tracking-wide";
  // Own settings and help, then the admin area, then log out, each block opens with a divider.
  const shown: Record<string, boolean> = { level: hasSession && showLanguageLevel, interfaces: hasSession && showInterfaces, tour: hasSession && showTour, evaluation: hasSession && showEvaluation, manual: hasSession && canViewManual, faq: hasSession, admin: hasSession && isAdmin, logout: hasSession && !isLocalMode };
  const blockStarts = blockStartRows(shown);
  const dividerFor = (row: string) => (blockStarts.has(row) ? { borderTop: "1px solid var(--border)", marginTop: 4 } : {});

  return (
    <div className="sm:hidden relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? t("menuClose") : t("menuOpen")}
        aria-expanded={open}
        className="relative flex items-center justify-center w-10 h-10 rounded-full btn-on-dark"
      >
        {open ? <X size={20} weight="bold" /> : <List size={20} weight="bold" />}
        {adminNotice && !open && <NoticeDot label={t("openFeedback")} className="absolute top-0 right-0" />}
      </button>

      {open && (
        <div
          className="fixed left-0 right-0 bottom-0 z-50 py-1 overflow-y-auto overscroll-contain"
          style={{
            top: sheetTop,
            backgroundColor: "var(--surface)",
            borderTop: "1px solid var(--border)",
          }}
        >
          {hasSession && hasTools && (
            <Link
              href="/services"
              onClick={closeIfHere("/services")}
              aria-current={onTools ? "page" : undefined}
              className={rowClass}
              style={{ color: "var(--foreground)", ...(onTools ? activeRowStyle : {}) }}
            >
              <LinkBusy size="sm">
                <SquaresFour size={20} weight="bold" />
              </LinkBusy>
              <span>{t("tools")}</span>
            </Link>
          )}
          {hasSession && hasTools && (
            <Link
              href="/my-jobs"
              onClick={closeIfHere("/my-jobs")}
              aria-current={onJobsPage ? "page" : undefined}
              className={rowClass}
              style={{ color: "var(--foreground)", ...(onJobsPage ? activeRowStyle : {}) }}
            >
              <LinkBusy size="sm">
                <Stack size={20} weight="bold" />
              </LinkBusy>
              <span>{t("jobs")}</span>
            </Link>
          )}
          {hasSession && hasAia && (
            <Link
              href="/calendar"
              onClick={closeIfHere("/calendar")}
              aria-current={onCalendar ? "page" : undefined}
              className={rowClass}
              style={{ color: "var(--foreground)", ...(onCalendar ? activeRowStyle : {}) }}
            >
              <LinkBusy size="sm">
                <CalendarBlank size={20} weight="bold" />
              </LinkBusy>
              <span>{t("calendar")}</span>
            </Link>
          )}
          <div
            className={headingClass}
            style={{
              color: "var(--muted)",
              ...(hasSession && (hasAia || hasTools) ? { borderTop: "1px solid var(--border)", marginTop: 4 } : {}),
            }}
          >
            {tLang("title")}
          </div>
          {LOCALES.map((loc) => {
            const isSelected = loc === currentLocale;
            return (
              <button
                key={loc}
                type="button"
                role="menuitemradio"
                aria-checked={isSelected}
                onClick={() => chooseLocale(loc)}
                className={rowClass}
                style={{ color: "var(--foreground)" }}
              >
                <span className="text-xs uppercase font-mono w-5" style={{ color: "var(--muted)" }} aria-hidden="true">{loc}</span>
                <span className="flex-1" style={{ fontWeight: isSelected ? 600 : 400 }}>{tLang(loc)}</span>
                {isSelected && <Check size={14} weight="bold" style={{ color: "var(--kb-dark)" }} aria-hidden="true" />}
              </button>
            );
          })}

          <div className={headingClass} style={{ color: "var(--muted)", borderTop: "1px solid var(--border)", marginTop: 4 }}>
            {t("sectionAppearance")}
          </div>
          {THEMES.map((th) => {
            const isSelected = th === theme;
            return (
              <button
                key={th}
                type="button"
                role="menuitemradio"
                aria-checked={isSelected}
                onClick={() => chooseTheme(th)}
                className={rowClass}
                style={{ color: "var(--foreground)" }}
              >
                {th === "dark"
                  ? <Moon size={20} weight="bold" aria-hidden="true" />
                  : <Sun size={20} weight="bold" aria-hidden="true" />}
                <span className="flex-1" style={{ fontWeight: isSelected ? 600 : 400 }}>
                  {th === "dark" ? t("themeDark") : t("themeLight")}
                </span>
                {isSelected && <Check size={14} weight="bold" style={{ color: "var(--kb-dark)" }} aria-hidden="true" />}
              </button>
            );
          })}

          {hasSession && showLanguageLevel && (
            <Link
              href="/language-level"
              onClick={closeIfHere("/language-level")}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("level") }}
            >
              <LinkBusy size="sm">
                <Medal size={20} weight="bold" />
              </LinkBusy>
              <span>{t("languageLevel")}</span>
            </Link>
          )}
          {hasSession && showInterfaces && (
            <Link
              href="/interfaces"
              onClick={closeIfHere("/interfaces")}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("interfaces") }}
            >
              <LinkBusy size="sm">
                <Plugs size={20} weight="bold" />
              </LinkBusy>
              <span>{t("interfaces")}</span>
            </Link>
          )}
          {hasSession && showTour && (
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                onStartTour?.();
              }}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("tour") }}
            >
              <Compass size={20} weight="bold" />
              <span>{t("tour")}</span>
            </button>
          )}
          {hasSession && showEvaluation && (
            <Link
              href="/evaluation"
              onClick={closeIfHere("/evaluation")}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("evaluation") }}
            >
              <LinkBusy size="sm">
                <PencilSimple size={20} weight="bold" />
              </LinkBusy>
              <span>{t("evaluation")}</span>
            </Link>
          )}
          {hasSession && canViewManual && (
            <Link
              href="/manual"
              onClick={closeIfHere("/manual")}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("manual") }}
            >
              <LinkBusy size="sm">
                <FileText size={20} weight="bold" />
              </LinkBusy>
              <span>{tManual("title")}</span>
            </Link>
          )}
          {hasSession && (
            <Link
              href="/#faq"
              onClick={closeIfHere("/")}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("faq") }}
            >
              <LinkBusy size="sm">
                <Question size={20} weight="bold" />
              </LinkBusy>
              <span>{t("faq")}</span>
            </Link>
          )}
          {hasSession && isAdmin && (
            <Link
              href="/admin"
              onClick={closeIfHere("/admin")}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("admin") }}
            >
              <LinkBusy size="sm">
                <UserCircleGear size={20} weight="bold" />
              </LinkBusy>
              <span>{t(areaKey)}</span>
              {adminNotice && <NoticeDot label={t("openFeedback")} />}
            </Link>
          )}
          {hasSession && !isLocalMode && (
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                onLogout();
              }}
              className={logoutRowClass}
              style={{ color: "var(--foreground)", ...dividerFor("logout") }}
            >
              <SignOut size={20} weight="bold" />
              <span>{t("logout")}</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
