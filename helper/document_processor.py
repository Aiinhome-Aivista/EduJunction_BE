"""Text extraction + chunking for uploaded curriculum documents.
Supports PDF (.pdf), Word (.docx, .doc), Rich Text (.rtf), Plain Text (.txt), and CSV (.csv).
"""
import csv
import io
import re

from pypdf import PdfReader
from docx import Document as DocxDocument

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


def extract_text(file_bytes: bytes, ext: str) -> str:
    """Extracts text from uploaded files based on extension."""
    if ext == "pdf":
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    
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


def clean_text(raw_text: str) -> str:
    lines = [line.strip() for line in raw_text.splitlines()]
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
    "Mathematics": [r"\bmathematics\b", r"\bmaths\b", r"\bmath\b", r"\balgebra\b", r"\bcalculus\b", r"\bgeometry\b", r"\btrigonometry\b"],
    "Physics": [r"\bphysics\b", r"\bkinematics\b", r"\belectrodynamics\b", r"\bthermodynamics\b", r"\boptics\b"],
    "Chemistry": [r"\bchemistry\b", r"\borganic\s+chemistry\b", r"\binorganic\s+chemistry\b", r"\bchemical\s+bonding\b"],
    "Biology": [r"\bbiology\b", r"\bzoology\b", r"\bbotany\b", r"\bgenetics\b", r"\bhuman\s+anatomy\b"],
    "Computer Science": [r"\bcomputer\s+science\b", r"\binformatics\b", r"\bpython\b", r"\bdata\s+structure\b", r"\bcoding\b"],
    "English": [r"\benglish\b", r"\bgrammar\b", r"\bliterature\b", r"\bprose\b", r"\bpoetry\b"],
    "Social Studies": [r"\bsocial\s+science\b", r"\bsocial\s+studies\b", r"\bhistory\b", r"\bgeography\b", r"\bcivics\b", r"\beconomics\b"],
}


def detect_curriculum_metadata(filename: str, sample_text: str = "") -> dict:
    """Detects Board, ClassGrade, and Subject from filename and header text."""
    combined = f"{filename} {sample_text}"
    # Replace underscores, hyphens, and dots with spaces so word boundary regex matches correctly
    normalized = re.sub(r"[-_.]", " ", combined).lower()
    
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

    detected_subject = None
    for subject_name, patterns in SUBJECT_PATTERNS.items():
        if any(re.search(p, normalized, re.IGNORECASE) for p in patterns):
            detected_subject = subject_name
            break

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

    # 1. Validate Board
    if target_board:
        t_board = target_board.upper().strip()
        t_patterns = BOARD_PATTERNS.get(t_board, [])
        t_matched = any(re.search(p, combined, re.IGNORECASE) for p in t_patterns)

        # Check council/board compatibility
        if not t_matched:
            if t_board in ["CBSE", "NCERT"] and any(re.search(p, combined, re.IGNORECASE) for p in BOARD_PATTERNS.get("NCERT", []) + BOARD_PATTERNS.get("CBSE", [])):
                t_matched = True
            elif t_board in ["ICSE", "ISC"] and any(re.search(p, combined, re.IGNORECASE) for p in BOARD_PATTERNS.get("ICSE", []) + BOARD_PATTERNS.get("ISC", [])):
                t_matched = True

        # If target board did not match, check if another distinct board was explicitly detected
        if not t_matched:
            detected_other_board = None
            for check_str in [norm_fn, norm_sample[:1500]]:
                for b_name, patterns in BOARD_PATTERNS.items():
                    if b_name == t_board:
                        continue
                    if (t_board in ["CBSE", "NCERT"] and b_name in ["CBSE", "NCERT"]):
                        continue
                    if (t_board in ["ICSE", "ISC"] and b_name in ["ICSE", "ISC"]):
                        continue
                    if any(re.search(p, check_str, re.IGNORECASE) for p in patterns):
                        detected_other_board = b_name
                        break
                if detected_other_board:
                    break

            if detected_other_board:
                raise ValidationError(
                    f"Board Mismatch: Document content/filename indicates '{detected_other_board}', "
                    f"but '{target_board}' was selected in the dropdown. Please select the matching Board."
                )

    # 2. Validate Class
    if target_class:
        t_class = target_class.strip()
        t_patterns = CLASS_PATTERNS.get(t_class, [])
        t_matched = any(re.search(p, combined, re.IGNORECASE) for p in t_patterns)

        if not t_matched:
            detected_other_class = None
            for check_str in [norm_fn, norm_sample[:1500]]:
                for c_name, patterns in CLASS_PATTERNS.items():
                    if c_name.lower().replace(" ", "") == t_class.lower().replace(" ", ""):
                        continue
                    if any(re.search(p, check_str, re.IGNORECASE) for p in patterns):
                        detected_other_class = c_name
                        break
                if detected_other_class:
                    break

            if detected_other_class:
                raise ValidationError(
                    f"Class Mismatch: Document content/filename indicates '{detected_other_class}', "
                    f"but '{target_class}' was selected in the dropdown. Please select '{detected_other_class}'."
                )

    # 3. Validate Subject
    if target_subject:
        t_sub = target_subject.strip()
        t_patterns = SUBJECT_PATTERNS.get(t_sub, [])
        t_matched = any(re.search(p, combined, re.IGNORECASE) for p in t_patterns)

        if not t_matched and t_sub.lower() == "science":
            if any(re.search(p, combined, re.IGNORECASE) for p in SUBJECT_PATTERNS.get("Physics", []) + SUBJECT_PATTERNS.get("Chemistry", []) + SUBJECT_PATTERNS.get("Biology", [])):
                t_matched = True

        if not t_matched:
            detected_other_subject = None
            for check_str in [norm_fn, norm_sample[:1500]]:
                for s_name, patterns in SUBJECT_PATTERNS.items():
                    if s_name.lower() == t_sub.lower():
                        continue
                    if t_sub.lower() == "science" and s_name in ["Physics", "Chemistry", "Biology"]:
                        continue
                    if any(re.search(p, check_str, re.IGNORECASE) for p in patterns):
                        detected_other_subject = s_name
                        break
                if detected_other_subject:
                    break

            if detected_other_subject:
                raise ValidationError(
                    f"Subject Mismatch: Document content/filename indicates '{detected_other_subject}', "
                    f"but '{target_subject}' was selected in the dropdown. Please select '{detected_other_subject}'."
                )
