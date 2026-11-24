"use client";

import { useCallback, useEffect, useState } from "react";
import { PREFS_KEY, readPrefs, updatePrefs, type Theme } from "@/lib/browserStore";

export type { Theme };

const COOKIE_KEY = "askf-theme";
const CHANGE_EVENT = "askf-theme:change";

function readTheme(): Theme {
  return readPrefs().theme === "dark" ? "dark" : "light";
}

function writeThemeCookie(theme: Theme) {
  if (typeof document === "undefined") return;
  // 1 year, site-wide. SameSite=Lax so it survives locale prefix navigations.
  document.cookie = `${COOKIE_KEY}=${theme}; path=/; max-age=${60 * 60 * 24 * 365}; SameSite=Lax`;
}

function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
}

export function useTheme(): { theme: Theme; toggle: () => void; setTheme: (t: Theme) => void } {
  const [theme, setThemeState] = useState<Theme>("light");

  useEffect(() => {
    setThemeState(readTheme());

    const onCustom = (e: Event) => {
      const detail = (e as CustomEvent<Theme>).detail;
      if (detail === "light" || detail === "dark") setThemeState(detail);
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key === PREFS_KEY) setThemeState(readTheme());
    };

    window.addEventListener(CHANGE_EVENT, onCustom);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(CHANGE_EVENT, onCustom);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const setTheme = useCallback((next: Theme) => {
    updatePrefs({ theme: next });
    writeThemeCookie(next);
    applyTheme(next);
    try { window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: next })); } catch { /* ignore */ }
    setThemeState(next);
  }, []);

  const toggle = useCallback(() => {
    setTheme(readTheme() === "dark" ? "light" : "dark");
  }, [setTheme]);

  return { theme, toggle, setTheme };
}
