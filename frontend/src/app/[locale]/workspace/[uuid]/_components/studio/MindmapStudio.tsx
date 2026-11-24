import "mind-elixir/style.css";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  ArrowsInLineVertical,
  ArrowsOutLineVertical,
  CaretLeft,
  CornersIn,
  CornersOut,
  MagnifyingGlassMinus,
  MagnifyingGlassPlus,
  SidebarSimple,
  TreeStructure,
} from "@phosphor-icons/react";
import Spinner from "@/components/ui/Spinner";
import type { Source } from "../../_types";
import { _isMediaFile } from "../../_utils";
import { MinimizeContext } from "../../_context";
import type { BreadcrumbItem } from "../layout/SubviewHeader";
import { getActiveChipTarget, setActiveChipTarget, subscribeActiveChip } from "../chat/_citations";
import { StudioSourceLegend } from "./StudioSourceLegend";
import { InstructionNote } from "./InstructionField";
import { StudioSavedList } from "./StudioSavedList";
import { StudioViewerCrumbs } from "./StudioViewerCrumbs";
import { chipKey, findSource, numberMindmapSources, pageNumberOf, timeLabelSeconds, type MindmapNodeData } from "./_sourceRefs";

export type { MindmapNodeData };

// Leaves the browser full screen and releases the orientation lock.
async function exitBrowserFullscreen() {
  if (document.fullscreenElement) {
    try { await document.exitFullscreen(); } catch { /* ignore */ }
  }
  unlockOrientation();
}

function unlockOrientation() {
  const orientation = screen.orientation as ScreenOrientation & { unlock?: () => void };
  orientation?.unlock?.();
}

export function MindmapStudio({
  mindmap, loading, onGenerate, onBack,
  savedList, onSelect, onDelete, onRename, sourceCount,
  sources, pickedSources, onPillClick, breadcrumbs,
  openInViewer, onViewerOpened, instruction, instructionUnmatched,
}: {
  mindmap: MindmapNodeData | null;
  loading: boolean;
  onGenerate: (instruction: string) => void;
  onBack: () => void;
  savedList: { id: number; created_at: string | null; topic: string; user_instruction?: string }[];
  onSelect: (id: number) => void;
  onDelete: (id: number) => void;
  onRename?: (id: number, title: string) => Promise<void>;
  sourceCount: number;
  sources?: Source[];
  /** What the user ticked when this map was made, used ones and unused ones. */
  pickedSources?: { number: number; filename: string }[];
  onPillClick?: (sourceUuid: string, page: number, filename: string, sourceText?: string, startTime?: number) => void;
  breadcrumbs?: BreadcrumbItem[];
  openInViewer?: boolean;
  onViewerOpened?: () => void;
  /** The instruction the shown map was made with, and whether the sources had nothing on it. */
  instruction?: string;
  instructionUnmatched?: boolean;
}) {
  const t = useTranslations("workspace.detail.studio");
  const tMm = useTranslations("workspace.detail.studio.mindmap");
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const meInstanceRef = useRef<any>(null);
  const [view, setView] = useState<"viewer" | "list">(openInViewer ? "viewer" : "list");
  const [allExpanded, setAllExpanded] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const minimize = useContext(MinimizeContext);

  useEffect(() => {
    if (openInViewer) {
      setView("viewer");
      onViewerOpened?.();
    }
  }, [openInViewer, onViewerOpened]);

  // Leaves the browser full screen too, not just the CSS overlay.
  async function leaveFullscreen() {
    await exitBrowserFullscreen();
    setFullscreen(false);
  }

  // Full screen with an orientation lock, otherwise plain CSS full screen.
  async function handleFullscreenToggle() {
    const el = viewerRef.current;
    if (!fullscreen) {
      if (el?.requestFullscreen) {
        try { await el.requestFullscreen(); } catch { /* user gesture or permission denied */ }
      }
      const orientation = screen.orientation as ScreenOrientation & { lock?: (o: string) => Promise<void> };
      if (orientation?.lock) {
        try { await orientation.lock("landscape"); } catch { /* desktop or unsupported */ }
      }
      setFullscreen(true);
    } else {
      await leaveFullscreen();
    }
  }

  // Release the lock, even when full screen is left another way.
  useEffect(() => {
    function onChange() {
      if (!document.fullscreenElement) {
        setFullscreen(false);
        unlockOrientation();
      }
    }
    document.addEventListener("fullscreenchange", onChange);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      unlockOrientation();
    };
  }, []);

  const sourcesRef = useRef(sources);
  sourcesRef.current = sources;
  const onPillClickRef = useRef(onPillClick);
  onPillClickRef.current = onPillClick;
  const nodeSourceMapRef = useRef(new Map<string, { source_label: string; page_number?: number | string; keyword?: string; topic: string }>());
  // Computed during render, so the legend below is right on the first paint.
  const { index: sourceIndexMap, used: usedNames } = useMemo(
    () => numberMindmapSources(mindmap, pickedSources),
    [mindmap, pickedSources],
  );

  // Frames the chip that was clicked last, the same mark the chat chips carry.
  function paintActiveChip() {
    const active = getActiveChipTarget();
    containerRef.current?.querySelectorAll<HTMLElement>(".mm-src-chip").forEach((chip) => {
      chip.classList.toggle("mm-src-chip--active", !!active && chip.dataset.chipTarget === active);
    });
  }

  useEffect(() => subscribeActiveChip(() => paintActiveChip()), []);

  function expandAll(node: any) {
    if (node.children && node.children.length > 0) {
      node.expanded = true;
      node.children.forEach(expandAll);
    }
  }
  function collapseAll(me: any) {
    const root = me.nodeData;
    function collapseDeep(node: any) {
      if (node.children && node.children.length > 0) {
        node.expanded = false;
        node.children.forEach(collapseDeep);
      }
    }
    if (root.children) {
      root.children.forEach(collapseDeep);
    }
  }

  function handleToggleExpand() {
    const me = meInstanceRef.current;
    if (!me) return;
    if (allExpanded) {
      collapseAll(me);
    } else {
      expandAll(me.nodeData);
    }
    me.refresh();
    me.toCenter();
    paintActiveChip();
    setAllExpanded(!allExpanded);
  }

  function handleZoomIn() {
    const me = meInstanceRef.current;
    if (!me) return;
    me.scale((me.scaleVal || 1) * 1.4);
  }

  function handleZoomOut() {
    const me = meInstanceRef.current;
    if (!me) return;
    me.scale((me.scaleVal || 1) * 0.6);
  }

  useEffect(() => {
    const el = containerRef.current;
    if (!mindmap || !el || view !== "viewer") return;

    let cancelled = false;
    let me: any = null;
    let removeListeners: (() => void) | null = null;

    (async () => {
      const MindElixir = (await import("mind-elixir")).default;
      if (cancelled) return;

      let nid = 0;
      nodeSourceMapRef.current = new Map();
      function convert(node: MindmapNodeData): any {
        const id = `node-${nid++}`;
        const result: any = { id, topic: node.topic };
        if (node.source_label) {
          nodeSourceMapRef.current.set(id, { source_label: node.source_label, page_number: node.page_number, keyword: node.keyword, topic: node.topic });
          const srcNum = sourceIndexMap.get(node.source_label);
          if (srcNum) {
            // Without a verified spot the chip names the file alone, it still opens it.
            const isMedia = _isMediaFile(node.source_label);
            const rawLabel = node.page_number == null
              ? ""
              : isMedia && typeof node.page_number === "string"
                ? node.page_number
                : tMm("pageLabel", { page: node.page_number });
            const esc = node.topic.replace(/&/g, "&amp;").replace(/</g, "&lt;");
            // The chip label is escaped too, it ends up in innerHTML.
            const label = String(rawLabel).replace(/&/g, "&amp;").replace(/</g, "&lt;");
            const chipSrc = sourcesRef.current ? findSource(sourcesRef.current, node.source_label) : undefined;
            const keyAttr = chipSrc ? ` data-chip-target="${chipKey(chipSrc, node.page_number)}"` : "";
            result.dangerouslySetInnerHTML =
              `${esc} <span class="mm-src-chip"${keyAttr}>[${srcNum}]${label ? ` ${label}` : ""}</span>`;
          }
        }
        if (node.children && node.children.length > 0) {
          result.children = node.children.map(convert);
        }
        return result;
      }

      el.innerHTML = "";

      const baseTheme = MindElixir.THEME;
      me = new MindElixir({
        el,
        direction: MindElixir.SIDE,
        editable: false,
        contextMenu: false,
        toolBar: false,
        keypress: false,
        allowUndo: false,
        scaleMin: 0.1,
        scaleMax: 5,
        theme: {
          ...baseTheme,
          name: "askf-mindmap",
          palette: ["var(--mm-c1)", "var(--mm-c2)", "var(--mm-c3)", "var(--mm-c4)", "var(--mm-c5)", "var(--mm-c6)"],
        },
      });

      me.init({ nodeData: convert(mindmap) });

      collapseAll(me);
      // A fresh map starts collapsed, the toggle has to say so too.
      setAllExpanded(false);
      me.refresh();
      me.toCenter();

      // Click via pointer events, because the map shifts on every movement.
      let downTpc: HTMLElement | null = null;
      let downX = 0;
      let downY = 0;
      const CLICK_THRESHOLD = 6;
      const onDown = (ev: PointerEvent) => {
        if (ev.button !== 0) return;
        const tpc = (ev.target as HTMLElement).closest("me-tpc") as any;
        if (!tpc) { downTpc = null; return; }
        downTpc = tpc;
        downX = ev.clientX;
        downY = ev.clientY;
      };
      const onUp = async (ev: PointerEvent) => {
        if (!downTpc || ev.button !== 0) return;
        const dx = ev.clientX - downX;
        const dy = ev.clientY - downY;
        if (dx * dx + dy * dy > CLICK_THRESHOLD * CLICK_THRESHOLD) { downTpc = null; return; }
        const tpc = downTpc as any;
        downTpc = null;
        const nId = tpc.nodeObj?.id;
        if (!nId) return;
        const srcInfo = nodeSourceMapRef.current.get(nId);
        if (!srcInfo) return;
        const srcs = sourcesRef.current;
        const cb = onPillClickRef.current;
        if (!srcs || !cb) return;
        const src = findSource(srcs, srcInfo.source_label);
        if (src) {
          setActiveChipTarget(chipKey(src, srcInfo.page_number));
          paintActiveChip();
          // Leave full screen, otherwise the sources panel stays invisible.
          await exitBrowserFullscreen();
          setFullscreen(false);
          const isMedia = _isMediaFile(src.filename);
          if (isMedia && typeof srcInfo.page_number === "string") {
            cb(src.uuid, 0, src.filename, undefined, timeLabelSeconds(srcInfo.page_number) ?? 0);
          } else {
            // Keyword and topic together name the passage to mark.
            cb(src.uuid, pageNumberOf(srcInfo.page_number), src.filename, [srcInfo.keyword, srcInfo.topic].filter(Boolean).join(" "));
          }
        }
      };
      el.addEventListener("pointerdown", onDown);
      el.addEventListener("pointerup", onUp);
      removeListeners = () => {
        el.removeEventListener("pointerdown", onDown);
        el.removeEventListener("pointerup", onUp);
      };

      meInstanceRef.current = me;
    })();

    // The element is captured, the ref is already empty when the viewer unmounts.
    return () => {
      cancelled = true;
      removeListeners?.();
      if (me) {
        try { me.destroy?.(); } catch { /* ignore */ }
      }
      if (meInstanceRef.current === me) meInstanceRef.current = null;
      el.innerHTML = "";
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mindmap, view, pickedSources]);

  const activeTopicName = mindmap?.topic ?? tMm("fallbackTopic");

  return (
    <div className="flex flex-col h-full">
      {/* ── List view ── */}
      <div style={{ display: view === "list" ? "flex" : "none" }} className="flex-col h-full">
        <StudioSavedList
          toolKey="Mindmap" modalId="mindmap-instruction" icon={TreeStructure}
          labels={{ title: tMm("title"), emptyHint: tMm("emptyHint"), countOne: tMm("countOne"), countMany: tMm("countMany") }}
          items={savedList.map((m) => ({ ...m, title: m.topic }))} loading={loading} sourceCount={sourceCount} breadcrumbs={breadcrumbs}
          onBack={onBack} onGenerate={onGenerate}
          onOpen={(id) => { onSelect(id); setView("viewer"); }}
          onDelete={onDelete} onRename={onRename}
        />
      </div>

      {/* ── Mindmap Viewer ── */}
      <div ref={viewerRef} style={{
        display: view === "viewer" ? "flex" : "none",
        ...(fullscreen ? { position: "fixed" as const, inset: 0, zIndex: 9999, backgroundColor: "var(--background)" } : {}),
      }} className="flex-col h-full">
        <div data-panel-header={fullscreen ? undefined : ""} className="flex items-center gap-2 px-4 py-3 flex-shrink-0" style={{ borderBottom: "1px solid var(--border)" }}>
          <button type="button" onClick={() => { if (fullscreen) void leaveFullscreen(); else setView("list"); }}
            className="w-7 h-7 flex items-center justify-center rounded-full btn-icon"
            style={{ backgroundColor: "var(--surface-dim)" }}>
            <CaretLeft size={13} />
          </button>
          <StudioViewerCrumbs toolKey="Mindmap" toolTitle={tMm("title")} activeTitle={activeTopicName} breadcrumbs={breadcrumbs}
            onToolClick={() => { if (fullscreen) void leaveFullscreen(); setView("list"); }} />
          <div className="flex items-center gap-1.5">
            <button type="button" onClick={handleZoomOut} title={tMm("zoomOut")}
              className="w-7 h-7 flex items-center justify-center rounded-full btn-icon"
              style={{ backgroundColor: "var(--surface-dim)" }}>
              <MagnifyingGlassMinus size={13} />
            </button>
            <button type="button" onClick={handleZoomIn} title={tMm("zoomIn")}
              className="w-7 h-7 flex items-center justify-center rounded-full btn-icon"
              style={{ backgroundColor: "var(--surface-dim)" }}>
              <MagnifyingGlassPlus size={13} />
            </button>
            <button type="button" onClick={handleToggleExpand} title={allExpanded ? tMm("collapseAll") : tMm("expandAll")}
              className="w-7 h-7 flex items-center justify-center rounded-full btn-icon"
              style={{ backgroundColor: "var(--surface-dim)" }}>
              {allExpanded ? <ArrowsInLineVertical size={13} /> : <ArrowsOutLineVertical size={13} />}
            </button>
            <button type="button" onClick={handleFullscreenToggle} title={fullscreen ? tMm("exitFullscreen") : tMm("fullscreen")}
              className="w-7 h-7 flex items-center justify-center rounded-full btn-icon"
              style={{ backgroundColor: "var(--surface-dim)" }}>
              {fullscreen ? <CornersIn size={13} /> : <CornersOut size={13} />}
            </button>
            {minimize && (
              <button type="button" onClick={minimize} title={t("minimizePanel")}
                className="w-7 h-7 flex items-center justify-center rounded-full btn-icon"
                style={{ backgroundColor: "var(--surface-dim)" }}>
                <SidebarSimple size={13} style={{ transform: "scaleX(-1)" }} />
              </button>
            )}
          </div>
        </div>
        <div className="flex-1 overflow-hidden flex flex-col">
          {mindmap && (instruction || instructionUnmatched) && (
            <div className="px-4 pt-3">
              <InstructionNote instruction={instruction} unmatched={instructionUnmatched}
                shownText={t("generate.instructionShown", { text: instruction || "" })}
                unmatchedText={t("generate.instructionUnmatched")} />
            </div>
          )}
          {!mindmap && loading && (
            <div className="flex-1 flex items-center justify-center">
              <div className="flex flex-col items-center gap-3">
                <Spinner size="lg" />
                <p className="text-sm" >{tMm("loadingViewer")}</p>
              </div>
            </div>
          )}
          {mindmap && (
            <>
              <div
                ref={containerRef}
                className="flex-1"
                style={{ minHeight: 300 }}
              />
              {(() => {
                const eintraege = (pickedSources && pickedSources.length > 0)
                  ? pickedSources
                  : Array.from(sourceIndexMap.entries())
                      .map(([filename, number]) => ({ number, filename }));
                if (eintraege.length === 0) return null;
                return (
                <StudioSourceLegend
                  count={eintraege.length}
                  className="px-4 py-2 flex-shrink-0"
                  listClassName="flex flex-wrap gap-x-4 gap-y-1 pl-4"
                  style={{ borderTop: "1px solid var(--border)" }}
                >
                  {eintraege.map((s) => (
                    <span key={s.number}
                          className={`text-xs leading-snug text-[var(--muted)]${usedNames.has(s.filename) ? "" : " opacity-60"}`}>
                      [{s.number}] {s.filename}
                    </span>
                  ))}
                </StudioSourceLegend>
                );
              })()}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
