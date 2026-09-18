"""Post-exam diagnostic analysis (master prompt §17), with a deterministic
fallback synthesizer ported from server.ts's `synthesizeFallbackAnalysis` for
when Mistral is unavailable or returns invalid content."""
from pydantic import ValidationError as PydanticValidationError

from model import mistral_client
from model.models import Exam
from prompts import evaluation_prompt
from utils.ai_schemas import DiagnosticAnalysisSchema
from utils.logger import logger


def generate_diagnostic_analysis(
    exam: Exam,
    marks_obtained: int,
    evaluations: list[dict],
    time_taken_seconds: int,
    student_name: str,
) -> tuple[dict, str]:
    """Returns (analysis_dict, source) where source is 'mistral' or 'fallback'."""
    accuracy_percentage = round((marks_obtained / exam.total_marks) * 100, 2)

    if mistral_client.is_configured():
        try:
            user_prompt = evaluation_prompt.build_user_prompt(
                student_name=student_name, board=exam.board, class_grade=exam.class_grade,
                subject=exam.subject, difficulty=exam.difficulty, marks_obtained=marks_obtained,
                accuracy_percentage=accuracy_percentage, time_taken_seconds=time_taken_seconds,
                evaluations=evaluations,
            )
            raw = mistral_client.generate_json(evaluation_prompt.SYSTEM_PROMPT, user_prompt)
            validated = DiagnosticAnalysisSchema.model_validate(raw)
            analysis = validated.model_dump()
            analysis["masteryScorePercentage"] = accuracy_percentage
            return analysis, "mistral"
        except (mistral_client.MistralUnavailableError, PydanticValidationError) as exc:
            logger.error(f"Diagnostic analysis via Mistral failed, using fallback: {exc}")

    return _synthesize_fallback_analysis(exam, marks_obtained, evaluations, student_name, accuracy_percentage), "fallback"


def _synthesize_fallback_analysis(
    exam: Exam, marks_obtained: int, evaluations: list[dict], student_name: str, accuracy_percentage: float
) -> dict:
    if accuracy_percentage >= 90:
        band, next_diff = "Competitive Ready", "hard"
    elif accuracy_percentage >= 70:
        band = "Proficient"
        next_diff = "hard" if exam.difficulty != "simple" else "medium"
    elif accuracy_percentage >= 50:
        band = "Developing"
        next_diff = "medium" if exam.difficulty == "hard" else exam.difficulty
    else:
        band, next_diff = "Needs Foundation", "simple"

    incorrect_topics = [e["topic"] for e in evaluations if not e["isCorrect"]]
    total_m = exam.total_marks or (5 if str(exam.class_grade).lower() in ['class 1', 'class 2', 'class 3', 'class 4'] else 15)

    return {
        "overallBand": band,
        "masteryScorePercentage": accuracy_percentage,
        "strengths": [
            f"Demonstrated consistent speed and confidence across {exam.subject} fundamentals.",
            "Accurate handling of core conceptual definitions and primary questions.",
            "Active engagement with adaptive assessment challenges.",
        ],
        "areasToImprove": (
            [f"Reinforce problem-solving speed and edge cases in: {t}" for t in incorrect_topics]
            or ["Maintain peak accuracy by practicing timed interactive formats."]
        ),
        "kGraphInsights": [
            {
                "topic": f"{exam.subject} Core Fundamentals",
                "masteryPercentage": max(30, accuracy_percentage),
                "status": "mastered" if accuracy_percentage >= 80 else ("reinforce" if accuracy_percentage >= 50 else "critical_gap"),
                "recommendedAction": "Advance to higher level drills." if accuracy_percentage >= 80 else "Review core chapter fundamentals.",
            },
            {
                "topic": "Accuracy & Knowledge Retention",
                "masteryPercentage": 85 if accuracy_percentage >= 70 else 60,
                "status": "mastered" if accuracy_percentage >= 70 else "reinforce",
                "recommendedAction": "Practice writing down and reviewing intermediate steps carefully.",
            },
        ],
        "evolutionaryRoadmap": (
            f"{student_name} completed the {exam.class_grade} {exam.board} {exam.subject} {exam.difficulty} "
            f"assessment with a score of {marks_obtained}/{total_m}. Evolutionary roadmap: Focus on weak concept nodes "
            f"identified in the review below, then progress to {next_diff} difficulty challenge."
        ),
        "encouragementNote": (
            f"Great work {student_name}! Every diagnostic highlights your strengths and pinpoints "
            f"misconceptions early. Keep practicing to build permanent concept mastery."
        ),
        "recommendedNextExam": {
            "board": exam.board, "classGrade": exam.class_grade, "subject": exam.subject,
            "difficulty": next_diff,
            "reason": (
                "High mastery achieved! Ready for next difficulty benchmark."
                if marks_obtained >= 8
                else "Targeted reinforcement test recommended to solidify core concept grasp."
            ),
        },
        "curatedStudyLinks": [
            {
                "title": f"{exam.board} {exam.subject} Curriculum Portal", "source": "Official Board Repository",
                "url": "https://ncert.nic.in/textbook.php",
                "description": "Official digital learning modules and exemplary problem solutions.",
                "type": "official_syllabus",
            },
            {
                "title": f"Khan Academy {exam.subject} Interactive Lessons", "source": "Khan Academy",
                "url": "https://www.khanacademy.org",
                "description": "Guided concept walkthroughs and step-by-step problem sets.",
                "type": "video",
            },
        ],
    }
