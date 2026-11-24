// Programmatic highlights: a selection of your own, and the spot a chip claim rests on.

import { PdfBlendMode } from "@embedpdf/models";
import { findClaimSpot, normalizePageText } from "./_claim_match";

export type HighlightRefs = {
  // The current transient highlight, with its position for jumping back.
  citationHighlightRef: { current: { pageIndex: number; ids: string[]; scrollY?: number } | null };
  // Toggles the "dismiss highlight" control in the viewer.
  onHighlightActive?: (active: boolean) => void;
};

// Controls whether it scrolls after drawing and whether it keeps the current marks.
type DrawOpts = { scroll?: boolean; append?: boolean };

// A passive light blue mark, not a text selection.
export const CITATION_HL_COLOR = "#9BD2F0";   // light CD blue, same as the highlight tool
// Matches the native highlighter's own default: the renderer only paints opacity 1 reliably,
// the paleness of CITATION_HL_COLOR itself is what keeps the mark soft.
const CITATION_HL_OPACITY = 1;
const HIGHLIGHT_SUBTYPE = 9;           // PdfAnnotationSubtype.HIGHLIGHT

// The page frame on a chip jump, as a square instead of a highlight.
const SQUARE_SUBTYPE = 5;              // PdfAnnotationSubtype.SQUARE
// The page frame takes the strong brand blue, not the pale highlight colour.
const CITATION_FRAME_COLOR = "#004261";   // --kb
const BORDER_STYLE_SOLID = 1;         // PdfAnnotationBorderStyle.SOLID
const PAGE_BORDER_WIDTH = 3;          // px frame thickness
const PAGE_BORDER_OPACITY = 0.95;     // crisp frame

// Folds accents length preserving so the search tolerates umlauts.
function _foldDiacritics(s: string): string {
  let out = "";
  for (let i = 0; i < s.length; i++) {
    const d = s[i].normalize("NFKD");
    out += d[0] || s[i];
  }
  return out.toLowerCase();
}


// Maps a text position onto the geometry, invisible characters shift it.
function makeFindGeo(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  engine: any, doc: any, targetPageIndex: number, totalChars: number, rawLen: number,
): (rawIdx: number) => Promise<number> {
  const phantoms = totalChars - rawLen;
  return (rawIdx: number): Promise<number> => {
    if (phantoms === 0) return Promise.resolve(rawIdx);
    let lo = rawIdx + 1, hi = Math.min(rawIdx + 1 + phantoms, totalChars);
    const step = (): Promise<number> => {
      if (lo >= hi) return Promise.resolve(lo - 1);
      const mid = (lo + hi) >> 1;
      const t = engine.getTextSlices?.(doc, [{ pageIndex: targetPageIndex, charIndex: 0, charCount: mid }]);
      return (t?.toPromise?.() ?? Promise.resolve(null)).then((res: unknown) => {
        const len = (res as string[])?.[0]?.length ?? 0;
        if (len < rawIdx + 1) lo = mid + 1; else hi = mid;
        return step();
      });
    };
    return step();
  };
}


// Builds the rectangles per line from the page geometry.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildSegmentRects(g: any, a: number, b: number): { segmentRects: any[]; bbox: any } {
  const segs: { origin: { x: number; y: number }; size: { width: number; height: number } }[] = [];
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const run of (g.runs || [])) {
    const runStart = run.charStart;
    const runEnd = runStart + run.glyphs.length - 1;
    if (runEnd < a || runStart > b) continue;
    let lx = Infinity, ly = Infinity, hx = -Infinity, hy = -Infinity;
    for (let i = 0; i < run.glyphs.length; i++) {
      const idx = runStart + i;
      if (idx < a || idx > b) continue;
      const gl = run.glyphs[i];
      if (gl.flags === 2) continue; // empty glyph
      const x0 = gl.x, y0 = gl.y, x1 = gl.x + gl.width, y1 = gl.y + gl.height;
      if (x0 < lx) lx = x0; if (y0 < ly) ly = y0; if (x1 > hx) hx = x1; if (y1 > hy) hy = y1;
    }
    if (lx === Infinity) continue;
    segs.push({ origin: { x: lx, y: ly }, size: { width: hx - lx, height: hy - ly } });
    if (lx < minX) minX = lx; if (ly < minY) minY = ly; if (hx > maxX) maxX = hx; if (hy > maxY) maxY = hy;
  }
  if (!segs.length) return { segmentRects: [], bbox: null };
  return { segmentRects: segs, bbox: { origin: { x: minX, y: minY }, size: { width: maxX - minX, height: maxY - minY } } };
}


// Removes the current transient highlight, the file stays untouched.
export function clearCitationHighlight(refs: HighlightRefs, reg: unknown) {
  const cur = refs.citationHighlightRef?.current;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const anno = (reg as any)?.getPlugin?.("annotation")?.provides?.();
  for (const id of cur?.ids ?? []) {
    try { anno?.purgeAnnotation?.(cur!.pageIndex, id); } catch { /* ignore */ }
  }
  // Sweep for orphans our bookkeeping lost (a reset ref or a racing draw leaves a marker nobody tracks).
  try {
    const pages = anno?.getState?.()?.pages as Record<number, string[]> | undefined;
    for (const [pi, uids] of Object.entries(pages ?? {})) {
      for (const uid of [...uids]) {
        if (uid.startsWith("askf-cite-") || uid.startsWith("askf-pageborder-")) anno.purgeAnnotation(Number(pi), uid);
      }
    }
  } catch { /* ignore */ }
  if (!cur) return;
  refs.citationHighlightRef.current = null;
  refs.onHighlightActive?.(false);
}


// Draws a blue frame around the page that was jumped to.
function flashPageBorder(refs: HighlightRefs, reg: unknown, page: number) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const r = reg as any;
  const anno = r.getPlugin?.("annotation")?.provides?.();
  const docMgr = r.getPlugin?.("document-manager")?.provides?.();
  const docId = docMgr?.getActiveDocumentId?.();
  const doc = docMgr?.getActiveDocument?.();
  if (!anno?.createAnnotation || !docId || !doc) return;

  const pageIndex = page - 1;
  const pageObj = doc.pages?.[pageIndex];
  const pageW = pageObj?.size?.width ?? pageObj?.width;
  const pageH = pageObj?.size?.height ?? pageObj?.height;
  if (!pageW || !pageH) return;

  clearCitationHighlight(refs, r);   // one marker at a time

  // The frame sits on the page edge, a gap would depend on the zoom.
  const id = `askf-pageborder-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  try {
    anno.createAnnotation(pageIndex, {
      type: SQUARE_SUBTYPE,
      pageIndex,
      id,
      rect: { origin: { x: 0, y: 0 }, size: { width: pageW, height: pageH } },
      color: "transparent",
      strokeColor: CITATION_FRAME_COLOR,
      strokeWidth: PAGE_BORDER_WIDTH,
      strokeStyle: BORDER_STYLE_SOLID,
      opacity: PAGE_BORDER_OPACITY,
      flags: ["readOnly", "locked"],
      created: new Date(),
    });
    anno.deselectAnnotation?.();
    refs.citationHighlightRef.current = { pageIndex, ids: [id] };
    refs.onHighlightActive?.(true);
  } catch {
    /* frame is non-essential — ignore */
  }
}


// The glyph geometry of one page, from the selection plugin's cache when it is there.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function pageGeometry(r: any, doc: any, engine: any, pageIndex: number, pageObj: unknown): Promise<any> {
  const selection = r.getPlugin?.("selection")?.provides?.();
  const cachedGeo = selection?.getState?.()?.geometry?.[pageIndex];
  return cachedGeo
    ? Promise.resolve(cachedGeo)
    : (engine.getPageGeometry?.(doc, pageObj)?.toPromise?.() ?? Promise.resolve(null));
}


// Loads geometry and text of one page, null when the page carries no text.
function loadPageText(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  r: any, doc: any, engine: any, pageIndex: number,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
): Promise<{ g: any; totalChars: number; rawText: string } | null> {
  const pageObj = doc.pages?.[pageIndex];
  if (!pageObj) return Promise.resolve(null);
  return pageGeometry(r, doc, engine, pageIndex, pageObj).then((g) => {
    if (!g?.runs?.length) return null;
    const lastRun = g.runs[g.runs.length - 1];
    const totalChars = lastRun.charStart + lastRun.glyphs.length;
    if (totalChars < 50) return null;
    const sliceTask = engine.getTextSlices?.(doc, [{ pageIndex, charIndex: 0, charCount: totalChars }]);
    const slicePromise: Promise<unknown> = sliceTask?.toPromise?.() ?? Promise.resolve(null);
    return slicePromise.then((slices: unknown) => {
      const rawText = (slices as string[] | null)?.[0];
      return rawText ? { g, totalChars, rawText } : null;
    });
  });
}


// Draws the page frame and marks the passage the claim rests on, both go with the X.
export function markCitationSpot(refs: HighlightRefs, reg: unknown, page: number, claim?: string, title?: string) {
  flashPageBorder(refs, reg, page);
  const frameIds = refs.citationHighlightRef.current?.ids;
  if (!claim?.trim() || !frameIds?.length) return;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const r = reg as any;
  const engine = r.getEngine?.();
  const docMgr = r.getPlugin?.("document-manager")?.provides?.();
  const scroll = r.getPlugin?.("scroll")?.provides?.();
  const doc = docMgr?.getActiveDocument?.();
  if (!engine || !docMgr || !doc) return;
  const pageIndex = page - 1;
  // A later jump replaces the frame, then this result is stale.
  const stillCurrent = () => refs.citationHighlightRef.current?.ids[0] === frameIds[0];

  loadPageText(r, doc, engine, pageIndex).then((loaded) => {
    if (!loaded || !stillCurrent()) return;
    const { g, totalChars, rawText } = loaded;
    const { text, toRaw } = normalizePageText(rawText);
    const hit = findClaimSpot(text, claim, title);
    if (!hit) return;
    const findGeo = makeFindGeo(engine, doc, pageIndex, totalChars, rawText.length);
    const draws = hit.spans.map((span) =>
      Promise.all([findGeo(toRaw[span.start]), findGeo(toRaw[span.end - 1])]),
    );
    return Promise.all(draws).then((ranges) => {
      if (!stillCurrent()) return;
      let first = true;
      for (const [geoStart, geoEnd] of ranges) {
        if (geoEnd < geoStart) continue;
        // Only the first mark scrolls, the rest join it on the page.
        const ok = drawCitationHighlight(refs, r, docMgr, scroll, pageIndex, geoStart, geoEnd, g, { append: true, scroll: first });
        if (ok && first) {
          const rect = buildSegmentRects(g, geoStart, geoEnd).bbox;
          if (rect && refs.citationHighlightRef.current) refs.citationHighlightRef.current.scrollY = rect.origin.y;
        }
        if (ok) first = false;
      }
    });
  }).catch(() => { /* the frame alone is still a result */ });
}


// Scrolls the active highlight back into view, with its position.
export function scrollToCitationPage(refs: HighlightRefs, reg: unknown) {
  const cur = refs.citationHighlightRef.current;
  if (!cur) return;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const scroll = (reg as any)?.getPlugin?.("scroll")?.provides?.();
  scroll?.scrollToPage?.({
    pageNumber: cur.pageIndex + 1,
    ...(cur.scrollY != null
      ? { pageCoordinates: { x: 0, y: cur.scrollY }, alignY: 50 }
      : {}),
    behavior: "smooth",
  });
}


// Draws the highlight as a passive mark and scrolls to it.
export function drawCitationHighlight(
  refs: HighlightRefs,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  r: any, docMgr: any, scroll: any, targetPageIndex: number, geoStart: number, geoEnd: number, g: any,
  opts: DrawOpts = {},
): boolean {
  const doScroll = opts.scroll ?? true;
  const { segmentRects, bbox } = buildSegmentRects(g, geoStart, geoEnd);
  if (!segmentRects.length || !bbox) return false;
  const anno = r.getPlugin?.("annotation")?.provides?.();
  const docId = docMgr.getActiveDocumentId?.();
  if (!anno?.createAnnotation || !docId) return false;
  const cur = refs.citationHighlightRef.current;
  const keep = opts.append && cur?.pageIndex === targetPageIndex;
  if (!keep) clearCitationHighlight(refs, r);   // one highlight at a time
  const id = `askf-cite-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  try {
    anno.createAnnotation(targetPageIndex, {
      type: HIGHLIGHT_SUBTYPE,
      pageIndex: targetPageIndex,
      id,
      rect: bbox,
      segmentRects,
      strokeColor: CITATION_HL_COLOR,
      color: CITATION_HL_COLOR,
      opacity: CITATION_HL_OPACITY,
      // Without this the highlight never paints, the native tool sets it through its own
      // defaults, our marker skipped it until this was tracked down.
      blendMode: PdfBlendMode.Multiply,
      // readOnly + locked so the user can't accidentally select/drag/edit our marker.
      flags: ["readOnly", "locked"],
      created: new Date(),
    });
    anno.deselectAnnotation?.();      // no selection handles on the fresh annotation
    const prev = keep && cur ? cur : null;
    refs.citationHighlightRef.current = {
      pageIndex: targetPageIndex,
      ids: [...(prev?.ids ?? []), id],
      scrollY: prev?.scrollY ?? bbox.origin.y,
    };
    refs.onHighlightActive?.(true);
  } catch {
    return false;
  }
  if (scroll && doScroll) {
    scroll.scrollToPage({
      pageNumber: targetPageIndex + 1,
      pageCoordinates: { x: 0, y: bbox.origin.y },
      behavior: "instant",
      alignY: 50,
    });
  }
  return true;
}


// Highlights exactly the quote, without a fuzzy fallback.
function tryHighlightOnPage(
  refs: HighlightRefs,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  r: any, doc: any, engine: any, docMgr: any, scroll: any,
  targetPageIndex: number, searchText: string,
): Promise<boolean> {
  const pageObj = doc.pages?.[targetPageIndex];
  if (!pageObj) return Promise.resolve(false);

  return pageGeometry(r, doc, engine, targetPageIndex, pageObj).then((g) => {
    // A pure image page counts as done so nothing foreign gets highlighted.
    const noRuns = !g?.runs?.length;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const lastRun = !noRuns ? (g.runs[g.runs.length - 1] as any) : null;
    const totalChars = lastRun ? lastRun.charStart + lastRun.glyphs.length : 0;
    if (noRuns || totalChars < 50) {
      if (scroll) {
        scroll.scrollToPage({ pageNumber: targetPageIndex + 1, behavior: "instant" });
      }
      return true;
    }

    const sliceTask = engine.getTextSlices?.(doc, [{ pageIndex: targetPageIndex, charIndex: 0, charCount: totalChars }]);
    const slicePromise: Promise<unknown> = sliceTask?.toPromise?.() ?? Promise.resolve(null);

    return slicePromise.then((slices: unknown) => {
      const arr = slices as string[] | null;
      if (!arr?.[0]) return false;
      const rawPageText = arr[0];

      // Normalize whitespace for robust search, track mapping to raw indices.
      const cleanToRaw: number[] = [];
      let cleanText = "";
      let inSpace = false;
      for (let i = 0; i < rawPageText.length; i++) {
        const ch = rawPageText[i];
        if (ch === "\r" || ch === "\n" || ch === " " || ch === "\t") {
          if (!inSpace) { cleanText += " "; cleanToRaw.push(i); inSpace = true; }
        } else { cleanText += ch; cleanToRaw.push(i); inSpace = false; }
      }

      // The user's own selection stays untouched.
      const cleanInput = searchText.replace(/\s+/g, " ").trim()
        .replace(/^\d{1,3}\s+/, "").trim();
      // Accent folded so the search tolerates a broken text layer.
      const ptLower = _foldDiacritics(cleanText);
      const fullPhrase = _foldDiacritics(cleanInput);

      const fullIdx = ptLower.indexOf(fullPhrase);
      if (fullIdx < 0) {
        // Exact selection didn't match the page — scroll and bail, never fuzzy-match.
        if (scroll) {
          scroll.scrollToPage({ pageNumber: targetPageIndex + 1, behavior: "instant" });
        }
        return true;
      }
      const matchStart = fullIdx;
      const matchEnd = fullIdx + fullPhrase.length - 1;

      // Highlight EXACTLY what the user marked — no expansion, regardless of length.
      const rawStart = cleanToRaw[matchStart];
      const rawEnd = cleanToRaw[matchEnd];

      const findGeo = makeFindGeo(engine, doc, targetPageIndex, totalChars, rawPageText.length);

      if (!docMgr.getActiveDocumentId?.()) return false;

      return Promise.all([findGeo(rawStart), findGeo(rawEnd)]).then(([geoStart, geoEnd]) => {
        // Limited to the visible line, the character order misleads otherwise.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const runs = (g.runs || []) as any[];
        if (runs.length) {
          const runYMid = (rn: { rect?: { y?: number; height?: number } }) => {
            const y = rn.rect?.y ?? 0;
            const h = rn.rect?.height ?? 0;
            return y + h / 2;
          };
          const startRun = runs.find(rn => geoStart >= rn.charStart && geoStart < rn.charStart + rn.glyphs.length);
          const endRun = runs.find(rn => geoEnd >= rn.charStart && geoEnd < rn.charStart + rn.glyphs.length) ?? startRun;
          if (startRun?.rect) {
            const startY = runYMid(startRun);
            const endY = endRun?.rect ? runYMid(endRun) : startY;
            const lineH = Math.max(startRun.rect.height ?? 0, 6);
            const tol = lineH * 0.7;
            const yMin = Math.min(startY, endY) - tol;
            const yMax = Math.max(startY, endY) + tol;
            const startIdx = runs.indexOf(startRun);
            const endIdx = endRun ? runs.indexOf(endRun) : startIdx;
            let minStart = startRun.charStart;
            let maxEnd = (endRun ?? startRun).charStart + (endRun ?? startRun).glyphs.length - 1;
            for (let i = startIdx - 1; i >= 0; i--) {
              const rn = runs[i]; if (!rn.rect) break;
              const y = runYMid(rn);
              if (y < yMin || y > yMax) break;
              minStart = rn.charStart;
            }
            for (let i = endIdx + 1; i < runs.length; i++) {
              const rn = runs[i]; if (!rn.rect) break;
              const y = runYMid(rn);
              if (y < yMin || y > yMax) break;
              maxEnd = rn.charStart + rn.glyphs.length - 1;
            }
            geoStart = Math.max(geoStart, minStart);
            geoEnd = Math.min(geoEnd, maxEnd);
          }
        }
        return drawCitationHighlight(refs, r, docMgr, scroll, targetPageIndex, geoStart, geoEnd, g);
      });
    });
  }).catch(() => false);
}


// Scroll to the page, clear the old, then highlight the text.
export function doHighlightSearch(
  refs: HighlightRefs, reg: unknown, page: number, text: string,
) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const r = reg as any;
  const scroll = r.getPlugin?.("scroll")?.provides?.();
  scroll?.scrollToPage?.({ pageNumber: page, behavior: "instant" });

  const engine = r.getEngine?.();
  const docMgr = r.getPlugin?.("document-manager")?.provides?.();
  if (!engine || !docMgr) return;

  const doc = docMgr.getActiveDocument?.();
  if (!doc) return;

  // Clear the previous highlight (and any stray selection) before a new one.
  clearCitationHighlight(refs, r);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const selCap = r.getPlugin?.("selection")?.provides?.() as any;
  const activeDocId = docMgr.getActiveDocumentId?.();
  try { selCap?.clear?.(activeDocId); } catch { /* ignore */ }

  if (!text?.trim()) return;

  const pageIndex = page - 1;

  // Only the named page, otherwise the highlight lands on the wrong one.
  tryHighlightOnPage(refs, r, doc, engine, docMgr, scroll, pageIndex, text);
}
