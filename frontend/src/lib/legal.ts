"use client";

/** Contact address, imprint and privacy policy of this installation, entered in Admin -> System. */

import { useEffect, useState } from "react";

export type LegalTexts = { de: string; en: string };
export type Legal = { contactEmail: string; imprint: LegalTexts; privacy: LegalTexts };

let cache: Promise<Legal> | null = null;

/** One request per page load, read from the open labels the start page uses as well. */
export function loadLegal(): Promise<Legal> {
  cache ??= fetch("/api/health/labels", { cache: "no-store" })
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json() as Promise<Record<string, unknown>>;
    })
    .then((d) => {
      const text = (key: string) => (typeof d[key] === "string" ? (d[key] as string) : "");
      return {
        contactEmail: text("legal_contact_email"),
        imprint: { de: text("legal_imprint_de"), en: text("legal_imprint_en") },
        privacy: { de: text("legal_privacy_de"), en: text("legal_privacy_en") },
      };
    })
    .catch((e) => {
      cache = null;
      throw e;
    });
  return cache;
}

/** The text in the page language, English falls back to German while it is empty. */
export function legalText(texts: LegalTexts, locale: string): string {
  return (locale === "en" ? texts.en.trim() : "") || texts.de.trim();
}

/** undefined while loading, null when the request failed. */
export function useLegal(): Legal | null | undefined {
  const [value, setValue] = useState<Legal | null | undefined>(undefined);
  useEffect(() => {
    let active = true;
    loadLegal()
      .then((v) => { if (active) setValue(v); })
      .catch(() => { if (active) setValue(null); });
    return () => { active = false; };
  }, []);
  return value;
}
