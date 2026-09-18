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
- 'easy': Direct memory recall, basic definition, direct formula identification (Foundational).
- 'medium': Conceptual understanding, application of principles, standard calculations (Standard).
- 'hard': HOTS (Higher Order Thinking Skills), multi-step problem solving, tricky traps, analytical synthesis (Advanced).

CRITICAL RULES:
1. Every question MUST be grounded strictly in the provided text.
2. The output array 'questions' MUST contain EXACTLY the requested number of questions. Do NOT generate fewer.
3. 'difficulty' must be one of: 'easy', 'medium', 'hard'.
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

    # Determine calibrated difficulty
    if target_diff.lower() in ["easy", "medium", "hard"]:
        final_difficulty = target_diff.lower()
    else:
        raw_diff = str(q.get("difficulty") or "medium").strip().lower()
        final_difficulty = raw_diff if raw_diff in ["easy", "medium", "hard"] else "medium"

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

    # Normalize difficulty instruction
    diff_instruction = ""
    req_diff = difficulty.lower() if difficulty else "all"
    if req_diff == "easy":
        diff_instruction = "Difficulty MUST be strictly 'easy' (Foundation level: direct definitions, factual recall, basic terminology)."
    elif req_diff == "medium":
        diff_instruction = "Difficulty MUST be strictly 'medium' (Standard level: conceptual understanding, application of principles, standard formulas)."
    elif req_diff == "hard":
        diff_instruction = "Difficulty MUST be strictly 'hard' (Analytical level / HOTS: multi-step reasoning, analytical synthesis, trap avoidance)."
    else:
        diff_instruction = "Distribute difficulty evenly across 'easy' (30%), 'medium' (50%), and 'hard' (20%)."

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
        response_json = mistral_client.generate_json(SYSTEM_PROMPT, user_prompt, temperature=0.35)
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
                topup_json = mistral_client.generate_json(SYSTEM_PROMPT, topup_prompt, temperature=0.4)
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
