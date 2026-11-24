"use client";

import { useState } from "react";
import Image from "next/image";
import { useTranslations } from "next-intl";
import { NotePencil, PencilSimple, SidebarSimple, Trash } from "@phosphor-icons/react";
import { Link } from "@/i18n/navigation";
import Wordmark from "@/components/layout/Wordmark";
import Modal from "@/components/ui/Modal";
import { InlineRename } from "@/components/ui/InlineRename";
import { gruppiere, type GruppenKey } from "../_gruppen";
import type { CampusChatEintrag } from "../_types";

const GRUPPEN: GruppenKey[] = ["heute", "woche", "aelter"];

export default function ChatVerlauf({
  chats,
  activeId,
  retentionDays,
  onSelect,
  onNew,
  onRename,
  onDelete,
  collapsed = false,
  onToggle,
}: {
  chats: CampusChatEintrag[];
  activeId: number | null;
  retentionDays: number;
  onSelect: (id: number) => void;
  onNew: () => void;
  onRename: (id: number, title: string) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  /** Only the narrow strip with Francis, toggle and new chat. */
  collapsed?: boolean;
  /** Folds the bar on the desktop, closes the drawer on the phone. */
  onToggle: () => void;
}) {
  const t = useTranslations("tools.campus");
  const tHeader = useTranslations("header");
  const [renaming, setRenaming] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<CampusChatEintrag | null>(null);
  const [busy, setBusy] = useState(false);
  const gruppen = gruppiere(chats);

  const loeschen = async () => {
    if (!confirm) return;
    setBusy(true);
    try {
      await onDelete(confirm.id);
      setConfirm(null);
    } finally {
      setBusy(false);
    }
  };

  const toggleLabel = collapsed ? t("openMenu") : t("closeMenu");
  const toggle = (
    <button
      type="button"
      onClick={onToggle}
      aria-label={toggleLabel}
      title={toggleLabel}
      aria-expanded={!collapsed}
      className="w-9 h-9 flex items-center justify-center rounded-full btn-icon flex-shrink-0"
      data-testid="campus-sidebar-toggle"
    >
      <SidebarSimple size={20} />
    </button>
  );

  if (collapsed) {
    return (
      <div className="flex flex-col items-center h-full min-h-0 gap-2 py-2" data-testid="campus-history-collapsed">
        {/* The strip shows only Francis, it opens the bar again. */}
        <button
          type="button"
          onClick={onToggle}
          aria-label={toggleLabel}
          title={toggleLabel}
          aria-expanded={false}
          className="w-11 h-9 flex items-center justify-center logo-link"
          data-testid="campus-sidebar-toggle"
        >
          <Image src="/logos/askfrancis-icon.svg" alt="" width={27} height={27} className="h-7 w-auto" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="campus-history">
      <div className="flex items-center justify-between pl-4 pr-2 flex-shrink-0" style={{ height: 48 }}>
        {/* The wordmark leads to the workspaces, like the one in the header of the other pages. */}
        <Link href="/workspace" aria-label={tHeader("homeAria")} title={tHeader("homeAria")} className="flex items-center logo-link" data-testid="campus-home">
          <Wordmark size="sm" themed />
        </Link>
        {toggle}
      </div>
      <div className="px-2 pt-1 pb-3 flex-shrink-0">
        <button
          type="button"
          onClick={onNew}
          className="btn-ghost bg-surface-dim w-full flex items-center gap-2.5 px-3 py-2 text-sm font-medium rounded-xl text-foreground"
          data-testid="campus-new-chat"
        >
          <NotePencil size={20} />
          {t("newChat")}
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto px-2 pb-2">
        {chats.length === 0 && (
          <p className="text-xs px-2 pt-2" style={{ color: "var(--muted)" }}>{t("noChats")}</p>
        )}
        {GRUPPEN.map((key) =>
          gruppen[key].length === 0 ? null : (
            <div key={key} className="mb-3">
              <p className="text-2xs font-semibold uppercase tracking-wide px-2 py-1" style={{ color: "var(--muted)" }}>{t(`group.${key}`)}</p>
              <ul className="flex flex-col gap-0.5">
                {gruppen[key].map((chat) => {
                  const active = chat.id === activeId;
                  return (
                    <li key={chat.id} className="group relative">
                      {renaming === chat.id ? (
                        <div className="px-1 py-0.5">
                          <InlineRename
                            value={chat.title}
                            onSave={(next) => onRename(chat.id, next)}
                            onCancel={() => setRenaming(null)}
                            errorText={t("renameFailed")}
                          />
                        </div>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => onSelect(chat.id)}
                            className="w-full text-left text-sm px-2 py-1.5 pr-14 rounded-lg truncate border-2 transition-colors"
                            style={{
                              borderColor: active ? "var(--kb)" : "transparent",
                              backgroundColor: active ? "rgba(var(--kb-rgb),0.07)" : "transparent",
                              color: "var(--foreground)",
                            }}
                            aria-current={active ? "true" : undefined}
                            title={chat.title}
                          >
                            {chat.title}
                          </button>
                          <span className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
                            <button type="button" onClick={() => setRenaming(chat.id)} title={t("rename")} className="w-6 h-6 flex items-center justify-center rounded-full btn-icon" style={{ backgroundColor: "var(--surface-dim)" }}>
                              <PencilSimple size={12} weight="bold" />
                            </button>
                            <button type="button" onClick={() => setConfirm(chat)} title={t("delete")} className="w-6 h-6 flex items-center justify-center rounded-full btn-icon" style={{ backgroundColor: "var(--surface-dim)" }}>
                              <Trash size={12} weight="bold" />
                            </button>
                          </span>
                        </>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          ),
        )}
      </div>
      {retentionDays > 0 && (
        <div className="flex-shrink-0 px-2 pt-2 pb-3" style={{ borderTop: "1px solid var(--border-soft)" }}>
          <p className="text-2xs px-2" style={{ color: "var(--muted)" }}>
            {t("retentionHint", { days: retentionDays })}
          </p>
        </div>
      )}
      <Modal
        open={confirm !== null}
        onClose={() => (busy ? undefined : setConfirm(null))}
        title={t("deleteTitle")}
        size="sm"
        footer={
          <>
            <button type="button" onClick={() => setConfirm(null)} disabled={busy} className="px-4 py-2 text-sm rounded-md border-2 border-border text-foreground-soft hover:border-kb transition-colors disabled:opacity-60">
              {t("cancel")}
            </button>
            <button type="button" onClick={loeschen} disabled={busy} className="px-4 py-2 text-sm btn-danger rounded-md transition-colors disabled:opacity-60">
              {t("delete")}
            </button>
          </>
        }
      >
        <p className="text-sm">{t("deleteConfirm", { title: confirm?.title ?? "" })}</p>
      </Modal>
    </div>
  );
}
