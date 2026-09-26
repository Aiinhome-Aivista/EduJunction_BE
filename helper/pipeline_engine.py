"""Curriculum & Question Paper Ingestion Pipeline Engine.
Executes the 5-step automated processing pipeline for Textbooks and Old Question Papers:
1. Data Read (extract text from PDF/DOCX)
2. Short Contextual Analysis (AI overview & chapter/paper classification)
3. Question Detection & Extraction (High-yield textbook synthesis vs PYQ extraction)
4. JSON Schema Preparation (strict formatting for question_master)
5. Database Storage (Insertion into question_master, documents, document_chunks & ChromaDB)
"""
import json
import re
import uuid
from typing import Any, Dict, List, Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import vector_db
from helper import document_processor, embedding_engine
from model import mistral_client
from model.models import Document, DocumentChunk
from utils.errors import ValidationError
from utils.logger import logger


# ANSI Color Codes for terminal prints
class TermColors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    MAGENTA = "\033[35m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"


TEXTBOOK_QUESTION_PROMPT = """You are an expert curriculum designer and senior board examiner (CBSE, ICSE, Cambridge, State Boards).
Your task is to analyze the provided textbook/chapter text and generate high-yield, pedagogically accurate examination questions.

QUESTION TYPES:
1. 'MCQ' (Multiple Choice): Provide exactly 4 options labeled 'A) ', 'B) ', 'C) ', 'D) '. 'correct_answer' must be the single letter ('A', 'B', 'C', or 'D'). Marks: 1.
2. 'SAQ' (Short Answer Question): Conceptual explanation, definition, or theorem statement (2-3 lines). 'options' MUST be empty list []. Marks: 2 or 3.
3. 'NUMERICAL': Quantitative calculation or formula application with step-by-step solution in explanation. 'options' MUST be empty list []. Marks: 3 or 5.
4. 'OBJECTIVE': Direct one-word answer, formula name, or fill-in-the-blank. 'options' MUST be empty list []. Marks: 1.

DIFFICULTY GUIDELINES:
- 'easy': Foundational memory recall, basic definition, direct formula identification.
- 'medium': Conceptual application, standard calculations, analytical reasoning.
- 'hard': HOTS (Higher Order Thinking Skills), multi-step synthesis, tricky problem solving.

CRITICAL RULES:
1. Every question MUST be grounded strictly in the provided text.
2. Return strictly valid JSON object matching the schema below. No Markdown outside JSON.

JSON Schema:
{
  "questions": [
    {
      "question": "State the relationship between electric current and drift velocity in a conductor.",
      "type": "SAQ",
      "difficulty": "medium",
      "marks": 2,
      "options": [],
      "correct_answer": "I = n * e * A * v_d, where I is current, n is charge carrier density, e is electron charge, A is cross-sectional area, and v_d is drift velocity.",
      "explanation": "Derived from the transport of charge carriers across unit cross section per unit time.",
      "topic_suggested": "Current Electricity"
    }
  ]
}
"""

OLD_QUESTION_PAPER_PROMPT = """You are a senior national board paper evaluator, bilingual digitizer, and curriculum expert (CBSE, ICSE, ISC, State Boards).
Your task is to parse the provided Old Question Paper / PYQ text, identify all individual exam questions, and convert them into structured digital question records with exact official marks.

CRITICAL BILINGUAL & MULTILINGUAL INSTRUCTIONS:
1. BILINGUAL PAPERS (Hindi/Bengali + English):
   - For CBSE, ICSE, ISC, and general subjects (Science, Physics, Chemistry, Biology, Mathematics, Social Studies, Computer Science, English), extract the clean ENGLISH version of the question text and options.
   - Strip out parallel Hindi, Bengali, or regional duplicate sentences, headers (e.g. 'अथवा / OR', 'प्रश्न 1.'), and option translations (e.g. '(A) कोयला / Coal' -> 'A) Coal').
   - For Language subjects (e.g., Hindi Course A/B, Bengali Language, Sanskrit), preserve the respective native language of the subject.

2. MARKS-WISE & SECTION DIRECTIVES:
   - Identify section directives (e.g., Section A = 1 Mark, Section B = 2 Marks, Section C = 3 Marks, Section D = 4 Marks Case Study / Source Based, Section E = 5 Marks Long Answer, Section F = 8 Marks Evaluative) and inline mark brackets like [1], [2], [3], [4], [5], [8].
   - Assign exact official marks (1, 2, 3, 4, 5, or 8) and matching question type:
     • 1 Mark: 'MCQ', 'ASSERTION REASON', or 'OBJECTIVE'
     • 2 Marks: 'SAQ' (Short Answer Question - 2M)
     • 3 Marks: 'SHORT ANSWER (3M)' or 'NUMERICAL'
     • 4 Marks: 'CASE STUDY' (Case-based / passage-based with sub-questions)
     • 5 Marks: 'LONG ANSWER'
     • 8 Marks: 'LONG EVALUATIVE'

3. OPTIONS & MODEL ANSWERS:
   - For Multiple Choice Questions (MCQ), extract all 4 options labeled 'A) ', 'B) ', 'C) ', 'D) ' and determine the correct single-letter answer key ('A', 'B', 'C', or 'D').
   - For descriptive questions, provide a comprehensive model answer in 'correct_answer' and detailed step-by-step working/explanation in 'explanation'.

4. EXTRACTION COMPLETENESS:
   - Extract EVERY distinguishable question present in the text without skipping.

JSON Schema:
{
  "questions": [
    {
      "question": "Which of the following is a displacement reaction?",
      "type": "MCQ",
      "difficulty": "easy",
      "marks": 1,
      "options": ["A) CaO + H2O -> Ca(OH)2", "B) Fe + CuSO4 -> FeSO4 + Cu", "C) 2H2 + O2 -> 2H2O", "D) CaCO3 -> CaO + CO2"],
      "correct_answer": "B",
      "explanation": "Iron is more reactive than copper and displaces copper from copper sulphate solution.",
      "topic_suggested": "Chemical Reactions and Equations"
    }
  ]
}
"""


def _print_separator(title: str, color: str = TermColors.CYAN):
    print(f"\n{color}{TermColors.BOLD}{'=' * 80}")
    print(f" {title.center(78)} ")
    print(f"{'=' * 80}{TermColors.END}")


def _print_step_header(step_num: int, step_name: str, color: str = TermColors.YELLOW):
    print(f"\n{color}{TermColors.BOLD}>>> [STEP {step_num}: {step_name.upper()}]{TermColors.END}")


def perform_contextual_analysis(
    text_content: str = "",
    filename: str = "",
    board: str = "",
    class_grade: str = "",
    subject: str = "",
    document_type: str = "textbook",
    session: Optional[Session] = None,
    cleaned_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Generates a fast, high-quality contextual analysis of the document and identifies subject & chapter accurately without hallucination."""
    raw_text = cleaned_text if cleaned_text is not None else text_content
    excerpt = raw_text[:7000]

    # Pre-fetch existing official chapters from MySQL for this (Board, Class, Subject)
    official_chapters: List[str] = []
    if session:
        try:
            sql = text("""
                SELECT ch.chapter_name
                FROM chapter_master ch
                JOIN subject_master s ON ch.subject_id = s.id
                JOIN board_master b ON s.board_id = b.id
                JOIN class_master c ON s.class_id = c.id
                WHERE LOWER(TRIM(b.board_name)) = LOWER(TRIM(:b))
                  AND (LOWER(TRIM(c.class_name)) = LOWER(TRIM(:c)) OR LOWER(TRIM(REPLACE(c.class_name, 'Class ', ''))) = LOWER(TRIM(:c)))
                  AND (LOWER(TRIM(s.subject_name)) = LOWER(TRIM(:s)) OR (LOWER(TRIM(:s)) = 'science' AND LOWER(TRIM(s.subject_name)) IN ('physics', 'chemistry', 'biology', 'science')))
                  AND ch.is_active = 1
                ORDER BY ch.id ASC
            """)
            official_chapters = [r[0] for r in session.execute(sql, {"b": board, "c": class_grade, "s": subject}).fetchall()]
        except Exception:
            pass

    chapters_ref_prompt = ""
    if official_chapters:
        chapters_ref_prompt = f"""
Official Curriculum Chapters for this Subject:
{json.dumps(official_chapters, indent=2)}

ANTI-HALLUCINATION REQUIREMENT:
- If the uploaded text matches one of the official curriculum chapters above, you MUST set "title" to the EXACT matching official chapter title from this list (do NOT invent new names or add Chapter numbers).
"""

    system_prompt = f"""You are an expert curriculum auditor and senior board paper reviewer.
Analyze the provided educational document excerpt and accurately determine:
1. The EXACT, SPECIFIC educational subject/discipline of the document.
   CRITICAL REQUIREMENT:
   - For science topics, do NOT output generic "Science". You MUST specify the exact discipline:
     • "Chemistry" (e.g. chemical reactions, acids, bases, salts, metals, carbon compounds, bonding, periodic table, mole concept, atoms, molecules, electrochemistry, organic chemistry)
     • "Physics" (e.g. motion, force, gravitation, work, energy, sound, light, optics, electricity, magnetism, electromagnetic induction)
     • "Biology" (e.g. life processes, cells, reproduction, genetics, heredity, evolution, ecology, anatomy, botany, zoology, photosynthesis, human physiology)
   - For other subjects, output "Mathematics", "Social Studies", "English", or "Computer Science".
2. The core chapter or paper title.
3. Summary of concepts covered.
4. Specific key concept topics.{chapters_ref_prompt}"""

    user_prompt = f"""Document Metadata:
- File Name: {filename}
- Target Board: {board}
- Target Class: {class_grade}
- Selected Target Subject: {subject}
- Document Type: {document_type} (textbook or old_question_paper)

--- DOCUMENT EXCERPT ---
{excerpt}
--- END EXCERPT ---

Return strictly a JSON object with this exact structure:
{{
  "title": "Clear Title of Chapter or Question Paper",
  "summary": "2-3 concise sentences summarizing the core content, concepts covered, and educational scope.",
  "detected_subject": "Exact Specific Subject (Chemistry, Physics, Biology, Mathematics, Social Studies, English, or Computer Science - NEVER return generic 'Science' if specific discipline)",
  "detected_topics": ["Topic 1", "Topic 2", "Topic 3"],
  "estimated_difficulty": "easy | medium | hard",
  "recommended_question_count": 12
}}
Note: recommended_question_count MUST be between 10 (minimum) and 15 (maximum).
"""
    try:
        res = mistral_client.generate_json(system_prompt, user_prompt, temperature=0.2, scenario="pdf_generation")
        if isinstance(res, dict) and "title" in res:
            rec_q = res.get("recommended_question_count")
            if isinstance(rec_q, (int, float)):
                res["recommended_question_count"] = max(10, min(15, int(rec_q)))
            else:
                res["recommended_question_count"] = 12
            return res
    except Exception as e:
        logger.warning(f"Contextual analysis LLM fallback: {e}")

    # Fallback contextual analysis with regex
    meta = document_processor.detect_curriculum_metadata(raw_text[:3000])
    detected_sub = meta.get("subject") or subject
    first_lines = [line.strip() for line in raw_text.splitlines() if line.strip()][:5]
    guessed_title = first_lines[0] if first_lines else filename.rsplit(".", 1)[0]
    return {
        "title": guessed_title[:120],
        "summary": f"Curriculum document for {board} {class_grade} {detected_sub} containing {len(raw_text)} characters.",
        "detected_subject": detected_sub,
        "detected_topics": [detected_sub, "General Concepts"],
        "estimated_difficulty": "medium",
        "recommended_question_count": 12,
    }


def sanitize_question_item(
    q: dict,
    default_type: str,
    target_diff: str,
    meta: dict,
    index: int
) -> Optional[Dict[str, Any]]:
    """Sanitizes and strictly formats a question item for question_master schema with bilingual filtering."""
    q_text = (q.get("question") or "").strip()
    if not q_text:
        return None

    # Check if subject is language (Hindi, Bengali, Sanskrit, English)
    sub_lower = str(meta.get("subject") or "").lower()
    is_lang_subject = any(lang in sub_lower for lang in ["hindi", "bengali", "bangla", "sanskrit", "arabic", "urdu"])

    # 1. Bilingual cleanup for CBSE / ICSE / ISC and STEM / General subjects
    if not is_lang_subject:
        # If question contains 'Non-English / English', extract the English part
        if "/" in q_text:
            parts = [p.strip() for p in q_text.split("/") if p.strip()]
            for p in parts:
                ascii_chars = sum(1 for c in p if ord(c) < 128)
                if ascii_chars / max(len(p), 1) > 0.70 and len(p.split()) >= 2:
                    q_text = p
                    break

        # Remove leading Question markers like 'Q1. ', '1. ', 'Question 1: '
        q_text = re.sub(r'^(?:Q(?:uestion)?\.?\s*\d+[\.\:\)]|\d+[\.\)])\s*', '', q_text).strip()

    # 2. Extract embedded marks tag in question text e.g. [1 Mark], [2 Marks], [3M], (4), [5]
    mark_match = re.search(r'[\(\[]\s*(\d+)\s*(?:Marks?|M)?\s*[\)\]]$', q_text, re.IGNORECASE)
    extracted_marks = None
    if mark_match:
        try:
            extracted_marks = int(mark_match.group(1))
            q_text = q_text[:mark_match.start()].strip()
        except Exception:
            extracted_marks = None

    raw_type = str(q.get("type") or default_type or "MCQ").strip().upper()
    if "CASE" in raw_type:
        resolved_type = "CASE STUDY"
        default_m = 4
    elif "ASSERT" in raw_type:
        resolved_type = "ASSERTION REASON"
        default_m = 1
    elif "LONG EVALUATIVE" in raw_type or "8M" in raw_type:
        resolved_type = "LONG EVALUATIVE"
        default_m = 8
    elif "LONG" in raw_type or "LAQ" in raw_type:
        resolved_type = "LONG ANSWER"
        default_m = 5
    elif "SHORT ANSWER (3M)" in raw_type or "3M" in raw_type or int(q.get("marks") or 0) == 3:
        resolved_type = "SHORT ANSWER (3M)"
        default_m = 3
    elif "NUM" in raw_type:
        resolved_type = "NUMERICAL"
        default_m = int(q.get("marks") or 3)
    elif "SAQ" in raw_type or "SHORT" in raw_type:
        resolved_type = "SAQ"
        default_m = 2
    elif raw_type in ["TRUE_FALSE", "TRUE/FALSE", "TF", "OBJECTIVE", "ONE_WORD", "FILL_IN"]:
        resolved_type = "OBJECTIVE"
        default_m = 1
    else:
        resolved_type = "MCQ"
        default_m = 1

    # Clean options
    q_opts = q.get("options")
    clean_opts: List[str] = []
    if resolved_type in ["MCQ", "ASSERTION REASON"]:
        if isinstance(q_opts, list):
            for opt in q_opts:
                opt_str = str(opt).strip()
                if opt_str:
                    clean_opts.append(opt_str)
        elif isinstance(q_opts, dict):
            clean_opts = [f"{k}) {v}" for k, v in q_opts.items()]

        # Clean bilingual slash in options (e.g. "कोयला / Coal" -> "Coal")
        if not is_lang_subject:
            clean_opt_list = []
            for opt_val in clean_opts:
                if "/" in opt_val:
                    opt_parts = [p.strip() for p in opt_val.split("/") if p.strip()]
                    eng_opt = None
                    for op in opt_parts:
                        ascii_chars = sum(1 for c in op if ord(c) < 128)
                        if ascii_chars / max(len(op), 1) > 0.70:
                            eng_opt = op
                            break
                    clean_opt_list.append(eng_opt or opt_val)
                else:
                    clean_opt_list.append(opt_val)
            clean_opts = clean_opt_list

        # Ensure standard prefix A), B), C), D)
        formatted_opts = []
        for opt_idx, opt_val in enumerate(clean_opts[:4]):
            prefix = chr(65 + opt_idx)  # A, B, C, D
            if not re.match(r"^[A-D][\)\.\:\s]", opt_val, re.IGNORECASE):
                formatted_opts.append(f"{prefix}) {opt_val}")
            else:
                formatted_opts.append(opt_val)
        if len(formatted_opts) < 2:
            formatted_opts = ["A) Option A", "B) Option B", "C) Option C", "D) Option D"]
        clean_opts = formatted_opts
    else:
        clean_opts = []

    # Clean correct_answer
    corr = str(q.get("correct_answer") or "").strip()
    if resolved_type in ["MCQ", "ASSERTION REASON"] and clean_opts and corr:
        match_prefix = re.match(r"^([A-D])[\)\.\:\s]", corr, re.IGNORECASE)
        if match_prefix:
            corr = match_prefix.group(1).upper()

    # Determine calibrated difficulty
    raw_diff = str(q.get("difficulty") or target_diff or "medium").strip().lower()
    final_difficulty = raw_diff if raw_diff in ["easy", "medium", "hard"] else "medium"

    # Clean explanation
    raw_expl = q.get("explanation")
    if isinstance(raw_expl, (dict, list)):
        clean_expl = json.dumps(raw_expl)
    elif raw_expl is not None:
        clean_expl = str(raw_expl).strip()
    else:
        clean_expl = "Derived directly from curriculum document."

    # Assigned marks
    raw_m = q.get("marks")
    try:
        marks = int(raw_m if raw_m and str(raw_m).isdigit() else (extracted_marks or default_m))
    except (ValueError, TypeError):
        marks = extracted_marks or default_m

    marks = max(1, min(marks, 20))

    # Re-calibrate question type by marks if generic
    if marks == 1 and resolved_type not in ["MCQ", "ASSERTION REASON"]:
        resolved_type = "OBJECTIVE"
    elif marks == 2 and resolved_type not in ["MCQ", "ASSERTION REASON"]:
        resolved_type = "SAQ"
    elif marks == 3 and resolved_type not in ["NUMERICAL"]:
        resolved_type = "SHORT ANSWER (3M)"
    elif marks == 4 and resolved_type not in ["NUMERICAL"]:
        resolved_type = "CASE STUDY"
    elif marks == 5 and resolved_type not in ["NUMERICAL"]:
        resolved_type = "LONG ANSWER"
    elif marks >= 8:
        resolved_type = "LONG EVALUATIVE"

    return {
        "id": f"gen_{index + 1}",
        "question": q_text,
        "type": resolved_type,
        "difficulty": final_difficulty,
        "marks": marks,
        "options": clean_opts,
        "correct_answer": corr or (clean_opts[0] if clean_opts else "Model Solution"),
        "explanation": clean_expl,
        "topic_suggested": q.get("topic_suggested") or meta.get("subject") or "General",
    }


def extract_questions_from_document_text(
    cleaned_text: str,
    filename: str,
    board: str,
    class_grade: str,
    subject: str,
    title: str,
    document_type: str = "textbook",
    target_q_count: Optional[int] = None,
    detected_topics: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Extracts all questions from curriculum document or question bank across all chunks without truncation."""
    meta = {"board": board, "classGrade": class_grade, "subject": subject, "title": title}
    raw_questions: List[Dict[str, Any]] = []

    if document_type in ["old_question_paper", "question_bank"]:
        # QUESTION BANK / PYQ MODE: Extract 100% of all questions across chunks
        chunk_window = 12000
        overlap = 1000
        text_len = len(cleaned_text)

        chunks = []
        if text_len <= chunk_window:
            chunks = [cleaned_text]
        else:
            start = 0
            while start < text_len:
                end = min(start + chunk_window, text_len)
                chunks.append(cleaned_text[start:end])
                if end == text_len:
                    break
                start = end - overlap

        print(f"  [+] Extraction Strategy: Parsing {len(chunks)} text section(s) for complete Question Bank digitization...")

        system_prompt = OLD_QUESTION_PAPER_PROMPT
        for c_idx, c_text in enumerate(chunks):
            section_label = f"Section {c_idx + 1} of {len(chunks)}"
            user_prompt = f"""Target Details:
- Board: {board}
- Class/Grade: {class_grade}
- Subject: {subject}
- Chapter/Paper Title: {title}
- Document Mode: {document_type}
- Section: {section_label}

--- DOCUMENT CONTENT ({section_label}) ---
{c_text}
--- END DOCUMENT CONTENT ---

CRITICAL INSTRUCTIONS:
1. Extract and digitize EVERY single question present in this text section without skipping any.
2. If there are Multiple Choice Questions (MCQ), extract all options ('A) ', 'B) ', 'C) ', 'D) ') and identify the correct option letter.
3. For Short Answer (2M or 3M), Case Studies (4M), Long Answer (5M or 8M), Numerical, Assertion Reason, or Objective questions, extract full question text and write accurate model solutions in 'correct_answer' and 'explanation'.
4. Extract all distinguishable questions present in this section without an artificial limit."""

            try:
                response_json = mistral_client.generate_json(system_prompt, user_prompt, temperature=0.25, scenario="pdf_generation")
                q_list = response_json.get("questions", []) if isinstance(response_json, dict) else []
                if isinstance(q_list, list) and q_list:
                    raw_questions.extend(q_list)
                    print(f"    -> [{section_label}] Extracted {len(q_list)} question(s)")
            except Exception as e:
                logger.error(f"Error extracting questions from chunk {c_idx + 1}: {e}")

        # Fallback question detection if LLM returned 0 questions
        if not raw_questions:
            q_pattern = re.compile(r'(?i)(?:^|\n)(?:Q(?:uestion)?\.?\s*\d+|^\d+[\.\)])\s+(.+?)(?=(?:\n(?:Q(?:uestion)?\.?\s*\d+|^\d+[\.\)])|\Z))', re.DOTALL)
            matches = q_pattern.findall(cleaned_text)
            for m_idx, m_text in enumerate(matches[:40]):
                m_clean = m_text.strip()
                if len(m_clean) > 15:
                    raw_questions.append({
                        "question": m_clean[:300],
                        "type": "SAQ",
                        "difficulty": "medium",
                        "marks": 2,
                        "options": [],
                        "correct_answer": f"Standard curriculum solution for {title}.",
                        "explanation": f"Extracted from {filename}",
                        "topic_suggested": subject,
                    })

    else:
        # TEXTBOOK SYNTHESIS MODE
        q_count = target_q_count or 12
        system_prompt = TEXTBOOK_QUESTION_PROMPT
        if len(cleaned_text) > 18000:
            doc_excerpt = (
                cleaned_text[:9000]
                + "\n\n...[Middle Concepts]...\n\n"
                + cleaned_text[len(cleaned_text) // 2 : len(cleaned_text) // 2 + 5000]
                + "\n\n...[End Summaries & Exercises]...\n\n"
                + cleaned_text[-5000:]
            )
        else:
            doc_excerpt = cleaned_text[:15000]

        user_prompt = f"""Target Details:
- Board: {board}
- Class/Grade: {class_grade}
- Subject: {subject}
- Chapter/Paper Title: {title}
- Required Question Count: {q_count}
- Document Mode: {document_type}

--- DOCUMENT CONTENT ---
{doc_excerpt}
--- END DOCUMENT CONTENT ---

Extract/generate EXACTLY {q_count} comprehensive structured questions covering all key concepts, definitions, numericals, and core topics in the document."""

        try:
            response_json = mistral_client.generate_json(system_prompt, user_prompt, temperature=0.35, scenario="pdf_generation")
            raw_questions = response_json.get("questions", []) if isinstance(response_json, dict) else []
        except Exception as e:
            logger.error(f"LLM question extraction failed: {e}")
            raw_questions = []

        if not raw_questions:
            sentences = [s.strip() for s in re.split(r'[\n\.]+', cleaned_text) if len(s.strip()) > 20]
            if not sentences:
                sentences = [f"Core fundamental principle of {subject} in {title}"]
            for s_idx in range(q_count):
                sent = sentences[s_idx % len(sentences)]
                raw_questions.append({
                    "question": f"Explain the principle: {sent[:120]}?",
                    "type": "SAQ" if s_idx % 2 == 0 else "MCQ",
                    "difficulty": "easy" if s_idx < 3 else ("medium" if s_idx < 8 else "hard"),
                    "marks": 2 if s_idx % 2 == 0 else 1,
                    "options": [f"A) {sent[:30]}", "B) Alternative Concept", "C) Null Condition", "D) Secondary Effect"] if s_idx % 2 != 0 else [],
                    "correct_answer": "A" if s_idx % 2 != 0 else f"Principle: {sent}.",
                    "explanation": f"Derived directly from curriculum document: {sent}",
                    "topic_suggested": subject,
                })

    # Sanitize and deduplicate within extracted batch
    sanitized: List[Dict[str, Any]] = []
    seen_texts = set()

    for idx, q in enumerate(raw_questions):
        norm = sanitize_question_item(q, "MCQ", "medium", meta, idx)
        if not norm:
            continue

        clean_key = re.sub(r'[^a-zA-Z0-9]', '', norm["question"].lower())[:80]
        if clean_key in seen_texts and len(clean_key) > 10:
            continue
        seen_texts.add(clean_key)
        sanitized.append(norm)

    return sanitized


def _ensure_curriculum_tables(session: Session):
    """Ensures taxonomy & question tables exist for standalone/test SQLite execution."""
    is_sqlite = session.bind and session.bind.dialect.name == "sqlite"
    if is_sqlite:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS board_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS class_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS subject_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id INTEGER,
                class_id INTEGER,
                subject_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS chapter_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER,
                chapter_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS topic_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_id INTEGER,
                topic_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS question_type_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_type_name TEXT NOT NULL
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS difficulty_level_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                difficulty_level_name TEXT NOT NULL
            );
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS question_master (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER NOT NULL,
                question_type_id INTEGER DEFAULT 1,
                difficulty_level_id INTEGER DEFAULT 2,
                question TEXT NOT NULL,
                options TEXT,
                correct_answer TEXT NOT NULL,
                explanation TEXT,
                marks INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        # Seed defaults if empty
        try:
            if not session.execute(text("SELECT id FROM question_type_master LIMIT 1")).scalar():
                session.execute(text("INSERT INTO question_type_master (id, question_type_name) VALUES (1, 'MCQ'), (2, 'SAQ'), (3, 'NUMERICAL'), (4, 'OBJECTIVE')"))
            if not session.execute(text("SELECT id FROM difficulty_level_master LIMIT 1")).scalar():
                session.execute(text("INSERT INTO difficulty_level_master (id, difficulty_level_name) VALUES (1, 'easy'), (2, 'medium'), (3, 'hard')"))
            if not session.execute(text("SELECT id FROM topic_master LIMIT 1")).scalar():
                session.execute(text("INSERT INTO board_master (id, board_name) VALUES (1, 'CBSE')"))
                session.execute(text("INSERT INTO class_master (id, class_name) VALUES (1, 'Class 10')"))
                session.execute(text("INSERT INTO subject_master (id, board_id, class_id, subject_name) VALUES (1, 1, 1, 'Physics'), (2, 1, 1, 'Science')"))
                session.execute(text("INSERT INTO chapter_master (id, subject_id, chapter_name) VALUES (1, 1, 'Electricity'), (2, 2, 'Science General')"))
                session.execute(text("INSERT INTO topic_master (id, chapter_id, topic_name) VALUES (1, 1, 'Ohm Law & Circuits'), (2, 2, 'General Science')"))
            session.commit()
        except Exception:
            session.rollback()


def _normalize_title(text_val: str) -> str:
    """Helper to clean chapter and topic strings for robust matching."""
    if not text_val:
        return ""
    # Strip common prefixes like 'Chapter 1: ', 'Unit 2 - ', 'Ch. 3 '
    cleaned = re.sub(r'^(?:Chapter|Unit|Ch\.?|Lesson|Section)\s*\d+[\s\:\-\.]*', '', text_val, flags=re.IGNORECASE).strip()
    # Remove special characters and lowercase
    return re.sub(r'[^a-zA-Z0-9]', '', cleaned).lower()


def resolve_subject_topic_id(
    session: Session,
    board: str,
    class_grade: str,
    subject: str,
    target_topic_id: Optional[int] = None,
    title: Optional[str] = None,
    detected_topics: Optional[List[str]] = None,
) -> int:
    """Strictly resolves or creates a matching topic_id for the given Board, Class, and Subject,
    preventing duplicate chapters and topics."""
    # 1. If target_topic_id is provided, verify it strictly belongs to this (board, class_grade, subject)
    if target_topic_id:
        try:
            is_valid = session.execute(
                text("""
                    SELECT t.id 
                    FROM topic_master t
                    JOIN chapter_master ch ON t.chapter_id = ch.id
                    JOIN subject_master s ON ch.subject_id = s.id
                    JOIN board_master b ON s.board_id = b.id
                    JOIN class_master c ON s.class_id = c.id
                    WHERE t.id = :tid
                      AND LOWER(TRIM(b.board_name)) = LOWER(TRIM(:b))
                      AND (LOWER(TRIM(c.class_name)) = LOWER(TRIM(:c)) OR LOWER(TRIM(REPLACE(c.class_name, 'Class ', ''))) = LOWER(TRIM(:c)))
                      AND (LOWER(TRIM(s.subject_name)) = LOWER(TRIM(:s)) OR (LOWER(TRIM(:s)) = 'science' AND LOWER(TRIM(s.subject_name)) IN ('physics', 'chemistry', 'biology', 'science')))
                    LIMIT 1
                """),
                {"tid": target_topic_id, "b": board, "c": class_grade, "s": subject}
            ).scalar()
            if is_valid:
                return int(target_topic_id)
        except Exception:
            pass

    # 2. Lookup subject_id in subject_master
    sub_id = None
    try:
        sub_id = session.execute(
            text("""
                SELECT s.id 
                FROM subject_master s
                JOIN board_master b ON s.board_id = b.id
                JOIN class_master c ON s.class_id = c.id
                WHERE LOWER(TRIM(b.board_name)) = LOWER(TRIM(:b))
                  AND (LOWER(TRIM(c.class_name)) = LOWER(TRIM(:c)) OR LOWER(TRIM(REPLACE(c.class_name, 'Class ', ''))) = LOWER(TRIM(:c)))
                  AND (LOWER(TRIM(s.subject_name)) = LOWER(TRIM(:s)) OR (LOWER(TRIM(:s)) = 'science' AND LOWER(TRIM(s.subject_name)) IN ('physics', 'chemistry', 'biology', 'science')))
                ORDER BY s.id ASC
                LIMIT 1
            """),
            {"b": board, "c": class_grade, "s": subject}
        ).scalar()
    except Exception:
        pass

    if not sub_id:
        first_topic = session.execute(text("SELECT id FROM topic_master LIMIT 1")).scalar()
        return int(first_topic or 1)

    norm_title = _normalize_title(title or "")
    matched_chapter_id = None

    # 3. Search existing chapters under this subject_id to avoid duplication
    try:
        existing_chapters = session.execute(
            text("SELECT id, chapter_name FROM chapter_master WHERE subject_id = :sid AND is_active = 1"),
            {"sid": sub_id}
        ).fetchall()

        for ch_id, ch_name in existing_chapters:
            norm_ch = _normalize_title(ch_name)
            if norm_title and (norm_title == norm_ch or norm_title in norm_ch or norm_ch in norm_title):
                matched_chapter_id = ch_id
                break
    except Exception:
        pass

    # 4. If no existing chapter matched, create chapter under subject_id
    if not matched_chapter_id:
        try:
            ch_name_to_create = title.strip() if title and len(title.strip()) > 2 else f"General {subject}"
            session.execute(
                text("INSERT INTO chapter_master (subject_id, chapter_name, is_active) VALUES (:sid, :cn, 1)"),
                {"sid": sub_id, "cn": ch_name_to_create}
            )
            session.commit()
            matched_chapter_id = session.execute(
                text("SELECT id FROM chapter_master WHERE subject_id = :sid AND chapter_name = :cn ORDER BY id DESC LIMIT 1"),
                {"sid": sub_id, "cn": ch_name_to_create}
            ).scalar()
        except Exception:
            session.rollback()

    if not matched_chapter_id:
        first_topic = session.execute(text("SELECT id FROM topic_master LIMIT 1")).scalar()
        return int(first_topic or 1)

    # 5. Search existing topics under this matched chapter
    primary_topic_name = (detected_topics[0] if detected_topics and detected_topics[0] else title) or f"{subject} Concepts"
    norm_topic = _normalize_title(primary_topic_name)

    try:
        existing_topics = session.execute(
            text("SELECT id, topic_name FROM topic_master WHERE chapter_id = :chid AND is_active = 1"),
            {"chid": matched_chapter_id}
        ).fetchall()

        for t_id, t_name in existing_topics:
            norm_t = _normalize_title(t_name)
            if norm_topic and (norm_topic == norm_t or norm_topic in norm_t or norm_t in norm_topic):
                return int(t_id)

        # If chapter already has topics, reuse the first one
        if existing_topics:
            return int(existing_topics[0][0])
    except Exception:
        pass

    # 6. If no topic under chapter, create it
    try:
        session.execute(
            text("INSERT INTO topic_master (chapter_id, topic_name, is_active) VALUES (:chid, :tn, 1)"),
            {"chid": matched_chapter_id, "tn": primary_topic_name.strip()[:150]}
        )
        session.commit()
        new_tid = session.execute(
            text("SELECT id FROM topic_master WHERE chapter_id = :chid ORDER BY id DESC LIMIT 1"),
            {"chid": matched_chapter_id}
        ).scalar()
        if new_tid:
            return int(new_tid)
    except Exception:
        session.rollback()

    first_topic = session.execute(text("SELECT id FROM topic_master LIMIT 1")).scalar()
    return int(first_topic or 1)


def process_curriculum_document_pipeline(
    session: Session,
    file_bytes: bytes,
    filename: str,
    board: str,
    class_grade: str,
    subject: str,
    document_type: str = "textbook",
    question_count: Optional[int] = None,
    target_topic_id: Optional[int] = None,
    uploaded_by: Optional[int] = None,
) -> Dict[str, Any]:
    """Executes the complete 5-step processing pipeline with real-time terminal output."""
    _print_separator(f"PIPELINE START: {filename}", TermColors.MAGENTA)

    # -------------------------------------------------------------------------
    # STEP 1: DATA READ & TEXT EXTRACTION
    # -------------------------------------------------------------------------
    _print_step_header(1, "DATA READ & EXTRACTION", TermColors.CYAN)
    ext = document_processor.validate_upload(filename, len(file_bytes))
    raw_text = document_processor.extract_text(file_bytes, ext)
    cleaned_text = document_processor.clean_text(raw_text)

    char_count = len(cleaned_text)
    word_count = len(cleaned_text.split())
    line_count = len(cleaned_text.splitlines())

    print(f"  • File Name       : {TermColors.BOLD}{filename}{TermColors.END}")
    print(f"  • File Type       : .{ext.upper()} ({len(file_bytes) / 1024:.1f} KB)")
    print(f"  • Target Config   : Board=[{board}] | Class=[{class_grade}] | Subject=[{subject}]")
    print(f"  • Document Mode   : {TermColors.GREEN}{document_type.upper()}{TermColors.END}")
    print(f"  • Text Extracted  : {TermColors.BOLD}{char_count:,}{TermColors.END} chars | {word_count:,} words | {line_count:,} lines")

    if not cleaned_text.strip():
        raise ValueError("Failed to extract readable text from the uploaded document.")

    # -------------------------------------------------------------------------
    # STEP 2: SHORT CONTEXTUAL ANALYSIS
    # -------------------------------------------------------------------------
    _print_step_header(2, "SHORT CONTEXTUAL ANALYSIS", TermColors.YELLOW)
    analysis = perform_contextual_analysis(
        cleaned_text=cleaned_text,
        filename=filename,
        board=board,
        class_grade=class_grade,
        subject=subject,
        document_type=document_type,
        session=session,
    )
    title = analysis.get("title", filename)
    summary = analysis.get("summary", "")
    detected_topics = analysis.get("detected_topics", [subject])
    est_diff = analysis.get("estimated_difficulty", "medium")
    detected_subject = analysis.get("detected_subject")

    if not detected_subject or detected_subject == "Science":
        meta_detected = document_processor.detect_curriculum_metadata(cleaned_text[:6000])
        specific_sub = meta_detected.get("subject")
        if specific_sub and specific_sub != "Science":
            detected_subject = specific_sub
        elif not detected_subject:
            detected_subject = specific_sub or subject

    # -------------------------------------------------------------------------
    # VALIDATION GATE: Check Subject Content Compatibility with Dropdown Target
    # -------------------------------------------------------------------------
    if detected_subject and not document_processor.is_subject_compatible(subject, detected_subject):
        concepts_str = ", ".join(detected_topics[:3]) if detected_topics else "unrelated domain"
        error_msg = (
            f"Content Mismatch: Uploaded document '{filename}' contains '{detected_subject}' content "
            f"(Concepts: {concepts_str}), but you selected '{subject}' in the dropdown. "
            f"Please change the dropdown Subject to '{detected_subject}' to process this file."
        )
        print(f"\n{TermColors.BOLD}\033[91m❌ [VALIDATION BLOCKED] {error_msg}{TermColors.END}")
        raise ValidationError(error_msg)

    # Determine calibrated question count (min 10, max 15 questions per document/chapter)
    rec_q = analysis.get("recommended_question_count")
    if question_count and 10 <= int(question_count) <= 15:
        target_q_count = int(question_count)
    elif rec_q and isinstance(rec_q, (int, float)) and 10 <= int(rec_q) <= 15:
        target_q_count = int(rec_q)
    else:
        # Dynamic calibration based on chapter text volume
        if char_count > 10000:
            target_q_count = 15
        elif char_count > 5000:
            target_q_count = 13
        else:
            target_q_count = 10

    print(f"  • Inferred Title  : {TermColors.BOLD}{title}{TermColors.END}")
    print(f"  • Inferred Subject: {TermColors.BOLD}{detected_subject or subject}{TermColors.END} (Target: {subject})")
    print(f"  • Detected Topics : {', '.join(detected_topics)}")
    print(f"  • Est. Difficulty : {est_diff.capitalize()}")
    print(f"  • Target Questions: {TermColors.BOLD}{target_q_count}{TermColors.END} (Calibrated 10-15 per Chapter)")
    print(f"  • Overview Summary: {TermColors.CYAN}{summary}{TermColors.END}")

    # -------------------------------------------------------------------------
    # STEP 3: QUESTION DETECTION & EXTRACTION
    # -------------------------------------------------------------------------
    _print_step_header(3, f"QUESTION DETECTION & EXTRACTION ({document_type.upper()})", TermColors.BLUE)
    final_questions = extract_questions_from_document_text(
        cleaned_text=cleaned_text,
        filename=filename,
        board=board,
        class_grade=class_grade,
        subject=subject,
        title=title,
        document_type=document_type,
        target_q_count=target_q_count,
        detected_topics=detected_topics,
    )

    # -------------------------------------------------------------------------
    # STEP 4: PREPARE JSON SCHEMA OBJECTS
    # -------------------------------------------------------------------------
    _print_step_header(4, "JSON SCHEMA PREPARATION & VALIDATION", TermColors.MAGENTA)
    # Type & Difficulty Breakdown
    type_counts: Dict[str, int] = {}
    diff_counts: Dict[str, int] = {}
    for q in final_questions:
        type_counts[q["type"]] = type_counts.get(q["type"], 0) + 1
        diff_counts[q["difficulty"]] = diff_counts.get(q["difficulty"], 0) + 1

    print(f"  • Total Validated : {TermColors.BOLD}{len(final_questions)}{TermColors.END} questions matching schema")
    print(f"  • Type Breakdown  : {json.dumps(type_counts)}")
    print(f"  • Diff Breakdown  : {json.dumps(diff_counts)}")
    if final_questions:
        sample_q = final_questions[0]
        print(f"  • Sample JSON Schema Sample:")
        print(f"    - Question : {sample_q['question'][:80]}...")
        print(f"    - Type     : {sample_q['type']} | Marks: {sample_q['marks']} | Diff: {sample_q['difficulty']}")
        print(f"    - Answer   : {sample_q['correct_answer']}")

    # -------------------------------------------------------------------------
    # STEP 5: DATABASE INSERTION (question_master + documents + ChromaDB)
    # -------------------------------------------------------------------------
    _print_step_header(5, "DATABASE INSERTION & VECTOR INDEXING", TermColors.GREEN)

    _ensure_curriculum_tables(session)

    # 5.1 Resolve or Lookup topic_id in topic_master
    resolved_topic_id = resolve_subject_topic_id(
        session=session,
        board=board,
        class_grade=class_grade,
        subject=subject,
        target_topic_id=target_topic_id,
        title=title,
        detected_topics=detected_topics,
    )

    # Preload types and diff lookup dicts
    types_map = {
        r[0].upper(): r[1]
        for r in session.execute(text("SELECT question_type_name, id FROM question_type_master")).fetchall()
    }
    diffs_map = {
        r[0].lower(): r[1]
        for r in session.execute(text("SELECT difficulty_level_name, id FROM difficulty_level_master")).fetchall()
    }

    # 5.2 Insert Questions into question_master
    inserted_questions_count = 0
    updated_questions_count = 0

    for q in final_questions:
        q_type_upper = str(q.get("type", "MCQ")).upper()
        q_type_id = types_map.get(q_type_upper)
        if not q_type_id:
            if "CASE" in q_type_upper:
                q_type_id = types_map.get("CASE STUDY", types_map.get("SAQ", 2))
            elif "ASSERT" in q_type_upper:
                q_type_id = types_map.get("ASSERTION REASON", types_map.get("MCQ", 1))
            elif "LONG" in q_type_upper:
                q_type_id = types_map.get("LONG ANSWER", types_map.get("LONG EVALUATIVE (8M)", 3))
            elif "SHORT" in q_type_upper or "SAQ" in q_type_upper:
                if int(q.get("marks", 2)) == 3:
                    q_type_id = types_map.get("SHORT ANSWER (3M)", types_map.get("SAQ", 2))
                else:
                    q_type_id = types_map.get("SAQ", 2)
            elif "NUM" in q_type_upper:
                q_type_id = types_map.get("NUMERICAL", 5)
            else:
                q_type_id = types_map.get("MCQ", 1)

        q_diff = q["difficulty"].lower()
        if q_diff in ["simple", "easy"]:
            diff_id = diffs_map.get("easy", diffs_map.get("simple", 1))
        else:
            diff_id = diffs_map.get(q_diff, 2)

        options_json = json.dumps(q["options"]) if q["options"] else None

        # Check existing for deduplication
        existing_id = session.execute(
            text("""
                SELECT id FROM question_master
                WHERE topic_id = :t_id AND LOWER(TRIM(question)) = LOWER(TRIM(:q_text))
                LIMIT 1
            """),
            {"t_id": resolved_topic_id, "q_text": q["question"]}
        ).scalar()

        if existing_id:
            session.execute(
                text("""
                    UPDATE question_master
                    SET options = :options, correct_answer = :correct_answer, explanation = :explanation,
                        marks = :marks, difficulty_level_id = :diff_id, question_type_id = :type_id,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {
                    "id": existing_id,
                    "options": options_json,
                    "correct_answer": q["correct_answer"],
                    "explanation": q["explanation"],
                    "marks": q["marks"],
                    "diff_id": diff_id,
                    "type_id": q_type_id
                }
            )
            updated_questions_count += 1
        else:
            session.execute(
                text("""
                    INSERT INTO question_master 
                    (topic_id, question_type_id, difficulty_level_id, question, options, correct_answer, explanation, marks, is_active, created_at, updated_at)
                    VALUES 
                    (:topic_id, :type_id, :diff_id, :question, :options, :correct_answer, :explanation, :marks, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """),
                {
                    "topic_id": resolved_topic_id,
                    "type_id": q_type_id,
                    "diff_id": diff_id,
                    "question": q["question"],
                    "options": options_json,
                    "correct_answer": q["correct_answer"],
                    "explanation": q["explanation"],
                    "marks": q["marks"]
                }
            )
            inserted_questions_count += 1

    # 5.3 Insert Document and Document Chunks
    doc_id = str(uuid.uuid4())
    doc_record = Document(
        id=doc_id,
        filename=filename,
        content_type=f"application/{ext}",
        board=board,
        class_grade=class_grade,
        subject=subject,
        uploaded_by=uploaded_by,
        status="PROCESSED",
    )
    session.add(doc_record)
    session.flush()

    chunks = document_processor.chunk_text(cleaned_text)
    chunk_ids = []
    chunk_texts = []
    chunk_metas = []
    for c_idx, c_text in enumerate(chunks):
        chunk_uuid = str(uuid.uuid4())
        chunk_record = DocumentChunk(
            id=chunk_uuid,
            document_id=doc_id,
            chunk_index=c_idx,
            content=c_text,
            vector_id=chunk_uuid,
        )
        session.add(chunk_record)
        chunk_ids.append(chunk_uuid)
        chunk_texts.append(c_text)
        chunk_metas.append({
            "document_id": doc_id,
            "filename": filename,
            "board": board,
            "class_grade": class_grade,
            "subject": subject,
            "document_type": document_type,
            "chunk_index": c_idx,
        })

    session.commit()

    # 5.4 ChromaDB Vector Upsert
    if vector_db.is_enabled() and chunk_texts:
        try:
            embeddings = embedding_engine.embed(chunk_texts)
            vector_db.upsert_chunks(chunk_ids, chunk_texts, embeddings, chunk_metas)
            print(f"  • ChromaDB Synced : {len(chunk_texts)} chunks indexed with Mistral Embeddings")
        except Exception as vec_err:
            logger.warning(f"Vector store indexing notice: {vec_err}")

    # 5.5 ArangoDB Knowledge Graph Sync
    try:
        from database import graph_db
        if graph_db.is_enabled():
            chapter_name_clean = title or filename.replace(".pdf", "").replace(".docx", "").replace(".doc", "").replace("_", " ")
            topics_to_push = detected_topics if (detected_topics and len(detected_topics) > 0) else [chapter_name_clean]
            graph_db.upsert_hierarchical_curriculum_branch(
                board=board,
                class_grade=class_grade,
                subject=subject,
                chapter=chapter_name_clean,
                topics_list=topics_to_push
            )
            print(f"  • ArangoDB Synced : Hierarchy & {len(topics_to_push)} topic node(s) linked to knowledge graph")
    except Exception as graph_err:
        logger.warning(f"ArangoDB sync notice in pipeline: {graph_err}")

    print(f"  • Questions Saved : {TermColors.BOLD}{inserted_questions_count} inserted{TermColors.END}, {updated_questions_count} updated in `question_master`")
    print(f"  • Document ID     : {doc_id} (`documents` table)")
    print(f"  • Chunks Created  : {len(chunks)} (`document_chunks` table)")
    print(f"  • Linked Topic ID : {resolved_topic_id}")

    _print_separator(f"PIPELINE COMPLETED: {filename} [SUCCESS]", TermColors.GREEN)

    return {
        "success": True,
        "filename": filename,
        "document_id": doc_id,
        "document_type": document_type,
        "title": title,
        "summary": summary,
        "detected_topics": detected_topics,
        "total_extracted": len(final_questions),
        "questions_inserted": inserted_questions_count,
        "questions_updated": updated_questions_count,
        "topic_id": resolved_topic_id,
        "chunk_count": len(chunks),
        "questions": final_questions,
    }


def extract_curriculum_questions_preview(
    session: Session,
    file_bytes: bytes,
    filename: str,
    board: str,
    class_grade: str,
    subject: str,
    document_type: str = "textbook",
    question_count: Optional[int] = None,
    target_topic_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Executes Steps 1 to 4 (Extraction, Context Analysis, Question Generation, Duplicate Check)

    without persisting to the database. Returns questions with duplicate indicators for UI review.
    """
    _print_separator(f"EXTRACTION PREVIEW: {filename}", TermColors.MAGENTA)

    # 1. DATA READ
    _print_step_header(1, "DATA READ & EXTRACTION", TermColors.CYAN)
    ext = document_processor.validate_upload(filename, len(file_bytes))
    raw_text = document_processor.extract_text(file_bytes, ext)
    cleaned_text = document_processor.clean_text(raw_text)

    char_count = len(cleaned_text)
    word_count = len(cleaned_text.split())
    line_count = len(cleaned_text.splitlines())

    print(f"  • File Name       : {TermColors.BOLD}{filename}{TermColors.END}")
    print(f"  • Target Config   : Board=[{board}] | Class=[{class_grade}] | Subject=[{subject}]")
    print(f"  • Text Extracted  : {TermColors.BOLD}{char_count:,}{TermColors.END} chars | {word_count:,} words")

    if not cleaned_text.strip():
        raise ValueError("Failed to extract readable text from the uploaded document.")

    # 2. CONTEXTUAL ANALYSIS
    _print_step_header(2, "SHORT CONTEXTUAL ANALYSIS", TermColors.YELLOW)
    analysis = perform_contextual_analysis(
        cleaned_text=cleaned_text,
        filename=filename,
        board=board,
        class_grade=class_grade,
        subject=subject,
        document_type=document_type,
        session=session,
    )
    title = analysis.get("title", filename)
    summary = analysis.get("summary", "")
    detected_topics = analysis.get("detected_topics", [subject])
    est_diff = analysis.get("estimated_difficulty", "medium")
    detected_subject = analysis.get("detected_subject")

    if not detected_subject or detected_subject == "Science":
        meta_detected = document_processor.detect_curriculum_metadata(cleaned_text[:6000])
        specific_sub = meta_detected.get("subject")
        if specific_sub and specific_sub != "Science":
            detected_subject = specific_sub
        elif not detected_subject:
            detected_subject = specific_sub or subject

    if detected_subject and not document_processor.is_subject_compatible(subject, detected_subject):
        concepts_str = ", ".join(detected_topics[:3]) if detected_topics else "unrelated domain"
        error_msg = (
            f"Content Mismatch: Uploaded document '{filename}' contains '{detected_subject}' content "
            f"(Concepts: {concepts_str}), but you selected '{subject}' in the dropdown. "
            f"Please change the dropdown Subject to '{detected_subject}' to process this file."
        )
        print(f"\n{TermColors.BOLD}\033[91m❌ [VALIDATION BLOCKED] {error_msg}{TermColors.END}")
        raise ValidationError(error_msg)

    # Calibrate Question Count
    rec_q = analysis.get("recommended_question_count")
    if question_count and 10 <= int(question_count) <= 25:
        target_q_count = int(question_count)
    elif rec_q and isinstance(rec_q, (int, float)) and 10 <= int(rec_q) <= 25:
        target_q_count = int(rec_q)
    else:
        target_q_count = 15 if char_count > 10000 else (13 if char_count > 5000 else 10)

    # 3. QUESTION DETECTION & EXTRACTION
    _print_step_header(3, f"QUESTION DETECTION & EXTRACTION ({document_type.upper()})", TermColors.BLUE)
    extracted_questions = extract_questions_from_document_text(
        cleaned_text=cleaned_text,
        filename=filename,
        board=board,
        class_grade=class_grade,
        subject=subject,
        title=title,
        document_type=document_type,
        target_q_count=target_q_count,
        detected_topics=detected_topics,
    )

    # 4. JSON SCHEMA PREP & PRE-INSERTION DUPLICATE CHECKER
    _print_step_header(4, "SCHEMA PREPARATION & DUPLICATE CHECKER", TermColors.YELLOW)
    _ensure_curriculum_tables(session)

    # Resolve target topic_id
    resolved_topic_id = resolve_subject_topic_id(
        session=session,
        board=board,
        class_grade=class_grade,
        subject=subject,
        target_topic_id=target_topic_id,
        title=title,
        detected_topics=detected_topics,
    )

    final_questions = []
    duplicate_count = 0
    meta = {"board": board, "classGrade": class_grade, "subject": subject, "title": title}

    for idx, norm in enumerate(extracted_questions):
        if not norm:
            continue
        q_text = norm["question"]

        # Check existing in question_master
        is_dup = False
        try:
            existing_id = session.execute(
                text("""
                    SELECT id FROM question_master
                    WHERE topic_id = :t_id AND LOWER(TRIM(question)) = LOWER(TRIM(:q_text))
                    LIMIT 1
                """),
                {"t_id": resolved_topic_id, "q_text": q_text}
            ).scalar()
            if existing_id:
                is_dup = True
                duplicate_count += 1
        except Exception:
            is_dup = False

        norm["id"] = str(uuid.uuid4())
        norm["is_duplicate"] = is_dup
        final_questions.append(norm)

    print(f"  • Total Extracted : {len(final_questions)} Questions ({duplicate_count} Existing / Duplicates Detected)")

    return {
        "success": True,
        "filename": filename,
        "document_type": document_type,
        "board": board,
        "class_grade": class_grade,
        "subject": subject,
        "title": title,
        "summary": summary,
        "detected_topics": detected_topics,
        "estimated_difficulty": est_diff,
        "status": "PREVIEW_READY",
        "total_extracted": len(final_questions),
        "new_questions_count": len(final_questions) - duplicate_count,
        "duplicate_questions_count": duplicate_count,
        "duplicate_count": duplicate_count,
        "topic_id": resolved_topic_id,
        "cleaned_text": cleaned_text,
        "char_count": char_count,
        "questions": final_questions,
    }


def save_curriculum_extracted_questions_pipeline(
    session: Session,
    questions: List[Dict[str, Any]],
    filename: str,
    board: str,
    class_grade: str,
    subject: str,
    document_type: str = "textbook",
    cleaned_text: str = "",
    target_topic_id: Optional[int] = None,
    uploaded_by: Optional[int] = None,
    detected_topics: List[str] = None,
    title: str = None,
    summary: str = None,
) -> Dict[str, Any]:
    """Persists Admin-approved questions into question_master with Duplicate Protection,

    stores document chunks, updates ChromaDB Vector Store, and syncs ArangoDB K-Graph.
    """
    _print_separator(f"PERSISTING APPROVED QUESTIONS: {filename}", TermColors.GREEN)
    _ensure_curriculum_tables(session)

    # 1. Resolve topic_id
    resolved_topic_id = resolve_subject_topic_id(
        session=session,
        board=board,
        class_grade=class_grade,
        subject=subject,
        target_topic_id=target_topic_id,
        title=title,
        detected_topics=detected_topics,
    )

    # 2. Lookup Dicts for Question Types and Difficulties
    types_map = {
        r[0].upper(): r[1]
        for r in session.execute(text("SELECT question_type_name, id FROM question_type_master")).fetchall()
    }
    diffs_map = {
        r[0].lower(): r[1]
        for r in session.execute(text("SELECT difficulty_level_name, id FROM difficulty_level_master")).fetchall()
    }

    inserted_count = 0
    updated_count = 0
    duplicate_skipped = 0

    for q in questions:
        q_type_upper = str(q.get("type", "MCQ")).upper()
        q_type_id = types_map.get(q_type_upper)
        if not q_type_id:
            if "CASE" in q_type_upper:
                q_type_id = types_map.get("CASE STUDY", types_map.get("SAQ", 2))
            elif "ASSERT" in q_type_upper:
                q_type_id = types_map.get("ASSERTION REASON", types_map.get("MCQ", 1))
            elif "LONG" in q_type_upper:
                q_type_id = types_map.get("LONG ANSWER", types_map.get("LONG EVALUATIVE (8M)", 3))
            elif "SHORT" in q_type_upper or "SAQ" in q_type_upper:
                if int(q.get("marks", 2)) == 3:
                    q_type_id = types_map.get("SHORT ANSWER (3M)", types_map.get("SAQ", 2))
                else:
                    q_type_id = types_map.get("SAQ", 2)
            elif "NUM" in q_type_upper:
                q_type_id = types_map.get("NUMERICAL", 5)
            else:
                q_type_id = types_map.get("MCQ", 1)

        q_diff = str(q.get("difficulty", "medium")).lower()
        if q_diff in ["simple", "easy"]:
            diff_id = diffs_map.get("easy", diffs_map.get("simple", 1))
        else:
            diff_id = diffs_map.get(q_diff, 2)

        options_json = json.dumps(q.get("options", [])) if q.get("options") else None
        q_text = q.get("question", "").strip()

        # Check existing for deduplication
        existing_id = session.execute(
            text("""
                SELECT id FROM question_master
                WHERE topic_id = :t_id AND LOWER(TRIM(question)) = LOWER(TRIM(:q_text))
                LIMIT 1
            """),
            {"t_id": resolved_topic_id, "q_text": q_text}
        ).scalar()

        if existing_id:
            # Update existing with refined explanation and options
            session.execute(
                text("""
                    UPDATE question_master
                    SET options = :options, correct_answer = :correct_answer, explanation = :explanation,
                        marks = :marks, difficulty_level_id = :diff_id, question_type_id = :type_id,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                """),
                {
                    "id": existing_id,
                    "options": options_json,
                    "correct_answer": q.get("correct_answer", "A"),
                    "explanation": q.get("explanation", ""),
                    "marks": int(q.get("marks", 1)),
                    "diff_id": diff_id,
                    "type_id": q_type_id
                }
            )
            updated_count += 1
            duplicate_skipped += 1
        else:
            session.execute(
                text("""
                    INSERT INTO question_master 
                    (topic_id, question_type_id, difficulty_level_id, question, options, correct_answer, explanation, marks, is_active, created_at, updated_at)
                    VALUES 
                    (:topic_id, :type_id, :diff_id, :question, :options, :correct_answer, :explanation, :marks, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """),
                {
                    "topic_id": resolved_topic_id,
                    "type_id": q_type_id,
                    "diff_id": diff_id,
                    "question": q_text,
                    "options": options_json,
                    "correct_answer": q.get("correct_answer", "A"),
                    "explanation": q.get("explanation", ""),
                    "marks": int(q.get("marks", 1))
                }
            )
            inserted_count += 1

    # 3. Create Document and Document Chunks
    doc_id = str(uuid.uuid4())
    doc_record = Document(
        id=doc_id,
        filename=filename,
        content_type=document_type,
        board=board,
        class_grade=class_grade,
        subject=subject,
        uploaded_by=uploaded_by,
        status="PROCESSED",
    )
    session.add(doc_record)
    session.flush()

    # Create chunks from text if available
    chunks = []
    if cleaned_text:
        chunks = document_processor.chunk_text(cleaned_text, chunk_size=800, overlap=120)

    chunk_ids = []
    chunk_texts = []
    chunk_metas = []

    for c_idx, c_content in enumerate(chunks):
        c_id = str(uuid.uuid4())
        d_chunk = DocumentChunk(
            id=c_id,
            document_id=doc_id,
            chunk_index=c_idx,
            content=c_content,
            vector_id=f"{doc_id}_{c_idx}",
        )
        session.add(d_chunk)
        chunk_ids.append(f"{doc_id}_{c_idx}")
        chunk_texts.append(c_content)
        chunk_metas.append({
            "document_id": doc_id,
            "filename": filename,
            "board": board,
            "class_grade": class_grade,
            "subject": subject,
            "document_type": document_type,
            "chunk_index": c_idx,
        })

    session.commit()

    # 4. ChromaDB Vector Store Sync
    if vector_db.is_enabled() and chunk_texts:
        try:
            embeddings = embedding_engine.embed(chunk_texts)
            vector_db.upsert_chunks(chunk_ids, chunk_texts, embeddings, chunk_metas)
            print(f"  • ChromaDB Synced : {len(chunk_texts)} chunks indexed with Mistral Embeddings")
        except Exception as vec_err:
            logger.warning(f"Vector store indexing notice: {vec_err}")

    # 5. ArangoDB Knowledge Graph Sync
    try:
        from database import graph_db
        if graph_db.is_enabled():
            chapter_name_clean = title or filename.replace(".pdf", "").replace(".docx", "").replace(".doc", "").replace("_", " ")
            topics_to_push = detected_topics if (detected_topics and len(detected_topics) > 0) else [chapter_name_clean]
            graph_db.upsert_hierarchical_curriculum_branch(
                board=board,
                class_grade=class_grade,
                subject=subject,
                chapter=chapter_name_clean,
                topics_list=topics_to_push
            )
            print(f"  • ArangoDB Synced : Hierarchy & {len(topics_to_push)} topic node(s) linked to knowledge graph")
    except Exception as graph_err:
        logger.warning(f"ArangoDB sync notice in pipeline: {graph_err}")

    print(f"  • Questions Saved : {inserted_count} inserted, {updated_count} updated ({duplicate_skipped} duplicates protected)")
    _print_separator(f"QUESTIONS PERSISTED SUCCESSFULLY: {filename}", TermColors.GREEN)

    return {
        "success": True,
        "filename": filename,
        "document_id": doc_id,
        "title": title or filename,
        "total_processed": len(questions),
        "total_saved": inserted_count + updated_count,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "duplicate_skipped_count": duplicate_skipped,
        "chunk_count": len(chunks),
        "topic_id": resolved_topic_id,
    }

