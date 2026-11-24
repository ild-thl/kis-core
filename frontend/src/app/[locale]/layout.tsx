import type { Metadata } from "next";
import { Geist } from "next/font/google";
import { cookies } from "next/headers";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { setRequestLocale, getMessages, getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { routing } from "@/i18n/routing";
import "../globals.css";
import "katex/dist/katex.min.css";
import FooterWrapper from "@/components/layout/FooterWrapper";
import LayoutShell from "@/components/layout/LayoutShell";
import MaintenanceGuard from "@/components/auth/MaintenanceGuard";
import ConsentGuard from "@/components/auth/ConsentGuard";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "layoutMeta" });
  return {
    title: t("title"),
    description: t("description"),
    authors: [{ name: t("author") }],
    other: { copyright: t("copyright") },
  };
}

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

// Render dynamically, otherwise the build freezes the state without a session.
export const dynamic = "force-dynamic";

// Backfills the theme cookie so the server reads it on the next request. Reads the bundled prefs, the old single key as fallback.
const themeBootScript = `(function(){try{var t;try{t=JSON.parse(localStorage.getItem('askf.prefs')||'{}').theme;}catch(e){}if(!t){try{t=JSON.parse(localStorage.getItem('kis.prefs')||'{}').theme;}catch(e){}}if(!t)t=localStorage.getItem('kis.theme');var hasCookie=document.cookie.indexOf('askf-theme=')!==-1;if(t==='dark'){document.documentElement.setAttribute('data-theme','dark');if(!hasCookie)document.cookie='askf-theme=dark; path=/; max-age=31536000; SameSite=Lax';}else if(t==='light'&&!hasCookie){document.cookie='askf-theme=light; path=/; max-age=31536000; SameSite=Lax';}}catch(e){}})();`;

type Props = {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
};

export default async function RootLayout({ children, params }: Props) {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) {
    notFound();
  }
  setRequestLocale(locale);
  const messages = await getMessages();
  const cookieStore = await cookies();
  const themeCookie = cookieStore.get("askf-theme")?.value;
  const dataTheme = themeCookie === "dark" ? "dark" : undefined;
  // Same switch as the backend, only AUTH_DISABLED turns on the local mode.
  const isLocalMode = ["1", "true", "yes", "on"].includes((process.env.AUTH_DISABLED ?? "").toLowerCase());
  const hasSession = isLocalMode || !!cookieStore.get("session")?.value;

  return (
    <html lang={locale} data-theme={dataTheme} suppressHydrationWarning>
      <head>
        <link rel="license" href="https://www.apache.org/licenses/LICENSE-2.0" />
        <script dangerouslySetInnerHTML={{ __html: themeBootScript }} />
      </head>
      <body className={`${geist.variable} min-h-dvh flex flex-col`} suppressHydrationWarning>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <MaintenanceGuard />
          <ConsentGuard />
          {/* The content fills at least one screen, so the footer only appears after scrolling. */}
          <main className="flex-1 min-h-dvh">
            <LayoutShell hasSession={hasSession}>{children}</LayoutShell>
          </main>
          <FooterWrapper hasSession={hasSession} />
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
