"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { parseDetail } from "@/lib/api";
import type { WorkspaceDetail, Source } from "../_types";
import { classicUpload } from "./classicUpload";
import { forgetUpload, uploadFile } from "@/lib/directUpload";

// From this size an upload fills a typical home uplink long enough to slow the page down.
const LARGE_UPLOAD_BYTES = 50 * 1024 * 1024;

interface UseSourcesOptions {
  uuid: string;
  onModuleUpdate?: (workspace: WorkspaceDetail) => void;
}

export function useSources({ uuid, onModuleUpdate }: UseSourcesOptions) {
  const t = useTranslations("workspace.detail.errors");
  const [sources, setSources] = useState<Source[]>([]);
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);
  const [uploadProgress, setUploadProgress] = useState<{ current: number; total: number; percent: number; large: boolean } | null>(null);
  const [uploadErrors, setUploadErrors] = useState<{ filename: string; message: string }[]>([]);

  // Persist selected sources
  useEffect(() => {
    if (selectedSourceIds.length > 0) {
      sessionStorage.setItem(`askf-selected-sources-${uuid}`, JSON.stringify(selectedSourceIds));
    }
  }, [selectedSourceIds, uuid]);

  // Keep polling while a source is still being processed.
  useEffect(() => {
    const isProcessing = (s: Source) =>
      s.status === "pending" || s.status === "indexing" || (s.status === "ready" && !!s.progress);
    const isFullyReady = (s: Source) => s.status === "ready" && !s.progress;
    const pendingIds = sources.filter(isProcessing).map((s) => s.uuid);
    if (pendingIds.length === 0) return;
    let cancelled = false;
    const id = setInterval(async () => {
      try {
        const res = await fetch(`/api/ai-assistant/workspaces/${uuid}`, { credentials: "include" });
        if (!res.ok) return;
        const mod: WorkspaceDetail = await res.json();
        // An answer that arrives after the list changed would overwrite the newer state.
        if (cancelled) return;
        const srcs: Source[] = mod.sources ?? [];
        setSources(srcs);
        onModuleUpdate?.(mod);
        setSelectedSourceIds((prev) => {
          const justBecameReady = srcs.filter((s) => isFullyReady(s) && pendingIds.includes(s.uuid) && !prev.includes(s.uuid)).map((s) => s.uuid);
          return justBecameReady.length > 0 ? [...prev, ...justBecameReady] : prev;
        });
      } catch { /* the next tick asks again */ }
    }, 3000);
    return () => { cancelled = true; clearInterval(id); };
  }, [sources, uuid, onModuleUpdate]);

  const toggleSource = useCallback((srcUuid: string) => {
    setSelectedSourceIds((prev) =>
      prev.includes(srcUuid) ? prev.filter((id) => id !== srcUuid) : [...prev, srcUuid]
    );
  }, []);

  const deleteSource = useCallback(async (srcUuid: string) => {
    try {
      const res = await fetch(`/api/ai-assistant/workspaces/${uuid}/sources/${srcUuid}`, { method: "DELETE", credentials: "include" });
      if (res.ok) {
        setSources((prev) => prev.filter((s) => s.uuid !== srcUuid));
        setSelectedSourceIds((prev) => prev.filter((id) => id !== srcUuid));
      }
    } catch { /* ignore */ }
  }, [uuid]);

  const renameSource = useCallback(async (srcUuid: string, name: string) => {
    // Unlike deleting this swallows no error, a rejected name has to be noticed.
    const res = await fetch(`/api/ai-assistant/workspaces/${uuid}/sources/${srcUuid}`, {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "");
    setSources((prev) => prev.map((s) => (s.uuid === srcUuid ? { ...s, filename: data.filename } : s)));
  }, [uuid]);

  const retrySource = useCallback(async (srcUuid: string) => {
    try {
      const res = await fetch(`/api/ai-assistant/workspaces/${uuid}/sources/${srcUuid}/retry`, { method: "POST", credentials: "include" });
      if (res.ok) {
        setSources((prev) => prev.map((s) => s.uuid === srcUuid ? { ...s, status: "pending", error_message: null } : s));
      }
    } catch { /* ignore */ }
  }, [uuid]);

  // The progress makes the row spin and keeps the polling on until the summary is there.
  const summarizeSource = useCallback(async (srcUuid: string) => {
    try {
      const res = await fetch(`/api/ai-assistant/workspaces/${uuid}/sources/${srcUuid}/summary`, { method: "POST", credentials: "include" });
      if (res.ok) {
        setSources((prev) => prev.map((s) => s.uuid === srcUuid ? { ...s, progress: { stage: "summarizing" } } : s));
      }
    } catch { /* ignore */ }
  }, [uuid]);

  // A new row goes straight into the chosen chapter, it stays outside when that fails.
  const placeInChapter = useCallback(async (src: Source, chapterUuid?: string | null): Promise<Source> => {
    if (!chapterUuid) return src;
    try {
      const res = await fetch(`/api/ai-assistant/workspaces/${uuid}/sources/${src.uuid}/chapter`, {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chapter_uuid: chapterUuid }),
      });
      return res.ok ? { ...src, chapter_uuid: chapterUuid } : src;
    } catch {
      return src;
    }
  }, [uuid]);

  const uploadFiles = useCallback(async (files: File[], chapterUuid?: string | null) => {
    if (files.length === 0) return;
    // Only caps absurdly large batches, the real limits are drawn by the backend.
    const MAX_BATCH = 30;
    const skipped = files.length > MAX_BATCH ? files.slice(MAX_BATCH) : [];
    const toUpload = files.length > MAX_BATCH ? files.slice(0, MAX_BATCH) : files;
    const errors: { filename: string; message: string }[] = skipped.map((f) => ({
      filename: f.name,
      message: t("uploadSkippedMax", { max: MAX_BATCH }),
    }));
    setUploadErrors(errors);
    let rateLimitHit = false;
    // Existing names save the network trip, the backend stays authoritative.
    const existingNames = new Set(sources.map((s) => (s.filename ?? "").trim().toLowerCase()));
    for (let i = 0; i < toUpload.length; i++) {
      const file = toUpload[i];
      if (rateLimitHit) {
        // If the limit is full, the remaining files bounce off just the same.
        errors.push({ filename: file.name, message: t("uploadSkippedLimit") });
        continue;
      }
      const nameKey = file.name.trim().toLowerCase();
      if (existingNames.has(nameKey)) {
        errors.push({ filename: file.name, message: t("uploadDuplicate") });
        continue;
      }
      // Guard against duplicates within the same drop too.
      existingNames.add(nameKey);
      // Only the classic route shares the page's connection, a direct upload leaves it free.
      const large = file.size >= LARGE_UPLOAD_BYTES;
      setUploadProgress({ current: i + 1, total: toUpload.length, percent: 0, large: false });
      // A full server answers 503 after a short wait, the file then goes again by itself.
      const sendOnce = () => classicUpload(
        uuid,
        file,
        (percent) => setUploadProgress({ current: i + 1, total: toUpload.length, percent, large }),
        { failed: t("uploadFailed"), network: t("networkError") },
      );
      try {
        // Large files go in parts straight into the bucket, the same core every tool uses.
        const context = { workspace_uuid: uuid };
        const token = await uploadFile({
          tool: "aia",
          file,
          context,
          onPercent: (percent) => setUploadProgress({ current: i + 1, total: toUpload.length, percent, large: false }),
          failedText: t("uploadFailed"),
        });
        if (token) {
          const res = await fetch(`/api/ai-assistant/workspaces/${uuid}/sources/from-upload`, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ upload_token: token }),
          });
          forgetUpload("aia", file, context);
          if (!res.ok) {
            const body = await res.json().catch(() => null);
            throw Object.assign(new Error(parseDetail(body?.detail, t("uploadFailed"))), { status: res.status });
          }
          const placed = await placeInChapter((await res.json()) as Source, chapterUuid);
          setSources((prev) => [placed, ...prev]);
          continue;
        }
        const bis = Date.now() + 20 * 60 * 1000;
        for (;;) {
          try {
            const placed = await placeInChapter(await sendOnce(), chapterUuid);
            setSources((prev) => [placed, ...prev]);
            break;
          } catch (err) {
            const busy = (err as { status?: number }).status === 503;
            if (!busy || Date.now() > bis) throw err;
            await new Promise((r) => setTimeout(r, 5000 + Math.random() * 5000));
          }
        }
      } catch (err) {
        if ((err as { status?: number }).status === 429) rateLimitHit = true;
        errors.push({ filename: file.name, message: err instanceof Error ? err.message : t("uploadFailed") });
      }
    }
    setUploadProgress(null);
    if (errors.length > 0) setUploadErrors(errors);
  }, [uuid, sources, t, placeInChapter]);

  // One JSON post for every link-based source, the answer is the new row.
  const postSource = useCallback(async (path: string, payload: Record<string, string>, chapterUuid?: string | null) => {
    let res: Response;
    try {
      res = await fetch(`/api/ai-assistant/workspaces/${uuid}/sources/${path}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch {
      throw new Error(t("networkError"));
    }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      // The reason arrives sometimes as an object and sometimes as text.
      throw new Error(parseDetail(body?.detail, t("uploadFailed")));
    }
    const newSrc = await placeInChapter((await res.json()) as Source, chapterUuid);
    setSources((prev) => [newSrc, ...prev]);
  }, [uuid, t, placeInChapter]);

  const addLink = useCallback(
    (url: string, chapterUuid?: string | null) => postSource("link", { url }, chapterUuid),
    [postSource],
  );

  const addYoutube = useCallback(
    (url: string, transcript: string, chapterUuid?: string | null) => postSource("youtube", { url, transcript }, chapterUuid),
    [postSource],
  );

  const addPage = useCallback(
    (jobUuid: string, chapterUuid?: string | null) => postSource("page", { job_uuid: jobUuid }, chapterUuid),
    [postSource],
  );

  const addText = useCallback(
    (title: string, text: string, chapterUuid?: string | null) => postSource("text", { title, text }, chapterUuid),
    [postSource],
  );

  // The row spins again, the polling picks up the source once it is read in anew.
  const editText = useCallback(async (srcUuid: string, text: string) => {
    let res: Response;
    try {
      res = await fetch(`/api/ai-assistant/workspaces/${uuid}/sources/${srcUuid}/text`, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
    } catch {
      throw new Error(t("networkError"));
    }
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(typeof data?.detail === "string" ? data.detail : t("uploadFailed"));
    setSources((prev) => prev.map((s) => (s.uuid === srcUuid ? { ...s, status: "pending", error_message: null } : s)));
  }, [uuid, t]);

  return {
    sources, setSources,
    selectedSourceIds, setSelectedSourceIds,
    uploadProgress,
    uploadErrors, setUploadErrors,
    toggleSource, deleteSource, renameSource, retrySource, summarizeSource, uploadFiles, addLink, addYoutube, addPage, addText, editText,
  };
}
