"use client";

import { Fragment, createContext, useContext } from "react";
import { useTranslations } from "next-intl";
import {
  ArrowCounterClockwise,
  ArrowDown,
  ArrowUUpLeft,
  ArrowUUpRight,
  ArrowUp,
  ChartBar,
  Eye,
  EyeSlash,
  Image as ImageIcon,
  Info,
  ListBullets,
  Plus,
  Table,
  TextT,
  Trash,
} from "@phosphor-icons/react";
import Select from "@/components/ui/Select";
import ToolBackLink from "@/components/ui/ToolBackLink";
import { HEADINGS, type Block, type Design, type Heading, type Limits, type Page, type Section } from "../_lib/types";
import { EditCtx, Txt } from "./Txt";
import { LOOKS, looksOf, sectionLooks, type SectionLook } from "./looks";
import type { Look } from "./looks/registry";
import { PageEdit, PageLang, Picture, type EditControls, type FieldKind } from "./looks/shared";
import "./page.css";

export type { EditControls, FieldKind };

const FIELDS: { kind: FieldKind; icon: typeof Info }[] = [
  { kind: "text", icon: TextT }, { kind: "image", icon: ImageIcon }, { kind: "table", icon: Table },
  { kind: "chart", icon: ChartBar }, { kind: "list", icon: ListBullets }, { kind: "note", icon: Info },
];

/** The fixed parts of a page carry these ids, every other section belongs to the subject. */
const FRAME_IDS = new Set(["cover", "gist", "map", "words"]);
const isContent = (s: Section) => !s.hero && !FRAME_IDS.has(s.id);
const EXPLAINED = new Set(["map", "words"]);

/** A long title gets a smaller size, so it never breaks into a tower of single words. */
const titleSize = (title: string) =>
  (title.length > 48 ? " t-xl" : title.length > 26 ? " t-l" : "")
  // A very long word would break in the middle on a phone, the title shrinks there instead.
  + (Math.max(...title.split(/\s+/).map((w) => w.length)) > 13 ? " t-word" : "");

/** The look chosen for every block, keyed "section.block". */
const LookOf = createContext<Map<string, number>>(new Map());

interface Props {
  page: Page;
  limits: Limits;
  imageBase: string;
  edit?: EditControls | null;
  back?: { href: string; label: string };
  /** Buttons on the right of the back link's row. */
  tools?: React.ReactNode;
}

/** Figure and table numbers in reading order, counted over what is actually shown. */
function numbering(page: Page, editing: boolean): Map<string, number> {
  const nums = new Map<string, number>();
  let fig = 0, tab = 0;
  page.sections.forEach((s, i) => {
    // The title picture is no figure of the text, it gets no number.
    if (s.hero || s.id === "cover" || (s.hidden && !editing)) return;
    s.blocks.forEach((b, j) => {
      const key = `${i}.${j}`;
      if (b.kind === "table") nums.set(key, ++tab);
      else if (b.kind === "image" ? b.caption || editing : ["chart", "mindmap", "wordcloud"].includes(b.kind)) nums.set(key, ++fig);
    });
  });
  return nums;
}

export default function PageView({ page, limits, imageBase, edit, back, tools }: Props) {
  const t = useTranslations("tools.pages");
  const { editing } = useContext(EditCtx);
  const nums = numbering(page, editing);
  const looks = looksOf(page);
  const n = page.sections.length;
  const design: Design = page.design ?? "chapters";
  const hasCover = page.sections.some((x) => x.id === "cover" && x.blocks.some((b) => b.kind === "image"));
  // Chapters count only the sections of the subject, not the title, summary, map or words.
  const chapters = new Map<number, number>();
  page.sections.forEach((s, i) => {
    if (isContent(s) && s.heading !== "none" && !(s.hidden && !editing)) chapters.set(i, chapters.size + 1);
  });
  const builds = sectionLooks(page, design, isContent, editing);
  // Every second section of the subject and the summary lie on a light band, so the page reads in parts.
  const tinted = new Set<number>();
  let shownContent = 0;
  page.sections.forEach((s, i) => {
    if (s.hidden && !editing) return;
    if (s.id === "gist") tinted.add(i);
    if (!isContent(s) || builds.get(i) === "pair") return;
    if (shownContent++ % 2 === 1) tinted.add(i);
  });
  const view = (i: number) => (
    <SectionView s={page.sections[i]} i={i} n={n} limits={limits} imageBase={imageBase} nums={nums} edit={edit}
      chapter={chapters.get(i)} hasCover={hasCover} build={builds.get(i)} tint={tinted.has(i)} />
  );

  return (
    <PageEdit.Provider value={edit ?? null}>
    <PageLang.Provider value={page.lang}>
    <LookOf.Provider value={looks}>
    <div className={`askf-page d-${design}${editing ? " editing" : ""}`} lang={page.lang}>
      <main className="wrap">
        <div className="top-row">
          {back && <ToolBackLink href={back.href} label={back.label} />}
          {tools && <div className="top-tools">{tools}</div>}
        </div>
        {edit && (
          <div className="ed-only ed-actions ed-row">
            <button type="button" className="ed-btn icon-only" disabled={!edit.canUndo} onClick={edit.onUndo} aria-label={t("undo")} title={t("undoTitle")}>
              <ArrowUUpLeft size={14} weight="bold" />
            </button>
            <button type="button" className="ed-btn icon-only" disabled={!edit.canRedo} onClick={edit.onRedo} aria-label={t("redo")} title={t("redoTitle")}>
              <ArrowUUpRight size={14} weight="bold" />
            </button>
            <button type="button" className="ed-btn reset" disabled={!edit.dirty || edit.saving} onClick={edit.onReset} title={t("resetTitle")}>
              <ArrowCounterClockwise size={12} weight="bold" />
              {t("reset")}
            </button>
            <button type="button" className="ed-btn save" disabled={!edit.dirty || edit.saving} onClick={edit.onSave}>
              {t("save")}
            </button>
          </div>
        )}
        {page.sections.map((s, i) => {
          // The second of a pair stands in the first one's row.
          if (builds.get(i) === "pair" && builds.get(i - 1) === "pair" && pairStart(builds, i - 1)) return null;
          return (
            <Fragment key={s.id}>
              {builds.get(i) === "pair" ? <div className="sx-pair-row">{view(i)}{view(i + 1)}</div> : view(i)}
              {edit && <AddSection after={i} full={n >= limits.sections} max={limits.sections} onAdd={edit.onAddSection} />}
            </Fragment>
          );
        })}
        {edit && (
          <div className="ed-only ed-save" style={{ flexDirection: "column", alignItems: "flex-end" }}>
            <button type="button" className="ed-btn save" disabled={!edit.dirty || edit.saving} onClick={edit.onSave}>
              {t("save")}
            </button>
            {edit.error && <p className="ed-error" role="alert">{edit.error}</p>}
          </div>
        )}
        <footer className="pfoot">
          <Txt path="footer" value={page.footer} as="p" max={limits.long} />
        </footer>
      </main>
    </div>
    </LookOf.Provider>
    </PageLang.Provider>
    </PageEdit.Provider>
  );
}

/** Whether a paired section opens its pair, pairs follow each other two by two. */
function pairStart(builds: Map<number, SectionLook>, i: number): boolean {
  let k = i;
  while (builds.get(k - 1) === "pair") k--;
  return (i - k) % 2 === 0;
}

/** The round plus between two sections, it opens the choice of a layout for a new one. */
function AddSection({ after, full, max, onAdd }: { after: number; full: boolean; max: number; onAdd: (after: number) => void }) {
  const t = useTranslations("tools.pages");
  return (
    <div className="ed-only ed-add">
      <button type="button" disabled={full} onClick={() => onAdd(after)} aria-label={t("addSection")}
        title={full ? t("addSectionFull", { max }) : t("addSection")}>
        <Plus size={15} weight="bold" />
      </button>
    </div>
  );
}

/** An empty field of an added section: while editing the choice of its content, for readers nothing. */
function EmptyField({ i, j, limits }: { i: number; j: number; limits: Limits }) {
  const t = useTranslations("tools.pages");
  const ed = useContext(PageEdit);
  const { editing } = useContext(EditCtx);
  if (!ed || !editing) return <div className="fld fld-empty" />;
  return (
    <div className="fld fld-empty">
      <div className="fld-pick">
        <span>{t("fieldAsk")}</span>
        <div className="fld-opts">
          {FIELDS.map(({ kind, icon: Icon }) => {
            const off = kind === "image" && ed.imagesFull;
            return (
              <button key={kind} type="button" className="ed-btn" disabled={off} onClick={() => ed.onPick(i, j, kind)}
                title={off ? t("imagesFull", { max: limits.images }) : undefined}>
                <Icon size={13} weight="bold" />{t(`field.${kind}`)}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function Tools({ s, i, n, edit }: { s: Section; i: number; n: number; edit: EditControls }) {
  const t = useTranslations("tools.pages");
  return (
    <div className="ed-only ed-tools">
      <button type="button" className="ed-btn" disabled={i === 0} onClick={() => edit.onSection(i, "up")}>
        <ArrowUp size={12} weight="bold" />{t("up")}
      </button>
      <button type="button" className="ed-btn" disabled={i === n - 1} onClick={() => edit.onSection(i, "down")}>
        <ArrowDown size={12} weight="bold" />{t("down")}
      </button>
      <button type="button" className="ed-btn" onClick={() => edit.onSection(i, "hide")}>
        {s.hidden ? <Eye size={12} weight="bold" /> : <EyeSlash size={12} weight="bold" />}
        {s.hidden ? t("show") : t("hide")}
      </button>
      <button type="button" className="ed-btn del" onClick={() => edit.onSection(i, "del")}>
        <Trash size={12} weight="bold" />{t("remove")}
      </button>
      {s.layout && (
        <Select<Heading> size="sm" value={s.heading ?? "top"} ariaLabel={t("headingLabel")} onChange={(h) => edit.onHeading(i, h)}
          options={HEADINGS.map((h) => ({ value: h, label: t(`headings.${h}`) }))} />
      )}
    </div>
  );
}

interface SectionProps {
  /** How a section of the subject is built, absent for the frame. */
  build?: SectionLook;
  /** The section lies on a light band across the page. */
  tint?: boolean;
  /** Its number among the subject's sections, absent for the frame. */
  chapter?: number;
  s: Section;
  i: number;
  n: number;
  limits: Limits;
  imageBase: string;
  nums: Map<string, number>;
  edit?: EditControls | null;
  /** The page's picture stands as a section of its own above the title. */
  hasCover?: boolean;
}

function SectionView({ s, i, n, limits, imageBase, nums, edit, build, chapter, hasCover, tint }: SectionProps) {
  const t = useTranslations("tools.pages");
  const p = `sections.${i}`;
  const cls = (s.hidden ? " is-hidden" : "") + (tint ? " tint" : "");
  if (s.hero) {
    const j = s.blocks.findIndex((b) => b.kind === "image");
    const img = j >= 0 ? (s.blocks[j] as Extract<Block, { kind: "image" }>) : null;
    const figure = img && (
      <figure className="img" data-d={`${p}.blocks.${j}`}>
        <Picture src={img.src} alt={img.alt} p={`${p}.blocks.${j}`} imageBase={imageBase} />
      </figure>
    );
    return (
      <section id={s.id} className={`hero${titleSize(s.title)}${cls}`} data-i={i}>
        {edit && <Tools s={s} i={i} n={n} edit={edit} />}
        {/* An older page keeps its picture inside the title, it runs wide above the text there too. */}
        {figure}
        <div className="hero-text">
          <Txt path={`${p}.title`} value={s.title} as="h1" max={limits.short} />
          <Txt path={`${p}.lead`} value={s.lead} as="p" className="lead" max={limits.long} />
          <Txt path={`${p}.meta`} value={s.meta} as="p" className="meta" max={limits.long} />
        </div>
        {edit && !img && !hasCover && (
          <div className="ed-only ed-hero-add">
            <button type="button" className="ed-btn" disabled={edit.imagesFull} onClick={() => edit.onHeroImage(i)}>
              <ImageIcon size={13} weight="bold" />{t("addHeroImage")}
            </button>
          </div>
        )}
      </section>
    );
  }
  if (s.layout) {
    // The owner places title and lead above, beside, below the fields or leaves them out.
    const heading: Heading = s.heading ?? "top";
    return (
      <section id={s.id} className={`${chapter != null ? "content" : "frame"} added h-${heading}${cls}`} data-i={i}>
        {edit && <Tools s={s} i={i} n={n} edit={edit} />}
        {heading !== "none" && <div className="txt">
          <Txt path={`${p}.title`} value={s.title} as="h2" max={limits.short} />
          <Txt path={`${p}.lead`} value={s.lead} as="p" className="lead" max={limits.long} />
        </div>}
        <div className="body">
          <div className={`lay lay-${s.layout}`}>
            {s.blocks.map((b, j) => (b.kind === "empty" ? <EmptyField key={j} i={i} j={j} limits={limits} /> : (
              <div className="fld blk" data-d={`${p}.blocks.${j}`} key={j}>
                <BlockView b={b} p={`${p}.blocks.${j}`} at={`${i}.${j}`} limits={limits} imageBase={imageBase} num={nums.get(`${i}.${j}`)} />
              </div>
            )))}
          </div>
        </div>
      </section>
    );
  }
  const blocks = s.blocks.map((b, j) => (
    <div className={`blk k-${b.kind}`} data-d={`${p}.blocks.${j}`} key={j}>
      <BlockView b={b} p={`${p}.blocks.${j}`} at={`${i}.${j}`} limits={limits} imageBase={imageBase} num={nums.get(`${i}.${j}`)}
        pin={build === "split" && b.kind === "image" ? 0 : undefined} />
    </div>
  ));
  const kind = chapter != null ? "content" : "frame";
  return (
    <section id={s.id} className={`${kind}${build ? ` sx-${build}` : ""}${s.id === "cover" ? " cover" : ""}${cls}`} data-i={i}>
      {edit && <Tools s={s} i={i} n={n} edit={edit} />}
      <div className="txt">
        <Txt path={`${p}.title`} value={s.title} as="h2" max={limits.short} />
        {/* Map and word cloud explain themselves, older pages still carry a sentence there. */}
        {!EXPLAINED.has(s.id) && <Txt path={`${p}.lead`} value={s.lead} as="p" className="lead" max={limits.long} />}
      </div>
      <div className="body">{blocks}</div>
    </section>
  );
}

/** One block in the look the page chose for it. */
function BlockView({ b, p, limits, imageBase, num, at, pin }: { b: Block; p: string; limits: Limits; imageBase: string; num?: number; at: string; pin?: number }) {
  // A picture beside text in a split section always takes the plain banner.
  const picked = useContext(LookOf);
  const chosen = pin ?? picked.get(at);
  if (b.kind === "empty") return null;
  const all = LOOKS[b.kind] as Look[] | undefined;
  const look = all?.[chosen ?? 0] ?? all?.[0];
  if (!look) return null;
  const View = look.View;
  return <View b={b as never} p={p} limits={limits} imageBase={imageBase} num={num} />;
}
