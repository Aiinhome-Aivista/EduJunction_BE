"""PDF Report Generator for EduJunction.
Generates a professional, structured PDF report for exam submissions using ReportLab.
"""
import io
import html
import re
import unicodedata
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable


def clean_pdf_math_text(text: str) -> str:
    """Sanitizes mathematical text, vector hats, unicode glyphs, and special characters
    for clean rendering in ReportLab Helvetica Type 1 font without missing glyph boxes (■).
    """
    if not text:
        return ""
    s = str(text)

    # 1. Clean unit vectors and hats (î, ĵ, k̂, etc.)
    s = s.replace("î", "i^").replace("ĵ", "j^").replace("k̂", "k^")
    s = s.replace("î", "i^").replace("ĵ", "j^").replace("k̂", "k^")
    s = s.replace("■", "").replace("\ufffd", "")

    # Replace LaTeX vector & hat notations
    s = re.sub(r"\\hat\{([a-zA-Z])\}", r"\1^", s)
    s = re.sub(r"\\vec\{([a-zA-Z])\}", r"\1", s)
    s = re.sub(r"\\mathbf\{([a-zA-Z])\}", r"\1", s)

    # Replace common LaTeX math commands and operators
    replacements = {
        r"\implies": " => ",
        r"\Rightarrow": " => ",
        r"\Leftarrow": " <= ",
        r"\iff": " <=> ",
        r"\Leftrightarrow": " <=> ",
        r"\rightarrow": " -> ",
        r"\leftarrow": " <- ",
        r"\longrightarrow": " -> ",
        r"\longleftarrow": " <- ",
        r"\to": " -> ",
        r"\therefore": " therefore ",
        r"\because": " because ",
        r"\cdot": " * ",
        r"\bullet": " * ",
        r"\circ": " deg",
        r"\int": "Integral ",
        r"\theta": "theta",
        r"\pi": "pi",
        r"\alpha": "alpha",
        r"\beta": "beta",
        r"\gamma": "gamma",
        r"\delta": "delta",
        r"\lambda": "lambda",
        r"\mu": "mu",
        r"\sigma": "sigma",
        r"\omega": "omega",
        r"\sqrt": "sqrt",
        r"\le": "<=",
        r"\ge": ">=",
        r"\ne": "!=",
        r"\pm": "+/-",
        r"\times": "*",
        r"\div": "/",
        r"\approx": "~=",
        r"\infty": "inf",
        r"\quad": "  ",
        r"\qquad": "    ",
        r"\in": " in ",
        r"\notin": " not in ",
        r"\subset": " subset of ",
        r"\cup": " union ",
        r"\cap": " intersection ",
        r"\partial": "d",
        r"\sum": "Sum ",
        r"\prod": "Prod ",
    }
    for k, v in replacements.items():
        s = s.replace(k, v)

    # Normalize unicode and remove combining diacritics
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[\u0300-\u036f]", "", s)

    # Safe ASCII replacements for Greek, math symbols, and unicode arrows
    safe_map = {
        "⇒": " => ",
        "→": " -> ",
        "←": " <- ",
        "⇔": " <=> ",
        "↦": " -> ",
        "∴": " therefore ",
        "∵": " because ",
        "·": " * ",
        "•": "-",
        "θ": "theta",
        "π": "pi",
        "α": "alpha",
        "β": "beta",
        "γ": "gamma",
        "δ": "delta",
        "λ": "lambda",
        "μ": "mu",
        "σ": "sigma",
        "ω": "omega",
        "∫": "Integral ",
        "√": "sqrt",
        "≤": "<=",
        "≥": ">=",
        "≠": "!=",
        "±": "+/-",
        "×": "*",
        "÷": "/",
        "≈": "~=",
        "∞": "inf",
        "²": "^2",
        "³": "^3",
        "⁴": "^4",
        "∂": "d",
        "∈": " in ",
        "∉": " not in ",
        "■": " ",
        "\ufffd": "",
    }
    for k, v in safe_map.items():
        s = s.replace(k, v)

    # Clean any remaining non-printable or unsupported unicode symbols that cause Helvetica tofu
    s = re.sub(r"[^\x20-\x7E\n\r\t]", " ", s)
    s = re.sub(r" {2,}", " ", s)

    # Escape XML entities for ReportLab Paragraph
    s = html.escape(s)
    # Re-allow safe formatting tags
    s = s.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    s = s.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    s = s.replace("&lt;br/&gt;", "<br/>").replace("&lt;br&gt;", "<br/>")

    return s.strip()


def generate_exam_report_pdf(
    student_name: str,
    board: str,
    class_grade: str,
    subject: str,
    exam_title: str,
    exam_date: str,
    marks_obtained: float,
    total_marks: float,
    accuracy_percentage: float,
    time_taken_seconds: int,
    evaluations: list[dict],
    analysis: dict | None = None,
) -> bytes:
    """Generates an in-memory PDF report and returns the raw bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=20,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=12,
    )
    section_heading = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=colors.HexColor("#334155"),
        leading=13,
    )
    badge_style = ParagraphStyle(
        "BadgeText",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        textColor=colors.HexColor("#0f766e"),
    )

    story = []

    # Header Banner
    header_data = [
        [
            Paragraph("<b><font color=\"#000000\">Edu</font><font color=\"#000000\">Junction</font></b> &bull; Student Performance Analysis Report", title_style),
            Paragraph(f"<b>Date:</b> {exam_date}", subtitle_style),
        ]
    ]
    header_table = Table(header_data, colWidths=[400, 140])
    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ])
    )
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#e2e8f0"), spaceAfter=10))

    # Student & Exam Info Summary Box
    mins = time_taken_seconds // 60
    secs = time_taken_seconds % 60
    time_str = f"{mins}m {secs}s"

    info_data = [
        [
            Paragraph(f"<b>Student Name:</b> {student_name}", body_style),
            Paragraph(f"<b>Board & Class:</b> {board} - {class_grade}", body_style),
        ],
        [
            Paragraph(f"<b>Subject:</b> {subject}", body_style),
            Paragraph(f"<b>Exam Title:</b> {exam_title or 'Adaptive Diagnostic Test'}", body_style),
        ],
        [
            Paragraph(f"<b>Score:</b> <b>{marks_obtained} / {total_marks}</b> ({accuracy_percentage}%)", badge_style),
            Paragraph(f"<b>Time Taken:</b> {time_str}", body_style),
        ],
    ]
    info_table = Table(info_data, colWidths=[270, 270])
    info_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(info_table)
    story.append(Spacer(1, 10))

    # Strengths & Recommendations (if analysis present)
    if analysis:
        strengths = analysis.get("strengths") or []
        areas = analysis.get("areasToImprove") or []
        note = analysis.get("encouragementNote") or ""

        analysis_rows = []
        if strengths:
            if isinstance(strengths, list):
                str_text = "<br/>".join([f"&bull; {clean_pdf_math_text(s).rstrip('.')}" for s in strengths if s and str(s).strip()])
            else:
                str_text = clean_pdf_math_text(str(strengths))
            analysis_rows.append([Paragraph("<b>Key Strengths:</b>", body_style), Paragraph(str_text, body_style)])
        if areas:
            if isinstance(areas, list):
                ar_text = "<br/>".join([f"&bull; {clean_pdf_math_text(a).rstrip('.')}" for a in areas if a and str(a).strip()])
            else:
                ar_text = clean_pdf_math_text(str(areas))
            analysis_rows.append([Paragraph("<b>Areas to Focus:</b>", body_style), Paragraph(ar_text, body_style)])
        if note:
            analysis_rows.append([Paragraph("<b>Teacher/Parent Note:</b>", body_style), Paragraph(clean_pdf_math_text(str(note)), body_style)])

        if analysis_rows:
            story.append(Paragraph("Diagnostic Insights & Action Plan", section_heading))
            analysis_table = Table(analysis_rows, colWidths=[130, 410])
            analysis_table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdf4")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#bbf7d0")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dcfce7")),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ])
            )
            story.append(analysis_table)
            story.append(Spacer(1, 10))

    # Question Breakdown Table (Status column removed per parent feedback)
    story.append(Paragraph("Question Breakdown", section_heading))

    q_table_data = [
        [
            Paragraph("<b>#</b>", body_style),
            Paragraph("<b>Question / Topic</b>", body_style),
            Paragraph("<b>Your Answer</b>", body_style),
            Paragraph("<b>Correct Answer</b>", body_style),
            Paragraph("<b>Marks</b>", body_style),
        ]
    ]

    for idx, ev in enumerate(evaluations or []):
        q_num = str(idx + 1)
        raw_q_text = ev.get("questionText") or ev.get("question_text") or f"Question {idx+1}"
        if len(raw_q_text) > 95:
            raw_q_text = raw_q_text[:92] + "..."
        q_text = clean_pdf_math_text(raw_q_text)

        raw_student_ans = str(ev.get("studentAnswer") or ev.get("student_answer") or "Not Answered")
        if len(raw_student_ans) > 30:
            raw_student_ans = raw_student_ans[:27] + "..."
        student_ans = clean_pdf_math_text(raw_student_ans)

        raw_correct_ans = str(ev.get("correctAnswer") or ev.get("correct_answer") or "-")
        if len(raw_correct_ans) > 30:
            raw_correct_ans = raw_correct_ans[:27] + "..."
        correct_ans = clean_pdf_math_text(raw_correct_ans)

        marks = str(ev.get("marksAwarded", 0))

        q_table_data.append([
            Paragraph(q_num, body_style),
            Paragraph(q_text, body_style),
            Paragraph(student_ans, body_style),
            Paragraph(correct_ans, body_style),
            Paragraph(marks, body_style),
        ])

    q_table = Table(q_table_data, colWidths=[24, 256, 110, 110, 40])
    q_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ])
    )
    story.append(q_table)

    # Footer note
    story.append(Spacer(1, 14))
    footer_text = Paragraph(
        "<i>This report was automatically generated by EduJunction.</i>",
        subtitle_style,
    )
    story.append(footer_text)

    # Build document
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
