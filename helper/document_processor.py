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

        # 3. Third fallback: Multimodal Gemini Vision OCR for scanned image PDFs / photos
        logger.info(f"Digital text extraction yielded < 80 characters. Falling back to Gemini Vision OCR...")
        try:
            from helper.ocr_vision_engine import extract_scanned_pdf_with_vision
            vision_text = extract_scanned_pdf_with_vision(file_bytes, board=board, class_grade=class_grade, subject=subject)
            if vision_text and vision_text.strip():
                return vision_text.strip()
        except Exception as vision_err:
            logger.error(f"Gemini Vision OCR fallback failed: {vision_err}")

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
        r"\bcyber\s+safety\b", r"\bcomputer\s+networks?\b"
    ],
    "English": [
        r"\benglish\s+language\b", r"\benglish\s+literature\b", r"\benglish\s+grammar\b",
        r"\bfirst\s+flight\b", r"\bfootprints\s+without\s+feet\b", r"\bbeehive\b",
        r"\bmoments\b", r"\bhoneydew\b", r"\bcomprehension\b", r"\bprose\b", r"\bpoetry\b"
    ],
    "Social Studies": [
        r"\bsocial\s+science\b", r"\bsocial\s+studies\b", r"\bhistory\b", r"\bgeography\b",
        r"\bcivics\b", r"\beconomics\b", r"\bpolitical\s+science\b", r"\bdemocratic\s+politics\b",
        r"\bcontemporary\s+india\b", r"\bindia\s+and\s+the\s+contemporary\s+world\b"
    ],
    "Science": [
        r"\bscience\b", r"\bscientific\b", r"\bgeneral\s+science\b", r"\bnatural\s+science\b"
    ]
}


def is_subject_compatible(target_subject: str, detected_subject: str) -> bool:
    """Checks whether detected subject is strictly compatible with target dropdown subject."""
    t = (target_subject or "").strip().lower()
    d = (detected_subject or "").strip().lower()

    if not t or not d:
        return True
    if t == d:
        return True

    # 1. Biology (Strict: Botany, Zoology, Life Science)
    bio_synonyms = {"biology", "botany", "zoology", "life science", "life sciences", "bio"}
    if t in bio_synonyms:
        return d in bio_synonyms

    # 2. Chemistry (Strict: Chemical Science, Organic/Inorganic)
    chem_synonyms = {"chemistry", "chemical science", "organic chemistry", "inorganic chemistry", "physical chemistry", "chem"}
    if t in chem_synonyms:
        return d in chem_synonyms

    # 3. Physics (Strict: Physical Science, Applied Physics)
    phys_synonyms = {"physics", "applied physics", "phys"}
    if t in phys_synonyms:
        return d in phys_synonyms

    # 4. Mathematics (Strict: Maths, Math, Algebra, Geometry, Calculus)
    math_synonyms = {"mathematics", "math", "maths", "algebra", "geometry", "calculus", "applied mathematics", "pure mathematics"}
    if t in math_synonyms:
        return d in math_synonyms

    # 5. Computer Science
    cs_synonyms = {"computer science", "informatics", "informatics practices", "python", "computer", "information technology", "it", "ai", "artificial intelligence"}
    if t in cs_synonyms:
        return d in cs_synonyms

    # 6. Social Studies / Social Science
    sst_synonyms = {"social studies", "social science", "history", "geography", "civics", "political science", "economics", "sst"}
    if t in sst_synonyms:
        return d in sst_synonyms

    # 7. English
    eng_synonyms = {"english", "english language", "english literature", "grammar"}
    if t in eng_synonyms:
        return d in eng_synonyms

    # 8. General "Science" (Allowed for lower classes 1-10)
    if t in {"science", "general science"}:
        return d in {"science", "general science", "physics", "chemistry", "biology", "life science", "physical science"}

    # Substring / partial match fallback
    if t in d or d in t:
        return True

    # If the target subject is a custom subject not in the standard STEM taxonomy, accept it dynamically
    standard_categories = bio_synonyms | chem_synonyms | phys_synonyms | math_synonyms | cs_synonyms | sst_synonyms | eng_synonyms | {"science", "general science"}
    if t not in standard_categories:
        return True

    return False


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

