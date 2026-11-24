import React, { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Files, PencilSimple, Sparkle, Trash, type Icon } from "@phosphor-icons/react";
import Spinner from "@/components/ui/Spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { InlineRename } from "@/components/ui/InlineRename";
import { STUDIO_ITEM_MAX } from "../../_constants";
import { SubviewHeader, type BreadcrumbItem } from "../layout/SubviewHeader";
import { GenerateModal } from "./GenerateModal";

export interface StudioSavedItem {
  id: number;
  title: string;
  created_at: string | null;
  user_instruction?: string;
}

// The list of saved results with the create button, shared by mindmap and data table.
export function StudioSavedList({
  toolKey, modalId, icon: ToolIcon, labels,
  items, loading, sourceCount, breadcrumbs,
  onBack, onGenerate, onOpen, onDelete, onRename,
}: {
  toolKey: string;
  modalId: string;
  icon: Icon;
  labels: { title: string; emptyHint: string; countOne: string; countMany: string };
  items: StudioSavedItem[];
  loading: boolean;
  sourceCount: number;
  breadcrumbs?: BreadcrumbItem[];
  onBack: () => void;
  onGenerate: (instruction: string) => void;
  onOpen: (id: number) => void;
  onDelete: (id: number) => void;
  onRename?: (id: number, title: string) => Promise<void>;
}) {
  const t = useTranslations("workspace.detail.studio");
  const locale = useLocale();
  // The create dialog with the instruction field, opened by the Create button.
  const [dialogOpen, setDialogOpen] = useState(false);
  // Which card is currently being renamed, only one, nobody needs more at once.
  const [umbenennt, setUmbenennt] = useState<number | null>(null);
  const noSources = sourceCount === 0;
  const atLimit = items.length >= STUDIO_ITEM_MAX;

  const createButton = (
    <span title={atLimit ? t("generate.limitReached") : undefined}>
      <button type="button" onClick={() => setDialogOpen(true)}
        disabled={noSources || loading || atLimit}
        className="btn-outline-accent inline-flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg text-sm font-semibold transition-all disabled:opacity-40">
        <Sparkle size={12} weight="bold" /> {t("generate.create")}
      </button>
    </span>
  );

  return (
    <>
      <SubviewHeader title={labels.title} toolKey={toolKey} onBack={onBack} breadcrumbs={breadcrumbs} />
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
        <div className="rounded-xl px-3 py-2 text-sm font-medium flex items-center gap-2"
          style={{
            color: noSources ? "var(--error-strong)" : "var(--kb)",
          }}>
          <Files size={13} weight="bold" />
          {noSources
            ? t("sources.none")
            : sourceCount === 1
              ? t("sources.one")
              : t("sources.few", { n: sourceCount })}
        </div>

        {dialogOpen && (
          <GenerateModal id={modalId} toolName={labels.title}
            onClose={() => setDialogOpen(false)}
            onCreate={(text) => { setDialogOpen(false); onGenerate(text); }} />
        )}
        {items.length === 0 && !loading ? (
          <EmptyState
            className="pt-[15%]"
            size="lg"
            icon={<ToolIcon size={48} weight="bold" />}
            text={labels.emptyHint}
            action={createButton}
          />
        ) : (
          <>
            <div className="flex justify-center">
              {createButton}
            </div>
            <div className="flex items-center justify-between px-1">
              <span className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>{items.length} {items.length === 1 ? labels.countOne : labels.countMany}</span>
            </div>
            <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
              {loading && (
                <div className="bg-background rounded-xl p-3.5 flex flex-col gap-2 relative overflow-hidden opacity-70"
                  style={{ boxShadow: "0 2px 10px rgba(0,40,60,0.05), 0 0 0 1px rgba(0,40,60,0.03)", minHeight: 90 }}>
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <Spinner size="sm" />
                    <span className="text-sm font-semibold leading-snug flex-1 line-clamp-2" style={{ color: "var(--foreground)" }}>{t("generate.generating")}</span>
                  </div>
                </div>
              )}
              {items.map((item) => (
                <div key={item.id}
                  onClick={() => onOpen(item.id)}
                  className="bg-background rounded-xl p-3.5 flex flex-col gap-2 relative overflow-hidden group cursor-pointer hover:outline-2 hover:outline-[var(--kb)] -outline-offset-2 transition"
                  style={{ boxShadow: "0 2px 10px rgba(0,40,60,0.05), 0 0 0 1px rgba(0,40,60,0.03)", minHeight: 90 }}>
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <ToolIcon size={16} weight="bold" style={{ color: "var(--kb)", flexShrink: 0 }} />
                    {umbenennt === item.id && onRename ? (
                      <InlineRename
                        value={item.title}
                        errorText={t("common.renameFailed")}
                        onSave={(next) => onRename(item.id, next)}
                        onCancel={() => setUmbenennt(null)}
                      />
                    ) : (
                      <span className="text-sm font-semibold leading-snug flex-1 line-clamp-3 askf-tooltip" style={{ color: "var(--foreground)" }}
                        onDoubleClick={(e) => { if (onRename) { e.stopPropagation(); setUmbenennt(item.id); } }}
                        data-tip={item.title}>
                        {item.title}
                      </span>
                    )}
                  </div>
                  {item.user_instruction && (
                    <span className="text-xs text-muted line-clamp-1" title={item.user_instruction}>
                      {t("generate.instructionShown", { text: item.user_instruction })}
                    </span>
                  )}
                  <div className="flex items-center justify-between mt-auto pt-1">
                    <span className="text-xs font-medium" >
                      {item.created_at ? new Date(item.created_at).toLocaleDateString(locale === "en" ? "en-US" : "de-DE", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Berlin" }) : ""}
                    </span>
                    <div className="flex items-center gap-1.5">
                      {onRename && (
                        <button type="button" onClick={(e) => { e.stopPropagation(); setUmbenennt(item.id); }}
                          className="w-6 h-6 rounded-full flex items-center justify-center btn-icon"
                          style={{ backgroundColor: "var(--surface-dim)" }}
                          title={t("common.rename")}
                          aria-label={t("common.rename")}>
                          <PencilSimple size={12} />
                        </button>
                      )}
                      <button type="button" onClick={(e) => { e.stopPropagation(); onDelete(item.id); }}
                        className="w-6 h-6 rounded-full flex items-center justify-center btn-icon"
                        style={{ backgroundColor: "var(--surface-dim)" }}>
                        <Trash size={12} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </>
  );
}
