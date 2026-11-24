"use client";

import { useLocale, useTranslations } from "next-intl";

export interface HeaderAccount {
  name: string;
  email: string;
  /** Set only for accounts from an access code. */
  expiresAt: string | null;
}

/** Who is signed in, as a plain line at the top of the menu, with the deadline of an access code account below. */
export default function HeaderAccountRow({ account }: { account: HeaderAccount }) {
  const t = useTranslations("header");
  const locale = useLocale();
  const until = account.expiresAt
    ? new Date(account.expiresAt).toLocaleDateString(locale === "en" ? "en-US" : "de-DE", {
        day: "numeric",
        month: "long",
        year: "numeric",
        timeZone: "Europe/Berlin",
      })
    : null;
  const showEmail = account.email && account.email !== account.name;
  return (
    <div className="px-4 pt-3 pb-2.5 min-w-0" style={{ borderBottom: "1px solid var(--border)", marginBottom: 4 }} data-testid="header-account">
      <p className="text-sm font-semibold truncate" style={{ color: "var(--foreground)" }} title={account.name}>
        {account.name}
      </p>
      {showEmail && (
        <p className="text-xs truncate" style={{ color: "var(--muted)" }} title={account.email}>
          {account.email}
        </p>
      )}
      {until && (
        <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
          {t("accessUntil", { date: until })}
        </p>
      )}
    </div>
  );
}
