"""Question Quality & Sanity Guardrails with AI Inspector.

Validates and audits candidate questions from Database, Fallback, and LLM generation:
1. Missing Image / Broken Diagram filter: Rejects questions that refer to a figure/diagram without an image.
2. MCQ Options validation: Ensures 4 authentic options and non-empty correct answer (no placeholder Option A/B).
3. Cross-Subject Contamination filter: Prevents leakage of unrelated subjects.
4. Completeness & Length validation: Ensures clear pedagogical text.
5. AI Auditor & Auto-Polisher: Uses LLM to inspect, fix dummy choices, and regenerate defective questions.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Patterns indicating an explicit visual reference
_IMAGE_REFERENCE_PATTERNS = [
    r"\b(?:in\s+the\s+(?:given|below|above|following)\s+(?:figure|diagram|picture|image|graph|chart|drawing|illustration))\b",
    r"\b(?:refer\s+to\s+the\s+(?:figure|diagram|picture|image|graph|chart))\b",
    r"\b(?:as\s+shown\s+in\s+the\s+(?:figure|diagram|picture|image|graph|chart))\b",
    r"\b(?:observe\s+the\s+(?:figure|diagram|picture|image|graph|chart))\b",
    r"\b(?:from\s+the\s+(?:figure|diagram|graph|chart)\s+(?:given|shown))\b",
    r"\b(?:look\s+at\s+the\s+(?:figure|diagram|image))\b",
    r"\b(?:figure\s+\d+|fig\.\s*\d+)\b",
]

_COMPILED_IMAGE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _IMAGE_REFERENCE_PATTERNS]

# Pure subject-specific boundary keywords to catch cross-subject leakage
_SUBJECT_LEAKAGE_MAP = {
    "mathematics": {
        "forbidden_terms": [
            "photosynthesis", "chlorophyll", "mitochondria", "amoeba", "respiration in humans",
            "valency of", "periodic table", "atomic number of", "chemical reaction of",
            "french revolution", "mughal empire", "judiciary", "constitution of india", "future tense", "past tense"
        ],
        "allowed_math_terms": ["equation", "triangle", "polynomial", "derivative", "integral", "matrix", "vector", "probability", "algebra", "geometry", "trigonometry", "ratio", "function", "fraction", "multiplication", "division"]
    },
    "physics": {
        "forbidden_terms": [
            "mitochondria", "amoeba", "rbc and wbc", "digestive system", "french revolution", "mughal empire"
        ]
    },
    "chemistry": {
        "forbidden_terms": [
            "amoeba", "rbc and wbc", "digestive system", "french revolution", "judiciary", "constitution of india"
        ]
    },
    "biology": {
        "forbidden_terms": [
            "integration by parts", "pythagoras theorem", "quadratic formula", "derivative of", "french revolution"
        ]
    }
}


# Patterns indicating junk exam instructions or copyright artifacts
_JUNK_INSTRUCTION_PATTERNS = [
    r'\bplease\s+check\s+that\s+this\s+question\s+paper\s+contains\b',
    r'\broll\s+number\s*[\:\-]?',
    r'\bcandidate\s+must\s+write\s+the\s+q\.?p\.?\s*code\b',
    r'\bserial\s+number\s+of\s+the\s+question\b',
    r'\bno\s+part\s+of\s+this\s+(?:publication|book|document)\s+may\s+be\s+reproduced\b',
    r'\ball\s+rights\s+reserved\b',
    r'\bisbn\s*[\:\-]?\s*\d+',
    r'\bgeneral\s+instructions\s*[\:\-]',
    r'\bquestion\s+paper\s+code\b',
]
_COMPILED_JUNK_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _JUNK_INSTRUCTION_PATTERNS]

_DUMMY_ANSWER_PATTERNS = [
    r'\bstandard\s+model\s+solution\b',
    r'\bmodel\s+solution\s+for\b',
    r'^(?:[a-d]\s*[\)\.\:\-]\s*)?option\s*[a-d]$',
    r'^dummy\s+answer$',
    r'\boperates\s+linearly\s+under\s+standard\b',
]
_COMPILED_DUMMY_ANSWERS = [re.compile(p, re.IGNORECASE) for p in _DUMMY_ANSWER_PATTERNS]

_DUMMY_EXPL_PATTERNS = [
    r'\bconceptual\s+principle\s+for\b',
    r'\bstandard\s+conceptual\s+principle\b',
    r'\bstandard\s+curriculum\s+solution\b',
]
_COMPILED_DUMMY_EXPLS = [re.compile(p, re.IGNORECASE) for p in _DUMMY_EXPL_PATTERNS]


_DUMMY_CATEGORY_TITLES = {
    "long", "long answer", "long answer question", "long answer questions", "laq",
    "short", "short answer", "saq", "vsaq", "mcq", "multiple choice", "objective",
    "case study", "numerical", "assertion reason", "true or false", "fill in the blank",
    "fill in the blanks", "match the following", "one word", "vsa", "problem", "solution",
    "1 mark", "2 marks", "3 marks", "4 marks", "5 marks", "8 marks", "1m", "2m", "3m", "4m", "5m", "8m",
    "section a", "section b", "section c", "section d", "section e", "section f",
    "question", "questions", "answer the following", "solve", "evaluate"
}


def validate_question_quality(q: Dict[str, Any], requested_subject: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Validates a candidate question for pedagogical sanity, UI compatibility and completeness.
    
    Returns (True, None) if question is valid, or (False, reason) if rejected.
    """
    if not isinstance(q, dict):
        return False, "Malformed question data structure"

    q_text = str(q.get("question_text") or q.get("question") or q.get("questionText") or "").strip()
    if len(q_text) < 12:
        return False, f"Question text too short ({len(q_text)} chars)"

    clean_q_low = q_text.lower().strip('. :-\t\n')
    if clean_q_low in _DUMMY_CATEGORY_TITLES or len(q_text.split()) < 3:
        return False, f"Question text '{q_text}' is a dummy category placeholder or header"

    # 1. Exam paper instructions and publisher / copyright junk check
    for pat in _COMPILED_JUNK_PATTERNS:
        if pat.search(q_text):
            return False, "Question is an exam paper instruction or copyright artifact"

    # Detect broken fragments
    if re.search(r"^(?:explain\s+the\s+principle\s*:\s*|state\s+whether\s*:\s*|calculate\s*:\s*|the\s+following\s+questions\s*:\s*)$", q_text, re.IGNORECASE):
        return False, "Question is an incomplete prompt prefix"

    if re.search(r"\b(?:complete\s+the|to\s+the|of\s+the|in\s+the|at\s+the|for\s+the|is\s+a|is\s+an|is\s+the|are\s+the|such\s+as|like\s+a)\s*[\?\.\:]*$", q_text, re.IGNORECASE):
        return False, "Question ends abruptly with a truncated sentence fragment"

    # 2. Missing Image / Diagram check
    has_image = bool(q.get("image_url") or q.get("imageUrl") or q.get("image") or q.get("has_image"))
    if not has_image:
        for pat in _COMPILED_IMAGE_PATTERNS:
            if pat.search(q_text):
                return False, "Question refers to missing figure/diagram without image asset"

    # 3. MCQ option and answer validation
    q_type = str(q.get("type") or q.get("question_type") or "mcq").lower()
    raw_options = q.get("options")
    
    if "mcq" in q_type or "assertion" in q_type:
        if not raw_options or not isinstance(raw_options, (list, tuple)) or len(raw_options) < 2:
            return False, "MCQ question missing valid options list"
        
        non_empty_opts = [str(opt).strip() for opt in raw_options if str(opt).strip()]
        if len(non_empty_opts) < 2:
            return False, "MCQ options contain blank/empty choices"

        dummy_patterns = [
            r"^(?:[a-d]\s*[\)\.\:\-]\s*)?option\s*(?:[a-d]|\d+)$",
            r"^(?:[a-d]\s*[\)\.\:\-]\s*)?alternative\s+(?:concept|option\s+[b-d])$",
            r"^(?:[a-d]\s*[\)\.\:\-]\s*)?choice\s*(?:[a-d]|\d+)$",
            r"^null\s+condition$",
            r"^secondary\s+effect$",
            r"^placeholder\s+option",
            r"^dummy\s+(?:option|choice)",
        ]
        compiled_dummy = [re.compile(dp, re.IGNORECASE) for dp in dummy_patterns]
        dummy_count = 0
        for opt in non_empty_opts:
            for dp in compiled_dummy:
                if dp.match(opt):
                    dummy_count += 1
                    break
        if dummy_count >= 1:
            return False, "Question contains dummy placeholder options (e.g. Option A/B, Alternative Concept, Null Condition)"

    # 4. Correct Answer validation
    correct_ans = str(q.get("correct_answer") or q.get("correctAnswer") or "").strip()
    if not correct_ans:
        return False, "Question is missing correct_answer"

    for pat in _COMPILED_DUMMY_ANSWERS:
        if pat.search(correct_ans):
            return False, "Question has dummy/placeholder correct_answer"

    # 5. Explanation validation
    explanation_text = str(q.get("explanation") or "").strip()
    if explanation_text:
        for pat in _COMPILED_DUMMY_EXPLS:
            if pat.search(explanation_text):
                return False, "Question has dummy/boilerplate explanation"

    # 6. Cross-Subject Boundary check
    if requested_subject:
        subj_lower = requested_subject.strip().lower()
        for ref_subj, rules in _SUBJECT_LEAKAGE_MAP.items():
            if ref_subj in subj_lower:
                forbidden = rules.get("forbidden_terms", [])
                q_text_lower = q_text.lower()
                for term in forbidden:
                    if term in q_text_lower:
                        return False, f"Cross-subject contamination detected: '{term}' in {requested_subject} question"

    return True, None


def filter_valid_questions(questions: List[Dict[str, Any]], requested_subject: Optional[str] = None) -> List[Dict[str, Any]]:
    """Filters a list of candidate questions, dropping any invalid/broken ones."""
    valid_list = []
    for q in questions:
        is_ok, reason = validate_question_quality(q, requested_subject)
        if is_ok:
            valid_list.append(q)
        else:
            logger.info(f"Dropped question #{q.get('id', '?')} due to sanity filter: {reason}")
    return valid_list


def llm_audit_and_curate_questions(
    questions: List[Dict[str, Any]],
    board: str,
    class_grade: str,
    subject: str,
    difficulty: str,
    target_count: int = 10,
    force_mcq: bool = False,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Passes candidate questions through LLM for academic verification, dummy-option fixing, and polish.
    
    Returns (curated_questions, llm_success_flag).
    """
    from model import mistral_client

    if not mistral_client.is_configured("exam_generation"):
        logger.info("[LLM GUARD] LLM not configured, using deterministic rule sanitizer.")
        return filter_valid_questions(questions, requested_subject=subject), False

    # Prepare candidate payload for LLM audit
    condensed_candidates = []
    for idx, q in enumerate(questions[:target_count + 5]):
        condensed_candidates.append({
            "candidate_num": idx + 1,
            "type": "mcq" if force_mcq else q.get("type", "mcq"),
            "questionText": q.get("questionText") or q.get("question_text", ""),
            "options": q.get("options") or [],
            "correctAnswer": str(q.get("correctAnswer") or q.get("correct_answer", "")),
            "explanation": q.get("explanation", ""),
            "marks": int(q.get("marks", 1 if force_mcq else 1)),
        })

    system_prompt = (
        "You are an Elite Academic Question Quality Auditor for Indian School Boards (CBSE, ICSE, State Boards).\n"
        "Your task is to inspect, sanitize, polish, and output the EXACT required number of high-quality exam questions.\n\n"
        "STRICT AUDIT RULES:\n"
        "1. Fix any broken text, grammar errors, or incomplete prompts.\n"
        "2. For ALL MCQ questions: MUST have exactly 4 authentic, realistic, syllabus-appropriate answer choices (e.g. ['A) 24 cm²', 'B) 30 cm²', 'C) 36 cm²', 'D) 40 cm²']).\n"
        "3. NEVER allow dummy placeholders like 'Option A', 'Option B', 'Alternative Option', 'Null Condition', 'Choice 1'. If found, replace them with realistic topic distractors.\n"
        "4. If a question is defective or missing a diagram, REPLACE it completely with a fresh, authentic syllabus question for this class and subject.\n"
        "5. Re-verify that `correctAnswer` strictly matches one of the 4 MCQ options, or provides a clear model answer for SAQs.\n"
        "6. Return strictly valid JSON containing the 'questions' array matching the requested schema."
    )

    user_prompt = (
        f"TARGET CURRICULUM:\n"
        f"- Board: {board}\n"
        f"- Class/Grade: {class_grade}\n"
        f"- Subject: {subject}\n"
        f"- Difficulty Level: {difficulty}\n"
        f"- Required Questions Count: {target_count}\n"
        f"- Force 100% MCQ Format: {force_mcq}\n\n"
        f"CANDIDATE QUESTIONS TO AUDIT & REFINE:\n"
        f"{json.dumps(condensed_candidates, ensure_ascii=False, indent=2)}\n\n"
        f"Output JSON Structure:\n"
        f"{{\n"
        f'  "questions": [\n'
        f"    {{\n"
        f'      "questionNumber": 1,\n'
        f'      "type": "mcq" or "saq",\n'
        f'      "questionText": "...",\n'
        f'      "options": ["A) ...", "B) ...", "C) ...", "D) ..."],\n'
        f'      "correctAnswer": "...",\n'
        f'      "explanation": "...",\n'
        f'      "topic": "{subject}",\n'
        f'      "marks": 1\n'
        f"    }}\n"
        f"  ]\n"
        f"}}"
    )

    try:
        raw_response = mistral_client.generate_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            scenario="exam_generation",
        )
        if isinstance(raw_response, dict) and "questions" in raw_response and isinstance(raw_response["questions"], list):
            audited_qs = raw_response["questions"]
            valid_audited = filter_valid_questions(audited_qs, requested_subject=subject)
            if len(valid_audited) >= target_count:
                logger.info(f"[LLM GUARD] Successfully audited and verified {len(valid_audited)} questions via AI Engine.")
                return valid_audited[:target_count], True
    except Exception as exc:
        logger.warning(f"[LLM GUARD] LLM Question Audit encountered error: {exc}. Using deterministic fallback guard.")

    return filter_valid_questions(questions, requested_subject=subject), False
