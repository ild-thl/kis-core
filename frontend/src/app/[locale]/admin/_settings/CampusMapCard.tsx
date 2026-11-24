"use client";

/** Address and switch of the campus map, which lives outside KIS and feeds footer tile, place cards and places. */

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useSetting } from "./SettingsProvider";
import { SettingCard, Switch } from "./fields";

export default function CampusMapCard() {
  const t = useTranslations("admin.campusMapCard");
  const enabled = useSetting<boolean>("campus_map_enabled", true);
  const url = useSetting<string>("campus_map_url", "");
  const [draft, setDraft] = useState("");

  useEffect(() => {
    if (url.value !== null) setDraft(url.value);
  }, [url.value]);

  if (enabled.loading) return null;
  const on = enabled.value ?? false;

  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed !== url.value) void url.set(trimmed);
  };

  return (
    <SettingCard
      title={t("title")}
      description={on && draft.trim() ? t("active") : t("disabled")}
      error={enabled.error ?? url.error}
      control={<Switch checked={on} onChange={(n) => void enabled.set(n)} disabled={enabled.saving} label={t("toggleAria")} />}
    >
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
        disabled={url.saving}
        placeholder="https://"
        aria-label={t("title")}
        className="mt-3 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:border-kb disabled:opacity-50"
      />
      <p className="mt-2 text-xs text-muted-soft">{t("hint")}</p>
    </SettingCard>
  );
}
