"use client";

/** Access code as a poster in the stamp card look: scanning the QR opens the redeem page with the code filled in. */

import { forwardRef, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Key } from "@phosphor-icons/react";
import {
  ACCENT, INK, ISY_W, LOGO_IMG_H, LOGO_W, MONO, PAPER, PLATE_PAD, PLATE_W, SANS, SOFT, THL_W,
  nameLines, usePosterArt, type PosterArt,
} from "./event/PosterSvg";
import { POSTER_MM, exportPosterPng } from "./event/posterExport";

// Height of the askFrancis wordmark at the logo width, from its aspect ratio.
const WORDMARK_H = (LOGO_W * 13.08) / 89.78;

type Props = {
  code: string;
  label: string;
};

type PosterProps = {
  code: string;
  label: string;
  target: string;
  art: PosterArt | null;
};

const AccessCodePoster = forwardRef<SVGSVGElement, PosterProps>(function AccessCodePoster(
  { code, label, target, art },
  ref,
) {
  const t = useTranslations("admin.accessCodeQr");
  const lines = nameLines(label);
  const nameY = lines.length > 1 ? 68 : 72;
  const host = target.replace(/^https?:\/\//, "").split("?")[0];
  return (
    <svg
      ref={ref}
      xmlns="http://www.w3.org/2000/svg"
      viewBox={`0 0 ${POSTER_MM.w} ${POSTER_MM.h}`}
      className="w-full max-w-xs h-auto rounded-md border border-border shadow-sm"
      role="img"
      aria-label={t("alt")}
      data-testid="access-code-poster"
    >
      <rect width={POSTER_MM.w} height={POSTER_MM.h} fill={PAPER} />
      <rect width={POSTER_MM.w} height={16} fill={ACCENT} />
      {art && (
        <>
          <rect x={10} y={2} width={LOGO_W + PLATE_PAD * 2} height={12} rx={1.5} fill={PAPER} />
          <image href={art.francis} x={10 + PLATE_PAD} y={8 - WORDMARK_H / 2} width={LOGO_W} height={WORDMARK_H} />
        </>
      )}
      <text x={10 + LOGO_W + PLATE_PAD * 2 + 3} y={10.6} fontFamily={SANS} fontSize="5" fontWeight="600" fill={PAPER} letterSpacing="0.3">
        {t("kicker")}
      </text>
      {art && (
        <>
          <rect x={POSTER_MM.w - 10 - PLATE_W} y={2} width={PLATE_W} height={12} rx={1.5} fill={PAPER} />
          <image href={art.thl} x={POSTER_MM.w - 10 - PLATE_W + PLATE_PAD} y={4.5} width={THL_W} height={LOGO_IMG_H} />
          <image href={art.isy} x={POSTER_MM.w - 10 - PLATE_W + PLATE_PAD + THL_W + PLATE_PAD} y={4.5} width={ISY_W} height={LOGO_IMG_H} />
        </>
      )}
      <circle cx={74} cy={42} r={15} fill={ACCENT} />
      <Key x={63} y={31} width={22} height={22} color={PAPER} weight="bold" />
      {lines.map((line, i) => (
        <text key={i} x={74} y={nameY + i * 10} textAnchor="middle" fontFamily={SANS} fontSize="9" fontWeight="700" fill={INK}>
          {line}
        </text>
      ))}
      <rect x={38} y={84} width={72} height={72} rx={3} fill={PAPER} stroke={ACCENT} strokeWidth={0.6} />
      {art && <image href={art.qr} x={42} y={88} width={64} height={64} />}
      <text x={74} y={167} textAnchor="middle" fontFamily={SANS} fontSize="5.4" fill={SOFT}>
        {t("scanHint")}
      </text>
      <text x={74} y={185} textAnchor="middle" fontFamily={MONO} fontSize="12" fontWeight="700" fill={ACCENT} letterSpacing="1">
        {code}
      </text>
      <text x={74} y={196} textAnchor="middle" fontFamily={SANS} fontSize="4.2" fill={SOFT}>
        {host}
      </text>
      <rect x={10} y={203} width={128} height={1} fill={ACCENT} />
    </svg>
  );
});

export default function AccessCodeQr({ code, label }: Props) {
  const t = useTranslations("admin.accessCodeQr");
  const target = typeof window === "undefined" ? "" : `${window.location.origin}/redeem?code=${code}`;
  const art = usePosterArt(target);
  const svgRef = useRef<SVGSVGElement>(null);
  const [busy, setBusy] = useState(false);

  async function download() {
    if (!svgRef.current) return;
    setBusy(true);
    try {
      await exportPosterPng(svgRef.current, `zugangscode-${code}.png`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-center gap-3 py-2">
      <AccessCodePoster ref={svgRef} code={code} label={label} target={target} art={art} />
      <button
        type="button"
        onClick={() => void download()}
        disabled={!art || busy}
        className="px-4 py-2 text-sm btn-primary rounded-md disabled:opacity-50"
        data-testid="access-code-png"
      >
        {t("download")}
      </button>
    </div>
  );
}
