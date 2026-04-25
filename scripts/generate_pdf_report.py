#!/usr/bin/env python3
"""
Generate docs/final_report/report.pdf from the 7 chapter markdown files.

Uses:
  - markdown library  → convert .md to HTML
  - reportlab         → render HTML-ish content to PDF

Usage:
    python scripts/generate_pdf_report.py

Output:
    docs/final_report/report.pdf
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── Output paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "docs" / "final_report"
OUTPUT_PDF = REPORT_DIR / "report.pdf"

CHAPTER_FILES = [
    "01_executive_decision_framing.md",
    "02_cost_per_qualified_lead.md",
    "03_stalled_thread_rate_delta.md",
    "04_competitive_gap_reply_rate_delta.md",
    "05_pilot_scope_specificity.md",
    "06_public_signal_lossiness.md",
    "07_honest_unresolved_failure.md",
]

# ── ReportLab imports ─────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY


# ── Style definitions ─────────────────────────────────────────────────────────

def build_styles():
    base = getSampleStyleSheet()

    styles = {
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontSize=18,
            spaceAfter=12,
            spaceBefore=24,
            textColor=colors.HexColor("#1a1a2e"),
            fontName="Helvetica-Bold",
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontSize=13,
            spaceAfter=8,
            spaceBefore=16,
            textColor=colors.HexColor("#16213e"),
            fontName="Helvetica-Bold",
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=base["Heading3"],
            fontSize=11,
            spaceAfter=6,
            spaceBefore=12,
            textColor=colors.HexColor("#0f3460"),
            fontName="Helvetica-BoldOblique",
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["Normal"],
            fontSize=10,
            leading=15,
            spaceAfter=6,
            alignment=TA_JUSTIFY,
            fontName="Helvetica",
        ),
        "code": ParagraphStyle(
            "Code",
            parent=base["Code"],
            fontSize=8.5,
            leading=12,
            fontName="Courier",
            backColor=colors.HexColor("#f5f5f5"),
            leftIndent=12,
            rightIndent=12,
            spaceAfter=8,
            spaceBefore=4,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            leftIndent=18,
            firstLineIndent=-10,
            spaceAfter=3,
            fontName="Helvetica",
        ),
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontSize=28,
            textColor=colors.HexColor("#1a1a2e"),
            fontName="Helvetica-Bold",
            alignment=TA_CENTER,
            spaceAfter=12,
        ),
        "cover_sub": ParagraphStyle(
            "CoverSub",
            parent=base["Normal"],
            fontSize=13,
            textColor=colors.HexColor("#444444"),
            fontName="Helvetica",
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
    }
    return styles


# ── Markdown → ReportLab flowables ───────────────────────────────────────────

def _escape(text: str) -> str:
    """Escape XML special chars for ReportLab Paragraph."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline_fmt(text: str) -> str:
    """Apply inline markdown: **bold**, *italic*, `code`."""
    text = _escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+)`", r'<font name="Courier" size="9">\1</font>', text)
    return text


def parse_markdown(md_text: str, styles: dict) -> list:
    """Convert markdown text to a list of ReportLab flowables."""
    flowables = []
    lines = md_text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # Chapter heading (# H1)
        if line.startswith("# ") and not line.startswith("## "):
            flowables.append(Paragraph(_inline_fmt(line[2:].strip()), styles["h1"]))
            flowables.append(HRFlowable(width="100%", thickness=1.5,
                                        color=colors.HexColor("#1a1a2e"), spaceAfter=6))
            i += 1
            continue

        # Section heading (## H2)
        if line.startswith("## ") and not line.startswith("### "):
            flowables.append(Paragraph(_inline_fmt(line[3:].strip()), styles["h2"]))
            i += 1
            continue

        # Subsection heading (### H3)
        if line.startswith("### "):
            flowables.append(Paragraph(_inline_fmt(line[4:].strip()), styles["h3"]))
            i += 1
            continue

        # Fenced code block
        if line.strip().startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(_escape(lines[i]))
                i += 1
            i += 1  # skip closing ```
            code_text = "<br/>".join(code_lines) if code_lines else "&nbsp;"
            flowables.append(Paragraph(code_text, styles["code"]))
            flowables.append(Spacer(1, 4))
            continue

        # Markdown table
        if "|" in line and line.strip().startswith("|"):
            table_lines = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            # Filter separator rows (|---|---|)
            rows = []
            for tl in table_lines:
                if re.match(r"^\s*\|[\s\-:]+\|", tl):
                    continue
                cells = [c.strip() for c in tl.strip().strip("|").split("|")]
                rows.append(cells)
            if rows:
                flowables.append(_build_table(rows, styles))
                flowables.append(Spacer(1, 6))
            continue

        # Horizontal rule
        if line.strip() in ("---", "***", "___"):
            flowables.append(HRFlowable(width="100%", thickness=0.5,
                                        color=colors.HexColor("#cccccc"),
                                        spaceAfter=6, spaceBefore=6))
            i += 1
            continue

        # Bullet list item
        if line.startswith("- ") or line.startswith("* "):
            text = _inline_fmt(line[2:].strip())
            flowables.append(Paragraph(f"• {text}", styles["bullet"]))
            i += 1
            continue

        # Numbered list item
        numbered = re.match(r"^(\d+)\.\s+(.*)", line)
        if numbered:
            text = _inline_fmt(numbered.group(2).strip())
            num = numbered.group(1)
            flowables.append(Paragraph(f"{num}. {text}", styles["bullet"]))
            i += 1
            continue

        # Blank line
        if not line.strip():
            flowables.append(Spacer(1, 4))
            i += 1
            continue

        # Regular paragraph
        flowables.append(Paragraph(_inline_fmt(line.strip()), styles["body"]))
        i += 1

    return flowables


def _build_table(rows: list[list[str]], styles: dict) -> Table:
    """Build a styled ReportLab table from a list of row data."""
    # Format cells
    formatted = []
    base = getSampleStyleSheet()
    header_style = ParagraphStyle(
        "TH", parent=base["Normal"],
        fontSize=9, fontName="Helvetica-Bold",
        textColor=colors.white, alignment=TA_CENTER,
    )
    cell_style = ParagraphStyle(
        "TD", parent=base["Normal"],
        fontSize=9, fontName="Helvetica",
        leading=12, alignment=TA_LEFT,
    )

    for r_idx, row in enumerate(rows):
        fmt_row = []
        for cell in row:
            style = header_style if r_idx == 0 else cell_style
            fmt_row.append(Paragraph(_inline_fmt(cell), style))
        formatted.append(fmt_row)

    col_count = max(len(r) for r in formatted)
    available_width = A4[0] - 4 * cm
    col_width = available_width / col_count

    tbl = Table(formatted, colWidths=[col_width] * col_count, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0),  colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
        ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, 0),  9),
        ("BACKGROUND",  (0, 1), (-1, -1), colors.HexColor("#f8f8f8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor("#f8f8f8"), colors.HexColor("#ebebeb")]),
        ("GRID",        (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tbl


# ── Cover page ────────────────────────────────────────────────────────────────

def build_cover(styles: dict) -> list:
    flowables = []
    flowables.append(Spacer(1, 3 * cm))
    flowables.append(Paragraph("Conversion Engine", styles["cover_title"]))
    flowables.append(Paragraph("Final Technical Report", styles["cover_sub"]))
    flowables.append(Spacer(1, 0.4 * cm))
    flowables.append(HRFlowable(width="60%", thickness=2,
                                color=colors.HexColor("#1a1a2e"),
                                hAlign="CENTER", spaceAfter=12))
    flowables.append(Spacer(1, 0.6 * cm))
    flowables.append(Paragraph("Tenacious Consulting &amp; Outsourcing", styles["cover_sub"]))
    flowables.append(Paragraph("10 Academy Intensive Program — April 2026", styles["cover_sub"]))
    flowables.append(Paragraph("Submitted by: Dereje Derib", styles["cover_sub"]))
    flowables.append(Spacer(1, 2 * cm))

    chapters = [
        "1. Executive Decision Framing",
        "2. Cost Per Qualified Lead Derivation",
        "3. Stalled-Thread Rate Delta",
        "4. Competitive-Gap Outbound Reply-Rate Delta",
        "5. Pilot Scope Specificity",
        "6. Public-Signal Lossiness of AI Maturity Scoring",
        "7. Honest Unresolved Failure from the Mechanism",
    ]
    body_style = ParagraphStyle(
        "TOC", parent=getSampleStyleSheet()["Normal"],
        fontSize=10, leading=18, fontName="Helvetica",
        alignment=TA_CENTER, textColor=colors.HexColor("#333333"),
    )
    for ch in chapters:
        flowables.append(Paragraph(ch, body_style))

    flowables.append(PageBreak())
    return flowables


# ── Main builder ──────────────────────────────────────────────────────────────

def build_pdf() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    styles = build_styles()

    doc = SimpleDocTemplate(
        str(OUTPUT_PDF),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Conversion Engine — Final Technical Report",
        author="Dereje Derib, 10 Academy Intensive Program",
        subject="Automated Lead Generation System — Tenacious Consulting",
    )

    story = build_cover(styles)

    for idx, fname in enumerate(CHAPTER_FILES):
        fpath = REPORT_DIR / fname
        if not fpath.exists():
            print(f"  [WARN] Missing chapter file: {fpath}")
            continue
        md_text = fpath.read_text(encoding="utf-8")
        print(f"  Processing: {fname}")
        chapter_flowables = parse_markdown(md_text, styles)
        story.extend(chapter_flowables)
        if idx < len(CHAPTER_FILES) - 1:
            story.append(PageBreak())

    doc.build(story)
    size_kb = OUTPUT_PDF.stat().st_size // 1024
    print(f"\nPDF written: {OUTPUT_PDF}  ({size_kb} KB)")


if __name__ == "__main__":
    print("Generating final report PDF...")
    build_pdf()
