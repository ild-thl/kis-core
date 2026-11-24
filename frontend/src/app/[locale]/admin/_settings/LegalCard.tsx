"use client";

/** Contact address, imprint and privacy policy of this installation, each field saved on leaving it. */

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useSettingGroup } from "./SettingsProvider";
import { SettingCard } from "./fields";

const INPUT = "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:border-kb disabled:opacity-50";
const KEYS = ["legal_contact_email", "legal_imprint_de", "legal_imprint_en", "legal_privacy_de", "legal_privacy_en"] as const;
type Key = (typeof KEYS)[number];

export default function LegalCard() {
  const t = useTranslations("admin.legalCard");
  const group = useSettingGroup([...KEYS]);
  const [draft, setDraft] = useState<Record<Key, string> | null>(null);

  useEffect(() => {
    if (!group.settings) return;
    setDraft(Object.fromEntries(KEYS.map((k) => [k, String(group.settings?.[k] ?? "")])) as Record<Key, string>);
  }, [group.settings]);

  if (!draft) return null;

  const commit = (key: Key) => {
    const value = draft[key].trim();
    if (value !== String(group.settings?.[key] ?? "")) void group.save({ [key]: value });
  };
  const field = (key: Key) => ({
    value: draft[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setDraft({ ...draft, [key]: e.target.value }),
    onBlur: () => commit(key),
    disabled: group.saving,
    "data-testid": key,
  });
  const missing = !draft.legal_imprint_de.trim() || !draft.legal_privacy_de.trim();

  return (
    <SettingCard title={t("title")} description={t("description")} error={group.error}>
      {missing && (
        <p role="alert" data-testid="legal-missing-warning" className="mt-3 rounded-md border border-warn-border bg-warn-bg px-3 py-2 text-sm text-warn-strong">
          {t("missing")}
        </p>
      )}
      <label className="mt-4 block">
        <span className="text-sm font-medium text-foreground">{t("email")}</span>
        <input type="email" {...field("legal_contact_email")} className={`${INPUT} mt-1`} />
        <span className="mt-1 block text-xs text-muted-soft">{t("emailHint")}</span>
      </label>
      {(["imprint", "privacy"] as const).map((kind) => (
        <div key={kind} className="mt-5">
          <p className="text-sm font-medium text-foreground">{t(kind)}</p>
          <div className="mt-1 grid gap-3 md:grid-cols-2">
            {(["de", "en"] as const).map((lang) => (
              <label key={lang} className="block">
                <span className="text-xs text-muted">{t(lang === "de" ? "german" : "english")}</span>
                <textarea {...field(`legal_${kind}_${lang}`)} rows={10} className={`${INPUT} mt-1 font-mono resize-y`} />
              </label>
            ))}
          </div>
        </div>
      ))}
      <p className="mt-2 text-xs text-muted-soft">{t("markdownHint")}</p>
    </SettingCard>
  );
}
