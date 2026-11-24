"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useTranslations } from "next-intl";

import { campusApi } from "@/lib/campus/api";

// The THL lettering is much heavier than the rest, a narrower cap evens out how much of its tile it fills.
const PARTNERS = [
  { src: "/logos/logo-thl.jpg", alt: "TH Lübeck", href: "https://www.th-luebeck.de", width: 473, height: 166, maxWidth: "78%" },
  { src: "/logos/isy-logo.png", alt: "ISY", href: "https://www.th-luebeck.de/isy/", width: 634, height: 523 },
  { src: "/logos/stiftung-hochschullehre.jpg", alt: "Gefördert durch die Stiftung Innovation in der Hochschullehre", href: "https://stiftung-hochschullehre.de/", width: 1920, height: 942 },
];

const TILE = "flex items-center justify-center bg-white rounded-lg px-4 py-3 h-20 sm:h-24";
const LOGO = "max-h-full max-w-full w-auto h-auto object-contain";

export default function Footer({ loggedIn }: { loggedIn?: boolean }) {
  const t = useTranslations("footer");
  const [mapUrl, setMapUrl] = useState("");

  // The map link is an admin setting, without it the footer shows no map link.
  useEffect(() => {
    campusApi.map().then((r) => setMapUrl(r.map_url)).catch(() => setMapUrl(""));
  }, []);

  return (
    <footer
      className="px-6 pt-10 pb-6 text-base"
      style={{ backgroundColor: "var(--header-bg)", color: "rgba(255,255,255,0.6)", borderTop: "1px solid var(--border)" }}
    >
      <div className="mx-auto w-full max-w-5xl flex flex-col gap-8">
        {loggedIn && (
          <div className="pb-6 text-xs leading-relaxed text-center" style={{ borderBottom: "1px solid rgba(255,255,255,0.15)" }}>
            <div className="mx-auto max-w-2xl flex flex-col gap-1">
              <p>{t("aiNotice")}</p>
              <p>
                <Link href="/feedback" className="link-footer">
                  {t("feedback")}
                </Link>
              </p>
            </div>
          </div>
        )}
        <div className="flex flex-col md:flex-row items-stretch gap-4 md:gap-8">
          <Link href={loggedIn ? "/workspace" : "/"} aria-label="KIS" className={`${TILE} logo-link md:w-60 flex-shrink-0`}>
            <Image src="/logos/kis-logo-claim.svg" alt="KIS – KInternationalisierung von Studiengängen" width={228} height={142} className={LOGO} />
          </Link>
          <div className="hidden md:block w-px self-stretch" style={{ backgroundColor: "rgba(255,255,255,0.15)" }} />
          <div className="grid grid-cols-3 gap-3 sm:gap-4 flex-1">
            {PARTNERS.map((p) => (
              <a key={p.src} href={p.href} target="_blank" rel="noopener noreferrer" aria-label={p.alt} className={`${TILE} logo-link`}>
                <Image src={p.src} alt={p.alt} width={p.width} height={p.height} className={LOGO} style={{ maxWidth: p.maxWidth }} />
              </a>
            ))}
          </div>
        </div>

        <div className="flex flex-col items-center gap-3 pt-6 text-center" style={{ borderTop: "1px solid rgba(255,255,255,0.15)" }}>
          <div className="text-sm">
            <Link href="/imprint" className="link-footer">
              {t("imprint")}
            </Link>
            <span className="mx-2 opacity-40">|</span>
            <Link href="/privacy" className="link-footer">
              {t("privacy")}
            </Link>
            {mapUrl && (
              <>
                <span className="mx-2 opacity-40">|</span>
                <Link href="/campusmap" target="_blank" rel="noopener noreferrer" className="link-footer">
                  {t("campusMap")}
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </footer>
  );
}
