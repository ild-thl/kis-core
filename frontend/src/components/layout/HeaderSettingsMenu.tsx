"use client";

import type { AreaKey } from "@/lib/permissions";
import Link from "next/link";
import LinkBusy from "@/components/ui/LinkBusy";
import NoticeDot from "@/components/ui/NoticeDot";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Check, Compass, FileText, Gear, Medal, Moon, PencilSimple, Plugs, Question, SignOut, Sun, UserCircleGear } from "@phosphor-icons/react";
import { usePathname } from "@/i18n/navigation";
import type { Locale } from "@/i18n/routing";
import { useTheme, type Theme } from "@/hooks/useTheme";
import HeaderAccountRow, { type HeaderAccount } from "./HeaderAccountRow";
import { blockStartRows, LOCALES, THEMES, useLocaleSwitch } from "./_headerMenu";

interface HeaderSettingsMenuProps {
  /** Who is signed in, shown as a plain line at the top. */
  account?: HeaderAccount | null;
  isAdmin?: boolean;
  canViewManual?: boolean;
  showLanguageLevel?: boolean;
  /** Own accounts at outside voice services, only with the permission for it. */
  showInterfaces?: boolean;
  showTour?: boolean;
  onStartTour?: () => void;
  /** The start-page card can be dismissed for good, this is the way back to it. */
  showEvaluation?: boolean;
  areaKey?: AreaKey;
  showLogout?: boolean;
  /** Jumps to the FAQ band on the start page. */
  showFaq?: boolean;
  /** Open feedback waits in the admin area. */
  adminNotice?: boolean;
  onLogout?: () => void;
}

export default function HeaderSettingsMenu({ account = null, isAdmin = false, canViewManual = false, showLanguageLevel = false, showInterfaces = false, showTour = false, onStartTour, showEvaluation = false, areaKey = "admin", showLogout = false, showFaq = false, adminNotice = false, onLogout }: HeaderSettingsMenuProps) {
  const t = useTranslations("header");
  const tLang = useTranslations("languageSwitch");
  const tManual = useTranslations("manual");
  const pathname = usePathname();
  const { currentLocale, switchLocale } = useLocaleSwitch();
  const { theme, setTheme } = useTheme();

  const [open, setOpen] = useState(false);

  // The menu stays open while the page loads, so the row can show its spinner.
  useEffect(() => { setOpen(false); }, [pathname]);

  // Clicking the page you already stand on never changes the path, so close right away.
  const closeIfHere = (href: string) => () => {
    if (pathname === href || pathname.startsWith(`${href}/`)) setOpen(false);
  };

  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  // Remembers which row gets the focus by keyboard after opening.
  const focusOnOpen = useRef<"first" | "last" | null>(null);

  const rows = () => Array.from(menuRef.current?.querySelectorAll<HTMLElement>("[data-row]") ?? []);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  useEffect(() => {
    if (!open || !focusOnOpen.current) return;
    const where = focusOnOpen.current;
    focusOnOpen.current = null;
    (where === "last" ? rows().at(-1) : rows()[0])?.focus();
  }, [open]);

  const close = () => {
    setOpen(false);
    buttonRef.current?.focus();
  };

  const chooseLocale = (next: Locale) => {
    setOpen(false);
    buttonRef.current?.focus();
    switchLocale(next);
  };

  const chooseTheme = (next: Theme) => {
    setOpen(false);
    buttonRef.current?.focus();
    if (next !== theme) setTheme(next);
  };

  const moveFocus = (step: number) => {
    const list = rows();
    if (list.length === 0) return;
    const at = list.indexOf(document.activeElement as HTMLElement);
    const next = at < 0 ? (step > 0 ? 0 : list.length - 1) : (at + step + list.length) % list.length;
    list[next]?.focus();
  };

  // The browser triggers Enter and Space on the focused row itself.
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        focusOnOpen.current = e.key === "ArrowUp" ? "last" : "first";
        setOpen(true);
      }
      return;
    }
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); moveFocus(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); moveFocus(-1); }
    else if (e.key === "Home") { e.preventDefault(); rows()[0]?.focus(); }
    else if (e.key === "End") { e.preventDefault(); rows().at(-1)?.focus(); }
    else if (e.key === "Tab") { setOpen(false); }
  };

  const rowBase = "flex items-center gap-3 w-full px-4 py-2.5 text-sm font-medium text-left no-underline cursor-pointer outline-none";
  const rowClass = `${rowBase} hover:bg-[var(--surface-dim)] focus:bg-[var(--surface-dim)]`;
  // Log out rests on a grey band, so hover has to go one step darker to stay visible.
  const logoutRowClass = `${rowBase} bg-[var(--border-soft)] hover:bg-[var(--border)] focus:bg-[var(--border)]`;
  const headingClass = "px-4 pt-2.5 pb-1 text-2xs font-semibold uppercase tracking-wide";
  // Own settings and help, then the admin area, then log out, each block opens with a divider.
  const shown: Record<string, boolean> = { level: showLanguageLevel, interfaces: showInterfaces, tour: showTour, evaluation: showEvaluation, manual: canViewManual, faq: showFaq, admin: isAdmin, logout: showLogout };
  const blockStarts = blockStartRows(shown);
  const dividerFor = (row: string) => (blockStarts.has(row) ? { borderTop: "1px solid var(--border)", marginTop: 4 } : {});

  return (
    <div ref={rootRef} className="relative" onKeyDown={onKeyDown}>
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("settingsMenu")}
        title={t("settingsMenu")}
        onClick={() => setOpen((v) => !v)}
        className="relative flex items-center justify-center w-9 h-9 rounded-full btn-on-dark"
      >
        <Gear size={18} weight="bold" aria-hidden="true" />
        {adminNotice && <NoticeDot label={t("openFeedback")} className="absolute top-0 right-0" />}
      </button>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          aria-label={t("settingsMenu")}
          className="absolute right-0 top-full mt-2 z-50 w-56 rounded-xl py-1 overflow-hidden"
          style={{
            backgroundColor: "var(--surface)",
            border: "1px solid var(--border)",
            boxShadow: "0 8px 24px rgba(0,40,60,0.18)",
          }}
        >
          {account?.name && <HeaderAccountRow account={account} />}
          <div className={headingClass} style={{ color: "var(--muted)" }}>{tLang("title")}</div>
          {LOCALES.map((loc) => {
            const isSelected = loc === currentLocale;
            return (
              <button
                key={loc}
                data-row
                type="button"
                role="menuitemradio"
                aria-checked={isSelected}
                tabIndex={-1}
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
                data-row
                type="button"
                role="menuitemradio"
                aria-checked={isSelected}
                tabIndex={-1}
                onClick={() => chooseTheme(th)}
                className={rowClass}
                style={{ color: "var(--foreground)" }}
              >
                {th === "dark"
                  ? <Moon size={18} weight="bold" aria-hidden="true" />
                  : <Sun size={18} weight="bold" aria-hidden="true" />}
                <span className="flex-1" style={{ fontWeight: isSelected ? 600 : 400 }}>
                  {th === "dark" ? t("themeDark") : t("themeLight")}
                </span>
                {isSelected && <Check size={14} weight="bold" style={{ color: "var(--kb-dark)" }} aria-hidden="true" />}
              </button>
            );
          })}

          {showLanguageLevel && (
            <Link
              data-row
              href="/language-level"
              role="menuitem"
              tabIndex={-1}
              onClick={closeIfHere("/language-level")}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("level") }}
            >
              <LinkBusy size="sm">
                <Medal size={18} weight="bold" aria-hidden="true" />
              </LinkBusy>
              <span className="flex-1">{t("languageLevel")}</span>
            </Link>
          )}

          {showInterfaces && (
            <Link
              data-row
              href="/interfaces"
              role="menuitem"
              tabIndex={-1}
              onClick={closeIfHere("/interfaces")}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("interfaces") }}
            >
              <LinkBusy size="sm">
                <Plugs size={18} weight="bold" aria-hidden="true" />
              </LinkBusy>
              <span className="flex-1">{t("interfaces")}</span>
            </Link>
          )}

          {showTour && (
            <button
              data-row
              type="button"
              role="menuitem"
              tabIndex={-1}
              onClick={() => {
                setOpen(false);
                onStartTour?.();
              }}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("tour") }}
            >
              <Compass size={18} weight="bold" aria-hidden="true" />
              <span className="flex-1">{t("tour")}</span>
            </button>
          )}

          {showEvaluation && (
            <Link
              data-row
              href="/evaluation"
              role="menuitem"
              tabIndex={-1}
              onClick={closeIfHere("/evaluation")}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("evaluation") }}
            >
              <LinkBusy size="sm">
                <PencilSimple size={18} weight="bold" aria-hidden="true" />
              </LinkBusy>
              <span className="flex-1">{t("evaluation")}</span>
            </Link>
          )}

          {canViewManual && (
            <Link
              data-row
              href="/manual"
              role="menuitem"
              tabIndex={-1}
              onClick={closeIfHere("/manual")}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("manual") }}
            >
              <LinkBusy size="sm">
                <FileText size={18} weight="bold" aria-hidden="true" />
              </LinkBusy>
              <span className="flex-1">{tManual("title")}</span>
            </Link>
          )}

          {showFaq && (
            <Link
              data-row
              href="/#faq"
              role="menuitem"
              tabIndex={-1}
              onClick={closeIfHere("/")}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("faq") }}
            >
              <LinkBusy size="sm">
                <Question size={18} weight="bold" aria-hidden="true" />
              </LinkBusy>
              <span className="flex-1">{t("faq")}</span>
            </Link>
          )}

          {isAdmin && (
            <Link
              data-row
              href="/admin"
              role="menuitem"
              tabIndex={-1}
              onClick={closeIfHere("/admin")}
              className={rowClass}
              style={{ color: "var(--foreground)", ...dividerFor("admin") }}
            >
              <LinkBusy size="sm">
                <UserCircleGear size={18} weight="bold" aria-hidden="true" />
              </LinkBusy>
              <span className="flex-1">{t(areaKey)}</span>
              {adminNotice && <NoticeDot label={t("openFeedback")} />}
            </Link>
          )}

          {showLogout && (
            <button
              data-row
              type="button"
              role="menuitem"
              tabIndex={-1}
              onClick={() => {
                setOpen(false);
                onLogout?.();
              }}
              className={logoutRowClass}
              style={{ color: "var(--foreground)", ...dividerFor("logout") }}
            >
              <SignOut size={18} weight="bold" aria-hidden="true" />
              <span className="flex-1">{t("logout")}</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
