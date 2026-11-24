"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { CalendarBlank, Lock } from "@phosphor-icons/react";
import { useRouter } from "@/i18n/navigation";
import Spinner from "@/components/ui/Spinner";
import { TourInvite } from "./TourInvite";
import { LanguageTrainerInvite } from "./LanguageTrainerInvite";
import { EvaluationInvite } from "./EvaluationInvite";
import WorkspaceList from "./WorkspaceList";
import { formatDay } from "../_shared";
import { parseDetail } from "@/lib/api";
import { StampButton } from "../../_components/StampButton";
import { TaskCard, TaskGiftButton } from "@/components/event/TaskCard";
import { useEventTasks, useTaskCardMinimized } from "@/lib/event/tasks";
import { stampCardState, usePublicEvent } from "@/lib/event/usePublicEvent";

interface LinkPreview {
  workspace_uuid: string;
  title: string;
  /** Maintained voluntarily, so the line drops out entirely without it. */
  description?: string | null;
  /** Name of the teacher so the link gets a face. */
  owner_name?: string | null;
  access_until?: string | null;
  /** Whether this person may enter right now, enrolling works on a closed room too. */
  is_open?: boolean;
}

/** Two letters from the name for the circle next to the teacher. */
function initialen(name: string): string {
  const teile = name.trim().split(/\s+/).filter(Boolean);
  if (teile.length === 0) return "";
  const ersterBuchstabe = (wort: string) => [...wort][0] ?? "";
  return (ersterBuchstabe(teile[0]) + (teile.length > 1 ? ersterBuchstabe(teile[teile.length - 1]) : "")).toUpperCase();
}

interface Props {
  /** May own workspaces. Controls the owned block only, never the access link. */
  canCreate: boolean;
  /** Everyone holding the language level right gets the trainer offer. */
  languageInvite: boolean;
}

/** One start page for all roles, ownership decides the view. */
export default function WorkspaceHome({ canCreate, languageInvite }: Props) {
  const t = useTranslations("workspace.list");
  const locale = useLocale();
  const router = useRouter();
  const searchParams = useSearchParams();
  const tasks = useEventTasks();
  const [tasksMin, setTasksMin] = useTaskCardMinimized();
  const { data: event } = usePublicEvent();
  const stamp = stampCardState(event);
  const [enrolling, setEnrolling] = useState(false);
  const [enrollError, setEnrollError] = useState<string | null>(null);
  const [linkPreview, setLinkPreview] = useState<LinkPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewCode, setPreviewCode] = useState<string | null>(null);
  const [previewInvalid, setPreviewInvalid] = useState(false);
  // Enrolled in a closed course, without a notice the grey row would be inexplicable.
  const [joinedClosed, setJoinedClosed] = useState(false);

  useEffect(() => {
    const code = searchParams.get("code");
    if (!code) {
      setLinkPreview(null);
      setPreviewCode(null);
      setPreviewInvalid(false);
      return;
    }
    // A late answer for a code that is no longer in the address must not win.
    let cancelled = false;
    setPreviewCode(code);
    setPreviewLoading(true);
    setPreviewInvalid(false);
    fetch(`/api/ai-assistant/access-link/preview?code=${encodeURIComponent(code)}`, {
      credentials: "include",
    })
      .then(async (res) => {
        const data = res.ok ? ((await res.json()) as LinkPreview) : null;
        if (cancelled) return;
        setLinkPreview(data);
        setPreviewInvalid(!data);
      })
      .catch(() => {
        if (cancelled) return;
        setLinkPreview(null);
        setPreviewInvalid(true);
      })
      .finally(() => { if (!cancelled) setPreviewLoading(false); });
    return () => { cancelled = true; };
  }, [searchParams]);

  async function handleEnrollLink() {
    if (!previewCode) return;
    setEnrolling(true);
    setEnrollError(null);
    try {
      const res = await fetch("/api/ai-assistant/enroll", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enroll_code: previewCode }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(parseDetail(err.detail, t("enrollInvalidCode")));
      }
      const data = (await res.json()) as { workspace_uuid?: string; is_open?: boolean };
      // The way leads to the list, where the new row carries the notice.
      if (data.is_open === false) {
        setJoinedClosed(true);
        router.replace("/workspace");
        return;
      }
      if (data.workspace_uuid) router.replace(`/workspace/${data.workspace_uuid}`);
    } catch (err: unknown) {
      setEnrollError(err instanceof Error ? err.message : t("unknownError"));
    } finally {
      setEnrolling(false);
    }
  }

  // An access link takes over the page until it is accepted or turns out invalid.
  if (previewCode && previewLoading) {
    return (
      <div className="px-4 sm:px-6 md:px-8 pt-10 pb-20 lg:pt-15 lg:pb-30">
        <div className="max-w-5xl mx-auto flex items-center justify-center min-h-[40vh]">
          <Spinner size="lg" />
        </div>
      </div>
    );
  }

  if (linkPreview) {
    const zu = linkPreview.is_open === false;
    const zugangBis = linkPreview.access_until ? formatDay(linkPreview.access_until, locale) : null;
    return (
      <div className="px-4 sm:px-6 md:px-8 pt-10 pb-20 lg:pt-15 lg:pb-30">
        <div className="max-w-2xl mx-auto">
          <section
            className="rounded-xl p-6 sm:p-8 flex flex-col gap-5"
            style={{ backgroundColor: "var(--surface)", boxShadow: "var(--shadow)" }}
          >
            <div>
              <p className="text-2xs font-semibold uppercase tracking-wider" style={{ color: "var(--muted)" }}>
                {t("enrollEyebrow")}
              </p>
              <h2 className="text-2xl font-semibold mt-2" style={{ color: "var(--foreground)" }}>
                {linkPreview.title}
              </h2>
              {linkPreview.description && (
                <p className="text-sm mt-2 max-w-prose" style={{ color: "var(--foreground-soft)" }}>
                  {linkPreview.description}
                </p>
              )}
            </div>

            {(linkPreview.owner_name || zugangBis || zu) && (
              <hr style={{ borderColor: "var(--border-soft)" }} />
            )}

            {linkPreview.owner_name && (
              <div className="flex items-center gap-3">
                <span
                  className="flex items-center justify-center rounded-full shrink-0 text-xs font-semibold w-9 h-9"
                  style={{ backgroundColor: "var(--kb20)", color: "var(--kb)" }}
                  aria-hidden="true"
                >
                  {initialen(linkPreview.owner_name)}
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium truncate">{linkPreview.owner_name}</span>
                  <span className="block text-xs" style={{ color: "var(--muted)" }}>
                    {t("enrollOwnerRole")}
                  </span>
                </span>
              </div>
            )}

            {(zugangBis || zu) && (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs" style={{ color: "var(--muted)" }}>
                {zugangBis && (
                  <span className="inline-flex items-center gap-1 whitespace-nowrap">
                    <CalendarBlank size={13} />
                    {t("enrollAccessUntil", { date: zugangBis })}
                  </span>
                )}
                {/* Der Raum ist zu, das Einschreiben geht trotzdem. */}
                {zu && (
                  <span className="inline-flex items-center gap-1 whitespace-nowrap font-medium">
                    <Lock size={13} weight="fill" />
                    {t("closedBadge")}
                  </span>
                )}
              </div>
            )}

            {zu && (
              <p className="text-sm max-w-prose" style={{ color: "var(--muted)" }}>
                {t("closedJoinHint")}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={handleEnrollLink}
                data-testid="enroll-submit"
                disabled={enrolling}
                className="btn-primary px-8 py-3 rounded-lg text-base font-medium inline-flex items-center gap-2 disabled:opacity-50"
              >
                {enrolling && <Spinner size="sm" color="current" />}
                {enrolling ? t("enrolling") : t("enroll")}
              </button>
            </div>

            {enrollError && (
              <p className="text-sm" style={{ color: "var(--error)" }}>
                {enrollError}
              </p>
            )}
          </section>
        </div>
      </div>
    );
  }

  return (
    <div className="page-shell pt-6 pb-20 lg:pt-15 lg:pb-30">
      <div className="max-w-7xl mx-auto">
        {/* The folded task card, or else the stamp card, sits at the right end above the cards. */}
        {((tasks.visible && tasksMin) || (stamp && !tasks.visible)) && (
          <div className="flex justify-end mb-4">
            {tasks.visible && tasksMin && <TaskGiftButton done={tasks.done} onOpen={() => setTasksMin(false)} />}
            {stamp && !tasks.visible && <StampButton stamp={stamp} from={event?.stamp?.availableFrom ?? ""} title={event?.stamp?.title} body={event?.stamp?.body} />}
          </div>
        )}

        <div className="flex flex-col md:flex-row gap-4 mb-8 empty:hidden">
          {tasks.visible && !tasksMin && (
            <TaskCard
              done={tasks.done}
              workspace={tasks.workspace}
              workspaceTitle={tasks.workspaceTitle}
              onMinimize={() => setTasksMin(true)}
            />
          )}
          <TourInvite />
          {languageInvite && <LanguageTrainerInvite />}
          <EvaluationInvite />
        </div>

        {previewInvalid && (
          <div
            className="rounded-xl p-4 mb-8 text-sm"
            style={{ backgroundColor: "var(--error-bg)", color: "var(--error)" }}
          >
            {t("enrollInvalidCode")}
          </div>
        )}

        {joinedClosed && (
          <div
            className="rounded-xl p-4 mb-8 text-sm"
            style={{ backgroundColor: "var(--surface-dim)", color: "var(--foreground-soft)" }}
          >
            {t("closedJoinedNotice")}
          </div>
        )}

        <WorkspaceList canCreate={canCreate} />
      </div>
    </div>
  );
}
