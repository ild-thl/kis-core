"use client";

import { useCallback, useEffect, type Dispatch, type MutableRefObject } from "react";
import { JobPausedError, parseDetail, pollJob, type JobStatus } from "@/lib/api";
import { notifyJobsChanged } from "@/lib/jobs-events";
import type { SlideData } from "@/types";
import type { ProviderWithVoices } from "@/hooks/useVoices";
import type { useFailedRender } from "@/hooks/useFailedRender";
import type { useRenderResult } from "@/hooks/useRenderResult";
import { computeVoiceLabel, laufStempelAusMeta, mitLaufStempel, renderProgress, type RenderProgress } from "../_utils";
import type { FlowAction } from "../_reducer";

export const RENDER_SESSION_KEY = "askf_screencast_active_render";

export interface RenderFlowMessages {
  stuck: string;
  queue: string;
  reconnected: string;
  renderError: string;
  retryFailed: string;
  tooManyJobs: string;
  jobFailed: string;
  unknownError: string;
  previousRenderBusy: string;
  renderLabel: (p: RenderProgress) => string;
}

interface UseScreencastRenderFlowOptions {
  // Flow state
  translateJobUuid: string;
  slides: SlideData[];
  dispatch: Dispatch<FlowAction>;

  // Render config
  targetLang: string;
  speed: number;
  slidePause: number;
  subtitles: boolean;
  dpi: number;
  voiceId: string;
  providerId: number;
  providers: ProviderWithVoices[];
  videoFolien: number[];
  neuVertonen: number[];

  // Sub-hooks
  failedRender: ReturnType<typeof useFailedRender>;
  renderResult: ReturnType<typeof useRenderResult>;

  // External callbacks
  checkBeforeSubmit: () => Promise<boolean>;
  goError: (msg: string) => void;
  setTtsSettingsError: (msg: string) => void;
  setRenderProgressLabel: (label: string) => void;
  setFertigeFolien: (folien: number[]) => void;
  setNichtDabei: (folien: number[]) => void;

  // Translated messages (from the component)
  messages: RenderFlowMessages;

  // Refs
  abortControllerRef: MutableRefObject<AbortController | null>;
  currentJobUuidRef: MutableRefObject<string | null>;
}

export function useScreencastRenderFlow(opts: UseScreencastRenderFlowOptions) {
  const {
    translateJobUuid,
    slides,
    dispatch,
    targetLang,
    speed,
    slidePause,
    subtitles,
    dpi,
    voiceId,
    providerId,
    providers,
    videoFolien,
    neuVertonen,
    failedRender,
    renderResult,
    checkBeforeSubmit,
    goError,
    setTtsSettingsError,
    setRenderProgressLabel,
    setFertigeFolien,
    setNichtDabei,
    messages,
    abortControllerRef,
    currentJobUuidRef,
  } = opts;

  const newSignal = useCallback(() => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = new AbortController();
    return abortControllerRef.current.signal;
  }, [abortControllerRef]);

  const onRenderProgress = useCallback(
    (status: JobStatus) => {
      const p = renderProgress(status);
      setRenderProgressLabel(messages.renderLabel(p));
      if (p.kind === "tts") {
        setFertigeFolien(p.fertig);
        setNichtDabei(p.nichtDabei);
      }
    },
    [setRenderProgressLabel, setFertigeFolien, setNichtDabei, messages],
  );

  const processRenderResultFromJob = useCallback(
    async (jobResult: JobStatus) => {
      sessionStorage.removeItem(RENDER_SESSION_KEY);
      const meta = jobResult.meta ?? {};
      const laufStempel = laufStempelAusMeta(meta);
      const videoUrl = mitLaufStempel(`/api/jobs/${jobResult.job_uuid}/video`, laufStempel);
      renderResult.apply(videoUrl, {
        audioId: meta.audio_id as string | undefined,
        audioCount: meta.audio_count as number | undefined,
        laufStempel,
        hasSubtitles: meta.subtitles === true,
        videoFolien: (meta.video_folien as number[] | undefined) ?? null,
      });
      dispatch({ type: "SET_LOADING", loading: false });
      dispatch({ type: "SET_STEP", step: "done" });
    },
    [dispatch, renderResult],
  );

  // ── Render from accepted scripts ──
  const handleStartRender = useCallback(async () => {
    setTtsSettingsError("");
    // Without this an old video makes the new run look like a review.
    renderResult.clear();
    // The lists of the last run would otherwise label the new one wrongly.
    setFertigeFolien([]);
    setNichtDabei([]);
    if (!translateJobUuid) {
      const ok = await checkBeforeSubmit();
      if (!ok) return;
    }
    dispatch({ type: "SET_STEP", step: "rendering" });
    dispatch({ type: "SET_LOADING", loading: true });
    const signal = newSignal();
    try {
      const uploadRes = await fetch("/api/screencast/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scripts: slides.map((s) => s.script),
          translate_job_uuid: translateJobUuid,
          target_lang: targetLang,
          voice_id: voiceId,
          voice_label: computeVoiceLabel(providerId, voiceId, providers),
          speed,
          slide_pause: slidePause,
          dpi,
          provider_id: providerId,
          subtitles,
          video_folien: videoFolien,
          neu_vertonen: neuVertonen,
        }),
        credentials: "include",
      });
      if (!uploadRes.ok) {
        const err = await uploadRes.json().catch(() => ({ detail: messages.renderError }));
        // 409 = previous render still stopping — stay on settings, show inline message
        if (uploadRes.status === 409) {
          dispatch({ type: "SET_STEP", step: "tts-settings" });
          dispatch({ type: "SET_LOADING", loading: false });
          setTtsSettingsError(messages.previousRenderBusy);
          return;
        }
        throw new Error(parseDetail(err.detail, messages.unknownError));
      }
      const { job_uuid } = await uploadRes.json();
      currentJobUuidRef.current = job_uuid;
      sessionStorage.setItem(RENDER_SESSION_KEY, JSON.stringify({ uuid: job_uuid }));
      notifyJobsChanged();

      if (signal.aborted) {
        await fetch(`/api/jobs/${job_uuid}/cancel`, { method: "POST", credentials: "include" }).catch(() => {});
        currentJobUuidRef.current = null;
        return;
      }

      const jobResult = await pollJob(
        job_uuid,
        onRenderProgress,
        5000,
        signal,
        () => setRenderProgressLabel(messages.stuck),
        60_000,
      );
      currentJobUuidRef.current = null;
      await processRenderResultFromJob(jobResult);
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      sessionStorage.removeItem(RENDER_SESSION_KEY);
      failedRender.mark(currentJobUuidRef.current, err instanceof JobPausedError);
      goError(err instanceof Error ? err.message : messages.unknownError);
    }
  }, [
    slides, translateJobUuid, targetLang, voiceId, providerId, providers,
    speed, slidePause, dpi, subtitles, videoFolien, neuVertonen,
    newSignal, onRenderProgress, setRenderProgressLabel, setTtsSettingsError,
    setFertigeFolien, setNichtDabei,
    failedRender, renderResult, processRenderResultFromJob,
    checkBeforeSubmit, goError, dispatch, currentJobUuidRef, messages,
  ]);

  // ── Retry a failed render ──
  const handleRetryRender = useCallback(async () => {
    const uuid = failedRender.jobUuid;
    if (!uuid) return;
    try {
      const res = await fetch(`/api/jobs/${uuid}/retry`, { method: "POST", credentials: "include" });

      if (res.status === 409) {
        const jobRes = await fetch(`/api/jobs/${uuid}`, { credentials: "include" });
        const jobData = await jobRes.json();
        if (jobData.status === "failed") {
          const err = await res.json().catch(() => ({}));
          throw new Error(parseDetail(err.detail, messages.tooManyJobs));
        }
        if (jobData.status === "success") {
          failedRender.clear();
          await processRenderResultFromJob(jobData);
          return;
        }
        // Job is running — fall through to polling
      } else if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: messages.retryFailed }));
        throw new Error(parseDetail(err.detail, messages.retryFailed));
      }

      setRenderProgressLabel(messages.queue);
      currentJobUuidRef.current = uuid;
      sessionStorage.setItem(RENDER_SESSION_KEY, JSON.stringify({ uuid }));
      notifyJobsChanged();
      dispatch({ type: "SET_STEP", step: "rendering" });
      dispatch({ type: "SET_ERROR_MESSAGE", message: "" });
      dispatch({ type: "SET_LOADING", loading: true });
      const signal = newSignal();
      const jobResult = await pollJob(
        uuid, onRenderProgress, 3000, signal,
        () => setRenderProgressLabel(messages.stuck), 60_000,
      );
      currentJobUuidRef.current = null;
      sessionStorage.removeItem(RENDER_SESSION_KEY);
      failedRender.clear();
      notifyJobsChanged();
      await processRenderResultFromJob(jobResult);
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      sessionStorage.removeItem(RENDER_SESSION_KEY);
      const msg = err instanceof Error ? err.message : messages.retryFailed;
      failedRender.mark(uuid, err instanceof JobPausedError);
      goError(msg);
    }
  }, [
    failedRender,
    newSignal, onRenderProgress, setRenderProgressLabel,
    processRenderResultFromJob, goError, dispatch, currentJobUuidRef, messages,
  ]);

  // Two ways to reconnect: a reload in the tab and a jump from the job list.
  const reconnectToRender = useCallback((uuid: string) => {
    sessionStorage.setItem(RENDER_SESSION_KEY, JSON.stringify({ uuid }));
    fetch(`/api/jobs/${uuid}`, { credentials: "include" })
      .then((r) => {
        // Stale job from a previous session/account - nothing to reconnect to, fail silently.
        if (!r.ok) {
          sessionStorage.removeItem(RENDER_SESSION_KEY);
          return null;
        }
        return r.json();
      })
      .then((job) => {
        if (!job) return;
        if (job.status === "success") {
          // Finished while nobody was looking: go straight to the finished page.
          processRenderResultFromJob(job).catch(() => {});
          return;
        }
        if (job.status === "failed" || job.status === "paused") {
          sessionStorage.removeItem(RENDER_SESSION_KEY);
          failedRender.mark(uuid, job.status === "paused");
          goError(job.error || messages.jobFailed);
          return;
        }
        currentJobUuidRef.current = uuid;
        setRenderProgressLabel(messages.reconnected);
        dispatch({ type: "SET_STEP", step: "rendering" });
        dispatch({ type: "SET_LOADING", loading: true });
        const ctrl = new AbortController();
        abortControllerRef.current = ctrl;
        pollJob(uuid, onRenderProgress, 3000, ctrl.signal,
          () => setRenderProgressLabel(messages.stuck), 60_000)
          .then((jobResult) => {
            sessionStorage.removeItem(RENDER_SESSION_KEY);
            currentJobUuidRef.current = null;
            failedRender.clear();
            notifyJobsChanged();
            processRenderResultFromJob(jobResult);
          })
          .catch((err) => {
            if (err instanceof Error && err.name === "AbortError") return;
            sessionStorage.removeItem(RENDER_SESSION_KEY);
            failedRender.mark(uuid, err instanceof JobPausedError);
            goError(err.message);
          });
      })
      .catch(() => sessionStorage.removeItem(RENDER_SESSION_KEY));
  }, [
    failedRender, goError, dispatch, messages, onRenderProgress,
    processRenderResultFromJob, setRenderProgressLabel,
    abortControllerRef, currentJobUuidRef,
  ]);

  // On a reload in the same tab the page reattaches by itself.
  useEffect(() => {
    const saved = sessionStorage.getItem(RENDER_SESSION_KEY);
    if (!saved) return;
    try {
      reconnectToRender(JSON.parse(saved).uuid);
    } catch {
      sessionStorage.removeItem(RENDER_SESSION_KEY);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    handleStartRender,
    handleRetryRender,
    newSignal,
    reconnectToRender,
    processRenderResultFromJob,
  };
}
