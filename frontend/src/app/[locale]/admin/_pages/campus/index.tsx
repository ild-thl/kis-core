"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ArrowsClockwise, Trash, UploadSimple } from "@phosphor-icons/react";
import { SettingCard } from "@/app/[locale]/admin/_settings/fields";
import { backendApi, parseDetail } from "@/lib/api";
import { formatDate } from "@/lib/format";
import HelpTooltip from "@/components/ui/HelpTooltip";
import PagesList from "./PagesList";
import { appendFile } from "@/lib/directUpload";

interface Settings {
  sitemap_url: string;
  start_urls: string;
  url_include: string;
  url_exclude: string;
  retention_days: number;
}

interface Overview {
  settings: Settings;
  status: Record<string, unknown>;
  stats: {
    pages: Record<string, Record<string, number>>;
    chunks: number;
    last_fetched_at: string | null;
  };
  limits: { max_pages: number; max_chunks_per_page: number };
  nightly: { hour_utc: number; minute_utc: number } | null;
  documents: { id: number; filename: string; status: string; chunk_count: number; error_message: string | null; created_at: string | null }[];
}

const INPUT = "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:border-kb disabled:opacity-50";
const BTN_PRIMARY = "px-3 py-2 text-sm btn-primary rounded-md transition-colors whitespace-nowrap disabled:opacity-60";
const BTN_SECONDARY = "px-4 py-2 text-sm rounded-md border-2 border-border text-foreground-soft hover:border-kb transition-colors disabled:opacity-60";

/** Tonight's UTC run time as a wall-clock time in the browser's zone, so summer and winter time come out right. */
function localTime(hourUtc: number, minuteUtc: number, locale: string): string {
  const d = new Date();
  d.setUTCHours(hourUtc, minuteUtc, 0, 0);
  return d.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
}

function sum(counts: Record<string, number> | undefined): number {
  return Object.values(counts ?? {}).reduce((a, b) => a + b, 0);
}

export default function CampusAdminPage() {
  const t = useTranslations("admin.sections.campus");
  const locale = useLocale();
  const [data, setData] = useState<Overview | null>(null);
  const [form, setForm] = useState<Settings | null>(null);
  const [errors, setErrors] = useState<Partial<Record<keyof Settings, string>>>({});
  const [crawlError, setCrawlError] = useState<string | null>(null);
  const [docError, setDocError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const docRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const out = await backendApi.getJson<Overview>("/admin/campus");
    setData(out);
    setForm((prev) => prev ?? out.settings);
  }, []);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  // While a refresh runs or a document is processed the numbers change, so the page looks again every few seconds.
  const working = !!data?.status?.running || !!data?.documents.some((d) => d.status === "pending" || d.status === "indexing");
  useEffect(() => {
    if (!working) return;
    const id = setInterval(() => load().catch(() => undefined), 5000);
    return () => clearInterval(id);
  }, [working, load]);

  const set = (patch: Partial<Settings>) => setForm((f) => (f ? { ...f, ...patch } : f));

  // Like every other settings page: a field saves itself once it is left, other drafts stay untouched.
  const commit = async <K extends keyof Settings>(field: K, value: Settings[K] = form![field]) => {
    if (!data || value === data.settings[field]) return;
    setErrors((e) => ({ ...e, [field]: undefined }));
    try {
      const out = await backendApi.patchJson<Overview>("/admin/campus", { [field]: value });
      setData(out);
      setForm((f) => (f ? { ...f, [field]: out.settings[field] } : f));
    } catch (e) {
      setErrors((prev) => ({ ...prev, [field]: parseDetail((e as { detail?: unknown })?.detail, t("saveFailed")) }));
    }
  };

  const blurOnEnter = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") e.currentTarget.blur();
  };

  const cardError = (...fields: (keyof Settings)[]) => fields.map((f) => errors[f]).find(Boolean) ?? null;

  const crawl = async () => {
    setBusy(true);
    setCrawlError(null);
    try {
      await backendApi.postJson("/admin/campus/crawl", {});
      await load();
    } catch (e) {
      setCrawlError(parseDetail((e as { detail?: unknown })?.detail, t("saveFailed")));
    } finally {
      setBusy(false);
    }
  };

  const upload = async (path: string, file: File) => {
    setBusy(true);
    setDocError(null);
    try {
      const body = new FormData();
      // A large document goes in parts straight into the bucket, a small one with the request.
      const forgetUpload = await appendFile(body, { tool: "campus", file });
      const res = await backendApi.fetch(path, { method: "POST", body });
      forgetUpload();
      if (!res.ok) {
        let msg = t("saveFailed");
        try {
          msg = parseDetail((await res.json())?.detail, msg);
        } catch {
          // The generic text stays.
        }
        setDocError(msg);
      }
      await load();
    } catch {
      setDocError(t("saveFailed"));
    } finally {
      setBusy(false);
    }
  };

  const removeDocument = async (id: number) => {
    setBusy(true);
    setDocError(null);
    try {
      const res = await backendApi.fetch(`/admin/campus/documents/${id}`, { method: "DELETE" });
      if (!res.ok) setDocError(t("saveFailed"));
      await load();
    } catch {
      setDocError(t("saveFailed"));
    } finally {
      setBusy(false);
    }
  };

  if (!data || !form) return null;
  const status = data.status;
  const pages = data.stats.pages.page ?? {};
  const lastRun = typeof status.finished_at === "string" ? formatDate(status.finished_at, locale) : null;

  return (
    <div className="flex flex-col gap-4 max-w-3xl">
      <SettingCard title={t("status.title")}>
        <dl className="mt-3 grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
          <div><dt className="text-xs text-muted inline-flex items-center gap-1">{t("status.pages")}<HelpTooltip text={t("status.pagesHelp", { max: data.limits.max_pages, chunks: data.limits.max_chunks_per_page })} /></dt><dd className="font-medium">{sum(pages)}{pages.failed ? ` (${pages.failed} ${t("status.failed")})` : ""}</dd></div>
          <div><dt className="text-xs text-muted">{t("status.chunks")}</dt><dd className="font-medium">{data.stats.chunks}</dd></div>
          <div><dt className="text-xs text-muted">{t("status.documents")}</dt><dd className="font-medium">{sum(data.stats.pages.document)}</dd></div>
          <div className="col-span-2"><dt className="text-xs text-muted inline-flex items-center gap-1">{t("status.lastRun")}<HelpTooltip text={data.nightly ? t("status.lastRunHelp", { time: localTime(data.nightly.hour_utc, data.nightly.minute_utc, locale) }) : t("status.lastRunHelpNoTime")} /></dt><dd className="font-medium">{status.running ? t("status.running") : lastRun ?? t("status.never")}</dd></div>
        </dl>
        {typeof status.error === "string" && status.error && (
          <p className="mt-2 text-xs" style={{ color: "var(--error)" }}>{t("status.error")}: {status.error}</p>
        )}
        {typeof status.capped === "number" && status.capped > 0 && (
          <p className="mt-2 text-xs text-muted">{t("status.capped", { max: Number(status.max_pages) || 0, count: status.capped })}</p>
        )}
        {crawlError && <p className="mt-2 text-xs text-error">{crawlError}</p>}
        <div className="mt-4">
          <button type="button" onClick={crawl} disabled={busy || !!status.running} className={`${BTN_PRIMARY} inline-flex items-center gap-1.5`}>
            <ArrowsClockwise size={15} weight="bold" className={status.running ? "animate-spin" : undefined} />
            {status.running ? t("crawlQueued") : t("crawlNow")}
          </button>
        </div>
      </SettingCard>

      <SettingCard title={t("sitemapUrl")} description={t("sitemapHint")} error={cardError("sitemap_url", "start_urls", "url_include", "url_exclude")}>
        <div className="mt-3 flex flex-col gap-3">
          <textarea value={form.sitemap_url} onChange={(e) => set({ sitemap_url: e.target.value })} onBlur={() => commit("sitemap_url")} className={INPUT} rows={2} placeholder="https://" />
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted">{t("startUrls")}</span>
            <textarea value={form.start_urls} onChange={(e) => set({ start_urls: e.target.value })} onBlur={() => commit("start_urls")} className={INPUT} rows={2} placeholder="https://" />
            <span className="text-2xs text-muted">{t("startUrlsHint")}</span>
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted">{t("include")}</span>
              <textarea value={form.url_include} onChange={(e) => set({ url_include: e.target.value })} onBlur={() => commit("url_include")} className={INPUT} rows={3} />
              <span className="text-2xs text-muted">{t("includeHint")}</span>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted">{t("exclude")}</span>
              <textarea value={form.url_exclude} onChange={(e) => set({ url_exclude: e.target.value })} onBlur={() => commit("url_exclude")} className={INPUT} rows={3} />
              <span className="text-2xs text-muted">{t("excludeHint")}</span>
            </label>
          </div>
        </div>
      </SettingCard>

      <SettingCard title={t("retention")} description={t("retentionHint")} error={cardError("retention_days")}>
        <div className="mt-3 flex items-center gap-2">
          <input type="number" min={0} max={3650} value={form.retention_days} onChange={(e) => set({ retention_days: Number(e.target.value) })} onBlur={() => commit("retention_days")} onKeyDown={blurOnEnter} className={INPUT.replace("w-full", "w-28")} />
          <span className="text-sm text-muted">{t("days")}</span>
        </div>
      </SettingCard>

      <PagesList refreshKey={pages.ready ?? 0} />

      <SettingCard title={t("documents.title")} description={t("documents.hint")}>
        <div className="mt-3 flex flex-col gap-2">
          <input ref={docRef} type="file" accept=".pdf,.docx,.pptx,.md,.txt" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload("/admin/campus/documents", f); e.target.value = ""; }} />
          <div>
            <button type="button" onClick={() => docRef.current?.click()} disabled={busy} className={`${BTN_SECONDARY} inline-flex items-center gap-1.5`}>
              <UploadSimple size={15} weight="bold" />
              {t("documents.upload")}
            </button>
          </div>
          {docError && <p className="text-xs text-error">{docError}</p>}
          {data.documents.length === 0 ? (
            <p className="text-xs text-muted">{t("documents.empty")}</p>
          ) : (
            <ul className="flex flex-col divide-y divide-border-soft">
              {data.documents.map((d) => (
                <li key={d.id} className="flex items-center gap-3 py-2 text-sm">
                  <span className="flex-1 min-w-0 truncate">{d.filename}</span>
                  <span className="text-xs text-muted whitespace-nowrap">
                    {t(`documents.status.${d.status}` as "documents.status.ready")}
                    {d.status === "ready" ? ` (${d.chunk_count})` : ""}
                  </span>
                  <button type="button" onClick={() => removeDocument(d.id)} disabled={busy} title={t("documents.delete")} className="w-7 h-7 flex items-center justify-center rounded-full btn-icon" style={{ backgroundColor: "var(--surface-dim)" }}>
                    <Trash size={13} weight="bold" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </SettingCard>
    </div>
  );
}
