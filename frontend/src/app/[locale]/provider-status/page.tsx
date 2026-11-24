"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import ProtectedRoute from "@/components/auth/ProtectedRoute";
import Spinner from "@/components/ui/Spinner";
import { toMs } from "@/lib/format";

type Eintrag = { name: string; status: "ok" | "error" | "busy" | null; checked_at: string | null };
type StatusResponse = { chat: Eintrag[]; tts: Eintrag[]; image_gen: Eintrag[] };

// Display order: the three capabilities users actually pick a provider for.
const GRUPPEN: Array<keyof StatusResponse> = ["chat", "tts", "image_gen"];

export default function ProviderStatusPage() {
  return (
    <ProtectedRoute>
      <ProviderStatusBody />
    </ProtectedRoute>
  );
}

// The oldest check on the page, so the time shown never claims more than every row has.
function geprueftUm(data: StatusResponse): number | null {
  const zeiten = GRUPPEN.flatMap((key) => data[key])
    .map((e) => e.checked_at)
    .filter((z): z is string => !!z)
    .map(toMs);
  return zeiten.length ? Math.min(...zeiten) : null;
}

function ProviderStatusBody() {
  const t = useTranslations("ki.providerStatus");
  const locale = useLocale();
  const [data, setData] = useState<StatusResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);

  const laden = useCallback((url: string, init?: RequestInit) => {
    return fetch(url, { credentials: "include", ...init })
      .then((res) => (res.ok ? (res.json() as Promise<StatusResponse>) : Promise.reject(new Error(String(res.status)))))
      .then((d) => {
        setData(d);
        setFailed(false);
      })
      .catch(() => setFailed(true));
  }, []);

  useEffect(() => {
    laden("/api/providers/status").finally(() => setLoading(false));
  }, [laden]);

  const pruefen = () => {
    setChecking(true);
    laden("/api/providers/status/refresh", { method: "POST" }).finally(() => setChecking(false));
  };

  const zeit = data ? geprueftUm(data) : null;

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-10">
      <div className="border border-border-soft rounded-xl bg-background p-6 sm:p-8">
        <h1 className="text-lg font-semibold text-foreground mb-1.5">{t("title")}</h1>
        <p className="text-sm text-muted-soft mb-5 max-w-[46ch]">{t("hint")}</p>

        <div className="flex items-center gap-3 mb-7">
          <button
            type="button"
            onClick={pruefen}
            disabled={loading || checking}
            className="btn-outline-accent inline-flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg text-sm font-semibold transition-all disabled:opacity-40"
          >
            {checking ? t("checking") : t("refresh")}
          </button>
          {checking ? (
            <Spinner />
          ) : zeit !== null ? (
            <span className="text-xs text-muted-soft">
              {t("checkedAt", {
                time: new Date(zeit).toLocaleTimeString(locale === "en" ? "en-GB" : "de-DE", {
                  hour: "2-digit",
                  minute: "2-digit",
                  timeZone: "Europe/Berlin",
                }),
              })}
            </span>
          ) : null}
        </div>

        {loading ? (
          <Spinner className="flex justify-center py-12" />
        ) : failed || !data ? (
          <p className="text-sm text-error">{t("loadError")}</p>
        ) : (
          <>
            <div>
              {GRUPPEN.map((key, i) => (
                <section key={key} className={i > 0 ? "border-t border-border-soft pt-4 mt-4" : ""}>
                  <p className="text-sm font-semibold text-foreground mb-3">{t(`group.${key}`)}</p>
                  {data[key].length === 0 ? (
                    <p className="text-xs text-muted-soft italic pb-2">{t("empty")}</p>
                  ) : (
                    data[key].map((p) => <ProviderRow key={p.name} entry={p} />)
                  )}
                </section>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ProviderRow({ entry }: { entry: Eintrag }) {
  const t = useTranslations("ki.providerStatus");
  const { label, farbe } =
    entry.status === "ok"
      ? { label: t("statusActive"), farbe: "text-success" }
      : entry.status === "error"
        ? { label: t("statusError"), farbe: "text-error" }
        : entry.status === "busy"
          ? { label: t("statusBusy"), farbe: "text-muted-soft" }
          : { label: t("statusUnprobed"), farbe: "text-muted-soft" };

  return (
    <div className="flex items-center gap-2.5 py-2">
      <span className="text-sm font-medium text-foreground">{entry.name}</span>
      <span className={`ml-auto text-sm font-semibold ${farbe}`}>{label}</span>
    </div>
  );
}
