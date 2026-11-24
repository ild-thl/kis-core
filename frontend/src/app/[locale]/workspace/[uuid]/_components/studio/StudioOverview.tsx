"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import dynamic from "next/dynamic";
import {
  SidebarSimple,
  Cards,
  Question,
  Table,
  TreeStructure,
  BookOpenText,
  PencilLine,
  TextAlignLeft,
} from "@phosphor-icons/react";
import Spinner from "@/components/ui/Spinner";
import HelpTooltip from "@/components/ui/HelpTooltip";
import type { Source, StudioView, LanguageTrainingView, StudentStats } from "../../_types";
import { LerntoolsGrid } from "../language_training/LerntoolsGrid";
import { RecentActivities } from "./RecentActivities";
import { StudioTabs } from "./StudioTabs";

const dynamicLoader = () => (
  <div className="flex-1 flex items-center justify-center p-6">
    <Spinner size="md" />
  </div>
);

const StudentStatsView = dynamic(
  () => import("../language_training/StudentStatsView").then((m) => ({ default: m.StudentStatsView })),
  { loading: dynamicLoader, ssr: false },
);

const ScheduleView = dynamic(
  () => import("./ScheduleView").then((m) => ({ default: m.ScheduleView })),
  { loading: dynamicLoader, ssr: false },
);

interface StudioOverviewProps {
  onSelect: (v: StudioView) => void;
  onMinimize: () => void;
  language_trainingActive: boolean;
  language_trainingContent?: React.ReactNode;
  glossaryContent?: React.ReactNode;
  notesContent?: React.ReactNode;
  workspaceUuid: string;
  statsVersion: number;
  onNavigateToSet?: (setId: number, tool: string, mode: string) => void;
  onSprachNavigate?: (view: LanguageTrainingView) => void;
  langTrainingView?: string;
  requestedTab?: { tab: "tools" | "glossary" | "notes" | "statistik" | "schedule"; nonce: number } | null;
  onRequestedTabHandled?: () => void;
  sources: Source[];
  selectedSourceIds: string[];
  onPillClick?: (sourceUuid: string, page: number, filename: string, sourceText?: string, startTime?: number) => void;
  hideHeader?: boolean;
}

type StudioTab = "tools" | "language_training" | "glossary" | "notes" | "statistik" | "schedule";

export function StudioOverview({
  onSelect,
  onMinimize,
  language_trainingActive,
  language_trainingContent,
  glossaryContent,
  notesContent,
  workspaceUuid,
  statsVersion,
  onNavigateToSet,
  onSprachNavigate,
  langTrainingView,
  requestedTab,
  onRequestedTabHandled,
  sources,
  selectedSourceIds,
  onPillClick,
  hideHeader,
}: StudioOverviewProps) {
  const t = useTranslations("workspace.detail.studio");
  const [studioTab, _setStudioTab] = useState<StudioTab>(() => {
    if (typeof window !== "undefined") {
      const saved = sessionStorage.getItem("askf-studio-tab");
      if (saved && ["tools", "glossary", "notes", "statistik", "schedule"].includes(saved))
        return saved as StudioTab;
    }
    return "tools";
  });
  const setStudioTab = (tab: StudioTab) => {
    _setStudioTab(tab);
    sessionStorage.setItem("askf-studio-tab", tab);
  };

  const [studentStats, setStudentStats] = useState<StudentStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);

  const refreshStats = useCallback(() => {
    setStatsLoading(true);
    fetch(`/api/ai-assistant/workspaces/${workspaceUuid}/stats`, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) setStudentStats(data);
      })
      .catch(() => {})
      .finally(() => setStatsLoading(false));
  }, [workspaceUuid]);

  useEffect(() => {
    if (studioTab === "statistik") refreshStats();
  }, [studioTab, workspaceUuid, refreshStats, statsVersion]);

  const lerntoolsTiles = [
    { key: "karteikarten" as const, Icon: Cards, label: t("tiles.karteikarten"), description: t("tileDescriptions.karteikarten"), iconBg: "var(--badge-emerald-bg)", iconColor: "var(--badge-emerald-fg)" },
    { key: "quiz" as const, Icon: Question, label: t("tiles.quiz"), description: t("tileDescriptions.quiz"), iconBg: "var(--badge-yellow-bg)", iconColor: "var(--badge-yellow-fg)" },
    { key: "data_table" as const, Icon: Table, label: t("tiles.dataTable"), description: t("tileDescriptions.dataTable"), iconBg: "var(--badge-orange-bg)", iconColor: "var(--badge-orange-fg)" },
    { key: "mindmap" as const, Icon: TreeStructure, label: t("tiles.mindmap"), description: t("tileDescriptions.mindmap"), iconBg: "var(--badge-teal-bg)", iconColor: "var(--badge-teal-fg)" },
  ];

  const langTrainingTiles = [
    { key: "lk-sets" as const, Icon: BookOpenText, label: t("tiles.lernkarten"), description: t("tileDescriptions.lernkarten"), iconBg: "var(--badge-amber-bg)", iconColor: "var(--badge-amber-fg)" },
    { key: "wo-sets" as const, Icon: TextAlignLeft, label: t("tiles.vocabulary"), description: t("tileDescriptions.vocabulary"), iconBg: "var(--badge-rose-bg)", iconColor: "var(--badge-rose-fg)" },
    { key: "gr-sets" as const, Icon: PencilLine, label: t("tiles.grammar"), description: t("tileDescriptions.grammar"), iconBg: "var(--badge-violet-bg)", iconColor: "var(--badge-violet-fg)" },
  ];

  useEffect(() => {
    if (studioTab === "language_training" && (!langTrainingView || langTrainingView === "overview")) {
      setStudioTab("tools");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [langTrainingView, studioTab]);

  // A tab wish applies once, the id prevents a replay.
  const servedTabNonce = useRef<number | null>(null);
  useEffect(() => {
    if (!requestedTab) return;
    if (servedTabNonce.current === requestedTab.nonce) return;
    servedTabNonce.current = requestedTab.nonce;
    setStudioTab(requestedTab.tab);
    onRequestedTabHandled?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedTab?.nonce]);

  return (
    <div className="flex flex-col h-full">
      {!hideHeader && (
        <div
          data-panel-header=""
          className="flex items-center justify-between px-4 py-3 flex-shrink-0"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <span className="text-base font-semibold" style={{ color: "var(--foreground)" }}>
            {t("panelTitle")}
          </span>
          <button
            type="button"
            onClick={onMinimize}
            className="w-7 h-7 flex items-center justify-center rounded-full btn-icon"
            style={{ backgroundColor: "var(--surface-dim)" }}
            title={t("minimizePanel")}
          >
            <SidebarSimple size={13} style={{ transform: "scaleX(-1)" }} />
          </button>
        </div>
      )}

      <StudioTabs
        tabs={[
          { key: "tools" as const, label: t("tabs.tools") },
          { key: "glossary" as const, label: t("tabs.glossary") },
          { key: "notes" as const, label: t("tabs.notes") },
          { key: "statistik" as const, label: t("tabs.statistik") },
          { key: "schedule" as const, label: t("tabs.schedule") },
        ]}
        active={studioTab === "language_training" ? "tools" : studioTab}
        onSelect={(k) => setStudioTab(k as StudioTab)}
      />

      {studioTab === "tools" && (
        <div className="flex-1 overflow-y-auto flex flex-col">
          <div className="px-3 pt-3 pb-1">
            <span className="text-xs font-semibold uppercase tracking-wider" >
              {t("headings.learningTools")}
            </span>
          </div>
          <div data-tour="tools-grid">
            <LerntoolsGrid tiles={lerntoolsTiles} onSelect={(key) => onSelect(key as StudioView)} />
          </div>

          {language_trainingActive && (
            <>
              <div className="px-3 pb-1 flex items-center gap-1.5">
                <span className="text-xs font-semibold uppercase tracking-wider" >
                  {t("headings.languageTraining")}
                </span>
                {/* Says where the exercises come from: material for the terms, AI for the wording. */}
                <HelpTooltip text={t("headings.languageTrainingHint")} />
              </div>
              <LerntoolsGrid
                tiles={langTrainingTiles}
                onSelect={(key) => {
                  if (onSprachNavigate) {
                    onSprachNavigate(key as LanguageTrainingView);
                    setStudioTab("language_training");
                  }
                }}
              />
            </>
          )}

          <RecentActivities workspaceUuid={workspaceUuid} onNavigateToSet={onNavigateToSet} refreshKey={statsVersion} />
        </div>
      )}

      {studioTab === "language_training" && (
        <div className="flex-1 overflow-hidden flex flex-col">{language_trainingContent}</div>
      )}

      {studioTab === "glossary" && (
        <div className="flex-1 overflow-hidden flex flex-col">{glossaryContent}</div>
      )}

      {studioTab === "notes" && (
        <div className="flex-1 overflow-hidden flex flex-col">{notesContent}</div>
      )}

      {studioTab === "statistik" && (
        <StudentStatsView
          stats={studentStats}
          loading={statsLoading}
          workspaceUuid={workspaceUuid}
          onNavigateToSet={onNavigateToSet}
          language_trainingActive={language_trainingActive}
        />
      )}

      {studioTab === "schedule" && (
        <div className="flex-1 overflow-hidden flex flex-col">
          <ScheduleView
            workspaceUuid={workspaceUuid}
            sources={sources}
            selectedSourceIds={selectedSourceIds}
            onPillClick={onPillClick}
          />
        </div>
      )}
    </div>
  );
}
