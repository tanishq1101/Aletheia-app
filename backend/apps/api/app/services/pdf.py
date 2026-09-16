"""Render a `ReportDocument` to PDF.

Kept separate from `report.py` so the document model stays a plain description
of *what* is in a report, testable without a PDF engine, and this module stays
the only place that knows reportlab exists.

The answers this renders are Markdown, because that is what the answering
prompt asks the model for (`answering.SYSTEM_PROMPT` rule 6). So a Markdown
subset has to be understood here or the PDF would show raw `**` and `|` to the
reader. The subset is deliberately the one the prompt actually requests —
headings, bold, italic, code, bullet and numbered lists, and the fixed-column
comparison table — rather than a general Markdown implementation. Anything
outside it degrades to plain text, which is readable, instead of raising.
"""

from __future__ import annotations

import re
from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.report import ReportDocument, ReportSection, ReportTable

# The screen palette, so a downloaded brief is recognisably the same artefact
# as the page it came from.
_INK = colors.HexColor("#1A1815")
_MUTED = colors.HexColor("#6B6560")
_BRASS = colors.HexColor("#8A6D3B")
_RULE = colors.HexColor("#DCD6CC")
_PANEL = colors.HexColor("#F6F3EE")

_MARGIN = 18 * mm


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    def style(name: str, **kw) -> ParagraphStyle:
        return ParagraphStyle(name, parent=base, **kw)

    return {
        "title": style("title", fontName="Helvetica-Bold", fontSize=20,
                       leading=25, textColor=_INK, spaceAfter=4),
        "subtitle": style("subtitle", fontSize=11, leading=15,
                          textColor=_MUTED, spaceAfter=2),
        "meta": style("meta", fontName="Courier", fontSize=7.5, leading=11,
                      textColor=_MUTED),
        "h1": style("h1", fontName="Helvetica-Bold", fontSize=14, leading=18,
                    textColor=_INK, spaceBefore=16, spaceAfter=6),
        "h2": style("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=15,
                    textColor=_INK, spaceBefore=12, spaceAfter=4),
        "h3": style("h3", fontName="Helvetica-Bold", fontSize=10, leading=13,
                    textColor=_BRASS, spaceBefore=10, spaceAfter=3),
        "body": style("body", fontSize=9.5, leading=14, textColor=_INK,
                      alignment=TA_LEFT, spaceAfter=7),
        "note": style("note", fontSize=8.5, leading=12.5, textColor=_MUTED,
                      spaceAfter=4),
        "cell": style("cell", fontSize=8, leading=11, textColor=_INK),
        "cellhead": style("cellhead", fontName="Helvetica-Bold", fontSize=8,
                          leading=11, textColor=_INK),
    }


# --- Markdown subset --------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_RULE_LINE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_TABLE_DIVIDER = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")

# Inline markup, applied to already-escaped text so a paper's own "<" or "&"
# cannot become markup. Bold before italic: `**x**` must not be read as two
# italics.
# The answering prompt asks for plain-text maths, but a model that reaches for
# LaTeX anyway must not put `\(O(n^2)\)` in front of a reader. Only the
# delimiters go: the expression inside them is already readable.
_MATH_DELIMITERS = re.compile(r"\\[()\[\]]")

_INLINE = (
    (re.compile(r"\*\*(.+?)\*\*", re.S), r"<b>\1</b>"),
    (re.compile(r"__(.+?)__", re.S), r"<b>\1</b>"),
    (re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", re.S), r"<i>\1</i>"),
    (re.compile(r"`([^`]+)`"), r'<font face="Courier">\1</font>'),
    # Markdown links: the label is what a reader needs; the bare URL after it
    # would double the line length of every citation.
    (re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)"), r'<link href="\2" color="#8A6D3B">\1</link>'),
)


def _inline(text: str) -> str:
    """Escape, then apply the inline subset. Order matters — see `_INLINE`."""
    out = _MATH_DELIMITERS.sub("", escape(text, quote=False))
    for pattern, replacement in _INLINE:
        out = pattern.sub(replacement, out)
    return out


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table_from(lines: list[str], start: int, styles) -> tuple[Table | None, int]:
    """Read a pipe table at `lines[start]`, or return (None, start).

    A header row followed by a `---|---` divider is the only shape accepted, so
    a line of prose that merely contains a pipe is never mistaken for a table.
    """
    if start + 1 >= len(lines):
        return None, start
    if "|" not in lines[start] or not _TABLE_DIVIDER.match(lines[start + 1]):
        return None, start

    header = _split_row(lines[start])
    rows, index = [], start + 2
    while index < len(lines) and "|" in lines[index] and lines[index].strip():
        cells = _split_row(lines[index])
        # Ragged rows are padded rather than dropped: a missing cell is better
        # shown as blank than the whole measurement table being discarded.
        rows.append((cells + [""] * len(header))[: len(header)])
        index += 1
    if not rows:
        return None, start

    data = [[Paragraph(_inline(c), styles["cellhead"]) for c in header]]
    data += [[Paragraph(_inline(c), styles["cell"]) for c in row] for row in rows]

    available = A4[0] - 2 * _MARGIN
    table = Table(data, colWidths=[available / len(header)] * len(header),
                  repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _PANEL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, _BRASS),
        ("GRID", (0, 0), (-1, -1), 0.25, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table, index


def markdown_flowables(text: str, styles: dict[str, ParagraphStyle]) -> list:
    """The Markdown subset the answering prompt asks for, as flowables."""
    flowables: list = []
    lines = (text or "").replace("\r\n", "\n").split("\n")
    paragraph: list[str] = []
    bullets: list[str] = []
    numbered: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            flowables.append(Paragraph(_inline(" ".join(paragraph)), styles["body"]))
            paragraph.clear()

    def flush_lists() -> None:
        for items, kind in ((bullets, "bullet"), (numbered, "1")):
            if items:
                flowables.append(ListFlowable(
                    [ListItem(Paragraph(_inline(i), styles["body"]),
                              leftIndent=14) for i in items],
                    bulletType=kind, leftIndent=14, bulletFontSize=8,
                    bulletColor=_BRASS, spaceAfter=6,
                ))
                items.clear()

    def flush() -> None:
        flush_paragraph()
        flush_lists()

    index = 0
    while index < len(lines):
        line = lines[index]

        table, consumed = _table_from(lines, index, styles)
        if table is not None:
            flush()
            flowables.extend([Spacer(1, 4), table, Spacer(1, 8)])
            index = consumed
            continue

        if not line.strip():
            flush()
        elif _RULE_LINE.match(line):
            flush()
            flowables.append(HRFlowable(width="100%", thickness=0.4,
                                        color=_RULE, spaceBefore=6, spaceAfter=8))
        elif heading := _HEADING.match(line):
            flush()
            level = min(len(heading.group(1)), 3)
            flowables.append(Paragraph(_inline(heading.group(2)),
                                       styles[f"h{level}"]))
        elif bullet := _BULLET.match(line):
            flush_paragraph()
            if numbered:
                flush_lists()
            bullets.append(bullet.group(1))
        elif number := _NUMBERED.match(line):
            flush_paragraph()
            if bullets:
                flush_lists()
            numbered.append(number.group(2))
        else:
            flush_lists()
            paragraph.append(line.strip())
        index += 1

    flush()
    return flowables


# --- Page furniture ---------------------------------------------------------

def _page_furniture(document: ReportDocument):
    """Footer on every page: what this is, and which page of how many."""
    def draw(canvas, doc) -> None:
        canvas.saveState()
        canvas.setStrokeColor(_RULE)
        canvas.setLineWidth(0.4)
        canvas.line(_MARGIN, 14 * mm, A4[0] - _MARGIN, 14 * mm)
        canvas.setFont("Courier", 7)
        canvas.setFillColor(_MUTED)
        canvas.drawString(_MARGIN, 10 * mm, document.footer[:110])
        canvas.drawRightString(A4[0] - _MARGIN, 10 * mm, f"page {doc.page}")
        canvas.restoreState()
    return draw


def _panel(rows: list[tuple[str, str]], styles) -> Table:
    """The key/value block under the title — provenance at a glance."""
    data = [[Paragraph(escape(k), styles["cellhead"]),
             Paragraph(_inline(v), styles["cell"])] for k, v in rows]
    available = A4[0] - 2 * _MARGIN
    table = Table(data, colWidths=[available * 0.26, available * 0.74],
                  hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _PANEL),
        ("LINEBEFORE", (0, 0), (0, -1), 1.5, _BRASS),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _report_table(spec: ReportTable, styles) -> list:
    data = [[Paragraph(escape(c), styles["cellhead"]) for c in spec.columns]]
    data += [[Paragraph(_inline(c), styles["cell"]) for c in row]
             for row in spec.rows]
    available = A4[0] - 2 * _MARGIN
    widths = spec.widths or [1 / len(spec.columns)] * len(spec.columns)
    table = Table(data, colWidths=[available * w for w in widths],
                  repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _PANEL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, _BRASS),
        ("GRID", (0, 0), (-1, -1), 0.25, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [Spacer(1, 4), table, Spacer(1, 8)]


def _section_flowables(section: ReportSection, styles) -> list:
    out: list = []
    if section.page_break_before:
        out.append(PageBreak())
    if section.heading:
        out.append(Paragraph(_inline(section.heading), styles["h1"]))
    if section.note:
        out.append(Paragraph(_inline(section.note), styles["note"]))
    if section.body:
        out.extend(markdown_flowables(section.body, styles))
    for table in section.tables:
        if table.caption:
            out.append(Paragraph(_inline(table.caption), styles["h3"]))
        out.extend(_report_table(table, styles))
    for child in section.children:
        # A sub-heading stranded at the foot of a page reads as a section with
        # no content, so it travels with its opening flowable.
        rendered = _section_flowables(child, styles)
        if rendered and child.heading and not child.page_break_before:
            out.append(KeepTogether(rendered[:2]))
            out.extend(rendered[2:])
        else:
            out.extend(rendered)
    return out


def render_pdf(document: ReportDocument) -> bytes:
    """The document as PDF bytes. Pure: no filesystem, no network."""
    styles = _styles()
    buffer = BytesIO()
    template = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=_MARGIN, rightMargin=_MARGIN,
        topMargin=_MARGIN, bottomMargin=24 * mm,
        title=document.title, author="Aletheia", subject=document.subtitle,
    )

    story: list = [Paragraph(_inline(document.title), styles["title"])]
    if document.subtitle:
        story.append(Paragraph(_inline(document.subtitle), styles["subtitle"]))
    story.append(Spacer(1, 10))
    if document.provenance:
        story.extend([_panel(document.provenance, styles), Spacer(1, 6)])
    for caveat in document.caveats:
        # A word, not a glyph: reportlab's base-14 fonts have no ⚠, and an
        # unmapped character draws as a filled box that reads as corruption.
        story.append(Paragraph(
            f'<font color="#8A6D3B"><b>Note —</b></font> {_inline(caveat)}',
            styles["note"],
        ))
    if document.caveats:
        story.append(Spacer(1, 4))
    for section in document.sections:
        story.extend(_section_flowables(section, styles))

    template.build(story, onFirstPage=_page_furniture(document),
                   onLaterPages=_page_furniture(document))
    return buffer.getvalue()


__all__ = ["render_pdf", "markdown_flowables"]
