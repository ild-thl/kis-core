"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocale, useTranslations } from "next-intl";
import { Eye, PencilSimple, Trash } from "@phosphor-icons/react";
import Tabs from "@/components/ui/Tabs";
import ToolBackLink from "@/components/ui/ToolBackLink";
import ScrollTopButton from "@/app/[locale]/_components/landing/ScrollTopButton";
import * as api from "../_lib/api";
import { clone, dropEmptyBlocks, getAt, imageCount, removeAt, setAt } from "../_lib/paths";
import { LAYOUTS, type Block, type Heading, type Languages, type Layout, type Limits, type OwnPage, type Page } from "../_lib/types";
import { DataModal, ImageModal, LayoutModal, type DataBlock } from "./EditModals";
import { readableOf } from "./Languages";
import PageView, { type FieldKind } from "./PageView";
import { ShareButton, ShareModal } from "./Sharing";
import { EditCtx } from "./Txt";
import { PageLoading } from "./ViewStates";

// A picture being drawn is asked for at this pace until it is there.
const DRAW_POLL_MS = 3000;
// Undo keeps this many steps, typing in one field is one step.
const UNDO_STEPS = 20;

type ImageBlock = Extract<Block, { kind: "image" }>;

interface History {
  rev: number;
  page: Page;
  past: Page[];
  future: Page[];
}

type Action =
  | { type: "change"; fn: (p: Page) => void }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "replace"; page: Page };

function reducer(h: History, a: Action): History {
  switch (a.type) {
    case "change": {
      const next = clone(h.page);
      a.fn(next);
      if (JSON.stringify(next) === JSON.stringify(h.page)) return h;
      return { rev: h.rev + 1, page: next, past: [...h.past, h.page].slice(-UNDO_STEPS), future: [] };
    }
    case "undo":
      if (!h.past.length) return h;
      return { rev: h.rev + 1, page: h.past[h.past.length - 1], past: h.past.slice(0, -1), future: [h.page, ...h.future] };
    case "redo":
      if (!h.future.length) return h;
      return { rev: h.rev + 1, page: h.future[0], past: [...h.past, h.page], future: h.future.slice(1) };
    case "replace":
      return { ...h, rev: h.rev + 1, page: a.page };
  }
}

/** Compares two pages by content, the save stamp is no change. */
const same = (a: Page, b: Page) => JSON.stringify({ ...a, saved_at: 0 }) === JSON.stringify({ ...b, saved_at: 0 });

export default function Editor({ uuid }: { uuid: string }) {
  const t = useTranslations("tools.pages");
  const locale = useLocale();
  const [loaded, setLoaded] = useState<OwnPage | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [languages, setLanguages] = useState<Languages | null>(null);
  const [languagesKnown, setLanguagesKnown] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setLanguagesKnown(false);
    api.getLanguages(uuid)
      .then((l) => { if (!cancelled) setLanguages(l); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLanguagesKnown(true); });
    return () => { cancelled = true; };
  }, [uuid, locale]);
  // The page opens in the language set in the settings when it has it, else in its own; null is its own.
  const lang = languages && locale !== languages.own.key
    && languages.languages.some((l) => l.key === locale && l.state === "done") ? locale : null;
  useEffect(() => {
    if (!languagesKnown) return;
    let cancelled = false;
    setLoaded(null);
    api.getPage(uuid, lang)
      .then((p) => { if (!cancelled) setLoaded(p); })
      .catch((e: Error) => { if (!cancelled) setLoadError(e.message || t("loadFailed")); });
    return () => { cancelled = true; };
  }, [uuid, lang, languagesKnown, t]);

  if (loadError) {
    return (
      <>
        <div className="max-w-6xl mx-auto px-4 pt-8"><ToolBackLink href="/tools/pages" label={t("back")} /></div>
        <p className="max-w-xl mx-auto mt-24 px-4 text-center text-sm" style={{ color: "var(--muted)" }} role="alert">{loadError}</p>
      </>
    );
  }
  if (!loaded) return <PageLoading />;
  return <Loaded key={lang ?? ""} uuid={uuid} data={loaded} lang={lang} languages={languages} />;
}

interface LoadedProps {
  uuid: string;
  data: OwnPage;
  lang: string | null;
  languages: Languages | null;
}

/** A fresh id for an added section, lower case like the run's own. */
function newId(page: Page): string {
  const taken = new Set(page.sections.map((s) => s.id));
  let id = "";
  do id = `n${Math.random().toString(36).slice(2, 8)}`; while (taken.has(id));
  return id;
}

function Loaded({ uuid, data, lang, languages }: LoadedProps) {
  const t = useTranslations("tools.pages");
  const [h, dispatch] = useReducer(reducer, { rev: 0, page: data.page, past: [], future: [] });
  const [saved, setSaved] = useState<Page>(data.page);
  const [editing, setEditing] = useState(false);
  const [typing, setTyping] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [share, setShare] = useState({ shared: data.shared, isPublic: data.public, code: data.code });
  const [shareOpen, setShareOpen] = useState(false);
  const [shareBusy, setShareBusy] = useState(false);
  const [layoutAt, setLayoutAt] = useState<number | null>(null);
  // A new title picture becomes a section of its own, inserted at ``cover``.
  const [imageAt, setImageAt] = useState<{ path: string; prompt: string; isNew: boolean; hero: boolean; suggesting?: boolean; cover?: number } | null>(null);
  const [dataAt, setDataAt] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Pictures being drawn: the new name with the name and prompt it replaces.
  const [drawing, setDrawing] = useState<Map<string, { old: string; prompt: string; path: string }>>(new Map());
  const pending = useMemo(() => new Map([...drawing].map(([k, v]) => [k, v.old])), [drawing]);
  const limits: Limits = data.limits;
  const dirty = typing || !same(h.page, saved);

  const commit = useCallback((path: string, value: string) => {
    setTyping(false);
    dispatch({
      type: "change",
      fn: (p) => {
        if (value) setAt(p, path, value);
        else removeAt(p, path);
      },
    });
  }, []);
  const ctx = useMemo(() => ({ editing, rev: h.rev, commit, typing: () => setTyping(true) }), [editing, h.rev, commit]);

  /** A field still being typed in is taken over first, so undo and save see it. */
  const flush = () => {
    const el = document.activeElement as HTMLElement | null;
    if (el?.isContentEditable) el.blur();
  };

  // The page as it is after the last render, for a save that waits one tick.
  const pageRef = useRef(h.page);
  pageRef.current = h.page;

  const undo = () => { flush(); dispatch({ type: "undo" }); };
  const redo = () => { flush(); dispatch({ type: "redo" }); };

  const save = async () => {
    flush();
    setSaving(true);
    setSaveError(null);
    // The blur above lands in the next render, so the save waits one tick for it.
    await new Promise((r) => window.setTimeout(r, 0));
    try {
      const res = await api.savePage(uuid, pageRef.current, lang);
      setSaved(res.page);
      dispatch({ type: "replace", page: res.page });
    } catch {
      setSaveError(t("saveFailed"));
    } finally {
      setSaving(false);
    }
  };
  const onSection = (i: number, action: "up" | "down" | "hide" | "del") => {
    flush();
    const other = action === "up" ? i - 1 : action === "down" ? i + 1 : -1;
    const moveId = other >= 0 ? h.page.sections[i]?.id : null;
    dispatch({
      type: "change",
      fn: (p) => {
        const S = p.sections;
        if (action === "up" && i > 0) [S[i - 1], S[i]] = [S[i], S[i - 1]];
        if (action === "down" && i < S.length - 1) [S[i + 1], S[i]] = [S[i], S[i + 1]];
        if (action === "hide") S[i].hidden = !S[i].hidden;
        if (action === "del") S.splice(i, 1);
      },
    });
    // The moved section stays in view, the reader follows it instead of losing it.
    if (moveId) window.setTimeout(() => document.getElementById(moveId)?.scrollIntoView({ block: "center" }), 0);
  };

  const change = (fn: (p: Page) => void) => { flush(); dispatch({ type: "change", fn }); };

  const addSection = (layout: Layout, heading: Heading) => {
    const after = layoutAt ?? h.page.sections.length - 1;
    const id = newId(h.page);
    setLayoutAt(null);
    change((p) => {
      p.sections.splice(after + 1, 0, {
        id, title: t("newSection"), lead: t("newLead"), layout, ...(heading === "top" ? {} : { heading }),
        blocks: Array.from({ length: LAYOUTS[layout] }, () => ({ kind: "empty" as const })),
      });
    });
    window.setTimeout(() => document.getElementById(id)?.scrollIntoView({ block: "center" }), 0);
  };

  const pick = (i: number, j: number, kind: FieldKind) => {
    const path = `sections.${i}.blocks.${j}`;
    if (kind === "image") { setImageAt({ path, prompt: "", isNew: true, hero: false }); return; }
    const fresh: Record<Exclude<FieldKind, "image">, Block> = {
      text: { kind: "text", text: t("newText") },
      note: { kind: "quote", text: t("newNote") },
      list: { kind: "bullets", items: [t("newItem1"), t("newItem2"), t("newItem3")] },
      table: {
        kind: "table", caption: "", header: [1, 2, 3].map((n) => t("newColumn", { n })),
        rows: [["…", "…", "…"], ["…", "…", "…"]],
      },
      chart: {
        kind: "chart", chart_type: "bar", caption: "", x_label: "", y_label: "",
        categories: [t("newValue1"), t("newValue2"), t("newValue3")], series: [{ name: "", values: [4, 7, 5] }],
      },
    };
    change((p) => setAt(p, path, fresh[kind]));
    if (kind === "chart") setDataAt(path);
  };

  const grow = (path: string, what: "item" | "row" | "col") => change((p) => {
    const b = getAt(p, path) as Block;
    if (what === "item" && (b.kind === "bullets" || b.kind === "checklist")) b.items.push(t("newItem"));
    if (what === "item" && b.kind === "definitions") b.items.push({ term: t("newItem"), text: t("newText") });
    if (what === "item" && b.kind === "accordion") b.items.push({ title: t("newItem"), text: t("newText") });
    if (what === "item" && b.kind === "cards") b.cards.push({ icon: "none", title: t("newItem"), text: t("newText") });
    if (b.kind !== "table") return;
    if (what === "row") b.rows.push(b.header.map(() => "…"));
    if (what === "col") {
      b.header.push(t("newColumn", { n: b.header.length + 1 }));
      b.rows.forEach((r) => r.push("…"));
    }
  });

  const openImage = (path: string) => {
    const b = getAt(h.page, path) as ImageBlock;
    const s = h.page.sections[Number(path.split(".")[1])];
    const hero = !!s?.hero || s?.id === "cover";
    setImageAt({ path, prompt: b.prompt, isNew: false, hero });
  };

  const draw = async (prompt: string) => {
    if (!imageAt) return;
    const { path, isNew, hero, cover } = imageAt;
    const res = await api.drawImage(uuid, { prompt, wrap: isNew, hero });
    const before = isNew ? null : (getAt(h.page, path) as ImageBlock);
    setDrawing((m) => new Map(m).set(res.src, { old: before?.src ?? "", prompt: before?.prompt ?? "", path }));
    change((p) => {
      const block: ImageBlock = { kind: "image", src: res.src, alt: "", prompt: res.prompt, caption: "" };
      if (cover != null) p.sections.splice(cover, 0, { id: p.sections.some((x) => x.id === "cover") ? newId(p) : "cover", title: "", lead: "", blocks: [block] });
      else if (isNew) setAt(p, path, block);
      else Object.assign(getAt(p, path) as ImageBlock, { src: res.src, prompt: res.prompt });
    });
    setImageAt(null);
    setNotice(null);
  };

  // Each picture being drawn is asked for until it is there or failed; a failed one goes back.
  useEffect(() => {
    if (!drawing.size) return;
    const id = window.setInterval(async () => {
      for (const [src, was] of drawing) {
        const { state } = await api.imageState(uuid, src).catch(() => ({ state: "pending" as const }));
        if (state === "pending") continue;
        setDrawing((m) => { const n = new Map(m); n.delete(src); return n; });
        if (state === "failed") {
          setNotice(was.old ? t("drawFailed") : t("drawFailedNew"));
          dispatch({
            type: "change",
            fn: (p) => {
              p.sections.forEach((s) => s.blocks.forEach((b, j) => {
                if (b.kind !== "image" || b.src !== src) return;
                if (was.old) Object.assign(b, { src: was.old, prompt: was.prompt });
                else s.blocks[j] = { kind: "empty" };
              }));
              dropEmptyBlocks(p);
              // A picture section left without its picture goes with it.
              p.sections = p.sections.filter((x) => x.hero || x.title || x.lead || x.blocks.length);
            },
          });
        }
      }
    }, DRAW_POLL_MS);
    return () => window.clearInterval(id);
  }, [drawing, uuid, t]);

  // Ctrl+Z and Ctrl+Shift+Z while editing, also from inside a text.
  useEffect(() => {
    if (!editing) return;
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z") return;
      e.preventDefault();
      if (e.shiftKey) redo();
      else undo();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  // Leaving with unsaved changes asks first, the browser shows its own question.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = t("leave"); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, t]);

  const toggleShare = async (on: boolean, isPublic?: boolean) => {
    setShareBusy(true);
    try {
      const res = await api.setShare(uuid, on, isPublic);
      setShare({ shared: res.shared, isPublic: res.public, code: res.code });
    } catch {
      // The switch stays where it was, the person may try again.
    } finally {
      setShareBusy(false);
    }
  };

  return (
    <EditCtx.Provider value={ctx}>
      {editing && (
        <div className="askf-page-hint px-4 py-1.5 text-xs" style={{ background: "rgba(var(--kb-rgb),.05)", borderBottom: "2px solid rgba(var(--kb-rgb),.15)", color: "var(--kb-dark)" }}>
          {t("editHint")}
          {lang && ` ${t("editingLanguage", { label: readableOf(languages).find((l) => l.key === lang)?.label ?? lang })}`}
        </div>
      )}
      <PageView
        page={h.page}
        limits={limits}
        imageBase={api.imageBase({ uuid })}
        back={{ href: "/tools/pages", label: t("back") }}
        tools={(
          <>
            <Tabs<"edit" | "view">
              variant="pill"
              className="mr-1.5"
              active={editing ? "edit" : "view"}
              onChange={(k) => { flush(); setEditing(k === "edit"); }}
              items={[
                { key: "edit", label: <><PencilSimple size={17} weight="bold" /><span className="hidden sm:inline">{t("modeEdit")}</span></> },
                { key: "view", label: <><Eye size={17} weight="bold" /><span className="hidden sm:inline">{t("modeView")}</span></> },
              ]}
            />
            <ShareButton on={share.shared} onClick={() => setShareOpen(true)} />
          </>
        )}
        edit={{
          canUndo: h.past.length > 0 || typing,
          canRedo: h.future.length > 0,
          dirty,
          // A picture still being drawn would be saved as a hole, so saving waits for it.
          saving: saving || drawing.size > 0,
          error: saveError ?? notice,
          onUndo: undo,
          onRedo: redo,
          onReset: () => { flush(); setTyping(false); dispatch({ type: "change", fn: (p) => Object.assign(p, clone(saved)) }); },
          onSave: save,
          onSection,
          onHeading: (i, heading) => change((p) => {
            if (heading === "top") delete p.sections[i].heading;
            else p.sections[i].heading = heading;
          }),
          pending,
          imagesFull: imageCount(h.page) >= limits.images,
          onAddSection: (after) => { flush(); setLayoutAt(after); },
          onPick: pick,
          onGrow: grow,
          onImage: openImage,
          onHeroImage: (i) => {
            flush();
            const path = `sections.${i}.blocks.${h.page.sections[i].blocks.length}`;
            // The title picture stands above the title as a section of its own.
            const cover = i;
            // Without the model's proposal the title is the starting point.
            const fallback = `a calm illustration that stands for the topic ${h.page.sections[i].title}`;
            // The model reads the whole page and proposes a picture for its topic, the owner may change it.
            setImageAt({ path, isNew: true, hero: true, prompt: "", suggesting: true, cover });
            api.suggestImage(uuid)
              .then((r) => setImageAt((x) => (x?.path === path ? { ...x, prompt: r.prompt || fallback, suggesting: false } : x)))
              .catch(() => setImageAt((x) => (x?.path === path ? { ...x, prompt: fallback, suggesting: false } : x)));
          },
          onData: (path) => { flush(); setDataAt(path); },
        }}
      />
      {editing && <DeleteOnHover onDelete={(path, section) => {
        flush();
        dispatch({
          type: "change",
          fn: (p) => {
            if (section != null) p.sections.splice(section, 1);
            else removeAt(p, path);
          },
        });
      }} />}
      <ScrollTopButton />
      <LayoutModal open={layoutAt !== null} left={limits.sections - h.page.sections.length}
        onClose={() => setLayoutAt(null)} onPick={addSection} />
      <ImageModal open={!!imageAt} isNew={!!imageAt?.isNew} prompt={imageAt?.prompt ?? ""} suggesting={!!imageAt?.suggesting} max={limits.imagePrompt}
        onClose={() => setImageAt(null)} onDraw={draw} />
      <DataModal block={dataAt ? (getAt(h.page, dataAt) as DataBlock) : null} limits={limits} onClose={() => setDataAt(null)}
        onApply={(b) => { const at = dataAt!; setDataAt(null); change((p) => setAt(p, at, b)); }} />
      <ShareModal
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        shared={share.shared}
        isPublic={share.isPublic}
        link={share.code ? api.shareUrl(share.code) : null}
        busy={shareBusy}
        onToggle={(on) => toggleShare(on)}
        onAudience={(isPublic) => toggleShare(true, isPublic)}
      />
    </EditCtx.Provider>
  );
}

/**
 * The round bin that follows the pointer while editing. It sits on the innermost element
 * under the pointer: an item, a text, a block or a whole section, which turns red on hover.
 */
function DeleteOnHover({ onDelete }: { onDelete: (path: string, section: number | null) => void }) {
  const t = useTranslations("tools.pages");
  const btn = useRef<HTMLButtonElement>(null);
  const target = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const b = btn.current!;
    const hide = () => {
      b.classList.remove("on");
      target.current?.classList.remove("ed-target");
      target.current = null;
    };
    const move = (e: MouseEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest(".askf-page-del")) return;
      if (!el.closest(".askf-page") || el.closest(".ed-tools,.ed-actions,.ed-save,.ed-add,.ed-grow,.ed-over,.fld-pick,.pfoot")) return hide();
      const hit = el.closest<HTMLElement>("[data-d],[data-p]:not([data-keep]),.askf-page section");
      if (!hit) return hide();
      if (hit === target.current) return;
      target.current?.classList.remove("ed-target");
      target.current = hit;
      const r = hit.getBoundingClientRect();
      const isSection = hit.tagName === "SECTION";
      const top = isSection ? parseFloat(getComputedStyle(hit, "::before").top) || 0 : 0;
      b.style.top = `${r.top + window.scrollY + top - 12}px`;
      b.style.left = `${Math.min(r.right + window.scrollX + (isSection ? 16 : 0) - 16, document.documentElement.clientWidth - 32)}px`;
      b.classList.add("on");
    };
    document.addEventListener("mousemove", move);
    return () => { document.removeEventListener("mousemove", move); hide(); };
  }, []);

  // On the body, so its position is the page's and no parent can shift it.
  return createPortal(
    <button
      ref={btn}
      type="button"
      className="askf-page-del"
      aria-label={t("removeElement")}
      title={t("remove")}
      onMouseEnter={() => target.current?.classList.add("ed-target")}
      onMouseLeave={() => target.current?.classList.remove("ed-target")}
      onClick={() => {
        const el = target.current;
        if (!el) return;
        el.classList.remove("ed-target");
        btn.current?.classList.remove("on");
        target.current = null;
        if (el.tagName === "SECTION") onDelete("", Number(el.dataset.i));
        else onDelete(el.dataset.d ?? el.dataset.p ?? "", null);
      }}
    >
      <Trash size={15} weight="bold" />
    </button>,
    document.body,
  );
}
