"use client";

/** Imprint and privacy policy as entered in Admin -> System, written in Markdown. */

import ReactMarkdown, { type Components } from "react-markdown";
import { useLocale, useTranslations } from "next-intl";
import { legalText, useLegal } from "@/lib/legal";

// Same classes the hard-coded pages had, the margins collapse so headings keep their old spacing.
const COMPONENTS: Components = {
  h1: ({ children }) => <h2 className="text-lg font-semibold mt-6 mb-2">{children}</h2>,
  h2: ({ children }) => <h2 className="text-lg font-semibold mt-6 mb-2">{children}</h2>,
  h3: ({ children }) => <p className="font-semibold text-foreground-soft mt-4 mb-2">{children}</p>,
  h4: ({ children }) => <p className="font-semibold text-foreground-soft mt-4 mb-2">{children}</p>,
  p: ({ children }) => <p className="text-foreground-soft whitespace-pre-line mb-2">{children}</p>,
  ul: ({ children }) => <ul className="list-disc pl-6 text-foreground-soft space-y-1 mb-2">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-6 text-foreground-soft space-y-1 mb-2">{children}</ol>,
  a: ({ href, children }) => (
    <a href={href} className="text-info hover:underline">
      {children}
    </a>
  ),
};

/** Plain Markdown without raw HTML, react-markdown escapes HTML and drops unsafe link targets on its own. */
export function LegalMarkdown({ text }: { text: string }) {
  return (
    <div className="[&>*:last-child]:mb-0">
      <ReactMarkdown components={COMPONENTS}>{text}</ReactMarkdown>
    </div>
  );
}

export default function LegalText({ kind }: { kind: "imprint" | "privacy" }) {
  const legal = useLegal();
  const locale = useLocale();
  const t = useTranslations("legal");
  if (legal === undefined) return null;
  const text = legal ? legalText(legal[kind], locale) : "";
  if (!text) {
    return (
      <p role="status" data-testid="legal-missing" className="rounded-lg border-2 border-border bg-surface-dim p-4 text-foreground-soft">
        {t(kind === "imprint" ? "imprintMissing" : "privacyMissing")}
      </p>
    );
  }
  return <LegalMarkdown text={text} />;
}
