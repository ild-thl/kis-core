"""PPTX-Verarbeitung: Text-Extraktion, AutoFit-Workaround, PPTX→PNG via LibreOffice."""

import os
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from loguru import logger
from PIL import ImageFont
from pptx import Presentation
from pptx.oxml.ns import qn

from src.limits import RENDER_MAX_WORKERS
from src.utils.pptx_text import (
    iter_linked_text_nodes,
    iter_slide_paragraphs,
    iter_visible_slides,
)

EMU_PER_PT = 12700
_DEFAULT_TEXT_INSET_EMU = 91440  # OOXML default lIns/rIns when the bodyPr omits them


def extract_text_per_slide(source: bytes | str | Path) -> list[str]:
    """Text per visible slide, hidden ones stay out."""
    prs = Presentation(BytesIO(source) if isinstance(source, bytes) else source)
    slide_texts: list[str] = []
    for slide in iter_visible_slides(prs):
        texts: list[str] = []
        for paragraph in iter_slide_paragraphs(slide):
            text = paragraph.text.strip()
            if text:
                texts.append(text)
        # SmartArt and charts keep their text outside the slide XML.
        for node in iter_linked_text_nodes(slide):
            text = (node.text or "").strip()
            if text:
                texts.append(text)
        slide_texts.append("\n".join(texts))
    return slide_texts


def extract_notes_per_slide(source: bytes | str | Path) -> list[str]:
    """Speaker notes per visible slide, empty where a slide has none."""
    prs = Presentation(BytesIO(source) if isinstance(source, bytes) else source)
    notizen: list[str] = []
    for slide in iter_visible_slides(prs):
        rahmen = slide.notes_slide.notes_text_frame if slide.has_notes_slide else None
        zeilen = [p.text.strip() for p in rahmen.paragraphs] if rahmen is not None else []
        notizen.append("\n".join(z for z in zeilen if z))
    return notizen


def soffice_profile_dir() -> Path:
    """Its own LibreOffice profile per process and thread, otherwise a conversion fails."""
    key = f"{os.getpid()}-{threading.get_ident()}"
    return Path(tempfile.gettempdir()) / "askf-lo-profiles" / key


def build_soffice_cmd(pptx_path: Path, output_dir: Path) -> list[str]:
    """The LibreOffice call for PPTX to PDF, without hidden slides."""
    profile = soffice_profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    pdf_filter = (
        'pdf:impress_pdf_Export:'
        '{"ExportHiddenSlides":{"type":"boolean","value":"false"}}'
    )
    return [
        "libreoffice", "--headless", "--norestore",
        f"-env:UserInstallation=file://{profile}",
        "--convert-to", pdf_filter,
        "--outdir", str(output_dir), str(pptx_path),
    ]


def _fix_broken_linebreak_runs(prs: Presentation) -> bool:
    """Some AI slide generators leave a bare '\\n' as its own run with an empty
    <a:rPr/> instead of <a:br/> - LibreOffice then renders it in a fallback
    font/size, pushing the following text onto a wrongly styled line."""
    changed = False
    for slide in prs.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for paragraph in shape.text_frame.paragraphs:
                p = paragraph._p
                runs = p.findall(qn('a:r'))
                for i, r in enumerate(runs):
                    t = r.find(qn('a:t'))
                    if t is None or t.text is None or t.text.strip('\n') or '\n' not in t.text:
                        continue
                    donor_rpr = None
                    for donor in (runs[i - 1] if i > 0 else None, runs[i + 1] if i + 1 < len(runs) else None):
                        if donor is None:
                            continue
                        donor_pr = donor.find(qn('a:rPr'))
                        if donor_pr is not None:
                            donor_rpr = donor_pr
                            break
                    for _ in range(t.text.count('\n')):
                        br = p.makeelement(qn('a:br'), {})
                        if donor_rpr is not None:
                            br.append(deepcopy(donor_rpr))
                        r.addprevious(br)
                    p.remove(r)
                    changed = True
    return changed


def _fix_tight_line_spacing(prs: Presentation, min_ratio: float = 1.2, min_pct: int = 100000) -> bool:
    """Some AI slide generators write a line height that is too small for the
    paragraph's own font size - either a fixed <a:spcPts> smaller than the
    font, or a <a:spcPct> below single-line spacing (100000 = 100%). Either
    way, multi-line text then overlaps itself, in any renderer."""
    changed = False
    for slide in prs.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for paragraph in shape.text_frame.paragraphs:
                p = paragraph._p
                p_pr = p.find(qn('a:pPr'))
                if p_pr is None:
                    continue
                ln_spc = p_pr.find(qn('a:lnSpc'))
                if ln_spc is None:
                    continue

                # Default 1800 (18pt) mirrors the fallback already used for
                # the sz-shrink above - a run without an explicit size (or
                # without an <a:rPr> at all) still needs to count towards the
                # paragraph's tallest line.
                sizes = []
                for r in p.findall(qn('a:r')):
                    r_pr = r.find(qn('a:rPr'))
                    sz = r_pr.get('sz') if r_pr is not None else None
                    sizes.append(int(sz) if sz else 1800)
                def_r_pr = p_pr.find(qn('a:defRPr'))
                if def_r_pr is not None and def_r_pr.get('sz'):
                    sizes.append(int(def_r_pr.get('sz')))
                if not sizes:
                    continue
                max_sz = max(sizes)

                spc_pts = ln_spc.find(qn('a:spcPts'))
                if spc_pts is not None:
                    val = int(spc_pts.get('val'))
                    if val < max_sz:
                        spc_pts.set('val', str(int(max_sz * min_ratio)))
                        changed = True
                    continue

                spc_pct = ln_spc.find(qn('a:spcPct'))
                if spc_pct is not None and int(spc_pct.get('val')) < min_pct:
                    spc_pct.set('val', str(min_pct))
                    changed = True
    return changed


@lru_cache(maxsize=64)
def _resolve_font_path(typeface: str) -> str:
    """Ask fontconfig which file LibreOffice would actually substitute for
    this typeface - the same resolution LibreOffice itself uses, so a
    measurement made with it matches what will really be rendered."""
    result = subprocess.run(
        ["fc-match", "-f", "%{file}", typeface],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout.strip()


@lru_cache(maxsize=256)
def _load_font(typeface: str, size_pt: int):
    return ImageFont.truetype(_resolve_font_path(typeface), max(size_pt, 1))


def _paragraph_line_count(p, max_width_pt: float) -> int:
    """Greedy word-wrap simulation across the paragraph's runs and explicit
    <a:br/> breaks, using the real installed fonts - an approximation of
    LibreOffice's own line breaking, close enough to catch real overflow."""
    lines = 1
    current_width = 0.0
    for child in p:
        if child.tag == qn('a:br'):
            lines += 1
            current_width = 0.0
            continue
        if child.tag != qn('a:r'):
            continue
        r_pr = child.find(qn('a:rPr'))
        sz = int(r_pr.get('sz')) if r_pr is not None and r_pr.get('sz') else 1800
        latin = r_pr.find(qn('a:latin')) if r_pr is not None else None
        typeface = latin.get('typeface') if latin is not None else 'Calibri'
        font = _load_font(typeface, round(sz / 100))
        t_el = child.find(qn('a:t'))
        text = t_el.text if t_el is not None and t_el.text else ''
        for word in text.split(' '):
            if not word:
                continue
            word_width = font.getlength(word)
            space_width = font.getlength(' ') if current_width > 0 else 0.0
            if current_width > 0 and current_width + space_width + word_width > max_width_pt:
                lines += 1
                current_width = word_width
            else:
                current_width += space_width + word_width
    return lines


def _paragraph_line_height_pt(p, max_run_sz: int) -> float:
    p_pr = p.find(qn('a:pPr'))
    ln_spc = p_pr.find(qn('a:lnSpc')) if p_pr is not None else None
    if ln_spc is not None:
        spc_pts = ln_spc.find(qn('a:spcPts'))
        if spc_pts is not None:
            return int(spc_pts.get('val')) / 100
        spc_pct = ln_spc.find(qn('a:spcPct'))
        if spc_pct is not None:
            return max_run_sz / 100 * (int(spc_pct.get('val')) / 100000)
    return max_run_sz / 100 * 1.2


def _shape_required_height_pt(tf, width_pt: float) -> float:
    total = 0.0
    for paragraph in tf.paragraphs:
        p = paragraph._p
        sizes = [
            int(r_pr.get('sz')) if r_pr is not None and r_pr.get('sz') else 1800
            for r_pr in (r.find(qn('a:rPr')) for r in p.findall(qn('a:r')))
        ]
        if not sizes:
            continue
        lines = _paragraph_line_count(p, width_pt)
        total += lines * _paragraph_line_height_pt(p, max(sizes))
    return total


def _fix_overflowing_spautofit_text(prs: Presentation, tolerance: float = 1.05, min_ratio: float = 0.5) -> bool:
    """spAutoFit trusts that the authored box already fits its text - true
    when the deck was authored against the same fonts we render with. When
    our installed fonts measure a bit wider than whatever authored the deck,
    the same text wraps onto more lines than the box was sized for and spills
    into whatever sits below it on the slide. Only shrink shapes where that
    is actually measured to happen, never as a blanket guess."""
    changed = False
    for slide in prs.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            tf = shape.text_frame
            body_pr = tf._txBody.find(qn('a:bodyPr'))
            if body_pr is None or body_pr.find(qn('a:spAutoFit')) is None:
                continue
            if body_pr.get('wrap') == 'none':
                continue
            width_emu, height_emu = shape.width, shape.height
            if not width_emu or not height_emu:
                continue
            l_ins = int(body_pr.get('lIns', _DEFAULT_TEXT_INSET_EMU))
            r_ins = int(body_pr.get('rIns', _DEFAULT_TEXT_INSET_EMU))
            width_pt = (width_emu - l_ins - r_ins) / EMU_PER_PT
            if width_pt <= 0:
                continue
            height_pt = height_emu / EMU_PER_PT

            try:
                required_pt = _shape_required_height_pt(tf, width_pt)
            except OSError as exc:
                logger.warning("Ueberlauf-Pruefung uebersprungen (Font nicht ladbar): {}", exc)
                continue
            if required_pt <= height_pt * tolerance:
                continue

            ratio = max(height_pt / required_pt, min_ratio)
            for r_pr in tf._txBody.iter(qn('a:rPr')):
                sz = r_pr.get('sz')
                base = int(sz) if sz else 1800
                r_pr.set('sz', str(max(int(base * ratio), 600)))
            for p_pr in tf._txBody.iter(qn('a:pPr')):
                ln_spc = p_pr.find(qn('a:lnSpc'))
                spc_pts = ln_spc.find(qn('a:spcPts')) if ln_spc is not None else None
                if spc_pts is not None:
                    spc_pts.set('val', str(max(int(int(spc_pts.get('val')) * ratio), 600)))
            changed = True
            logger.info(
                "spAutoFit-Ueberlauf korrigiert: benoetigt={:.1f}pt vorhanden={:.1f}pt ratio={:.2f}",
                required_pt, height_pt, ratio,
            )
    return changed


def _apply_autofit_for_rendering(pptx_path: Path) -> Path:
    """A temp copy with normAutofit text shrunk by 20 percent and genuinely
    overflowing spAutoFit text shrunk just enough to fit, the original stays."""
    prs = Presentation(str(pptx_path))
    linebreaks_fixed = _fix_broken_linebreak_runs(prs)
    line_spacing_fixed = _fix_tight_line_spacing(prs)
    changed = False
    for slide in prs.slides:
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            tf = shape.text_frame
            body_pr = tf._txBody.find(qn('a:bodyPr'))
            if body_pr is None:
                continue
            # spAutoFit means the shape already grew to fit this text at its
            # authored size - shrinking the font here only wastes space and,
            # worse, changes where lines wrap versus the design. Only
            # normAutofit (fixed box, text must shrink to fit) needs a fit
            # correction for LibreOffice.
            if body_pr.find(qn('a:normAutofit')) is None:
                continue
            # Work directly on XML - shrink sz on all <a:rPr> elements
            for r_pr in tf._txBody.iter(qn('a:rPr')):
                sz = r_pr.get('sz')
                if sz:
                    r_pr.set('sz', str(int(int(sz) * 0.80)))
                else:
                    # No explicit size - set one based on default 1800 (18pt)
                    r_pr.set('sz', str(int(1800 * 0.80)))
                changed = True
            # Also shrink defRPr inside <a:pPr> (paragraph-level default)
            for p_pr in tf._txBody.iter(qn('a:pPr')):
                def_r_pr = p_pr.find(qn('a:defRPr'))
                if def_r_pr is not None:
                    sz = def_r_pr.get('sz')
                    if sz:
                        def_r_pr.set('sz', str(int(int(sz) * 0.80)))
                        changed = True

    overflow_fixed = _fix_overflowing_spautofit_text(prs)

    render_path = pptx_path.parent / f"_render_{pptx_path.name}"
    prs.save(str(render_path))
    logger.info(
        "AutoFit XML-level applied: changed={}, linebreaks_fixed={}, line_spacing_fixed={}, overflow_fixed={}",
        changed, linebreaks_fixed, line_spacing_fixed, overflow_fixed,
    )
    return render_path


def pptx_to_images(pptx_path: Path, output_dir: Path, dpi: int = 100) -> list[Path]:
    """Convert PPTX slides to PNG images using LibreOffice."""
    # Reads the real slide dimensions so the aspect ratio is right.
    prs = Presentation(str(pptx_path))
    slide_width = prs.slide_width   # EMU (1 cm = 360000 EMU)
    slide_height = prs.slide_height
    width_cm = slide_width / 360000
    height_cm = slide_height / 360000
    slide_ratio = slide_width / slide_height
    logger.info("PPTX slide size: {:.2f}x{:.2f} cm (ratio {:.4f})", width_cm, height_cm, slide_ratio)

    render_pptx = _apply_autofit_for_rendering(pptx_path)

    try:
        cmd = build_soffice_cmd(render_pptx, output_dir)
        logger.info("Converting PPTX to PDF: {}", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    finally:
        # Clear the copy away, otherwise the folder stays behind after pre-rendering.
        render_pptx.unlink(missing_ok=True)

    pdf_path = output_dir / f"{render_pptx.stem}.pdf"
    if not pdf_path.exists():
        # PDF was not created - this is a real failure regardless of exit code
        logger.error("LibreOffice conversion failed (rc={}): {}", result.returncode, result.stderr[:300])
        raise RuntimeError(f"LibreOffice Konvertierung fehlgeschlagen: {result.stderr[:200]}")
    if result.returncode != 0:
        # PDF exists despite non-zero exit - treat javaldx / Java warnings as non-fatal
        logger.warning("LibreOffice exited with rc={} but PDF was created (non-fatal): {}", result.returncode, result.stderr[:200])

    # Get page count via pdfinfo
    pdfinfo_result = subprocess.run(
        ["pdfinfo", str(pdf_path)], capture_output=True, text=True, timeout=30
    )
    page_count = 1
    for line in pdfinfo_result.stdout.splitlines():
        if line.startswith("Pages:"):
            page_count = int(line.split(":")[1].strip())
            break
    logger.info("PDF has {} pages, rendering in parallel", page_count)

    # Convert PDF pages to PNG in parallel - one pdftoppm process per page.
    slide_prefix = str(output_dir / "slide")

    def _render_page(page: int) -> None:
        cmd = [
            "pdftoppm", "-png", "-r", str(dpi),
            "-f", str(page), "-l", str(page),
            str(pdf_path), slide_prefix,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"Seite {page} fehlgeschlagen: {result.stderr[:200]}")

    try:
        with ThreadPoolExecutor(max_workers=RENDER_MAX_WORKERS) as executor:
            futures = {executor.submit(_render_page, p): p for p in range(1, page_count + 1)}
            for future in as_completed(futures):
                future.result()  # re-raises on error
    finally:
        pdf_path.unlink(missing_ok=True)  # intermediate step, the PNGs are the result

    # Collect generated images (pdftoppm names them slide-1.png, slide-2.png, ...)
    images = sorted(output_dir.glob("slide-*.png"))
    if not images:
        raise RuntimeError("Keine Slide-Bilder erstellt")

    return images
