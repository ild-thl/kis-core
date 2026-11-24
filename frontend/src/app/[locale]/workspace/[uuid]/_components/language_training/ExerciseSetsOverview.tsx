import { ArrowClockwise, Cards, DownloadSimple, Files, PencilSimple, Sparkle, Trash } from "@phosphor-icons/react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import Spinner from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { InlineRename } from "@/components/ui/InlineRename";
import type { ExerciseSet } from "../../_types";
import { STUDIO_ITEM_MAX } from "../../_constants";
import { SubviewHeader, type BreadcrumbItem, type ToolCategory } from "../layout/SubviewHeader";
import { setProgressPct } from "./_progress";
import { InstructionNote } from "../studio/InstructionField";
import { setDisplayTitle } from "./_setTitle";

export function ExerciseSetsOverview({
  title, toolKey, sets, onBack, onSelect, onCreate, onDelete, onRename, onRetry, onDownload, sourceCount, breadcrumbs, category,
}: {
  title: string; toolKey?: string; sets: ExerciseSet[];
  onBack: () => void; onSelect: (s: ExerciseSet) => void;
  onCreate: () => void; onDelete: (id: number) => void;
  onRename?: (id: number, title: string) => Promise<void>;
  onRetry?: (id: number) => void;
  onDownload?: (s: ExerciseSet) => void;
  sourceCount: number;
  breadcrumbs?: BreadcrumbItem[];
  category?: ToolCategory;
}) {
  const t = useTranslations("workspace.detail.languageTraining");
  const locale = useLocale();
  const dateLocale = locale === "en" ? "en-US" : "de-DE";
  // Which card is currently being renamed, only one, nobody needs more at once.
  const [umbenennt, setUmbenennt] = useState<number | null>(null);

  const noSources = sourceCount === 0;
  const atLimit = sets.length >= STUDIO_ITEM_MAX;
  const isGenerating = sets.some((s) => s.status === "generating");
  const generatingLabel = t("common.generating");
  const createButton = (
    <span title={atLimit ? t("exerciseSets.limitReached") : undefined}>
      <button type="button" onClick={onCreate}
        disabled={noSources || atLimit || isGenerating}
        className="btn-outline-accent inline-flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg text-sm font-semibold transition-all disabled:opacity-40">
        <Sparkle size={12} weight="bold" /> {isGenerating ? generatingLabel : t("exerciseSets.createButton")}
      </button>
    </span>
  );
  return (
    <div className="flex flex-col h-full">
      <SubviewHeader title={title} toolKey={toolKey} onBack={onBack} breadcrumbs={breadcrumbs} category={category} />
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
        <div className="rounded-xl px-3 py-2 text-xs font-medium flex items-center gap-2"
          style={{
            color: noSources ? "var(--error-strong)" : "var(--kb)",
          }}>
          <Files size={13} weight="bold" />
          <span>
            {noSources
              ? t("sourceStatus.none")
              : sourceCount === 1
                ? t("sourceStatus.one")
                : t("sourceStatus.few", { count: sourceCount })}
          </span>
        </div>

        {sets.length === 0 ? (
          <EmptyState
            className="pt-[15%]"
            size="lg"
            icon={<Cards size={48} weight="bold" />}
            text={t("exerciseSets.emptyText")}
            action={createButton}
          />
        ) : (
          <>
            <div className="flex justify-center">
              {createButton}
            </div>
            <div className="flex items-center justify-between px-1">
              <span className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>{t("exerciseSets.exercisesCount", { count: sets.length })}</span>
              <span className="text-xs" >{t("exerciseSets.cardsCount", { count: sets.reduce((s, e) => s + e.card_count, 0) })}</span>
            </div>
            <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
              {sets.map((s) => {
                const generating = s.status === "generating";
                const failed = s.status === "failed";
                // The tool names the set while it generates, the mode would call Karteikarten "Lernkarten".
                const toolLabel = (() => {
                  switch (s.tool) {
                    case "karteikarten": return t("tools.karteikarten");
                    case "flashcards": return t("tools.flashcards");
                    case "grammatik": return t("tools.grammar");
                    case "quiz": return t("tools.quiz");
                    case "wortschatz": return t("tools.vocabulary");
                    default: return t("tools.exerciseFallback");
                  }
                })();
                // Exactly the name shown on the card is renamed.
                const anzeigeTitel = setDisplayTitle(s.title);
                const createdDate = new Date(s.created_at).toLocaleDateString(dateLocale, { day: "numeric", month: "short", timeZone: "Europe/Berlin" });
                const umbenennbar = !generating && !failed && !!onRename;
                return (
                  <div key={s.id} onClick={() => !generating && !failed && onSelect(s)}
                    className={`bg-background rounded-xl p-3.5 flex flex-col gap-2 relative overflow-hidden group border-2 border-transparent transition-colors ${generating ? "opacity-70" : "cursor-pointer hover:border-[var(--kb)]"}`}
                    style={{ boxShadow: "0 2px 10px rgba(0,40,60,0.05), 0 0 0 1px rgba(0,40,60,0.03)", minHeight: 90 }}>
                    {/* Which exercise type this is. Two grammar sets from one document
                        look identical otherwise, and the type is what the learner picked. */}
                    {!generating && s.grammar_topic_name && (
                      <span className="self-start text-3xs font-semibold px-1.5 py-0.5 rounded"
                        style={{ backgroundColor: "rgba(var(--kb-rgb),0.10)", color: "var(--kb)" }}>
                        {s.grammar_topic_name}
                      </span>
                    )}
                    {/* Title + Score */}
                    <div className="flex items-start gap-2.5 flex-1 min-w-0">
                      {/* A failed set never got a real title, so it still carries the
                          "generating" placeholder. Saying so in the title is the only
                          place the learner reliably reads. */}
                      {umbenennt === s.id && onRename ? (
                        <InlineRename
                          value={anzeigeTitel}
                          errorText={t("common.renameFailed")}
                          onSave={(next) => onRename(s.id, next)}
                          onCancel={() => setUmbenennt(null)}
                        />
                      ) : (
                        <span className="text-sm font-semibold leading-snug flex-1 line-clamp-3 mt-0.5 askf-tooltip"
                          style={{ color: failed ? "var(--error-strong)" : "var(--foreground)" }}
                          onDoubleClick={(e) => { if (umbenennbar) { e.stopPropagation(); setUmbenennt(s.id); } }}
                          data-tip={generating || failed ? undefined : anzeigeTitel}>
                          {generating ? generatingLabel : failed ? t("exerciseSets.failed") : anzeigeTitel}
                        </span>
                      )}
                      {generating ? (
                        <Spinner size="sm" />
                      ) : failed ? null : (() => {
                        // The value comes ready from the backend so ring and statistics count alike.
                        const pct = setProgressPct(s);
                        const r = 16; const c = 2 * Math.PI * r; const offset = c - (pct / 100) * c;
                        return (
                          <svg width="42" height="42" viewBox="0 0 42 42" className="shrink-0">
                            <circle cx="21" cy="21" r={r} fill="none" stroke="var(--border)" strokeWidth="3" />
                            <circle cx="21" cy="21" r={r} fill="none" stroke="var(--kb)" strokeWidth="3"
                              strokeDasharray={c} strokeDashoffset={offset} strokeLinecap="round"
                              transform="rotate(-90 21 21)" />
                            <text x="21" y="21" textAnchor="middle" dominantBaseline="central"
                              fontSize="10" fontWeight="700" fill="var(--kb)">{pct}%</text>
                          </svg>
                        );
                      })()}
                    </div>
                    {!generating && (s.user_instruction || s.instruction_unmatched) && (
                      <InstructionNote instruction={s.user_instruction} unmatched={s.instruction_unmatched}
                        shownText={t("exerciseSets.instructionShown", { text: s.user_instruction || "" })}
                        unmatchedText={t("exerciseSets.instructionUnmatched")} />
                    )}
                    {/* Bottom row: meta left, delete right */}
                    <div className="flex items-center justify-between mt-auto pt-1">
                      <span className="text-xs font-medium" >
                        {/* Nothing but the date on a failed set, it has no cards to count. */}
                        {generating ? toolLabel : failed ? null : t("exerciseSets.cardsCount", { count: s.card_count })}
                        {!generating && !failed && s.mode === "glossary" && t("exerciseSets.fromGlossarySuffix")}
                        {/* Only in source mode: a glossary set has no sources to count. */}
                        {!generating && !failed && s.mode !== "glossary" && (s.sources?.length ?? 0) > 0
                          && ` · ${t("exerciseSets.sourcesCount", { count: s.sources!.length })}`}
                        {!generating && (failed ? createdDate : ` · ${createdDate}`)}
                      </span>
                      <div className="flex items-center gap-1.5">
                        {failed && onRetry && (
                          <button type="button" onClick={(e) => { e.stopPropagation(); onRetry(s.id); }}
                            className="w-6 h-6 rounded-full flex items-center justify-center btn-icon"
                            style={{ backgroundColor: "var(--surface-dim)" }}
                            title={t("exerciseSets.retry")}
                            aria-label={t("exerciseSets.retry")}>
                            <ArrowClockwise size={12} />
                          </button>
                        )}
                        {!generating && !failed && onDownload && (
                          <button type="button" onClick={(e) => { e.stopPropagation(); onDownload(s); }}
                            className="w-6 h-6 rounded-full flex items-center justify-center btn-icon"
                            style={{ backgroundColor: "var(--surface-dim)" }}
                            title={t("common.downloadAsText")}>
                            <DownloadSimple size={12} />
                          </button>
                        )}
                        {umbenennbar && (
                          <button type="button" onClick={(e) => { e.stopPropagation(); setUmbenennt(s.id); }}
                            className="w-6 h-6 rounded-full flex items-center justify-center btn-icon"
                            style={{ backgroundColor: "var(--surface-dim)" }}
                            title={t("common.rename")}
                            aria-label={t("common.rename")}>
                            <PencilSimple size={12} />
                          </button>
                        )}
                        {!generating && <button type="button" onClick={(e) => { e.stopPropagation(); onDelete(s.id); }}
                          className="w-6 h-6 rounded-full flex items-center justify-center btn-icon"
                          style={{ backgroundColor: "var(--surface-dim)" }}
                          title={t("common.delete")}>
                          <Trash size={12} />
                        </button>}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
