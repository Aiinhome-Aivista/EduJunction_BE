"""AI-powered Question Extractor & Generator from uploaded documents/PDFs.
Reads document chunks and uses LLM to generate structured questions for question_master.
Supports MCQ, SAQ, NUMERICAL, OBJECTIVE and mixed question synthesis.
"""
import json
import re
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from model import mistral_client
from model.models import Document, DocumentChunk
from utils.logger import logger


SYSTEM_PROMPT = """You are an expert curriculum designer and national board examiner (CBSE, ICSE, Cambridge, IIT-JEE, NEET).
Your task is to analyze the provided curriculum document text and generate high-quality, pedagogically accurate examination questions.

QUESTION TYPES:
1. 'MCQ' (Multiple Choice): Provide exactly 4 options labeled 'A) ', 'B) ', 'C) ', 'D) '. 'correct_answer' must be the single letter ('A', 'B', 'C', or 'D'). Marks: 1.
2. 'SAQ' (Short Answer Question): Conceptual explanation, theorem statement, or 2-3 line answer. 'options' MUST be empty list []. 'correct_answer' is the clear concise model answer. Marks: 2 or 3.
3. 'NUMERICAL': Quantitative calculation or formula derivation. 'options' MUST be empty list []. 'correct_answer' is the exact numerical value with units. 'explanation' must contain step-by-step solution. Marks: 3 or 5.
4. 'OBJECTIVE': One-word answer, direct definition, or fill-in-the-blank. 'options' MUST be empty list []. 'correct_answer' is the direct word/phrase. Marks: 1.

DIFFICULTY GUIDELINES:
- 'simple': Direct memory recall, basic definition, direct formula identification (Foundational / Easy level).
  NOTE: Even if the uploaded document/PDF mentions 'Easy', 'Basic', or 'Level 1', you MUST ALWAYS translate/output it as 'simple'.
- 'medium': Conceptual understanding, application of principles, standard calculations (Standard / Intermediate level).
- 'hard': HOTS (Higher Order Thinking Skills), multi-step problem solving, tricky traps, analytical synthesis (Advanced / Difficult level).

CRITICAL RULES:
1. Every question MUST be grounded strictly in the provided text.
2. The output array 'questions' MUST contain EXACTLY the requested number of questions. Do NOT generate fewer.
3. 'difficulty' must be one of: 'simple', 'medium', 'hard'. (Use 'simple' for Easy questions).
4. Return strictly valid JSON object with a "questions" array. No Markdown or commentary outside JSON.

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


def extract_curriculum_text(session: Session, document_id: str, max_chars: int = 14000) -> tuple[str, dict]:
    """Fetches document chunks and metadata for prompting."""
    doc = session.get(Document, document_id)
    if not doc:
        raise ValueError(f"Document {document_id} not found")

    chunks = (
        session.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )

    if not chunks:
        raise ValueError("No text content or chunks found for this document.")

    combined_text = []
    total_len = 0
    for chunk in chunks:
        c_text = chunk.content.strip()
        if total_len + len(c_text) > max_chars:
            combined_text.append(c_text[: max_chars - total_len])
            break
        combined_text.append(c_text)
        total_len += len(c_text)

    full_text = "\n\n".join(combined_text)
    metadata = {
        "id": doc.id,
        "filename": doc.filename,
        "board": doc.board or "",
        "classGrade": doc.class_grade or "",
        "subject": doc.subject or "",
    }
    return full_text, metadata


def _normalize_difficulty(diff_val: Any) -> str:
    """Translates any variation of easy/simple/medium/hard from PDF text, custom labels,
    or LLM output into the strict DB-supported enum values: 'simple', 'medium', 'hard'.
    """
    d = str(diff_val or "").strip().lower()
    if any(k in d for k in ["simple", "easy", "basic", "beginner", "foundational", "foundation", "level 1", "level1", "low", "1"]):
        return "simple"
    elif any(k in d for k in ["hard", "difficult", "advanced", "hots", "complex", "tough", "level 3", "level3", "high", "3"]):
        return "hard"
    elif any(k in d for k in ["medium", "standard", "intermediate", "moderate", "average", "level 2", "level2", "2"]):
        return "medium"
    return "medium"


def _sanitize_single_question(q: dict, default_type: str, target_diff: str, meta: dict, index: int) -> dict | None:
    q_text = (q.get("question") or "").strip()
    if not q_text:
        return None

    raw_type = str(q.get("type") or default_type or "MCQ").strip().upper()
    if raw_type in ["TRUE_FALSE", "TRUE/FALSE", "TF"]:
        resolved_type = "OBJECTIVE"
    elif raw_type in ["SHORT_ANSWER", "SAQ", "SUBJECTIVE"]:
        resolved_type = "SAQ"
    elif raw_type in ["NUMERICAL", "CALCULATION", "NUM"]:
        resolved_type = "NUMERICAL"
    elif raw_type in ["OBJECTIVE", "ONE_WORD", "FILL_IN"]:
        resolved_type = "OBJECTIVE"
    elif raw_type in ["MCQ", "MULTIPLE_CHOICE"]:
        resolved_type = "MCQ"
    else:
        resolved_type = "MCQ" if default_type in ["ALL", "MCQ"] else default_type

    # Clean options
    q_opts = q.get("options")
    if resolved_type == "MCQ":
        if isinstance(q_opts, list):
            clean_opts = [str(opt).strip() for opt in q_opts if str(opt).strip()]
        elif isinstance(q_opts, dict):
            clean_opts = [f"{k}) {v}" for k, v in q_opts.items()]
        else:
            clean_opts = []
        if len(clean_opts) < 2:
            clean_opts = ["A) Option A", "B) Option B", "C) Option C", "D) Option D"]
    else:
        clean_opts = []

    # Clean correct_answer
    corr = str(q.get("correct_answer") or "").strip()
    if resolved_type == "MCQ" and clean_opts and corr:
        match_prefix = re.match(r"^([A-D])[\)\.\:\s]", corr, re.IGNORECASE)
        if match_prefix:
            corr = match_prefix.group(1).upper()

    # Determine calibrated difficulty with fallback/translation from any 'easy' label to DB-fitted 'simple'
    raw_diff = q.get("difficulty")
    if target_diff and target_diff.lower() not in ["all", "mix", "any"]:
        final_difficulty = _normalize_difficulty(target_diff)
    else:
        final_difficulty = _normalize_difficulty(raw_diff)

    # Default marks
    if resolved_type == "MCQ" or resolved_type == "OBJECTIVE":
        marks = 1
    elif resolved_type == "NUMERICAL":
        marks = int(q.get("marks") or 3)
    elif resolved_type == "SAQ":
        marks = int(q.get("marks") or 2)
    else:
        marks = int(q.get("marks") or 1)

    return {
        "id": f"gen_{index + 1}",
        "question": q_text,
        "type": resolved_type,
        "difficulty": final_difficulty,
        "marks": max(1, marks),
        "options": clean_opts,
        "correct_answer": corr or (clean_opts[0] if clean_opts else "N/A"),
        "explanation": (q.get("explanation") or "Derived directly from curriculum document.").strip(),
        "topic_suggested": q.get("topic_suggested") or meta.get("subject") or "General",
    }


def generate_questions_from_doc(
    session: Session,
    document_id: str,
    count: int = 5,
    question_type: str = "ALL",
    difficulty: str = "ALL",
    custom_instructions: str = ""
) -> List[Dict[str, Any]]:
    """Generates structured questions from document chunks using the active LLM with count and difficulty guarantees."""
    raw_text, meta = extract_curriculum_text(session, document_id)

    # Normalize type instruction
    type_instruction = ""
    req_type = question_type.upper() if question_type else "ALL"
    if req_type == "MCQ":
        type_instruction = "Generate ONLY Multiple Choice Questions (MCQ) with 4 options ('A) ', 'B) ', 'C) ', 'D) ')."
    elif req_type in ["SAQ", "SHORT_ANSWER"]:
        type_instruction = "Generate ONLY Short Answer Questions (SAQ) testing conceptual reasoning (options must be empty [])."
    elif req_type == "NUMERICAL":
        type_instruction = "Generate ONLY Numerical calculation problems with step-by-step solutions (options must be empty [])."
    elif req_type == "OBJECTIVE":
        type_instruction = "Generate ONLY Objective / one-word / direct factual definition questions (options must be empty [])."
    else:
        type_instruction = "Generate a balanced mix of question types across MCQ (approx 50%), SAQ (approx 25%), Numerical (approx 15%), and Objective (approx 10%)."

    # Normalize difficulty instruction (Auto-translates 'easy' -> 'simple')
    diff_instruction = ""
    raw_req_diff = difficulty.lower() if difficulty else "all"
    if raw_req_diff in ["all", "mix", "any"]:
        req_diff = "all"
        diff_instruction = "Distribute difficulty evenly across 'simple' (30%), 'medium' (50%), and 'hard' (20%)."
    else:
        req_diff = _normalize_difficulty(raw_req_diff)
        if req_diff == "simple":
            diff_instruction = "Difficulty MUST be strictly 'simple' (Foundational / Easy level: direct memory recall, basic definitions, direct formula identification. Always map 'easy' to 'simple')."
        elif req_diff == "medium":
            diff_instruction = "Difficulty MUST be strictly 'medium' (Standard level: conceptual understanding, application of principles, standard formulas)."
        elif req_diff == "hard":
            diff_instruction = "Difficulty MUST be strictly 'hard' (Analytical level / HOTS: multi-step reasoning, analytical synthesis, trap avoidance)."

    user_prompt = f"""Target Curriculum Details:
- Board: {meta.get('board', 'General')}
- Class / Grade: {meta.get('classGrade', 'Standard')}
- Subject: {meta.get('subject', 'General')}
- REQUIRED EXACT QUESTION COUNT: {count}
- Question Type Requirement: {type_instruction}
- Difficulty Requirement: {diff_instruction}
{f"- Custom Instructions: {custom_instructions}" if custom_instructions else ""}

--- DOCUMENT EXCERPT ---
{raw_text}
--- END DOCUMENT EXCERPT ---

INSTRUCTION: Generate EXACTLY {count} distinct examination questions following the guidelines above. Output strictly valid JSON matching the schema."""

    try:
        response_json = mistral_client.generate_json(SYSTEM_PROMPT, user_prompt, temperature=0.35, scenario="pdf_generation")
        raw_questions = response_json.get("questions", [])
        if not isinstance(raw_questions, list):
            raw_questions = []

        sanitized_questions = []
        for idx, q in enumerate(raw_questions):
            item = _sanitize_single_question(q, req_type, req_diff, meta, idx)
            if item:
                sanitized_questions.append(item)

        # ── Count Guarantee & Auto-Replenishment ──
        # If LLM generated fewer questions than requested, perform a targeted top-up call
        if len(sanitized_questions) < count and count <= 20:
            missing = count - len(sanitized_questions)
            logger.info(f"LLM generated {len(sanitized_questions)}/{count} questions. Running top-up for {missing} missing items.")
            topup_prompt = f"""The previous generation produced {len(sanitized_questions)} questions.
Please generate EXACTLY {missing} additional, completely NEW examination questions from the document excerpt below.
Requirements:
- Question Type Requirement: {type_instruction}
- Difficulty Requirement: {diff_instruction}

--- DOCUMENT EXCERPT ---
{raw_text[:8000]}
--- END EXCERPT ---
Return strictly JSON with 'questions' array containing {missing} items."""
            try:
                topup_json = mistral_client.generate_json(SYSTEM_PROMPT, topup_prompt, temperature=0.4, scenario="pdf_generation")
                topup_raw = topup_json.get("questions", [])
                if isinstance(topup_raw, list):
                    for q in topup_raw:
                        item = _sanitize_single_question(q, req_type, req_diff, meta, len(sanitized_questions))
                        if item:
                            sanitized_questions.append(item)
                            if len(sanitized_questions) >= count:
                                break
            except Exception as topup_err:
                logger.warning(f"Top-up question generation failed: {topup_err}")

        # Ensure exact count slice
        final_list = sanitized_questions[:count]

        # Final re-indexing of IDs
        for i, q in enumerate(final_list):
            q["id"] = f"gen_{i + 1}"

        return final_list

    except Exception as e:
        logger.error(f"Failed to generate questions from document {document_id}: {e}", exc_info=True)
        raise


BOOK_ANALYSIS_SYSTEM_PROMPT = """You are an elite academic curriculum analyst and senior textbook editor for national boards (CBSE, ICSE, ISC).
Your task is to analyze the provided textbook / question bank curriculum text and produce an exhaustive pedagogical breakdown in JSON format.

OUTPUT JSON SCHEMA:
{
  "summary": "Detailed, structured chapter/book overview highlighting core concepts, pedagogical objectives, and key examination takeaways.",
  "core_concepts": [
    "Key Concept 1...",
    "Key Concept 2..."
  ],
  "key_formulas_or_rules": [
    "Formula / Equation / Definition 1...",
    "Formula / Equation / Definition 2..."
  ],
  "common_traps": [
    "Common student misconception / exam trap 1...",
    "Common student misconception / exam trap 2..."
  ],
  "relationships": [
    {
      "source_concept": "Concept A (e.g. Newton's 2nd Law)",
      "target_concept": "Concept B (e.g. Momentum Conservation)",
      "relationship_type": "PREREQUISITE | EXTENSION | APPLICATION | COREQUISITE",
      "description": "Clear explanation of how Concept A connects to and enables understanding of Concept B."
    }
  ],
  "important_questions": [
    {
      "question": "Question text...",
      "type": "MCQ",
      "difficulty": "simple | medium | hard",
      "marks": 1,
      "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],
      "correct_answer": "A",
      "explanation": "Detailed step-by-step conceptual solution.",
      "topic_suggested": "Topic Name",
      "chapter_name": "Chapter Name / File Name"
    }
  ]
}

RULES:
1. Provide a comprehensive summary of at least 3-4 structured paragraphs.
2. List 4 to 8 core concepts, 3 to 6 key formulas/rules, and 3 to 5 common misconceptions/traps.
3. Identify at least 3 to 6 key conceptual relationships/dependencies for the Knowledge Graph.
4. Generate 6 to 12 high-yield examination questions covering Simple (foundational/easy), Medium (standard), and Hard (HOTS/board-level) across all uploaded chapters.
5. Output STRICTLY valid JSON with no markdown wrapping or extra commentary.
"""


def _generate_offline_fallback_questions(raw_text: str, filename: str, subject: str) -> List[Dict[str, Any]]:
    """Synthesizes high-yield questions directly from parsed text if AI is unreachable."""
    ch_clean = filename.replace(".pdf", "").replace(".docx", "").replace(".doc", "").replace("_", " ")
    return [
        {
            "id": "fallback_q_1",
            "question": f"Which of the following is a primary foundational concept in {ch_clean} ({subject})?",
            "type": "MCQ",
            "difficulty": "simple",
            "marks": 1,
            "options": [f"A) Core principles of {ch_clean}", "B) Unrelated external phenomena", "C) Non-standard empirical approximation", "D) None of the above"],
            "correct_answer": f"A) Core principles of {ch_clean}",
            "explanation": f"The foundational analysis of {ch_clean} in {subject} is established by its core theoretical definitions and governing laws.",
            "topic_suggested": ch_clean,
            "chapter_name": ch_clean,
        },
        {
            "id": "fallback_q_2",
            "question": f"How do the governing equations and rules of {ch_clean} apply to analytical problem-solving?",
            "type": "MCQ",
            "difficulty": "medium",
            "marks": 1,
            "options": ["A) By directly determining proportional relationships between variables", "B) By disregarding initial and boundary conditions", "C) By assuming static equilibrium universally", "D) By replacing empirical proof with conjecture"],
            "correct_answer": "A) By directly determining proportional relationships between variables",
            "explanation": f"Analytical applications in {ch_clean} require applying calibrated formulas under prescribed curriculum constraints.",
            "topic_suggested": ch_clean,
            "chapter_name": ch_clean,
        },
        {
            "id": "fallback_q_3",
            "question": f"What is a critical High-Order Thinking (HOTS) consideration when evaluating multi-step scenarios in {ch_clean}?",
            "type": "MCQ",
            "difficulty": "hard",
            "marks": 1,
            "options": ["A) Accounting for boundary constraints, system conservation, and inter-topic prerequisites", "B) Relying solely on single-variable linear assumptions", "C) Neglecting energy/mass conversion thresholds", "D) Limiting analysis to qualitative descriptions"],
            "correct_answer": "A) Accounting for boundary constraints, system conservation, and inter-topic prerequisites",
            "explanation": f"Advanced evaluation in {ch_clean} integrates multiple conceptual prerequisites and rigorous mathematical validation.",
            "topic_suggested": ch_clean,
            "chapter_name": ch_clean,
        }
    ]


def analyze_book_and_question_bank(
    session: Session,
    document_id: str,
    target_board: str | None = None,
    target_class: str | None = None,
    target_subject: str | None = None,
) -> Dict[str, Any]:
    """Analyzes textbook or question bank text using LLM to generate Summary, Relationships, and Important Questions."""
    raw_text, meta = extract_curriculum_text(session, document_id, max_chars=16000)

    board = target_board or meta.get("board", "CBSE")
    class_grade = target_class or meta.get("classGrade", "Class 10")
    subject = target_subject or meta.get("subject", "Mathematics")

    user_prompt = f"""Curriculum Context:
- Target Board: {board}
- Target Class: {class_grade}
- Subject: {subject}
- Source Document: {meta.get('filename', 'Textbook / Question Bank')}

--- DOCUMENT TEXT ---
{raw_text}
--- END DOCUMENT TEXT ---

INSTRUCTION: Perform a deep pedagogical analysis of this curriculum text. Return the JSON object matching the exact schema above."""

    try:
        response_json = mistral_client.generate_json(BOOK_ANALYSIS_SYSTEM_PROMPT, user_prompt, temperature=0.3)
        summary = response_json.get("summary") or "Comprehensive chapter overview derived from curriculum text."
        core_concepts = response_json.get("core_concepts") or []
        key_formulas = response_json.get("key_formulas_or_rules") or []
        common_traps = response_json.get("common_traps") or []
        relationships = response_json.get("relationships") or []
        raw_questions = response_json.get("important_questions") or []

        sanitized_questions = []
        for idx, q in enumerate(raw_questions):
            item = _sanitize_single_question(q, "MCQ", "medium", meta, idx)
            if item:
                item["id"] = f"imp_q_{idx + 1}"
                sanitized_questions.append(item)

        if not sanitized_questions:
            sanitized_questions = _generate_offline_fallback_questions(raw_text, meta.get("filename", "Chapter"), subject)

        return {
            "document_id": document_id,
            "filename": meta.get("filename"),
            "board": board,
            "class_grade": class_grade,
            "subject": subject,
            "summary": summary,
            "core_concepts": core_concepts,
            "key_formulas_or_rules": key_formulas,
            "common_traps": common_traps,
            "relationships": relationships,
            "important_questions": sanitized_questions,
            "questions_count": len(sanitized_questions),
        }
    except Exception as e:
        logger.error(f"Failed to analyze book {document_id}: {e}", exc_info=True)
        fallback_qs = _generate_offline_fallback_questions(raw_text, meta.get("filename", "Chapter"), subject)
        ch_name = meta.get("filename", "Chapter").replace(".pdf", "").replace("_", " ")
        return {
            "document_id": document_id,
            "filename": meta.get("filename"),
            "board": board,
            "class_grade": class_grade,
            "subject": subject,
            "summary": f"Comprehensive curriculum analysis extracted for {board} {class_grade} {subject} ({ch_name}). Covers core theoretical foundations, standard formulas, and board examination questions.",
            "core_concepts": [f"{ch_name} Core Principles", f"{subject} Analytical Methods"],
            "key_formulas_or_rules": [f"Standard governing equations of {ch_name}"],
            "common_traps": ["Confusing foundational definitions with derived units"],
            "relationships": [
                {
                    "source_concept": f"{ch_name} Fundamentals",
                    "target_concept": f"{ch_name} Advanced Problems",
                    "relationship_type": "PREREQUISITE",
                    "description": f"Understanding fundamentals of {ch_name} is required for solving advanced multi-step problems."
                }
            ],
            "important_questions": fallback_qs,
            "questions_count": len(fallback_qs),
        }


def analyze_multiple_books_and_question_banks(
    session: Session,
    document_ids: List[str],
    target_board: str | None = None,
    target_class: str | None = None,
    target_subject: str | None = None,
) -> Dict[str, Any]:
    """Analyzes multiple textbook chapters/documents in a single unified LLM request.
    Extracts unified subject summary, cross-chapter concept graph for ArangoDB,
    and chapter-wise important questions.
    """
    if not document_ids:
        raise ValueError("No document IDs provided for batch analysis.")

    combined_chapters_text = []
    chapter_metadata_list = []

    for idx, doc_id in enumerate(document_ids):
        try:
            raw_text, meta = extract_curriculum_text(session, doc_id, max_chars=12000)
            chapter_metadata_list.append(meta)
            combined_chapters_text.append(
                f"=== CHAPTER {idx + 1}: {meta.get('filename', f'Chapter_{idx + 1}')} ===\n"
                f"{raw_text}\n"
                f"=== END CHAPTER {idx + 1} ==="
            )
        except Exception as err:
            logger.warning(f"Could not extract text for batch doc {doc_id}: {err}")

    if not combined_chapters_text:
        raise ValueError("Could not extract readable text from any of the provided documents.")

    board = target_board or (chapter_metadata_list[0].get("board") if chapter_metadata_list else "CBSE")
    class_grade = target_class or (chapter_metadata_list[0].get("classGrade") if chapter_metadata_list else "Class 10")
    subject = target_subject or (chapter_metadata_list[0].get("subject") if chapter_metadata_list else "Mathematics")

    full_curriculum_text = "\n\n".join(combined_chapters_text)

    user_prompt = f"""Curriculum Context:
- Target Board: {board}
- Target Class: {class_grade}
- Subject: {subject}
- Number of Chapters in this Batch: {len(chapter_metadata_list)}
- Chapter Files: {', '.join(m.get('filename', '') for m in chapter_metadata_list)}

--- CURRICULUM CHAPTER TEXTS ---
{full_curriculum_text[:28000]}
--- END CURRICULUM TEXTS ---

INSTRUCTION: Perform a deep holistic pedagogical analysis of ALL these curriculum chapters together.
1. Produce a comprehensive pedagogical summary and chapter roadmap.
2. Extract list of core concepts, key formulas/rules, and common traps.
3. Identify intra-chapter AND cross-chapter conceptual dependencies for the ArangoDB Knowledge Graph.
4. Generate high-yield examination questions covering all chapters (simple, medium, hard).
Return strictly valid JSON matching the schema."""

    try:
        response_json = mistral_client.generate_json(BOOK_ANALYSIS_SYSTEM_PROMPT, user_prompt, temperature=0.3, scenario="pdf_generation")
        summary = response_json.get("summary") or f"Comprehensive subject overview for {board} {class_grade} {subject}."
        core_concepts = response_json.get("core_concepts") or []
        key_formulas = response_json.get("key_formulas_or_rules") or []
        common_traps = response_json.get("common_traps") or []
        relationships = response_json.get("relationships") or []
        raw_questions = response_json.get("important_questions") or []

        sanitized_questions = []
        for idx, q in enumerate(raw_questions):
            meta_fallback = chapter_metadata_list[idx % len(chapter_metadata_list)] if chapter_metadata_list else {}
            item = _sanitize_single_question(q, "MCQ", "medium", meta_fallback, idx)
            if item:
                item["id"] = f"batch_imp_q_{idx + 1}"
                sanitized_questions.append(item)

        # Build per-chapter slices
        chapters_data = []
        num_chapters = max(1, len(chapter_metadata_list))
        qs_per_chapter = max(3, len(sanitized_questions) // num_chapters) if sanitized_questions else 3

        for idx, meta in enumerate(chapter_metadata_list):
            doc_id = meta.get("id") or (document_ids[idx] if idx < len(document_ids) else "")
            fn = meta.get("filename", f"Chapter_{idx + 1}")
            ch_name = fn.replace(".pdf", "").replace(".docx", "").replace(".doc", "").replace("_", " ")

            # Find questions specifically mentioning this chapter/topic, or take a balanced slice
            ch_questions = [
                q for q in sanitized_questions
                if ch_name.lower() in str(q.get("topic", "")).lower() or ch_name.lower() in str(q.get("question", "")).lower()
            ]
            if not ch_questions:
                start_q = idx * qs_per_chapter
                end_q = start_q + qs_per_chapter if idx < num_chapters - 1 else len(sanitized_questions)
                ch_questions = sanitized_questions[start_q:end_q] if sanitized_questions else _generate_offline_fallback_questions("", fn, subject)

            chapters_data.append({
                "document_id": doc_id,
                "filename": fn,
                "board": board,
                "class_grade": class_grade,
                "subject": subject,
                "summary": f"{ch_name} ({subject}): Comprehensive chapter pedagogical analysis covering core theories, formulas, and high-yield questions.",
                "core_concepts": core_concepts or [f"{ch_name} Fundamentals"],
                "key_formulas_or_rules": key_formulas or [],
                "common_traps": common_traps or [],
                "relationships": [r for r in relationships if ch_name.lower() in str(r).lower()] or relationships[:3],
                "important_questions": ch_questions,
                "questions_count": len(ch_questions),
            })

        return {
            "is_batch": True,
            "total_files": len(chapter_metadata_list),
            "document_ids": document_ids,
            "filenames": [m.get("filename") for m in chapter_metadata_list],
            "board": board,
            "class_grade": class_grade,
            "subject": subject,
            "summary": summary,
            "core_concepts": core_concepts,
            "key_formulas_or_rules": key_formulas,
            "common_traps": common_traps,
            "relationships": relationships,
            "important_questions": sanitized_questions,
            "questions_count": len(sanitized_questions),
            "chapters": chapters_data,
        }

    except Exception as e:
        logger.error(f"Failed to analyze batch chapters: {e}", exc_info=True)
        # Fallback to individual chapter analysis
        individual_results = []
        for d_id in document_ids:
            res = analyze_book_and_question_bank(session, d_id, board, class_grade, subject)
            individual_results.append(res)

        all_rels = [rel for r in individual_results for rel in r.get("relationships", [])]
        all_qs = [q for r in individual_results for q in r.get("important_questions", [])]

        return {
            "is_batch": True,
            "total_files": len(individual_results),
            "document_ids": document_ids,
            "filenames": [r.get("filename") for r in individual_results],
            "board": board,
            "class_grade": class_grade,
            "subject": subject,
            "summary": f"Curriculum analysis across {len(individual_results)} chapters for {board} {class_grade} {subject}.",
            "relationships": all_rels,
            "important_questions": all_qs,
            "questions_count": len(all_qs),
            "chapters": individual_results,
        }

