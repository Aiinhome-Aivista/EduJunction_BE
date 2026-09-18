"""Prompt construction for exam generation. Ported 1:1 from the frontend's
existing server.ts prompt (which targeted Gemini) so exam quality/behavior
doesn't regress with the Mistral swap."""
import json

SYSTEM_PROMPT = (
    "You are the Master Curriculum Assessor for K-12 and competitive-exam "
    "boards (CBSE, ICSE, ISC, UK-Cambridge, NCERT, NEET, IIT). You generate "
    "rigorous, board-authentic diagnostic exams strictly grounded in the "
    "supplied curriculum knowledge graph context. You always respond with a "
    "single valid JSON object and nothing else."
)

RESPONSE_SCHEMA_HINT = {
    "title": "string",
    "questions": [
        {
            "questionNumber": "integer",
            "type": "mcq | numerical | objective | logical",
            "questionText": "string",
            "options": ["string (only for mcq/logical, exactly 4, formatted 'A) ...'..'D) ...')"],
            "correctAnswer": "string (letter for mcq/logical, exact value for numerical/objective)",
            "explanation": "string (step-by-step derivation)",
            "topic": "string",
            "difficulty": "simple | medium | hard",
            "marks": 1,
        }
    ],
}


def build_user_prompt(
    board: str,
    class_grade: str,
    subject: str,
    difficulty: str,
    student_name: str,
    weak_topics: list[str],
    rag_context: list[dict],
) -> str:
    weak_topics_str = ", ".join(weak_topics) if weak_topics else "Standard curriculum coverage"
    return f"""Board: {board} | Grade: {class_grade} | Subject: {subject}
Exam Level: {difficulty.upper()} (options: simple, medium, hard).
Student: {student_name} (Historical weak topics to reinforce: {weak_topics_str}).

Ground your assessment on these verified RAG Curriculum Knowledge Graph Runbooks:
{json.dumps(rag_context, indent=2, ensure_ascii=False)}

TASK SPECIFICATION:
Generate an EXACTLY 10-question, 10-mark diagnostic exam.
Each question carries exactly 1 mark (Total Marks = 10).
Include a balanced variety of question types:
- At least 4-5 Multiple Choice Questions (type: "mcq", with 4 distinct options formatted as "A) ...", "B) ...", "C) ...", "D) ...")
- 2 Numerical questions (type: "numerical", precise numerical integer or decimal answer)
- 2 Objective fill-in / one-phrase questions (type: "objective")
- 1-2 Logical reasoning or Assertion-Reasoning questions (type: "logical")

All questions must be strictly authentic to the {board} syllabus for {class_grade}.
Provide accurate step-by-step mathematical or conceptual explanation for each question and cite topic labels.

Return the result strictly as a valid JSON object matching this shape:
{json.dumps(RESPONSE_SCHEMA_HINT, indent=2)}
"""
