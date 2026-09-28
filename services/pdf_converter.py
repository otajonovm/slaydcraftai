import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, inch
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepInFrame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)

from services.pptx_generator import CONTENT_BOTTOM, CONTENT_W, MARGIN_X, SLIDE_H, SLIDE_W, Theme, get_theme
from services.schemas import PresentationContent, ReferatContent, ReferatMeta, Slide, chapter_label, labels

logger = logging.getLogger(__name__)

LIBREOFFICE_TIMEOUT = 180

# ------------------------------------------------------------------ LibreOffice


def find_libreoffice(configured: str = "") -> str | None:
    candidates = [configured] if configured else []
    candidates += [shutil.which("soffice"), shutil.which("libreoffice")]
    if os.name == "nt":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
            if root:
                candidates.append(str(Path(root) / "LibreOffice" / "program" / "soffice.exe"))
    else:
        candidates += ["/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice",
                       "/Applications/LibreOffice.app/Contents/MacOS/soffice"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _libreoffice_convert(binary: str, source: Path) -> Path | None:
    out_dir = source.parent
    with tempfile.TemporaryDirectory(prefix="lo_profile_") as profile:
        cmd = [
            binary,
            f"-env:UserInstallation={Path(profile).as_uri()}",
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(source),
        ]
        try:
            subprocess.run(cmd, check=True, timeout=LIBREOFFICE_TIMEOUT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("LibreOffice conversion failed for %s: %r", source.name, exc)
            return None
    result = source.with_suffix(".pdf")
    return result if result.is_file() and result.stat().st_size > 0 else None


# ------------------------------------------------------------------ fonts

_FONT_FILES = {
    "SC-Serif": ["times.ttf", "LiberationSerif-Regular.ttf", "DejaVuSerif.ttf", "PTSerif-Regular.ttf"],
    "SC-Serif-Bold": ["timesbd.ttf", "LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf", "PTSerif-Bold.ttf"],
    "SC-Serif-Italic": ["timesi.ttf", "LiberationSerif-Italic.ttf", "DejaVuSerif-Italic.ttf", "PTSerif-Italic.ttf"],
    "SC-Serif-BoldItalic": ["timesbi.ttf", "LiberationSerif-BoldItalic.ttf", "DejaVuSerif-BoldItalic.ttf"],
    "SC-Sans": ["segoeui.ttf", "arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"],
    "SC-Sans-Bold": ["segoeuib.ttf", "arialbd.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "SC-Sans-Italic": ["segoeuii.ttf", "ariali.ttf", "LiberationSans-Italic.ttf", "DejaVuSans-Oblique.ttf"],
    "SC-Sans-BoldItalic": ["segoeuiz.ttf", "arialbi.ttf", "LiberationSans-BoldItalic.ttf", "DejaVuSans-BoldOblique.ttf"],
}
_BUILTIN = {
    "SC-Serif": "Times-Roman", "SC-Serif-Bold": "Times-Bold", "SC-Serif-Italic": "Times-Italic",
    "SC-Serif-BoldItalic": "Times-BoldItalic", "SC-Sans": "Helvetica", "SC-Sans-Bold": "Helvetica-Bold",
    "SC-Sans-Italic": "Helvetica-Oblique", "SC-Sans-BoldItalic": "Helvetica-BoldOblique",
}


def _font_dirs() -> list[Path]:
    dirs = [Path(__file__).resolve().parent.parent / "assets" / "fonts"]
    if os.name == "nt":
        dirs.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
             Path.home() / ".local/share/fonts", Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
    return [d for d in dirs if d.is_dir()]


@lru_cache(maxsize=1)
def _fonts() -> dict[str, str]:
    index: dict[str, Path] = {}
    for directory in _font_dirs():
        for path in directory.rglob("*.tt[fc]"):
            index.setdefault(path.name.lower(), path)

    resolved: dict[str, str] = {}
    for alias, files in _FONT_FILES.items():
        resolved[alias] = _BUILTIN[alias]
        for name in files:
            path = index.get(name.lower())
            if not path:
                continue
            try:
                pdfmetrics.registerFont(TTFont(alias, str(path)))
                resolved[alias] = alias
                break
            except Exception:
                logger.debug("Cannot register font %s", path, exc_info=True)

    for family in ("SC-Serif", "SC-Sans"):
        if resolved[family] == family:
            pdfmetrics.registerFontFamily(
                family,
                normal=resolved[family],
                bold=resolved[f"{family}-Bold"],
                italic=resolved[f"{family}-Italic"],
                boldItalic=resolved[f"{family}-BoldItalic"],
            )
    return resolved


# ------------------------------------------------------------ slides -> PDF


def _fit(text: str, font: str, size: float, width: float, height: float, leading: float, min_size: float):
    while True:
        lines: list[str] = []
        for part in text.split("\n"):
            lines.extend(simpleSplit(part, font, size, width) or [""])
        if len(lines) * size * leading <= height or size <= min_size:
            return lines, size
        size -= 0.5


class _SlidePdf:
    def __init__(self, c: rl_canvas.Canvas, theme: Theme) -> None:
        self.c = c
        self.t = theme
        f = _fonts()
        self.regular, self.bold, self.italic = f["SC-Sans"], f["SC-Sans-Bold"], f["SC-Sans-Italic"]

    def _y(self, y: float, h: float) -> float:
        return (SLIDE_H - y - h) * inch

    def rect(self, x, y, w, h, color, *, radius=0.0, alpha=1.0, stroke: str | None = None, oval=False):
        c = self.c
        c.saveState()
        c.setFillColor(HexColor("#" + color))
        c.setFillAlpha(alpha)
        if stroke:
            c.setStrokeColor(HexColor("#" + stroke))
            c.setLineWidth(1)
        args = (x * inch, self._y(y, h), w * inch, h * inch)
        if oval:
            c.ellipse(args[0], args[1], args[0] + args[2], args[1] + args[3], stroke=int(bool(stroke)), fill=1)
        elif radius:
            c.roundRect(*args, radius * inch, stroke=int(bool(stroke)), fill=1)
        else:
            c.rect(*args, stroke=int(bool(stroke)), fill=1)
        c.restoreState()

    def text(self, x, y, w, h, text, *, size, color, font=None, align="left", valign="top",
             leading=1.2, min_size=9):
        font = font or self.regular
        lines, size = _fit(text, font, size, w * inch, h * inch, leading, min_size)
        line_h = size * leading
        block_h = len(lines) * line_h
        top = (SLIDE_H - y) * inch
        if valign == "middle":
            top -= max(0.0, (h * inch - block_h) / 2)
        elif valign == "bottom":
            top -= max(0.0, h * inch - block_h)
        c = self.c
        c.setFillColor(HexColor("#" + color))
        c.setFont(font, size)
        baseline = top - size
        for line in lines:
            if align == "center":
                c.drawCentredString((x + w / 2) * inch, baseline, line)
            elif align == "right":
                c.drawRightString((x + w) * inch, baseline, line)
            else:
                c.drawString(x * inch, baseline, line)
            baseline -= line_h

    def badge(self, x, y, d, label, color, text_color, size):
        self.rect(x, y, d, d, color, oval=True)
        self.c.setFillColor(HexColor("#" + text_color))
        self.c.setFont(self.bold, size)
        self.c.drawCentredString((x + d / 2) * inch, self._y(y, d) + d * inch / 2 - size * 0.35, label)

    def check(self, x, y, d, color, mark_color):
        self.rect(x, y, d, d, color, oval=True)
        c = self.c
        c.saveState()
        c.setStrokeColor(HexColor("#" + mark_color))
        c.setLineWidth(d * inch * 0.1)
        c.setLineCap(1)
        c.setLineJoin(1)
        bx, by, s = x * inch, self._y(y, d), d * inch
        path = c.beginPath()
        path.moveTo(bx + s * 0.28, by + s * 0.50)
        path.lineTo(bx + s * 0.44, by + s * 0.34)
        path.lineTo(bx + s * 0.73, by + s * 0.66)
        c.drawPath(path, stroke=1, fill=0)
        c.restoreState()


class _PresentationPdfRenderer:
    def __init__(self, content: PresentationContent, theme_key: str, watermark: str | None = None) -> None:
        self.content = content
        self.watermark = watermark
        self.t = get_theme(theme_key)
        self.l = labels(content.language)
        self.total = len(content.slides)

    def render(self, output: Path) -> Path:
        c = rl_canvas.Canvas(str(output), pagesize=(SLIDE_W * inch, SLIDE_H * inch))
        c.setTitle(self.content.presentation_title)
        c.setAuthor("SlideCraft AI")
        pdf = _SlidePdf(c, self.t)
        renderers = {
            "title": self._title, "bullet_points": self._bullets, "comparison": self._comparison,
            "quote": self._quote, "summary": self._summary,
        }
        for index, slide in enumerate(self.content.slides, start=1):
            renderers.get(slide.layout_type, self._bullets)(pdf, slide, index)
            c.showPage()
        c.save()
        return output

    def _footer(self, p: _SlidePdf, index: int, color: str) -> None:
        if self.watermark and index == self.total:
            p.rect(MARGIN_X, 6.9, 6.6, 0.44, self.t.accent, radius=0.22)
            p.text(MARGIN_X + 0.2, 6.9, 6.2, 0.44, self.watermark, size=12, color=self.t.on_accent,
                   font=p.bold, align="center", valign="middle", min_size=8)
        else:
            p.text(MARGIN_X, 6.98, 8.5, 0.3, self.content.presentation_title, size=10, color=color, min_size=10)
        p.text(SLIDE_W - MARGIN_X - 1.6, 6.98, 1.6, 0.3, f"{index:02d} / {self.total:02d}",
               size=10, color=color, font=p.bold, align="right")

    def _frame(self, p: _SlidePdf, s: Slide, index: int) -> float:
        t = self.t
        p.rect(0, 0, SLIDE_W, SLIDE_H, t.bg)
        p.rect(0, 0, 0.16, SLIDE_H, t.accent)
        p.rect(SLIDE_W - 1.9, -0.9, 2.6, 2.6, t.accent2, oval=True, alpha=0.14)
        p.rect(SLIDE_W - 1.05, 0.55, 0.32, 0.32, t.accent, oval=True, alpha=0.6)
        p.text(MARGIN_X, 0.42, CONTENT_W - 1.4, 0.95, s.title, size=30, color=t.title, font=p.bold,
               valign="middle", leading=1.05, min_size=18)
        p.rect(MARGIN_X, 1.42, 1.1, 0.07, t.accent)
        top = 1.8
        if s.subtitle:
            p.text(MARGIN_X, 1.6, CONTENT_W, 0.45, s.subtitle, size=16, color=t.muted, valign="middle", min_size=11)
            top = 2.25
        self._footer(p, index, t.muted)
        return top

    def _dark(self, p: _SlidePdf) -> None:
        t = self.t
        p.rect(0, 0, SLIDE_W, SLIDE_H, t.dark)
        p.rect(8.7, -1.9, 6.8, 6.8, t.accent, oval=True, alpha=0.22)
        p.rect(10.7, 3.9, 4.3, 4.3, t.accent2, oval=True, alpha=0.25)
        p.rect(9.35, 5.25, 0.36, 0.36, t.accent2, oval=True)
        p.rect(0, 0, SLIDE_W, 0.12, t.accent)

    def _title(self, p: _SlidePdf, s: Slide, index: int) -> None:
        t = self.t
        self._dark(p)
        chip = self.l["presentation"]
        chip_w = max(2.0, 0.16 * len(chip) + 0.9)
        p.rect(MARGIN_X, 1.25, chip_w, 0.48, t.accent, radius=0.24)
        p.text(MARGIN_X, 1.25, chip_w, 0.48, chip, size=12, color=t.on_accent, font=p.bold, align="center", valign="middle")
        title = s.title or self.content.presentation_title
        p.text(MARGIN_X, 1.95, 8.1, 2.7, title, size=48, color=t.on_dark, font=p.bold, valign="bottom",
               leading=1.05, min_size=24)
        p.rect(MARGIN_X, 4.85, 1.5, 0.08, t.accent)
        subtitle = s.subtitle or (s.bullet_points[0] if s.bullet_points else "")
        if subtitle:
            p.text(MARGIN_X, 5.1, 8.1, 1.2, subtitle, size=20, color=t.on_dark_muted, min_size=13)

    def _bullets(self, p: _SlidePdf, s: Slide, index: int) -> None:
        t = self.t
        top = self._frame(p, s, index)
        items = s.bullet_points[:6] or [s.subtitle or s.title]
        n = len(items)
        cols, rows = (n, 1) if n <= 3 else (2, 2) if n == 4 else (3, 2)
        gap = 0.3
        card_w = (CONTENT_W - gap * (cols - 1)) / cols
        card_h = (CONTENT_BOTTOM - top - gap * (rows - 1)) / rows
        for i, item in enumerate(items):
            r, col = divmod(i, cols)
            x = MARGIN_X + col * (card_w + gap)
            y = top + r * (card_h + gap)
            p.rect(x, y, card_w, card_h, t.surface, radius=0.18, stroke=t.border)
            if rows == 1:
                p.rect(x, y + 0.35, 0.07, 0.75, t.accent)
                p.badge(x + 0.4, y + 0.35, 0.75, f"{i + 1:02d}", t.accent, t.on_accent, 16)
                p.text(x + 0.4, y + 1.4, card_w - 0.8, card_h - 1.7, item, size=22 if cols < 3 else 19,
                       color=t.text, min_size=12)
            else:
                p.badge(x + 0.3, y + card_h / 2 - 0.31, 0.62, str(i + 1), t.accent, t.on_accent, 15)
                p.text(x + 1.15, y + 0.25, card_w - 1.4, card_h - 0.5, item, size=18 if cols == 2 else 16,
                       color=t.text, valign="middle", min_size=11)

    def _comparison(self, p: _SlidePdf, s: Slide, index: int) -> None:
        t = self.t
        top = self._frame(p, s, index)
        gap, header_h = 0.6, 0.75
        col_w = (CONTENT_W - gap) / 2
        for col, (heading, points, color) in enumerate(
            ((s.left_title, s.left_points, t.accent), (s.right_title, s.right_points, t.accent2))
        ):
            x = MARGIN_X + col * (col_w + gap)
            p.rect(x, top, col_w, CONTENT_BOTTOM - top, t.surface, radius=0.18, stroke=t.border)
            p.rect(x, top, col_w, header_h, color, radius=0.18)
            p.text(x + 0.2, top, col_w - 0.4, header_h, heading or ("A" if col == 0 else "B"), size=20,
                   color=t.on_accent, font=p.bold, align="center", valign="middle", min_size=12)
            y = top + header_h + 0.35
            avail = CONTENT_BOTTOM - y - 0.25
            per = avail / max(len(points), 1)
            for point in points:
                p.rect(x + 0.4, y + 0.12, 0.13, 0.13, color)
                p.text(x + 0.7, y, col_w - 1.1, per - 0.1, point, size=17, color=t.text, min_size=10)
                y += per
        p.badge(SLIDE_W / 2 - 0.42, top + header_h / 2 - 0.37, 0.84, "VS", t.title, t.bg, 14)

    def _quote(self, p: _SlidePdf, s: Slide, index: int) -> None:
        t = self.t
        p.rect(0, 0, SLIDE_W, SLIDE_H, t.bg)
        p.rect(0, 0, 0.16, SLIDE_H, t.accent)
        p.rect(-1.2, 5.2, 3.2, 3.2, t.accent2, oval=True, alpha=0.15)
        p.rect(SLIDE_W - 2.0, -1.0, 3.0, 3.0, t.accent, oval=True, alpha=0.12)
        p.text(MARGIN_X, 0.45, CONTENT_W, 0.7, s.title, size=22, color=t.muted, font=p.bold, valign="middle")
        x, y, w, h = 1.3, 1.45, SLIDE_W - 2.6, 4.85
        p.rect(x, y, w, h, t.surface, radius=0.25, stroke=t.border)
        p.rect(x, y + 0.6, 0.1, h - 1.2, t.accent)
        p.text(x + 0.5, y - 0.1, 1.6, 1.6, "\u201C", size=110, color=t.accent, font=p.bold, leading=1.0)
        p.text(x + 1.0, y + 0.85, w - 2.0, h - 2.0, s.quote or s.subtitle, size=30, color=t.title,
               font=p.italic, align="center", valign="middle", min_size=14)
        if s.quote_author:
            p.text(x + 1.0, y + h - 1.0, w - 2.0, 0.5, f"— {s.quote_author}", size=18, color=t.accent,
                   font=p.bold, align="center", valign="middle")
        self._footer(p, index, t.muted)

    def _summary(self, p: _SlidePdf, s: Slide, index: int) -> None:
        t = self.t
        self._dark(p)
        title = s.title or self.l["summary"]
        p.text(MARGIN_X, 0.5, 7.6, 1.0, title, size=36, color=t.on_dark, font=p.bold, valign="middle", min_size=20)
        p.rect(MARGIN_X, 1.55, 1.3, 0.08, t.accent)
        items = (s.bullet_points or [s.subtitle or title])[:5]
        gap = 0.18
        row_h = min(1.15, (4.65 - gap * (len(items) - 1)) / len(items))
        for i, item in enumerate(items):
            y = 1.95 + i * (row_h + gap)
            p.rect(MARGIN_X, y, 7.5, row_h, t.on_dark, radius=0.2, alpha=0.08)
            p.check(MARGIN_X + 0.25, y + row_h / 2 - 0.25, 0.5, t.accent, t.on_accent)
            p.text(MARGIN_X + 1.0, y + 0.08, 6.3, row_h - 0.16, item, size=18, color=t.on_dark,
                   valign="middle", min_size=10)
        p.rect(8.95, 1.95, 3.6, 4.65, t.accent, radius=0.3)
        p.text(9.25, 2.35, 3.0, 2.4, self.l["thanks"], size=26, color=t.on_accent, font=p.bold,
               align="center", valign="middle", min_size=14)
        p.rect(10.35, 4.85, 0.8, 0.06, t.on_accent)
        p.text(9.25, 5.05, 3.0, 1.1, self.l["questions"], size=18, color=t.on_accent, align="center", valign="middle")
        self._footer(p, index, t.on_dark_muted)


# ------------------------------------------------------------ referat -> PDF


def _render_referat_pdf(
    content: ReferatContent, meta: ReferatMeta, output: Path, watermark: str | None = None
) -> Path:
    f = _fonts()
    serif, bold = f["SC-Serif"], f["SC-Serif-Bold"]
    l = labels(meta.language)

    body = ParagraphStyle("body", fontName=serif, fontSize=14, leading=21, alignment=TA_JUSTIFY, firstLineIndent=1.25 * cm)
    h1 = ParagraphStyle("h1", fontName=bold, fontSize=16, leading=24, alignment=TA_CENTER, spaceAfter=12)
    h2 = ParagraphStyle("h2", fontName=bold, fontSize=16, leading=24, alignment=TA_LEFT, firstLineIndent=1.25 * cm,
                        spaceBefore=12, spaceAfter=12)
    center = ParagraphStyle("center", fontName=bold, fontSize=14, leading=17, alignment=TA_CENTER)
    toc = ParagraphStyle("toc", fontName=serif, fontSize=14, leading=21, alignment=TA_LEFT, spaceAfter=2)
    ref = ParagraphStyle("ref", parent=body, firstLineIndent=-0.75 * cm, leftIndent=0.75 * cm)
    sign = ParagraphStyle("sign", fontName=serif, fontSize=14, leading=20, leftIndent=9 * cm)

    def para(text: str, style: ParagraphStyle) -> Paragraph:
        return Paragraph(escape(text), style)

    def on_title(c, doc) -> None:
        c.saveState()
        c.setFont(bold, 14)
        c.drawCentredString(A4[0] / 2, 1.3 * cm, f"{meta.city} – {meta.year}")
        c.restoreState()

    def on_body(c, doc) -> None:
        c.saveState()
        c.setFont(serif, 12)
        c.drawCentredString(A4[0] / 2, 1.0 * cm, str(doc.page))
        c.restoreState()

    doc = BaseDocTemplate(
        str(output), pagesize=A4, leftMargin=3 * cm, rightMargin=1.5 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
        title=content.title, author=meta.student or "SlideCraft AI",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, leftPadding=0, rightPadding=0,
                  topPadding=0, bottomPadding=0)
    doc.addPageTemplates([
        PageTemplate(id="title", frames=[frame], onPage=on_title),
        PageTemplate(id="body", frames=[frame], onPage=on_body),
    ])

    ministry = l["ministry"].get(meta.institution_type, l["ministry"]["otm"])
    blank = "_" * 14
    title_flow = [para(ministry, center), Spacer(1, 6)]
    if meta.institution:
        title_flow.append(para(meta.institution.upper(), center))
    title_flow += [
        Spacer(1, 150),
        para(l["work"].get(meta.work_type, l["work"]["referat"]),
             ParagraphStyle("work", fontName=bold, fontSize=28, leading=34, alignment=TA_CENTER)),
        Spacer(1, 18),
        para(l["topic"], ParagraphStyle("tl", fontName=f["SC-Serif-BoldItalic"], fontSize=16, leading=20, alignment=TA_CENTER)),
        Spacer(1, 4),
        para(content.title.upper(), ParagraphStyle("topic", fontName=bold, fontSize=20 if len(content.title) <= 60 else 17,
                                                   leading=25, alignment=TA_CENTER)),
        Spacer(1, 140),
        para(f"{l['done_by']} {meta.student or blank}", sign),
        Spacer(1, 8),
        para(f"{l['checked_by']} {meta.teacher or blank}", sign),
    ]
    story: list = [KeepInFrame(doc.width, doc.height - 1.5 * cm, title_flow, mode="shrink"),
                   NextPageTemplate("body"), PageBreak()]

    story.append(para(l["contents"], h1))
    story.append(para(l["intro"].capitalize(), ParagraphStyle("t0", parent=toc, fontName=bold)))
    for ci, chapter in enumerate(content.chapters):
        story.append(para(f"{chapter_label(meta.language, ci)} {chapter.title}", ParagraphStyle("t1", parent=toc, fontName=bold)))
        for si, section in enumerate(chapter.sections):
            story.append(para(f"{ci + 1}.{si + 1}. {section.title}", ParagraphStyle("t2", parent=toc, leftIndent=1 * cm)))
    story.append(para(l["conclusion"].capitalize(), ParagraphStyle("t3", parent=toc, fontName=bold)))
    story.append(para(l["references"].capitalize(), ParagraphStyle("t4", parent=toc, fontName=bold)))
    story.append(PageBreak())

    story.append(para(l["intro"], h1))
    story += [para(t, body) for t in content.introduction]
    for ci, chapter in enumerate(content.chapters):
        story.append(PageBreak())
        story.append(para(f"{chapter_label(meta.language, ci)} {chapter.title.upper()}", h1))
        for si, section in enumerate(chapter.sections):
            story.append(para(f"{ci + 1}.{si + 1}. {section.title}", h2))
            story += [para(t, body) for t in section.paragraphs]
    story += [PageBreak(), para(l["conclusion"], h1)]
    story += [para(t, body) for t in content.conclusion]
    if content.references:
        story += [PageBreak(), para(l["references"], h1)]
        story += [para(f"{i}. {r}", ref) for i, r in enumerate(content.references, start=1)]
    if watermark:
        story += [
            Spacer(1, 30),
            para(watermark, ParagraphStyle(
                "wm", fontName=f["SC-Serif-Italic"], fontSize=11, leading=14, alignment=TA_CENTER,
                textColor=HexColor("#808080"),
            )),
        ]

    doc.build(story)
    return output


# ------------------------------------------------------------------ public API


class PdfConverter:
    def __init__(self, libreoffice_path: str = "") -> None:
        self.libreoffice = find_libreoffice(libreoffice_path)
        if self.libreoffice:
            logger.info("LibreOffice found: %s", self.libreoffice)
        else:
            logger.info("LibreOffice not found, PDFs will be rendered with reportlab")

    async def presentation_to_pdf(
        self, pptx_path: Path, content: PresentationContent, theme_key: str, watermark: str | None = None
    ) -> Path | None:
        if self.libreoffice:
            result = await asyncio.to_thread(_libreoffice_convert, self.libreoffice, pptx_path)
            if result:
                return result
        try:
            return await asyncio.to_thread(
                _PresentationPdfRenderer(content, theme_key, watermark).render, pptx_path.with_suffix(".pdf")
            )
        except Exception:
            logger.exception("reportlab presentation PDF failed")
            return None

    async def referat_to_pdf(
        self, docx_path: Path, content: ReferatContent, meta: ReferatMeta, watermark: str | None = None
    ) -> Path | None:
        if self.libreoffice:
            result = await asyncio.to_thread(_libreoffice_convert, self.libreoffice, docx_path)
            if result:
                return result
        try:
            return await asyncio.to_thread(
                _render_referat_pdf, content, meta, docx_path.with_suffix(".pdf"), watermark
            )
        except Exception:
            logger.exception("reportlab referat PDF failed")
            return None
