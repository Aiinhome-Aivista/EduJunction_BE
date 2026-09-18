"""Prompt construction for post-exam diagnostic analysis. Ported from the
frontend's existing server.ts /api/evaluate-exam prompt."""
import json

SYSTEM_PROMPT = (
    "You are a Senior Academic Assessor & Child Pedagogy Specialist. You "
    "analyze a student's diagnostic exam performance and produce an "
    "encouraging, evidence-based evolutionary learning report. You always "
    "respond with a single valid JSON object and nothing else."
)

RESPONSE_SCHEMA_HINT = {
    "overallBand": "Needs Foundation | Developing | Proficient | Advanced Mastery | Competitive Ready",
    "strengths": ["string x3"],
    "areasToImprove": ["string x3"],
    "kGraphInsights": [
        {
            "topic": "string",
            "masteryPercentage": "integer 0-100",
            "status": "mastered | reinforce | critical_gap",
            "recommendedAction": "string",
        }
    ],
    "evolutionaryRoadmap": "string (paragraph)",
    "encouragementNote": "string",
    "recommendedNextExam": {
        "board": "string", "classGrade": "string", "subject": "string",
        "difficulty": "simple | medium | hard", "reason": "string",
    },
    "curatedStudyLinks": [
        {"title": "string", "source": "string", "url": "string", "description": "string", "type": "string"}
    ],
}


def build_user_prompt(
    student_name: str,
    board: str,
    class_grade: str,
    subject: str,
    difficulty: str,
    marks_obtained: int,
    accuracy_percentage: float,
    time_taken_seconds: int,
    evaluations: list[dict],
) -> str:
    return f"""Student Name: {student_name}
Exam Board: {board} | Grade: {class_grade} | Subject: {subject} | Difficulty: {difficulty}
Marks Scored: {marks_obtained} / 10 ({accuracy_percentage}% accuracy).
Time Taken: {time_taken_seconds} seconds.

Student Performance on all 10 Questions:
{json.dumps(evaluations, indent=2, ensure_ascii=False)}

Provide an analytical diagnostic result to help the child's evolutionary progress:
1. Overall performance band
2. 3 concrete strengths
3. 3 specific areas to improve (focusing on misconceptions)
4. Knowledge Graph insights per topic node
5. An evolutionary roadmap paragraph
6. Warm, encouraging note for both the child and their parent
7. Recommended next exam (suggesting higher difficulty if score >= 8, same level if 5-7, or foundational if < 5)
8. Curated official study reference links (NCERT, Khan Academy, CIE, NTA, etc.)

Return strictly as a valid JSON object matching this shape:
{json.dumps(RESPONSE_SCHEMA_HINT, indent=2)}
"""
