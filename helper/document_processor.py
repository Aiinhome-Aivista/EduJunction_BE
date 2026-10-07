"""Text extraction + chunking for uploaded curriculum documents.
Supports PDF (.pdf), Word (.docx, .doc), Rich Text (.rtf), Plain Text (.txt), and CSV (.csv).
"""
import os
import csv
import io
import re

try:
    import pymupdf as fitz  # PyMuPDF modern import
except ImportError:
    import fitz  # Legacy fallback
from pypdf import PdfReader
from docx import Document as DocxDocument
from utils.logger import logger

try:
    import importlib
    _striprtf_mod = importlib.import_module("striprtf.striprtf")
    rtf_to_text = getattr(_striprtf_mod, "rtf_to_text", None)
except Exception:
    rtf_to_text = None

from utils.errors import ValidationError

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "rtf", "txt", "csv"}
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
CHUNK_SIZE_CHARS = 1200
CHUNK_OVERLAP_CHARS = 150


def validate_upload(filename: str, content_length: int):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(f"Unsupported file type '.{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}")
    if content_length > MAX_FILE_SIZE_BYTES:
        raise ValidationError("File exceeds the 50MB upload limit")
    return ext


def extract_rtf_text(file_bytes: bytes) -> str:
    """Extracts clean plain text from Rich Text Format (.rtf) files."""
    if rtf_to_text:
        try:
            raw_str = file_bytes.decode("latin-1", errors="ignore")
            extracted = rtf_to_text(raw_str)
            if extracted and extracted.strip():
                return extracted.strip()
        except Exception:
            pass

    # Built-in robust regex RTF parser fallback
    try:
        raw_str = file_bytes.decode("latin-1", errors="ignore")
        # Remove destinations like {\*\generator...}, font tables, color tables
        raw_str = re.sub(r'\{\\\*(?:(?!\})[\s\S])*\}', '', raw_str)
        raw_str = re.sub(r'\{\\(?:fonttbl|colortbl|stylesheet|info|pict)(?:(?!\})[\s\S])*\}', '', raw_str)
        # Convert Unicode escapes \u1234?
        raw_str = re.sub(
            r'\\u(-?\d+)\??',
            lambda m: chr(int(m.group(1)) if int(m.group(1)) >= 0 else int(m.group(1)) + 65536)
            if 0 <= (int(m.group(1)) if int(m.group(1)) >= 0 else int(m.group(1)) + 65536) <= 0x10FFFF else '',
            raw_str
        )
        # Convert hex escapes \'hh
        raw_str = re.sub(r"\\\'([0-9a-fA-F]{2})", lambda m: bytes.fromhex(m.group(1)).decode('latin-1', errors='ignore'), raw_str)
        # Replace line breaks and tabs
        raw_str = re.sub(r'\\(?:par|line|page)\b', '\n', raw_str)
        raw_str = re.sub(r'\\tab\b', '\t', raw_str)
        # Remove remaining control words
        raw_str = re.sub(r'\\[a-zA-Z]+-?\d*\s?', '', raw_str)
        # Remove braces
        raw_str = re.sub(r'[{}]', '', raw_str)
        return raw_str.strip()
    except Exception:
        return file_bytes.decode("utf-8", errors="ignore")


def extract_doc_text(file_bytes: bytes) -> str:
    """Extracts text from Word documents (.doc legacy binary or renamed .docx)."""
    # 1. First attempt: OpenXML docx parser
    try:
        doc = DocxDocument(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)
        if paragraphs:
            return "\n".join(paragraphs)
    except Exception:
        pass

    # 2. Second attempt: Extract text stream runs from Word binary format (.doc)
    try:
        text_parts = []
        # Word binary documents store text in UTF-16LE runs
        utf16_runs = re.findall(b'(?:[\x20-\x7E\r\n\t]\x00){4,}', file_bytes)
        for run in utf16_runs:
            try:
                decoded = run.decode('utf-16le', errors='ignore').strip()
                if len(decoded) > 3 and not decoded.startswith(('Root Entry', 'WordDocument', 'SummaryInformation', 'CompObj')):
                    text_parts.append(decoded)
            except Exception:
                pass

        if text_parts:
            return "\n".join(text_parts)

        # Fallback to printable ASCII runs
        ascii_runs = re.findall(b'[\x20-\x7E\r\n\t]{6,}', file_bytes)
        for run in ascii_runs:
            decoded = run.decode('latin-1', errors='ignore').strip()
            if decoded and not any(meta in decoded for meta in ['CompObj', 'WordDocument', 'ObjectPool']):
                text_parts.append(decoded)
        return "\n".join(text_parts)
    except Exception:
        return file_bytes.decode("utf-8", errors="ignore")


UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "books")


def save_uploaded_file_to_disk(filename: str, file_bytes: bytes) -> str:
    """Saves uploaded book/question bank file to local uploads/books directory for permanent storage."""
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        safe_name = f"{re.sub(r'[^A-Za-z0-9_.-]', '_', filename)}"
        filepath = os.path.join(UPLOAD_DIR, safe_name)
        with open(filepath, "wb") as f:
            f.write(file_bytes)
        logger.info(f"Saved uploaded file to disk: {filepath}")
        return filepath
    except Exception as e:
        logger.warning(f"Failed to save copy of file to disk: {e}")
        return ""


def extract_text(
    file_bytes: bytes,
    ext: str,
    board: str = "General",
    class_grade: str = "Standard",
    subject: str = "General"
) -> str:
    """Extracts text from uploaded files based on extension with Vision OCR fallback for scanned PDFs."""
    if ext == "pdf":
        extracted_pages = []
        # 1. Primary: PyMuPDF (fitz) - high accuracy across modern and legacy PDFs
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            for page in doc:
                text = page.get_text()
                if text and text.strip():
                    extracted_pages.append(text.strip())
            doc.close()
            if extracted_pages and len(" ".join(extracted_pages).strip()) > 80:
                return "\n\n".join(extracted_pages)
        except Exception as err:
            logger.warning(f"PyMuPDF extraction error: {err}")

        # 2. Secondary fallback: pypdf
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            pypdf_pages = [page.extract_text() or "" for page in reader.pages]
            filtered = [p.strip() for p in pypdf_pages if p.strip()]
            if filtered and len(" ".join(filtered).strip()) > 80:
                return "\n\n".join(filtered)
        except Exception as err:
            logger.warning(f"pypdf extraction error: {err}")

        # 3. Third fallback: Multimodal Vision OCR for scanned image PDFs / photos
        logger.info("Digital text extraction yielded < 80 characters. Falling back to Dynamic Vision OCR...")
        try:
            from helper.ocr_vision_engine import extract_scanned_pdf_with_vision
            vision_text = extract_scanned_pdf_with_vision(file_bytes, board=board, class_grade=class_grade, subject=subject)
            if vision_text and vision_text.strip():
                return vision_text.strip()
        except Exception as vision_err:
            logger.error(f"Vision OCR fallback failed: {vision_err}")

        return ""
    
    if ext == "docx":
        doc = DocxDocument(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    paragraphs.append(row_text)
        return "\n".join(paragraphs)

    if ext == "doc":
        return extract_doc_text(file_bytes)

    if ext == "rtf":
        return extract_rtf_text(file_bytes)

    if ext == "txt":
        for encoding in ("utf-8", "utf-16", "cp1252", "latin-1"):
            try:
                return file_bytes.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return file_bytes.decode("utf-8", errors="ignore")

    if ext == "csv":
        text_stream = io.StringIO(file_bytes.decode("utf-8", errors="ignore"))
        reader = csv.reader(text_stream)
        return "\n".join(", ".join(row) for row in reader)

    raise ValidationError(f"No extractor implemented for '.{ext}'")


DISCLAIMER_PATTERNS = [
    r"no\s+part\s+of\s+this\s+publication\s+may\s+be\s+reproduced",
    r"stored\s+in\s+a\s+retrieval\s+system",
    r"transmitted\s+in\s+any\s+form\s+or\s+by\s+any\s+means",
    r"all\s+rights\s+reserved",
    r"national\s+council\s+of\s+educational\s+research\s+and\s+training",
    r"printed\s+in\s+india",
    r"published\s+at\s+the\s+publication\s+division",
    r"\bisbn\s*[:\d\-xX]+",
    r"price\s*:\s*(?:rs|inr|\u20B9)\.?\s*\d+",
    r"chief\s+advisor\s*:",
    r"editorial\s+board\s*:",
    r"\bforeword\b",
    r"\bpreface\b",
    r"\babout\s+(?:the\s+)?book\b",
    r"\bnote\s+(?:for|to)\s+(?:the\s+)?teachers?\b",
    r"\brationalisation\s+of\s+content\b",
    r"textbook\s+development\s+committee",
    r"textbook\s+development\s+team",
    r"printed\s+on\s+\d+\s*gsm\s+paper",
    r"reprinted\s+in\s+\d{4}",
    r"\bconstitution\s+of\s+india\b",
    r"\bfundamental\s+duties\b",
    r"\blearning\s+further\s+section\b",
    r"\bpedagogical\s+(?:framework|approach|guidelines)\b",
    r"\bhow\s+to\s+use\s+this\s+textbook\b",
    r"\bstructure\s+of\s+the\s+textbook\b",
    r"\bcuriosity\s*[:\-–]\s*textbook\s+of\s+science\b",
    r"www\.(?:tiwariacademy|vedantu|mycbseguide|selfstudys|learncbse|aglasem|topperlearning|byjus|meritnation)\.com",
    r"downloaded\s+from\s+www\.",
    r"visit\s+website\s*:\s*www\.",
    r"free\s+ncert\s+solutions\s+and\s+cbs?e\s+study\s+material",
]


def extract_table_of_contents_chapters(raw_text: str) -> list[dict]:
    """Scans for CONTENTS or Table of Contents table and extracts structured list of chapters."""
    if not raw_text:
        return []

    # Pattern to match "CONTENTS" or "TABLE OF CONTENTS" or "INDEX"
    toc_match = re.search(r'(?i)\b(?:CONTENTS|TABLE\s+OF\s+CONTENTS|INDEX)\b([\s\S]{100,5000}?)(?=\bCHAPTER\s+1\b|\bUNIT\s+1\b|\bLESSON\s+1\b|\Z)', raw_text)
    chapters = []
    toc_text = toc_match.group(1) if toc_match else raw_text[:12000]

    chap_pattern = re.compile(
        r'(?i)(?:CHAPTER|Chapter|UNIT|Unit|LESSON|Lesson)\s*(\d+|[IVXLCDM]+)[\s\:\.\-–—\n]+([^\n\d]{3,80})(?:\s+(\d+))?',
        re.MULTILINE
    )

    for m in chap_pattern.finditer(toc_text):
        c_num = m.group(1).strip()
        c_title = m.group(2).strip()
        c_title = re.sub(r'^(?:is\s+|are\s+|the\s+role\s+of\s+)', '', c_title, flags=re.IGNORECASE)
        c_title = re.sub(r'[\.\s\d]+$', '', c_title).strip()
        if len(c_title) >= 3 and not any(k in c_title.lower() for k in ["foreword", "preface", "about the book", "contents", "index"]):
            chapters.append({
                "number": int(c_num) if c_num.isdigit() else c_num,
                "title": c_title
            })

    return chapters


def strip_non_academic_preamble(raw_text: str) -> str:
    """Removes textbook publisher prefaces, copyright disclaimers, ISBNs, and editorial notes."""
    if not raw_text:
        return ""

    # 1. Front-Matter Auto-Purge: If full textbook with Chapter 1, slice off all preceding preface / about book pages
    first_chap_match = re.search(r'(?i)(?:\n|\A)\s*(?:CHAPTER|Chapter|UNIT|Unit|LESSON|Lesson)\s*[\-:]?\s*1[\s\:\.\-–—\n]+([^\n]{3,80})', raw_text)
    if first_chap_match and first_chap_match.start() > 100:
        preamble_text = raw_text[:first_chap_match.start()]
        if any(re.search(pat, preamble_text, re.IGNORECASE) for pat in [r'\bforeword\b', r'\babout\s+the\s+book\b', r'\bcontents\b', r'\bpreface\b', r'\btextbook\s+development\b', r'\bnote\s+for\s+the\s+teacher\b']):
            # Slice strictly from Chapter 1 onwards
            raw_text = raw_text[first_chap_match.start():]

    paragraphs = raw_text.split("\n\n")
    cleaned_paragraphs = []

    for para in paragraphs:
        para_clean = para.strip()
        if not para_clean:
            continue

        para_lower = para_clean.lower()
        is_junk = any(re.search(pat, para_lower) for pat in DISCLAIMER_PATTERNS)
        if is_junk:
            continue

        lines = para_clean.splitlines()
        valid_lines = []
        for line in lines:
            line_l = line.strip().lower()
            if not any(re.search(pat, line_l) for pat in DISCLAIMER_PATTERNS):
                valid_lines.append(line.strip())

        if valid_lines:
            cleaned_paragraphs.append("\n".join(valid_lines))

    return "\n\n".join(cleaned_paragraphs)


clean_text = strip_non_academic_preamble

VALID_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp"}


def save_diagram_to_disk(image_bytes: bytes, ext: str = "png", prefix: str = "diag") -> str:
    """Saves an actively referenced question diagram to uploads/questions/ on disk.
    
    Returns the relative URL (/edujunction/uploads/questions/...).
    """
    if not image_bytes:
        return ""
    try:
        from utils.config import config
        from uuid import uuid4
        questions_dir = os.path.join(config.UPLOAD_DIR, "questions")
        os.makedirs(questions_dir, exist_ok=True)

        clean_ext = ext.lower().replace(".", "")
        if clean_ext not in VALID_IMAGE_EXTS:
            clean_ext = "png"

        img_filename = f"{prefix}_{uuid4().hex[:12]}.{clean_ext}"
        filepath = os.path.join(questions_dir, img_filename)

        with open(filepath, "wb") as f:
            f.write(image_bytes)

        logger.info(f"Saved linked question diagram: {filepath} ({len(image_bytes)} bytes)")
        return f"/edujunction/uploads/questions/{img_filename}"
    except Exception as e:
        logger.warning(f"Failed to save linked diagram to disk: {e}")
        return ""


def crop_figure_from_pdf_page(file_bytes: bytes, page_num: int | None, fig_label: str) -> tuple[bytes | None, int | None]:
    """Precisely crops the visual figure, diagram, table, chart, or apparatus from the PDF using a 3-Layer progressive search.
    - Layer 1: Target question page (if page_num provided).
    - Layer 2: Adjacent neighbor pages (page_num ± 1, page_num ± 2).
    - Layer 3: Document-wide fallback (all remaining pages in document).

    Academic Quality & Universal Visual Support:
    1. Supports both Raster Figures (e.g. 'Fig. 4.16') and Vector Tables/Charts (e.g. 'Table 4.3').
    2. Horizontally co-aligned sub-diagram clustering and side label preservation ('X', 'Y', '1', '2', 'N').
    3. Multi-line caption and table title expansion.
    4. Side-text column boundary protection (prevents cutting into adjacent questions).
    5. Smart Background Whitener: Neutral light grey watermark erasure (NCERT 195-254) for crisp pure white background.
    6. High-resolution rendering at 180 DPI for razor-sharp diagrams.

    Returns:
        tuple[bytes | None, int | None]: (png_image_bytes, actual_matched_page_number)
    """
    if not file_bytes or not fig_label:
        return None, None
    try:
        import math
        import io
        from PIL import Image

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        total_pages = len(doc)
        if total_pages == 0:
            doc.close()
            return None, None

        clean_label = str(fig_label).strip()
        is_table_query = bool(re.search(r'\btable\b', clean_label, re.IGNORECASE))
        is_chart_query = bool(re.search(r'\bchart\b', clean_label, re.IGNORECASE))

        sub_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:\(?([a-zA-Z0-9]+)\)?)?', clean_label, re.IGNORECASE)
        base_num = sub_match.group(1) if sub_match else clean_label
        raw_sub = sub_match.group(2) if (sub_match and sub_match.group(2)) else None
        sub_id = raw_sub if (raw_sub and raw_sub.lower() not in ["figure", "fig", "table", "chart"]) else None

        target_p = int(page_num) if (page_num and 1 <= int(page_num) <= total_pages) else None
        layer1 = [target_p] if target_p else []
        layer2 = []
        if target_p:
            for offset in [1, -1, 2, -2]:
                p = target_p + offset
                if 1 <= p <= total_pages and p not in layer1 and p not in layer2:
                    layer2.append(p)
        layer3 = [p for p in range(1, total_pages + 1) if p not in layer1 and p not in layer2]

        for layer_idx, page_list in enumerate([layer1, layer2, layer3], 1):
            for pno in page_list:
                page = doc[pno - 1]
                page_blocks = page.get_text("blocks") or []

                # =========================================================================
                # PATH 1: TABLE & VECTOR CHART SEARCH & CROP (UNIVERSAL BI-DIRECTIONAL)
                # =========================================================================
                if is_table_query or is_chart_query:
                    exact_titles = []
                    for b in page_blocks:
                        b_text = b[4].strip()
                        if re.search(r'\b(?:what|which|explain|observe|answer|calculate|options\s+given|according\s+to|record\s+your|repeat\s+the)\b', b_text, re.IGNORECASE) or b_text.endswith("?"):
                            continue
                        # Genuine caption signature: starts with Table/Chart/Tab.
                        if re.match(r'^\s*(?:table|chart|tab\.)\s*' + re.escape(base_num) + r'(?![a-zA-Z0-9])', b_text, re.IGNORECASE):
                            if len(b_text) < 150:
                                exact_titles.append((fitz.Rect(b[:4]), b_text))

                    if not exact_titles:
                        continue

                    t_rect, t_text = exact_titles[0]

                    # Multi-line title subtitle expansion (directly above or below caption)
                    for b in page_blocks:
                        b_r = fitz.Rect(b[:4])
                        b_str = b[4].strip()
                        if b_str == t_text:
                            continue
                        if max(b_r.x0, t_rect.x0 - 40) < min(b_r.x1, t_rect.x1 + 40) and len(b_str.split()) <= 12:
                            if not b_str.endswith("?") and not re.match(r'^(?:Activity|\d+[\.\)]|Fig|Table|Chart|Q\.)', b_str, re.IGNORECASE):
                                # Subtitle directly below header caption
                                if -3 <= (b_r.y0 - t_rect.y1) <= 18:
                                    t_rect = t_rect | b_r
                                # Title directly above footer caption
                                elif -18 <= (t_rect.y0 - b_r.y1) <= 3:
                                    t_rect = t_rect | b_r

                    # Bi-directional Vector Drawings & Grid Expansion (Top-caption or Bottom-caption)
                    table_drawings_box = None
                    is_footer_caption = False

                    # First check if table drawings exist BELOW caption (Header mode)
                    for d in page.get_drawings():
                        d_r = d["rect"]
                        if d_r.width > page.rect.width * 0.85 or d_r.height > page.rect.height * 0.85:
                            continue
                        if d_r.width < 18 or d_r.height < 6 or d_r.height > 300 or d_r.width > 480:
                            continue
                        if d_r.y0 >= t_rect.y1 - 8 and d_r.y0 <= t_rect.y1 + 45 and max(d_r.x0, t_rect.x0 - 70) < min(d_r.x1, t_rect.x1 + 70):
                            if table_drawings_box is None:
                                table_drawings_box = d_r
                            else:
                                table_drawings_box = table_drawings_box | d_r

                    # If no drawings below, check if table drawings exist ABOVE caption (Footer mode)
                    if table_drawings_box is None:
                        for d in page.get_drawings():
                            d_r = d["rect"]
                            if d_r.width > page.rect.width * 0.85 or d_r.height > page.rect.height * 0.85:
                                continue
                            if d_r.width < 18 or d_r.height < 6 or d_r.height > 300 or d_r.width > 480:
                                continue
                            if d_r.y1 <= t_rect.y0 + 8 and d_r.y1 >= t_rect.y0 - 45 and max(d_r.x0, t_rect.x0 - 70) < min(d_r.x1, t_rect.x1 + 70):
                                is_footer_caption = True
                                if table_drawings_box is None:
                                    table_drawings_box = d_r
                                else:
                                    table_drawings_box = table_drawings_box | d_r

                    # Expand connected drawings in the active direction
                    if table_drawings_box:
                        for d in page.get_drawings():
                            d_r = d["rect"]
                            if d_r.width > page.rect.width * 0.85 or d_r.height > page.rect.height * 0.85:
                                continue
                            if d_r.width < 18 or d_r.height < 6 or d_r.height > 300 or d_r.width > 480:
                                continue
                            if d_r.y0 <= table_drawings_box.y1 + 10 and d_r.y1 >= table_drawings_box.y0 - 10:
                                if max(d_r.x0, table_drawings_box.x0 - 40) < min(d_r.x1, table_drawings_box.x1 + 40):
                                    table_drawings_box = table_drawings_box | d_r

                    table_box = t_rect
                    if table_drawings_box:
                        table_box = table_box | table_drawings_box
                        grid_y0 = table_drawings_box.y0 - 5
                        grid_y1 = table_drawings_box.y1 + 5
                        grid_x0 = table_drawings_box.x0
                        grid_x1 = table_drawings_box.x1
                    else:
                        if is_footer_caption:
                            grid_y0 = t_rect.y0 - 220
                            grid_y1 = t_rect.y0
                        else:
                            grid_y0 = t_rect.y1
                            grid_y1 = t_rect.y1 + 220
                        grid_x0 = t_rect.x0 - 20
                        grid_x1 = t_rect.x1 + 20

                    # Include Table row labels on the left & data cells inside grid
                    included_blocks = 0
                    for b in page_blocks:
                        b_r = fitz.Rect(b[:4])
                        b_str = b[4].strip()
                        if b_str == t_text:
                            continue
                        if re.match(r'^(?:\d+[\.\)]\s+[A-Z]|Activity|Fig|Q\.)', b_str):
                            continue
                        if grid_y0 <= b_r.y0 and b_r.y1 <= grid_y1 + 10:
                            if (grid_x0 - 55 <= b_r.x0 <= grid_x1 + 25) and (b_r.x1 <= grid_x1 + 25):
                                table_box = table_box | b_r
                                included_blocks += 1

                    # Table Structure Verification: must have drawings or data cells
                    if not table_drawings_box and included_blocks == 0:
                        continue

                    pad_x = 10
                    pad_y = 10
                    padded_rect = fitz.Rect(
                        max(0, table_box.x0 - pad_x),
                        max(0, table_box.y0 - pad_y),
                        min(page.rect.width, table_box.x1 + pad_x),
                        min(page.rect.height, table_box.y1 + pad_y)
                    )
                    pix = page.get_pixmap(clip=padded_rect, dpi=180)
                    img_bytes = pix.tobytes("png")

                    # Smart Whitener & Watermark Remover
                    try:
                        pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                        pixels = pil_img.load()
                        p_w, p_h = pil_img.size
                        for py in range(p_h):
                            for px in range(p_w):
                                pr, pg, pb = pixels[px, py]
                                # Neutral light grey watermark:
                                if pr >= 195 and pg >= 195 and pb >= 195 and abs(pr - pg) <= 10 and abs(pg - pb) <= 12:
                                    pixels[px, py] = (255, 255, 255)
                                # Tan/beige watermark ink (e.g. NCERT 'not to be republished'):
                                elif 195 <= pr <= 252 and 185 <= pg <= 248 and 165 <= pb <= 242:
                                    if 6 <= (pr - pb) <= 45 and (pr >= pg >= pb or abs(pr - pg) <= 15):
                                        pixels[px, py] = (255, 255, 255)
                        buf = io.BytesIO()
                        pil_img.save(buf, format="PNG")
                        img_bytes = buf.getvalue()
                    except Exception:
                        pass

                    doc.close()
                    return img_bytes, pno

                # =========================================================================
                # PATH 2: FIGURE / DIAGRAM SEARCH & CROP
                # =========================================================================
                if is_table_query or is_chart_query:
                    continue

                exact_captions = []
                fallback_captions = []

                for b in page_blocks:
                    b_text = b[4].strip()
                    if re.search(r'\b(?:what|which|explain|observe|answer|calculate|state|following\s+questions|activity|can\s+you)\b', b_text, re.IGNORECASE) or b_text.endswith("?"):
                        continue
                    if sub_id:
                        sub_pat = rf'fig(?:ure)?\.?\s*{re.escape(base_num)}\s*(?:\(\s*{re.escape(sub_id)}\s*\)|{re.escape(sub_id)})(?![a-zA-Z0-9])'
                        if re.search(sub_pat, b_text, re.IGNORECASE):
                            b_rect = fitz.Rect(b[:4])
                            if b_rect.height < 60 and len(b_text) < 120:
                                if re.match(r'^\s*fig(?:ure)?\.?', b_text, re.IGNORECASE):
                                    exact_captions.insert(0, (b_rect, b_text))
                                else:
                                    exact_captions.append((b_rect, b_text))
                    else:
                        pat = rf'fig(?:ure)?\.?\s*{re.escape(base_num)}(?![a-zA-Z0-9])'
                        if re.search(pat, b_text, re.IGNORECASE):
                            b_rect = fitz.Rect(b[:4])
                            if b_rect.height < 60 and len(b_text) < 120:
                                if re.match(r'^\s*fig(?:ure)?\.?', b_text, re.IGNORECASE):
                                    exact_captions.insert(0, (b_rect, b_text))
                                else:
                                    exact_captions.append((b_rect, b_text))

                chosen_caption = (exact_captions or fallback_captions or [None])[0]
                if not chosen_caption:
                    if not sub_id:
                        for b in page_blocks:
                            b_text = b[4].strip()
                            if any(term.lower() in b_text.lower() for term in [f"fig. {base_num}", f"fig.{base_num}", f"fig {base_num}", f"figure {base_num}"]):
                                b_rect = fitz.Rect(b[:4])
                                chosen_caption = (b_rect, b_text)
                                break

                if not chosen_caption:
                    continue

                cap_rect, cap_text = chosen_caption

                # Expand caption to include multi-line caption continuations directly below cap_rect
                for b in page_blocks:
                    b_rect = fitz.Rect(b[:4])
                    b_str = b[4].strip()
                    if b_str == cap_text:
                        continue
                    if -2 <= (b_rect.y0 - cap_rect.y1) <= 18:
                        if max(b_rect.x0, cap_rect.x0 - 40) < min(b_rect.x1, cap_rect.x1 + 40):
                            if not b_str.endswith("?") and not re.match(r'^(?:Activity|\d+\.|\d+\s+[A-Z]|Fig|Table|Q\.)', b_str, re.IGNORECASE):
                                if len(b_str.split()) <= 12:
                                    cap_rect = cap_rect | b_rect

                img_list = page.get_images(full=True)
                best_img = None
                min_dist = float("inf")
                all_valid_imgs = []

                for img in img_list:
                    xref = img[0]
                    base_image = doc.extract_image(xref)
                    if not base_image:
                        continue
                    ext = (base_image.get("ext") or "png").lower()
                    if ext not in ["png", "jpg", "jpeg", "webp"]:
                        continue
                    if base_image.get("colorspace") == 1:
                        continue
                    w = base_image.get("width", 0)
                    h = base_image.get("height", 0)
                    img_data = base_image.get("image", b"")
                    if (w < 35 and h < 35) or len(img_data) < 1500:
                        continue
                    aspect = w / max(h, 1)
                    if (0.64 <= aspect <= 0.82) and h >= 750 and w >= 550:
                        continue

                    r_list = page.get_image_rects(xref)
                    if not r_list:
                        continue
                    r = r_list[0]
                    if r.width > page.rect.width * 0.9 and r.height > page.rect.height * 0.9:
                        continue

                    dx = max(0, max(cap_rect.x0 - r.x1, r.x0 - cap_rect.x1))
                    dy = max(0, max(cap_rect.y0 - r.y1, r.y0 - cap_rect.y1))
                    dist = math.hypot(dx, dy)
                    all_valid_imgs.append((r, dist, xref))
                    if dist < min_dist:
                        min_dist = dist
                        best_img = (r, dist, xref)

                if not best_img or best_img[1] > 140:
                    continue

                r_best, _, _ = best_img
                # Cluster ONLY horizontally co-aligned sub-images (e.g. 3 thermometers at the same vertical band)
                cluster_rect = r_best
                for r, dist, _ in all_valid_imgs:
                    if dist <= 140:
                        v_overlap = min(r.y1, r_best.y1) - max(r.y0, r_best.y0)
                        if v_overlap > min(r.height, r_best.height) * 0.4:
                            cluster_rect = cluster_rect | r

                # Include short diagram labels (e.g., 'X', 'Y', '1', '2', 'A', 'B') located immediately beside cluster_rect
                for b in page_blocks:
                    b_rect = fitz.Rect(b[:4])
                    b_str = b[4].strip()
                    if b_str == cap_text:
                        continue
                    if len(b_str.split()) <= 2 and not b_str.endswith("?") and not re.match(r'^\d+\.\s', b_str):
                        if (cluster_rect.y0 - 15 <= b_rect.y0 <= cluster_rect.y1 + 15 or cluster_rect.y0 - 15 <= b_rect.y1 <= cluster_rect.y1 + 15):
                            dx = max(0, max(cluster_rect.x0 - b_rect.x1, b_rect.x0 - cluster_rect.x1))
                            if dx <= 35:
                                cluster_rect = cluster_rect | b_rect

                crop_rect = cluster_rect | cap_rect

                # Prevent right-side and left-side text bleeding: find nearest text columns
                max_x1 = page.rect.width
                min_x0 = 0.0
                for b in page_blocks:
                    b_rect = fitz.Rect(b[:4])
                    b_str = b[4].strip()
                    if b_str == cap_text or len(b_str.split()) <= 2:
                        continue
                    if b_rect.x0 >= crop_rect.x1 - 5 and max(b_rect.y0, crop_rect.y0) < min(b_rect.y1, crop_rect.y1):
                        if b_rect.x0 < max_x1:
                            max_x1 = b_rect.x0 - 2
                    if b_rect.x1 <= crop_rect.x0 + 5 and max(b_rect.y0, crop_rect.y0) < min(b_rect.y1, crop_rect.y1):
                        if b_rect.x1 > min_x0:
                            min_x0 = b_rect.x1 + 2

                pad_x = 6
                pad_y = 8
                padded_rect = fitz.Rect(
                    max(min_x0, crop_rect.x0 - pad_x),
                    max(0, crop_rect.y0 - pad_y),
                    min(max_x1, crop_rect.x1 + pad_x),
                    min(page.rect.height, crop_rect.y1 + pad_y)
                )
                pix = page.get_pixmap(clip=padded_rect, dpi=180)
                img_bytes = pix.tobytes("png")

                # Smart Background Whitener: Erase faint grey watermarks (e.g. 'NCERT not to be republished')
                try:
                    pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                    pixels = pil_img.load()
                    p_w, p_h = pil_img.size
                    for py in range(p_h):
                        for px in range(p_w):
                            pr, pg, pb = pixels[px, py]
                            # Neutral light grey watermark removal (NCERT watermark is solid 232 or anti-aliased 195-254)
                            if pr >= 195 and pg >= 195 and pb >= 195 and abs(pr - pg) <= 10 and abs(pg - pb) <= 12:
                                pixels[px, py] = (255, 255, 255)
                    buf = io.BytesIO()
                    pil_img.save(buf, format="PNG")
                    img_bytes = buf.getvalue()
                except Exception:
                    pass

                doc.close()
                return img_bytes, pno

        # =========================================================================
        # PATH 3: UNLABELLED VISUAL / DIAGRAM ON TARGET PAGE (GENERIC QUERIES ONLY)
        # =========================================================================
        if (clean_label.lower() in ["visual", "diagram", "apparatus", "image"]) and target_p and 1 <= target_p <= total_pages:
            page = doc[target_p - 1]
            img_list = page.get_images(full=True)
            for img in img_list:
                xref = img[0]
                base_image = doc.extract_image(xref)
                if not base_image or base_image.get("ext", "").lower() not in ["png", "jpg", "jpeg", "webp"]:
                    continue
                w = base_image.get("width", 0)
                h = base_image.get("height", 0)
                if w < 120 or h < 100:
                    continue
                aspect = w / max(h, 1)
                if (0.64 <= aspect <= 0.82) and h >= 750 and w >= 550:
                    continue
                r_list = page.get_image_rects(xref)
                if r_list:
                    r = r_list[0]
                    pad = 6
                    padded_rect = fitz.Rect(max(0, r.x0 - pad), max(0, r.y0 - pad), min(page.rect.width, r.x1 + pad), min(page.rect.height, r.y1 + pad))
                    pix = page.get_pixmap(clip=padded_rect, dpi=180)
                    img_bytes = pix.tobytes("png")
                    try:
                        pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                        pixels = pil_img.load()
                        p_w, p_h = pil_img.size
                        for py in range(p_h):
                            for px in range(p_w):
                                pr, pg, pb = pixels[px, py]
                                if pr >= 195 and pg >= 195 and pb >= 195 and abs(pr - pg) <= 10 and abs(pg - pb) <= 12:
                                    pixels[px, py] = (255, 255, 255)
                        buf = io.BytesIO()
                        pil_img.save(buf, format="PNG")
                        img_bytes = buf.getvalue()
                    except Exception:
                        pass
                    doc.close()
                    return img_bytes, target_p

        doc.close()
        return None, None
    except Exception as e:
        logger.warning(f"Precision 3-layer crop notice for Fig {fig_label} (p.{page_num}): {e}")
        return None, None


class DiagramList(list):
    """Subclass of list that allows attaching extraction metadata/metrics."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.metrics = {}


def extract_pdf_diagrams(file_bytes: bytes, max_diagrams: int = 150) -> list[dict]:
    """Extracts candidate embedded diagrams and figures from PDF in-memory without polluting disk.
    Applies strict academic diagram heuristics:
    1. Rejects full-page scanned text pages (where the entire page is an image).
    2. Rejects decorative icons, bullets, thought bubbles, and text banners.
    3. Retains true pedagogical diagrams (geometry, circuits, anatomy, maps, graphs).
    4. Computes exact spatial bounding-box caption and nearby text for precision matching.
    Returns list of diagram dicts with attached `.metrics` summary dict.
    """
    extracted_diagrams = DiagramList()
    metrics = {
        "total_raw_images": 0,
        "valid_diagrams": 0,
        "scanned_pages_rejected": 0,
        "icons_filtered": 0,
        "invalid_format_rejected": 0,
        "yield_pct": 0.0,
    }
    if not file_bytes:
        extracted_diagrams.metrics = metrics
        return extracted_diagrams

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        saved_count = 0

        for page_idx, page in enumerate(doc):
            page_num = page_idx + 1
            images = page.get_images(full=True)
            page_rect = page.rect
            page_width = page_rect.width
            page_height = page_rect.height
            page_text = page.get_text() or ""
            page_blocks = page.get_text("blocks") or []
            page_figs = [f.strip() for f in re.findall(r'\b(?:fig(?:ure)?\.?)\s*(\d+(?:\.\d+)?)\b', page_text, re.IGNORECASE)]

            for img_idx, img_info in enumerate(images):
                metrics["total_raw_images"] += 1
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                if not base_image:
                    continue

                image_bytes = base_image.get("image")
                image_ext = (base_image.get("ext") or "png").lower().strip()
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)

                # STRICT FILTER 1: Reject JPX (JPEG2000 masks) and non-web formats
                if image_ext not in VALID_IMAGE_EXTS:
                    metrics["invalid_format_rejected"] += 1
                    continue

                # STRICT FILTER 2: Filter out tiny icon decorations, bullets, thought bubbles, or decorative avatars
                if width < 140 or height < 120 or not image_bytes or len(image_bytes) < 5120:
                    metrics["icons_filtered"] += 1
                    continue

                # STRICT FILTER 3: Filter out extreme aspect ratio banners (e.g., NCERT header banners, sidebar bars)
                aspect = width / max(height, 1)
                if aspect > 3.0 or aspect < 0.25:
                    metrics["icons_filtered"] += 1
                    continue
                if aspect > 2.2 and height < 160:
                    metrics["icons_filtered"] += 1
                    continue

                # STRICT FILTER 4: REJECT FULL-PAGE SCANNED TEXT PAGES
                is_portrait_page_scan = (0.64 <= aspect <= 0.82) and height >= 750 and width >= 550
                if is_portrait_page_scan:
                    metrics["scanned_pages_rejected"] += 1
                    continue

                # SPATIAL CAPTION & PROXIMITY EXTRACTION
                rects = page.get_image_rects(xref)
                img_rect_tuple = None
                nearby_captions = []
                direct_figs = []

                if rects:
                    r = rects[0]
                    img_rect_tuple = (round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1))
                    for b in page_blocks:
                        b_rect = fitz.Rect(b[:4])
                        # Check if text is directly below, above, or adjacent to the image
                        is_below = 0 <= (b_rect.y0 - r.y1) <= 90
                        is_above = 0 <= (r.y0 - b_rect.y1) <= 60
                        is_adjacent = (b_rect.y0 <= r.y1 and b_rect.y1 >= r.y0) and (abs(b_rect.x0 - r.x1) <= 180 or abs(r.x0 - b_rect.x1) <= 180)
                        
                        if is_below or is_above or is_adjacent:
                            clean_b = b[4].strip().replace('\n', ' ')
                            if clean_b and len(clean_b) > 2:
                                nearby_captions.append(clean_b)
                                # Extract specific figure labels in this bounding vicinity (e.g. 'Fig. 4.16', 'Figure 7.10')
                                figs_found = re.findall(r'\b(?:fig(?:ure)?\.?)\s*(\d+(?:\.\d+)?)\b', clean_b, re.IGNORECASE)
                                for f in figs_found:
                                    direct_figs.append(f.strip())

                caption_str = " | ".join(nearby_captions[:3])
                
                # Filter out pure Page 1 story illustrations (introductory cliparts with no academic figure context)
                if page_num == 1 and not direct_figs:
                    is_story_clipart = any(w in caption_str.lower() for w in ["story", "fond of writing", "grandmother", "lived in", "trade in the olden days"])
                    if is_story_clipart:
                        metrics["icons_filtered"] += 1
                        continue

                # Combine direct figures with page-level figures
                all_figs = list(dict.fromkeys(direct_figs + page_figs))

                if saved_count < max_diagrams:
                    extracted_diagrams.append({
                        "image_bytes": image_bytes,
                        "ext": image_ext,
                        "page": page_num,
                        "rect": img_rect_tuple,
                        "caption": caption_str[:250],
                        "direct_figures": direct_figs,
                        "figures": all_figs,
                        "width": width,
                        "height": height,
                        "aspect": round(aspect, 2),
                        "size_kb": round(len(image_bytes) / 1024, 1),
                    })
                    saved_count += 1

        doc.close()
    except Exception as e:
        logger.warning(f"In-memory diagram extraction notice: {e}")

    metrics["valid_diagrams"] = len(extracted_diagrams)
    if metrics["total_raw_images"] > 0:
        metrics["yield_pct"] = round((metrics["valid_diagrams"] / metrics["total_raw_images"]) * 100, 1)

    extracted_diagrams.metrics = metrics
    return extracted_diagrams



def clean_text(raw_text: str) -> str:
    cleaned = strip_non_academic_preamble(raw_text)
    lines = [line.strip() for line in cleaned.splitlines()]
    return "\n".join(line for line in lines if line)


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    if not text:
        return []
    chunks = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        chunks.append(text[start:end])
        if end == length:
            break
        start = end - overlap
    return chunks


BOARD_PATTERNS = {
    "CBSE": [r"\bcbse\b", r"central\s+board\s+of\s+secondary\s+education"],
    "ICSE": [r"\bicse\b", r"indian\s+certificate\s+of\s+secondary\s+education"],
    "ISC": [r"\bisc\b", r"indian\s+school\s+certificate\b"],
    "WBBSE": [r"\bwbbse\b", r"west\s+bengal\s+board\s+of\s+secondary", r"\bmadhyamik\b"],
    "WBCHSE": [r"\bwbchse\b", r"west\s+bengal\s+council\s+of\s+higher\s+secondary"],
    "UK-Cambridge": [r"\bcambridge\b", r"\bigcse\b", r"\bcie\b", r"\bcaie\b"],
    "NCERT": [r"\bncert\b", r"national\s+council\s+of\s+educational\s+research"],
    "NEET": [r"\bneet\b", r"national\s+eligibility\s+cum\s+entrance"],
    "IIT": [r"\biit\b", r"\bjee\b", r"joint\s+entrance\s+examination"],
}

CLASS_PATTERNS = {
    "Class 12": [r"\bclass\s*(?:12|xii)\b", r"\bgrade\s*(?:12|xii)\b", r"\bstd\s*(?:12|xii)\b", r"\bclass_12\b", r"\bclass-12\b"],
    "Class 11": [r"\bclass\s*(?:11|xi)\b", r"\bgrade\s*(?:11|xi)\b", r"\bstd\s*(?:11|xi)\b", r"\bclass_11\b", r"\bclass-11\b"],
    "Class 10": [r"\bclass\s*(?:10|x)\b", r"\bgrade\s*(?:10|x)\b", r"\bstd\s*(?:10|x)\b", r"\bclass_10\b", r"\bclass-10\b", r"\bmatric\b"],
    "Class 9": [r"\bclass\s*(?:9|ix)\b", r"\bgrade\s*(?:9|ix)\b", r"\bstd\s*(?:9|ix)\b", r"\bclass_9\b", r"\bclass-9\b"],
    "Class 8": [r"\bclass\s*(?:8|viii)\b", r"\bgrade\s*(?:8|viii)\b", r"\bstd\s*(?:8|viii)\b", r"\bclass_8\b", r"\bclass-8\b"],
    "Class 7": [r"\bclass\s*(?:7|vii)\b", r"\bgrade\s*(?:7|vii)\b", r"\bstd\s*(?:7|vii)\b", r"\bclass_7\b", r"\bclass-7\b"],
    "Class 6": [r"\bclass\s*(?:6|vi)\b", r"\bgrade\s*(?:6|vi)\b", r"\bstd\s*(?:6|vi)\b", r"\bclass_6\b", r"\bclass-6\b"],
    "Class 5": [r"\bclass\s*(?:5|v)\b", r"\bgrade\s*(?:5|v)\b", r"\bstd\s*(?:5|v)\b", r"\bclass_5\b", r"\bclass-5\b"],
    "Class 4": [r"\bclass\s*(?:4|iv)\b", r"\bgrade\s*(?:4|iv)\b", r"\bstd\s*(?:4|iv)\b", r"\bclass_4\b", r"\bclass-4\b"],
    "Class 3": [r"\bclass\s*(?:3|iii)\b", r"\bgrade\s*(?:3|iii)\b", r"\bstd\s*(?:3|iii)\b", r"\bclass_3\b", r"\bclass-3\b"],
    "Class 2": [r"\bclass\s*(?:2|ii)\b", r"\bgrade\s*(?:2|ii)\b", r"\bstd\s*(?:2|ii)\b", r"\bclass_2\b", r"\bclass-2\b"],
    "Class 1": [r"\bclass\s*(?:1|i)\b", r"\bgrade\s*(?:1|i)\b", r"\bstd\s*(?:1|i)\b", r"\bclass_1\b", r"\bclass-1\b"],
}

SUBJECT_PATTERNS = {
    "Biology": [
        r"\bbiology\b", r"\bbotany\b", r"\bzoology\b", r"\blife\s+processes\b",
        r"\bphotosynthesis\b", r"\brespiration\b", r"\bhuman\s+anatomy\b", r"\bphysiology\b",
        r"\bcell(?:ular)?\b", r"\bgenetics\b", r"\bheredity\b", r"\bevolution\b",
        r"\breproduction\b", r"\bdigestive\b", r"\bcirculatory\b", r"\bexcretory\b",
        r"\bplant\s+kingdom\b", r"\banimal\s+kingdom\b", r"\becosystem\b", r"\bbiodiversity\b",
        r"\bbiotechnology\b", r"\bmicroorganisms\b", r"\bimmune\s+system\b", r"\bchromosomes?\b"
    ],
    "Chemistry": [
        r"\bchemistry\b", r"\bchemical\s+reactions?\b", r"\bchemical\s+equations?\b",
        r"\bacids?,\s*bases?\b", r"\bmetals?\s+and\s+non-metals?\b", r"\bcarbon\s+and\s+its\s+compounds\b",
        r"\bperiodic\s+(?:table|classification)\b", r"\bmole\s+concept\b", r"\batomic\s+structure\b",
        r"\bchemical\s+bonding\b", r"\borganic\s+chemistry\b", r"\binorganic\s+chemistry\b",
        r"\belectrochemistry\b", r"\bchemical\s+kinetics\b", r"\bthermodynamics\b", r"\boxidation\b",
        r"\breduction\b", r"\bsolutions?\b", r"\bequilibrium\b", r"\bhydrocarbons\b"
    ],
    "Physics": [
        r"\bphysics\b", r"\bkinematics\b", r"\bmotion\b", r"\bforce\s+and\s+laws\s+of\s+motion\b",
        r"\bgravitation\b", r"\bwork,\s*energy\s+and\s+power\b", r"\bsound\b", r"\blight\s*-\s*reflection\b",
        r"\brefraction\b", r"\bhuman\s+eye\b", r"\belectricity\b", r"\bcurrent\s+electricity\b",
        r"\belectromagnetism\b", r"\bmagnetic\s+effects?\b", r"\boptics\b", r"\belectrostatics\b",
        r"\bthermodynamics\b", r"\bsemiconductors?\b", r"\bdual\s+nature\b", r"\bnuclei\b", r"\batoms\b"
    ],
    "Mathematics": [
        r"\bmathematics\b", r"\bmaths\b", r"\bmath\b", r"\balgebra\b", r"\bcalculus\b",
        r"\bgeometry\b", r"\btrigonometry\b", r"\breal\s+numbers\b", r"\bpolynomials?\b",
        r"\bquadratic\s+equations?\b", r"\barithmetic\s+progression\b", r"\bstatistics\b",
        r"\bprobability\b", r"\bmatrices\b", r"\bdeterminants\b", r"\bintegrals?\b",
        r"\bdifferential\s+equations?\b", r"\bvectors?\b", r"\blinear\s+equations?\b"
    ],
    "Computer Science": [
        r"\bcomputer\s+science\b", r"\binformatics\b", r"\bpython\b", r"\bdata\s+structures?\b",
        r"\bcoding\b", r"\bprogramming\b", r"\bdatabase\b", r"\bsql\b", r"\balgorithms?\b",
        r"\bcyber\s+safety\b", r"\bcomputer\s+networks?\b", r"\bcomputer\s+applications\b", r"\bit\b"
    ],
    "English": [
        r"\benglish\s+language\b", r"\benglish\s+literature\b", r"\benglish\s+grammar\b",
        r"\bfirst\s+flight\b", r"\bfootprints\s+without\s+feet\b", r"\bbeehive\b",
        r"\bmoments\b", r"\bhoneydew\b", r"\bcomprehension\b", r"\bprose\b", r"\bpoetry\b",
        r"\bflamingo\b", r"\bvistas\b", r"\bhornbill\b", r"\bsnapshots\b", r"\bmarigold\b"
    ],
    "Hindi": [
        r"\bhindi\b", r"\bhindi\s+literature\b", r"\bhindi\s+grammar\b", r"\bvyakaran\b",
        r"\bkshitij\b", r"\bkritika\b", r"\bsparsh\b", r"\bsanchayan\b", r"\bvasant\b",
        r"\brimjhim\b", r"\baroh\b", r"\bvitan\b", r"\bantra\b", r"\bantral\b",
        r"\bsandhi\b", r"\bsamas\b", r"\bmuhavare\b", r"\bpatra\s+lekhan\b", r"\bnibandh\b",
        r"[\u0900-\u097F]"  # Devanagari script presence
    ],
    "Bengali": [
        r"\bbengali\b", r"\bbangla\b", r"\bbangla\s+sahitya\b", r"\bbyakaran\b",
        r"[\u0980-\u09FF]"  # Bengali script presence
    ],
    "Sanskrit": [
        r"\bsanskrit\b", r"\bsanskrith\b", r"\bshemushi\b", r"\bruchira\b", r"\bshloka\b",
        r"\bshabda\s+roop\b", r"\bdhatu\s+roop\b", r"\bvibhakti\b"
    ],
    "Accountancy": [
        r"\baccountancy\b", r"\baccounting\b", r"\baccounts?\b", r"\bjournal\s+entry\b",
        r"\bledger\b", r"\btrial\s+balance\b", r"\bbalance\s+sheet\b", r"\bdepreciation\b",
        r"\bpartnership\s+accounts?\b", r"\bgoodwill\b", r"\bshare\s+capital\b",
        r"\bdebentures?\b", r"\bcash\s+flow\s+statement\b", r"\bfinancial\s+statements?\b",
        r"\bratio\s+analysis\b", r"\baccounting\s+standards?\b"
    ],
    "Business Studies": [
        r"\bbusiness\s+studies\b", r"\bbusiness\s+organization\b", r"\bcommerce\b",
        r"\bprinciples\s+of\s+management\b", r"\bplanning\b", r"\borganising\b",
        r"\bstaffing\b", r"\bdirecting\b", r"\bcontrolling\b", r"\bmarketing\s+management\b",
        r"\bfinancial\s+management\b", r"\bfinancial\s+markets?\b", r"\bconsumer\s+protection\b"
    ],
    "Economics": [
        r"\beconomics\b", r"\bmicroeconomics\b", r"\bmacroeconomics\b", r"\bnational\s+income\b",
        r"\bmoney\s+and\s+banking\b", r"\bdemand\s+and\s+supply\b", r"\belasticity\b",
        r"\bgdp\b", r"\binflation\b", r"\bfiscal\s+policy\b", r"\bmonetary\s+policy\b",
        r"\bindian\s+economic\s+development\b", r"\bstatistics\s+for\s+economics\b"
    ],
    "Political Science": [
        r"\bpolitical\s+science\b", r"\bpolitics\b", r"\bcivics\b", r"\bconstitution\b",
        r"\bdemocracy\b", r"\bfederalism\b", r"\belection\b", r"\blegislature\b",
        r"\bexecutive\b", r"\bjudiciary\b", r"\bpolitical\s+theory\b",
        r"\bcontemporary\s+world\s+politics\b", r"\bindian\s+politics\b"
    ],
    "Physical Education": [
        r"\bphysical\s+education\b", r"\bphys\s*ed\b", r"\byoga\b", r"\bsports\b",
        r"\bfitness\b", r"\bnutrition\b", r"\bplanning\s+in\s+sports\b", r"\bbiomechanics\b",
        r"\bexercise\s+physiology\b", r"\btraining\s+in\s+sports\b", r"\banatomy\s+and\s+physiology\b"
    ],
    "Geography": [
        r"\bgeography\b", r"\bphysical\s+geography\b", r"\bhuman\s+geography\b",
        r"\bresources\s+and\s+development\b", r"\bclimate\b", r"\bsoils?\b",
        r"\bagriculture\b", r"\bminerals?\b", r"\bmanufacturing\s+industries\b",
        r"\bpopulation\b", r"\bmap\s+work\b", r"\btopography\b"
    ],
    "History": [
        r"\bhistory\b", r"\bancient\s+history\b", r"\bmedieval\s+history\b", r"\bmodern\s+history\b",
        r"\bworld\s+history\b", r"\bharappan\s+civilisation\b", r"\bnationalism\s+in\s+india\b",
        r"\bfrench\s+revolution\b", r"\brussian\s+revolution\b", r"\bindustrial\s+revolution\b",
        r"\bcolonialism\b", r"\bmughal\s+empire\b", r"\bmurti\b", r"\btreaty\b"
    ],
    "Social Studies": [
        r"\bsocial\s+science\b", r"\bsocial\s+studies\b", r"\bhistory\b", r"\bgeography\b",
        r"\bcivics\b", r"\beconomics\b", r"\bpolitical\s+science\b", r"\bdemocratic\s+politics\b",
        r"\bcontemporary\s+india\b", r"\bindia\s+and\s+the\s+contemporary\s+world\b"
    ],
    "Science": [
        r"\bscience\b", r"\bscientific\b", r"\bgeneral\s+science\b", r"\bnatural\s+science\b",
        r"\benvironmental\s+studies\b", r"\bevs\b", r"\bthe\s+world\s+around\s+us\b"
    ]
}


def is_subject_compatible(target_subject: str, detected_subject: str, class_grade: str = "") -> bool:
    """Checks whether detected subject is compatible with target dropdown subject,

    with full support for class tiers (Class 1-10 unified vs Class 11-12 split streams).
    """
    t = (target_subject or "").strip().lower()
    d = (detected_subject or "").strip().lower()

    if not t or not d:
        return True
    if t == d:
        return True

    # 1. Biology (Botanical, Zoological, Life Sciences)
    bio_synonyms = {"biology", "botany", "zoology", "life science", "life sciences", "bio", "anatomy", "physiology"}
    if t in bio_synonyms and d in bio_synonyms:
        return True

    # 2. Chemistry (Chemical sciences)
    chem_synonyms = {"chemistry", "chemical science", "organic chemistry", "inorganic chemistry", "physical chemistry", "chem"}
    if t in chem_synonyms and d in chem_synonyms:
        return True

    # 3. Physics (Physical sciences)
    phys_synonyms = {"physics", "applied physics", "phys", "physical science"}
    if t in phys_synonyms and d in phys_synonyms:
        return True

    # 4. Mathematics (Math, Calculus, Applied Math, Statistics)
    math_synonyms = {"mathematics", "math", "maths", "algebra", "geometry", "calculus", "applied mathematics", "pure mathematics", "statistics"}
    if t in math_synonyms and d in math_synonyms:
        return True

    # 5. Computer Science / IT / Informatics
    cs_synonyms = {"computer science", "informatics", "informatics practices", "python", "computer", "computer applications", "information technology", "it", "ai", "artificial intelligence"}
    if t in cs_synonyms and d in cs_synonyms:
        return True

    # 6. Languages (Hindi, Bengali, Sanskrit, English)
    hindi_synonyms = {"hindi", "hindi literature", "hindi grammar", "vyakaran", "kshitij", "sparsh"}
    if t in hindi_synonyms and d in hindi_synonyms:
        return True

    bengali_synonyms = {"bengali", "bangla", "bangla sahitya"}
    if t in bengali_synonyms and d in bengali_synonyms:
        return True

    sanskrit_synonyms = {"sanskrit", "sanskrith", "shemushi", "ruchira"}
    if t in sanskrit_synonyms and d in sanskrit_synonyms:
        return True

    eng_synonyms = {"english", "english language", "english literature", "grammar", "communicative english"}
    if t in eng_synonyms and d in eng_synonyms:
        return True

    # 7. Commerce Stream (Accountancy, Business Studies, Economics)
    commerce_synonyms = {"accountancy", "accounts", "business studies", "commerce", "commercial studies", "economics"}
    if t in commerce_synonyms and (d in commerce_synonyms or d in math_synonyms or d in {"mathematics", "math"}):
        return True
    if t in {"accountancy", "accounts"} and d in {"accountancy", "accounts", "commerce", "mathematics"}:
        return True
    if t in {"business studies", "commerce"} and d in {"business studies", "commerce", "commercial studies", "management"}:
        return True
    if t == "economics" and d in {"economics", "microeconomics", "macroeconomics", "statistics", "social science", "social studies"}:
        return True

    # 8. Humanities / Arts Stream (History, Geography, Political Science, Civics, Economics)
    arts_synonyms = {"history", "geography", "political science", "politics", "civics", "economics", "sociology", "psychology", "social studies", "social science", "sst"}
    if t in arts_synonyms and d in arts_synonyms:
        return True

    # 9. Physical Education / Health / Sports
    pe_synonyms = {"physical education", "health and physical education", "pe", "sports", "yoga", "fitness"}
    if t in pe_synonyms and (d in pe_synonyms or d in bio_synonyms or d in {"biology", "human anatomy"}):
        return True

    # 10. Unified Science Tier (For Class 1-10 or generalized curricula)
    science_cluster = {"science", "general science", "physics", "chemistry", "biology", "life science", "physical science", "environmental studies", "evs", "the world around us"}
    if t in {"science", "general science", "environmental studies", "evs", "the world around us"} and d in science_cluster:
        return True
    if t in {"physics", "chemistry", "biology"} and d in {"science", "general science", "physical science", "life science"}:
        return True

    # 11. Unified Social Studies Tier
    sst_cluster = {"social science", "social studies", "history", "geography", "civics", "political science", "economics", "sst", "democratic politics", "contemporary india"}
    if t in {"social science", "social studies", "sst"} and d in sst_cluster:
        return True
    if t in {"history", "geography", "political science", "civics", "economics"} and d in {"social science", "social studies", "sst"}:
        return True

    # Substring / partial match fallback
    if t in d or d in t:
        return True

    # Non-standard / custom subjects: Admin choice trusted
    return True


def detect_curriculum_metadata(sample_text: str = "") -> dict:
    """Detects Board, ClassGrade, and Subject strictly by scanning the document text content with frequency scoring."""
    normalized = re.sub(r"[-_.]", " ", sample_text or "").lower()
    
    detected_board = None
    for board_name, patterns in BOARD_PATTERNS.items():
        if any(re.search(p, normalized, re.IGNORECASE) for p in patterns):
            detected_board = board_name
            break

    detected_class = None
    for class_name, patterns in CLASS_PATTERNS.items():
        if any(re.search(p, normalized, re.IGNORECASE) for p in patterns):
            detected_class = class_name
            break

    # Subject frequency scoring
    subject_scores: dict[str, int] = {}
    for subject_name, patterns in SUBJECT_PATTERNS.items():
        score = 0
        for p in patterns:
            matches = re.findall(p, normalized, re.IGNORECASE)
            score += len(matches)
        if score > 0:
            subject_scores[subject_name] = score

    # Pick the highest scoring subject, prioritizing specific disciplines over generic Science
    detected_subject = None
    if subject_scores:
        # If specific disciplines scored, ignore generic Science
        specific_scored = {k: v for k, v in subject_scores.items() if k != "Science"}
        if specific_scored:
            detected_subject = max(specific_scored.items(), key=lambda x: x[1])[0]
        else:
            detected_subject = max(subject_scores.items(), key=lambda x: x[1])[0]

    return {
        "board": detected_board,
        "classGrade": detected_class,
        "subject": detected_subject,
    }


def validate_curriculum_metadata(
    filename: str,
    raw_text: str,
    target_board: str | None,
    target_class: str | None,
    target_subject: str | None,
):
    """Validates that target dropdown values match detected content in file/text."""
    norm_fn = re.sub(r"[-_.]", " ", filename or "").lower()
    norm_sample = re.sub(r"[-_.]", " ", (raw_text or "")[:10000]).lower()
    combined = f"{norm_fn} {norm_sample}".strip()

    if not combined:
        return

    # 1. Validate Board (lenient warning)
    if target_board:
        t_board = target_board.upper().strip()
        t_patterns = BOARD_PATTERNS.get(t_board, [])
        t_matched = any(re.search(p, combined, re.IGNORECASE) for p in t_patterns)

        if not t_matched:
            if t_board in ["CBSE", "NCERT"] and any(re.search(p, combined, re.IGNORECASE) for p in BOARD_PATTERNS.get("NCERT", []) + BOARD_PATTERNS.get("CBSE", [])):
                t_matched = True
            elif t_board in ["ICSE", "ISC"] and any(re.search(p, combined, re.IGNORECASE) for p in BOARD_PATTERNS.get("ICSE", []) + BOARD_PATTERNS.get("ISC", [])):
                t_matched = True

        if not t_matched:
            # Check filename specifically for board clash
            for b_name, patterns in BOARD_PATTERNS.items():
                if b_name == t_board or (t_board in ["CBSE", "NCERT"] and b_name in ["CBSE", "NCERT"]):
                    continue
                if any(re.search(p, norm_fn, re.IGNORECASE) for p in patterns):
                    logger.warning(f"Board check: Filename '{filename}' suggests '{b_name}' while '{target_board}' was selected.")
                    break

    # 2. Validate Class
    if target_class:
        t_class = target_class.strip()
        t_patterns = CLASS_PATTERNS.get(t_class, [])
        t_matched = any(re.search(p, combined, re.IGNORECASE) for p in t_patterns)

        if not t_matched:
            for c_name, patterns in CLASS_PATTERNS.items():
                if c_name.lower().replace(" ", "") == t_class.lower().replace(" ", ""):
                    continue
                if any(re.search(p, norm_fn, re.IGNORECASE) for p in patterns):
                    logger.warning(f"Class check: Filename '{filename}' suggests '{c_name}' while '{target_class}' was selected.")
                    break

    # 3. Validate Subject
    if target_subject:
        t_sub = target_subject.strip()
        t_patterns = SUBJECT_PATTERNS.get(t_sub, [])
        t_matched = any(re.search(p, combined, re.IGNORECASE) for p in t_patterns)

        if not t_matched and t_sub.lower() in ["science", "physics", "chemistry", "biology"]:
            science_all = SUBJECT_PATTERNS.get("Science", []) + SUBJECT_PATTERNS.get("Physics", []) + SUBJECT_PATTERNS.get("Chemistry", []) + SUBJECT_PATTERNS.get("Biology", [])
            if any(re.search(p, combined, re.IGNORECASE) for p in science_all):
                t_matched = True

        if not t_matched:
            logger.info(f"Custom curriculum subject '{target_subject}' accepted for '{filename}'.")


def validate_book_and_question_bank(
    filename: str,
    raw_text: str,
    board: str | None = None,
    class_grade: str | None = None,
    subject: str | None = None,
    year_declared: str | None = None,
):
    """Validates that uploaded file is a structured Book or Question Bank from the last 10-15 years (2011-2026)."""
    clean_fn = (filename or "").lower()
    ext = clean_fn.rsplit(".", 1)[-1].lower() if "." in clean_fn else ""
    if ext not in {"pdf", "docx", "doc"}:
        raise ValidationError(f"Invalid file format '.{ext}'. Only structured PDF, DOC, and DOCX files are supported.")

    sample_text = (raw_text or "")[:15000].lower()
    combined = f"{clean_fn} {sample_text}"

    # 1. Year Validation (2011 to 2026 - last 10-15 years)
    current_year = 2026
    min_allowed_year = current_year - 15  # 2011
    max_allowed_year = current_year + 1   # 2027

    # Check if year is declared in form
    declared_yr = None
    if year_declared and str(year_declared).strip().isdigit():
        declared_yr = int(year_declared.strip())
        if declared_yr < min_allowed_year or declared_yr > max_allowed_year:
            raise ValidationError(
                f"Year Restriction: Only Books and Question Banks from the last 10–15 years ({min_allowed_year}–{current_year}) are accepted. "
                f"Declared year {declared_yr} is outside the allowed curriculum range."
            )

    # Detect 4-digit years in filename and header text
    found_years = [int(y) for y in re.findall(r'\b(19\d{2}|20\d{2})\b', combined)]
    if found_years:
        valid_years = [y for y in found_years if min_allowed_year <= y <= max_allowed_year]
        outdated_years = [y for y in found_years if y < min_allowed_year]
        if not valid_years and outdated_years and not declared_yr:
            earliest = min(outdated_years)
            raise ValidationError(
                f"Outdated Document: Document indicates publication year {earliest}. "
                f"Only Books and Question Banks from the last 10–15 years ({min_allowed_year}–{current_year}) are accepted."
            )

    # 2. Board Validation (Only CBSE, ICSE, ISC)
    if board:
        norm_board = board.upper().strip()
        if norm_board not in {"CBSE", "ICSE", "ISC", "NCERT"}:
            raise ValidationError(f"Scope Restriction: Only CBSE, ICSE, and ISC boards are supported. Found: {board}")

    # 3. Class Validation (Class 5 to 10)
    if class_grade:
        match = re.search(r'(?:class|grade)?\s*(\d+)', class_grade.lower())
        if match:
            cnum = int(match.group(1))
            if cnum < 5 or cnum > 10:
                raise ValidationError(f"Scope Restriction: Supported classes are Class 5 to Class 10. Found: {class_grade}")

    return True

