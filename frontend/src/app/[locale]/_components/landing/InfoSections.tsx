"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ArrowCircleRight, Bank, Books, ChalkboardTeacher, Envelope, Flask, Globe, GraduationCap, type Icon } from "@phosphor-icons/react";
import { useLegal } from "@/lib/legal";
import Band from "./Band";

/** Shared section heading, large on wide screens. */
export function SectionHeading({ children }: { children: ReactNode }) {
  return <h2 className="text-3xl @min-[40rem]:text-4xl font-semibold tracking-[-0.02em] leading-tight">{children}</h2>;
}

type PanelRow = { key: string; icon: Icon };

const PROJECT_ROWS: PanelRow[] = [
  { key: "focus", icon: Globe },
  { key: "funding", icon: Bank },
  { key: "pilot", icon: Flask },
  { key: "next", icon: ArrowCircleRight },
];

const PLATFORM_ROWS: PanelRow[] = [
  { key: "students", icon: GraduationCap },
  { key: "teachers", icon: ChalkboardTeacher },
  { key: "workspaces", icon: Books },
];

/** One of the two panels that keep the project and the platform apart. */
function Panel({ group, rows, solid }: { group: "project" | "platform"; rows: PanelRow[]; solid: boolean }) {
  const t = useTranslations(`eventInfo.purpose.${group}`);
  return (
    // Subgrid keeps the divider of both panels on one line.
    <div className="grid grid-rows-subgrid row-span-2 gap-y-0 rounded-2xl border-2 border-border-soft bg-background p-6 @min-[40rem]:p-8" data-testid={`info-${group}`}>
      <div className="flex flex-col gap-3 items-start pb-6">
        <span
          className={`rounded-full px-3 py-1 text-sm font-semibold ${solid ? "bg-kb text-on-accent dark:bg-kb-dark dark:text-background" : "bg-kb/10 text-kb-dark dark:bg-kb-dark/20"}`}
        >
          {t("tag")}
        </span>
        <h3 className="text-2xl @min-[40rem]:text-3xl font-semibold tracking-[-0.02em] leading-tight dark:text-kb-dark!">{t("title")}</h3>
        <p className="text-lg leading-relaxed text-foreground-soft">{t("body")}</p>
      </div>
      <ul className="flex flex-col gap-5 border-t-2 border-border-soft pt-6">
        {rows.map(({ key, icon: Icon }) => (
          <li key={key} className="flex items-start gap-4">
            <span className="flex items-center justify-center w-11 h-11 shrink-0 rounded-full bg-kb/10 text-kb-dark dark:bg-kb-dark/20">
              <Icon size={24} weight="bold" aria-hidden="true" />
            </span>
            <div className="flex flex-col gap-0.5">
              <span className="text-sm font-semibold uppercase tracking-wide text-muted">{t(`rows.${key}.label`)}</span>
              <span className="text-lg font-medium leading-snug">{t(`rows.${key}.value`)}</span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Project and platform as two separate panels. */
export function PurposeSection() {
  const t = useTranslations("eventInfo.purpose");
  return (
    <Band testId="info-purpose">
      <div className="flex flex-col gap-10 @min-[40rem]:gap-14">
        <SectionHeading>{t("heading")}</SectionHeading>
        <div className="grid grid-cols-1 @min-[48rem]:grid-cols-2 gap-4 @min-[40rem]:gap-6">
          <Panel group="project" rows={PROJECT_ROWS} solid={false} />
          <Panel group="platform" rows={PLATFORM_ROWS} solid />
        </div>
      </div>
    </Band>
  );
}

/** Contact block at the end of the page, one address and a short invitation. */
export function ContactSection() {
  const t = useTranslations("eventInfo.contact");
  const contactEmail = useLegal()?.contactEmail ?? "";
  return (
    <Band testId="info-contact">
      <div className="grid grid-cols-1 @min-[64rem]:grid-cols-[minmax(0,4fr)_minmax(0,8fr)] gap-6 @min-[64rem]:gap-16 items-start">
        <SectionHeading>{t("heading")}</SectionHeading>
        <div className="flex flex-col items-start gap-6">
          <p className="text-lg @min-[40rem]:text-xl leading-snug text-foreground-soft max-w-prose">{t("body")}</p>
          {contactEmail && (
            <a
              href={`mailto:${contactEmail}`}
              className="inline-flex items-center gap-3 px-5 py-3 text-base btn-primary rounded-md transition-colors"
              data-testid="info-contact-mail"
            >
              <Envelope size={22} weight="bold" aria-hidden="true" />
              {contactEmail}
            </a>
          )}
        </div>
      </div>
    </Band>
  );
}
