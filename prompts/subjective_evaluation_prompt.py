"""Prompt construction for LLM-based subjective / SAQ evaluation with
class-wise proportional grading (step-marking & keyword matching)."""
import json

SYSTEM_PROMPT = (
    "You are an Expert Board Examiner and Academic Pedagogy Assessor (CBSE, ICSE, "
    "Cambridge, NCERT, ISC, State Boards). Your duty is to evaluate student subjective/SAQ answers "
    "with fair, proportional step-marking (partial credit) based on academic rubric and key concepts. "
    "You must adjust your grading strictness strictly according to the student's Grade Level. "
    "You always respond with a single valid JSON object matching the requested schema and nothing else."
)

RESPONSE_SCHEMA_HINT = {
    "evaluations": [
      {
        "questionId": "string",
        "marksAwarded": 1.5,
        "isCorrect": True,
        "matchedKeywords": ["string"],
        "missedKeywords": ["string"],
        "misconceptionIdentified": "string or null",
        "feedback": "string",
      }
    ]
}


def build_subjective_eval_prompt(
    board: str,
    class_grade: str,
    subject: str,
    items_to_evaluate: list[dict],
) -> str:
    """Builds a batch prompt for evaluating subjective/SAQ questions.
    
    Each item in items_to_evaluate must have:
    - questionId: str
    - questionText: str
    - correctAnswer: str (Model answer from DB)
    - explanation: str
    - questionMarks: float (e.g. 2.0 or 1.0)
    - studentAnswer: str
    - topic: str
    """
    cg_lower = (class_grade or "").lower()
    
    if any(k in cg_lower for k in ["class 1", "class 2", "class 3", "class 4", "primary", "kindergarten", "ukg", "lkg"]):
        pedagogical_instructions = """
GRADE TIER: FOUNDATIONAL / PRIMARY (Class 1-4)
- Lenient & Encouraging Pedagogy.
- DO NOT penalize spelling mistakes, phonetic typing, or informal sentence structure.
- If the child communicates the core conceptual intuition, award FULL MARKS (or >= 80% marks).
- Award 0 marks only if the response is completely blank, unintelligible, or totally wrong.
"""
    elif any(k in cg_lower for k in ["class 11", "class 12", "senior", "higher secondary", "isc", "neet", "iit"]):
        pedagogical_instructions = """
GRADE TIER: HIGHER SECONDARY & COMPETITIVE (Class 11-12 / ISC / NEET / IIT)
- Rigorous Academic Precision.
- Look for precise scientific/mathematical terminology, formula representations, definitions, and causal reasoning.
- Apply standard board step-marking:
  * Full Marks (e.g., 2.0/2.0): All essential keywords, core principle, and accurate reasoning present.
  * Partial Credit (e.g., 1.0 or 1.5/2.0): Core formula or definition correct, but missing elaboration or minor secondary term.
  * Partial Credit (e.g., 0.5/2.0): Minimal relevant conceptual anchor or initial step correct.
  * Zero (0.0/2.0): Misguided, completely irrelevant, or blank.
"""
    else:
        pedagogical_instructions = """
GRADE TIER: SECONDARY (Class 5-10)
- Balanced Concept & Keyword-Based Step-Marking.
- Assess whether the student captured the main points of the model answer in their own words.
- Apply step-marking:
  * Full Marks (2.0/2.0): All key concepts / steps expressed accurately in student's own words.
  * Partial Credit (1.5/2.0): Main concept is correct, 1 minor secondary detail or keyword missing.
  * Partial Credit (1.0/2.0): Exactly half the required points or key concept identified.
  * Partial Credit (0.5/2.0): Weak attempt but shows a faint relevant conceptual keyword.
  * Zero (0.0/2.0): Irrelevant, incorrect fact, or unattempted.
- Note: Students who express the correct concept in original/different phrasing MUST receive credit.
"""

    return f"""Board: {board} | Grade: {class_grade} | Subject: {subject}

{pedagogical_instructions}

EVALUATION TASK:
Evaluate the following {len(items_to_evaluate)} student subjective answer(s) against the verified database model answers and explanations.

Items to Evaluate:
{json.dumps(items_to_evaluate, indent=2, ensure_ascii=False)}

MARKING RULES:
1. `marksAwarded` MUST be a number between 0.0 and `questionMarks` (e.g., 0.0, 0.5, 1.0, 1.5, 2.0).
2. `isCorrect` MUST be true if `marksAwarded >= (questionMarks * 0.5)`, otherwise false.
3. `matchedKeywords`: List of specific concepts/keywords the student successfully included.
4. `missedKeywords`: List of important model answer concepts/keywords the student missed.
5. `misconceptionIdentified`: If marksAwarded < questionMarks, provide a concise 1-sentence diagnostic of their misunderstanding. If full marks, set to null.
6. `feedback`: 1 constructive, supportive sentence in teacher persona praising their correct points and advising on missing details.

Return strictly valid JSON with root key "evaluations":
{json.dumps(RESPONSE_SCHEMA_HINT, indent=2)}
"""
