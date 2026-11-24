"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { JOBS_CHANGED_EVENT, JOBS_STATUS_CHANGED_EVENT } from "@/lib/jobs-events";
import type { MyJob } from "./_myJob";

const CHANNEL = "askf-jobs";
// Through the proxy, so every dev server reaches its own backend.
const STREAM_URL = "/api/jobs/stream";
const FALLBACK_POLL_MS = 30000;

/** The newest own jobs, kept current by the stream and shared with the other tabs. */
export function useMyJobs(): MyJob[] {
  const [jobs, setJobs] = useState<MyJob[]>([]);
  const prevJobStatusesRef = useRef<Record<string, { status: string; isGeneratingScripts?: boolean }>>({});

  const applyJobs = useCallback((newJobs: MyJob[]) => {
    setJobs(newJobs);
    const prev = prevJobStatusesRef.current;
    const prevUuids = Object.keys(prev);
    const newUuids = new Set(newJobs.map((j) => j.job_uuid));
    const jobRemoved = prevUuids.some((uuid) => !newUuids.has(uuid));
    const changed = jobRemoved || newJobs.some((j) =>
      prev[j.job_uuid] !== undefined && (
        prev[j.job_uuid].status !== j.status ||
        prev[j.job_uuid].isGeneratingScripts !== j.is_generating_scripts
      )
    );
    if (changed) window.dispatchEvent(new CustomEvent(JOBS_STATUS_CHANGED_EVENT));
    prevJobStatusesRef.current = Object.fromEntries(
      newJobs.map((j) => [j.job_uuid, { status: j.status, isGeneratingScripts: j.is_generating_scripts }])
    );
  }, []);

  const fetchJobs = useCallback(async () => {
    try {
      const res = await fetch("/api/jobs/my?limit=20", { credentials: "include" });
      if (!res.ok) return;
      const data = await res.json();
      applyJobs(data.jobs ?? []);
    } catch {
      // silently ignore
    }
  }, [applyJobs]);

  // The stream only runs in the visible tab, otherwise the 6 connections fill up fast.
  useEffect(() => {
    let es: EventSource | null = null;
    let fallbackPoll: ReturnType<typeof setInterval> | null = null;
    // One channel for both directions, a tab never hears its own messages.
    const bc = new BroadcastChannel(CHANNEL);
    bc.onmessage = (e) => { if (e.data?.jobs) applyJobs(e.data.jobs); };

    const stopFallback = () => {
      if (fallbackPoll) { clearInterval(fallbackPoll); fallbackPoll = null; }
    };

    const openSSE = () => {
      if (es && es.readyState !== EventSource.CLOSED) return;
      if (es) es.close();
      es = new EventSource(STREAM_URL, { withCredentials: true });
      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          applyJobs(data.jobs ?? []);
          bc.postMessage({ jobs: data.jobs ?? [] });
        } catch { /* ignore parse errors */ }
        stopFallback();
      };
      // EventSource retries by itself, only a dead connection needs the fallback.
      es.onerror = () => {
        if (es?.readyState !== EventSource.CLOSED || fallbackPoll) return;
        fallbackPoll = setInterval(() => { fetchJobs(); openSSE(); }, FALLBACK_POLL_MS);
      };
    };

    const closeSSE = () => {
      if (es) { es.close(); es = null; }
    };

    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        openSSE();
        fetchJobs(); // immediate snapshot on tab switch
      } else {
        closeSSE();
        stopFallback();
      }
    };

    document.addEventListener("visibilitychange", onVisibility);

    // Initial fetch so the dot shows immediately before first SSE message arrives
    fetchJobs();
    if (document.visibilityState === "visible") openSSE();

    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      closeSSE();
      bc.close();
      stopFallback();
    };
  }, [applyJobs, fetchJobs]);

  // Refresh immediately when any tool page starts or cancels a job
  useEffect(() => {
    const handler = () => fetchJobs();
    window.addEventListener(JOBS_CHANGED_EVENT, handler);
    return () => window.removeEventListener(JOBS_CHANGED_EVENT, handler);
  }, [fetchJobs]);

  return jobs;
}
