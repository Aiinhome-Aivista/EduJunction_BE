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
    total_m = exam.total_marks or (5 if str(exam.class_grade).lower() in ['class 1', 'class 2', 'class 3', 'class 4'] else 15)
    accuracy_percentage = round((marks_obtained / max(total_m, 1)) * 100, 2)

    if mistral_client.is_configured():
        try:
            user_prompt = evaluation_prompt.build_user_prompt(
                student_name=student_name,
                board=exam.board,
                class_grade=exam.class_grade,
                subject=exam.subject,
                difficulty=exam.difficulty,
                marks_obtained=marks_obtained,
                total_marks=total_m,
                accuracy_percentage=accuracy_percentage,
                time_taken_seconds=time_taken_seconds,
                evaluations=evaluations,
            )
            raw = mistral_client.generate_json(evaluation_prompt.SYSTEM_PROMPT, user_prompt, scenario="diagnostic")
            validated = DiagnosticAnalysisSchema.model_validate(raw)
            analysis = validated.model_dump()
            analysis["masteryScorePercentage"] = accuracy_percentage
            analysis["kGraphInsights"] = _ensure_complete_kgraph_insights(
                analysis.get("kGraphInsights", []), evaluations, accuracy_percentage, exam.subject
            )
            return analysis, "mistral"
        except (mistral_client.MistralUnavailableError, PydanticValidationError) as exc:
            logger.error(f"Diagnostic analysis via Mistral failed, using fallback: {exc}")

    return _synthesize_fallback_analysis(exam, marks_obtained, evaluations, student_name, accuracy_percentage), "fallback"


def _ensure_complete_kgraph_insights(
    k_graph_insights: list[dict],
    evaluations: list[dict],
    accuracy_percentage: float,
    subject: str,
) -> list[dict]:
    """Guarantees that all tested topics from student evaluations are captured with exact topic-level percentage."""
    existing_topics = {
        k.get("topic", "").strip().lower(): k
        for k in (k_graph_insights or [])
        if k.get("topic")
    }

    # Group questions by topic to compute exact topic-specific accuracy
    topic_marks = {}
    for e in evaluations:
        t = (e.get("topic") or subject).strip()
        if t not in topic_marks:
            topic_marks[t] = {"obtained": 0.0, "total": 0.0}
        
        obtained = float(e.get("marksAwarded") or 0.0)
        # Determine question total marks (from eval or fallback)
        q_total = float(e.get("marks") or e.get("totalMarks") or (2.0 if obtained > 1.0 else 1.0))
        if obtained > q_total:
            q_total = obtained

        topic_marks[t]["obtained"] += obtained
        topic_marks[t]["total"] += max(q_total, 1.0)

    enriched = list(k_graph_insights or [])

    for topic, data in topic_marks.items():
        topic_lower = topic.lower()
        topic_pct = round((data["obtained"] / max(data["total"], 1.0)) * 100, 2)
        topic_pct = min(100.0, max(0.0, topic_pct))

        if topic_pct >= 85:
            status = "mastered"
            default_insight = (
                f"Awesome work! You handled {topic} with fantastic confidence and accuracy. You have a solid grasp of this concept, and you are ready to take on advanced level challenges to level up your streak!"
            )
            default_action = (
                f"Read the advanced problem-solving section in your {subject} textbook for {topic}, then try 3-4 challenging questions to sharpen your speed."
            )
        elif topic_pct >= 50:
            status = "reinforce"
            default_insight = (
                f"Good effort! You answered basic questions in {topic} nicely, but there are a few multi-step steps to polish. With a quick review, you will master it completely."
            )
            default_action = (
                f"Review the key formulas and worked examples for {topic} in your {subject} textbook, then practice 3 multi-step problems."
            )
        else:
            status = "critical_gap"
            default_insight = (
                f"Don't worry, every champion learns by trying! You gave a great attempt, but {topic} has a few tricky definitions that need a quick revision. With a little practice, you'll be on top of this topic in no time."
            )
            default_action = (
                f"Open your {subject} textbook chapter on {topic}, carefully read the core concept summary and definitions, and solve 2 foundational practice exercises."
            )

        if topic_lower in existing_topics:
            # Update the existing insight with exact topic-level calculation
            node = existing_topics[topic_lower]
            node["masteryPercentage"] = topic_pct
            node["status"] = status
            if not node.get("insight") or len(str(node.get("insight", "")).strip()) < 15:
                node["insight"] = default_insight
            if not node.get("recommendedAction") or len(str(node.get("recommendedAction", "")).strip()) < 15:
                node["recommendedAction"] = default_action
        else:
            node_insight = {
                "topic": topic,
                "masteryPercentage": topic_pct,
                "status": status,
                "insight": default_insight,
                "recommendedAction": default_action,
            }
            enriched.append(node_insight)
            existing_topics[topic_lower] = node_insight

    return enriched


def _synthesize_fallback_analysis(
    exam: Exam, marks_obtained: int, evaluations: list[dict], student_name: str, accuracy_percentage: float
) -> dict:
    total_m = exam.total_marks or (5 if str(exam.class_grade).lower() in ['class 1', 'class 2', 'class 3', 'class 4'] else 15)

    correct_items = [e for e in evaluations if e.get("isCorrect")]
    incorrect_items = [e for e in evaluations if not e.get("isCorrect")]

    correct_topics = list(dict.fromkeys([e.get("topic") or exam.subject for e in correct_items if e.get("topic")]))
    incorrect_topics = list(dict.fromkeys([e.get("topic") or exam.subject for e in incorrect_items if e.get("topic")]))

    # Pacing analysis
    fast_correct_topics = list(dict.fromkeys([
        e.get("topic") or exam.subject for e in correct_items if 0 < e.get("timeSpentSeconds", 0) <= 25 and e.get("topic")
    ]))
    time_bottleneck_topics = list(dict.fromkeys([
        e.get("topic") or exam.subject for e in incorrect_items if e.get("timeSpentSeconds", 0) >= 35 and e.get("topic")
    ]))

    if accuracy_percentage < 40:
        band = "Needs Foundation"
        next_diff = "simple"
        strengths = [
            f"Attempted all {len(evaluations)} diagnostic questions under timed assessment conditions.",
            f"Demonstrated initial familiarity with basic definitions in: {', '.join(correct_topics[:2])}." if correct_topics else f"Engaged actively with {exam.subject} syllabus question sets.",
            f"Good prompt execution speed in: {', '.join(fast_correct_topics[:2])}." if fast_correct_topics else "Willingness to attempt challenging multi-step examination problems."
        ]
        areas_to_improve = [
            f"Thoroughly review core textbook theory and fundamental formulas in: {', '.join(incorrect_topics[:2])}." if incorrect_topics else f"Re-read {exam.subject} textbook chapters from basics.",
            f"Work through calculation bottlenecks in: {', '.join(time_bottleneck_topics[:2])}." if time_bottleneck_topics else "Practice step-by-step fundamental definitions before attempting timed drills.",
            "Avoid rushing through questions; spend adequate time reading problem statements carefully."
        ]
        encouragement_note = (
            f"Take a step back to core textbook reading, {student_name}. Building a rock-solid grasp of foundational "
            f"definitions in {exam.subject} will significantly boost your score and confidence on the next attempt."
        )
        reason_text = "Targeted foundational reinforcement test recommended to solidify core concept grasp."

    elif accuracy_percentage < 70:
        band = "Developing"
        next_diff = "medium" if exam.difficulty == "hard" else exam.difficulty
        strengths = [
            f"Demonstrated accurate conceptual understanding in: {', '.join(correct_topics[:3])}." if correct_topics else f"Solved fundamental questions in {exam.subject}.",
            f"High solving fluency & speed in: {', '.join(fast_correct_topics[:2])}." if fast_correct_topics else f"Successfully answered {len(correct_items)} questions with correct reasoning and steps.",
            "Maintained steady pace and active engagement across core syllabus units."
        ]
        areas_to_improve = [
            f"Reinforce multi-step calculations and derivation steps in: {', '.join(incorrect_topics[:3])}." if incorrect_topics else "Review intermediate step-marking rubrics.",
            f"Resolve time friction / calculation stalling in: {', '.join(time_bottleneck_topics[:2])}." if time_bottleneck_topics else "Double-check calculation steps and units to prevent avoidable errors.",
            "Practice structured 2-mark and 3-mark analytical question formats."
        ]
        encouragement_note = (
            f"Good effort {student_name}! You have a developing foundation in {exam.subject}. Targeted practice on "
            f"multi-step problem solving will help you cross into the Proficient band."
        )
        reason_text = "Progressing well! Practice on similar difficulty questions will cement your concept mastery."

    else:
        band = "Competitive Ready" if accuracy_percentage >= 90 else "Proficient"
        next_diff = "hard"
        strengths = [
            f"Strong analytical precision and conceptual grasp across: {', '.join(correct_topics[:3])}." if correct_topics else f"High mastery across {exam.subject}.",
            f"High speed and swift execution in: {', '.join(fast_correct_topics[:3])}." if fast_correct_topics else f"High accuracy rate ({accuracy_percentage}%) with confident formula application.",
            "Excellent time management and problem-solving speed under exam conditions."
        ]
        areas_to_improve = [
            f"Tackle complex HOTS and edge-case questions in: {', '.join(incorrect_topics[:2])}." if incorrect_topics else "Maintain peak accuracy by practicing full-length mock examinations.",
            f"Refine multi-step efficiency in: {', '.join(time_bottleneck_topics[:2])}." if time_bottleneck_topics else "Explore advanced cross-topic application problems and Olympiad-level questions.",
            "Refine step presentation to ensure 100% full-credit marks in board examinations."
        ]
        encouragement_note = (
            f"Outstanding performance {student_name}! You have demonstrated impressive mastery across {exam.subject}. "
            f"Keep pushing toward full board examination excellence."
        )
        reason_text = "High mastery achieved! Ready for next-level competitive challenges."

    # Build topic-specific knowledge graph insights
    k_graph_insights = []
    for topic in (correct_topics + incorrect_topics)[:4]:
        is_topic_good = topic in correct_topics and topic not in incorrect_topics
        k_graph_insights.append({
            "topic": topic,
            "masteryPercentage": 85 if is_topic_good else (50 if topic in correct_topics else max(25, int(accuracy_percentage))),
            "status": "mastered" if is_topic_good else ("reinforce" if topic in correct_topics else "critical_gap"),
            "recommendedAction": f"Advance to higher difficulty practice in {topic}." if is_topic_good else f"Review core principles and formulas in {topic}.",
        })

    if not k_graph_insights:
        k_graph_insights.append({
            "topic": f"{exam.subject} Core Fundamentals",
            "masteryPercentage": int(accuracy_percentage),
            "status": "mastered" if accuracy_percentage >= 80 else ("reinforce" if accuracy_percentage >= 50 else "critical_gap"),
            "recommendedAction": "Advance to higher level drills." if accuracy_percentage >= 80 else "Review core chapter fundamentals.",
        })

    return {
        "overallBand": band,
        "masteryScorePercentage": accuracy_percentage,
        "strengths": strengths,
        "areasToImprove": areas_to_improve,
        "kGraphInsights": k_graph_insights,
        "evolutionaryRoadmap": (
            f"{student_name} completed the {exam.class_grade} {exam.board} {exam.subject} {exam.difficulty} "
            f"diagnostic assessment with a score of {marks_obtained}/{total_m} ({accuracy_percentage}%). "
            f"Evolutionary roadmap: Focus on the specific concept nodes identified in the analysis above, "
            f"then progress to {next_diff} level challenges."
        ),
        "encouragementNote": encouragement_note,
        "recommendedNextExam": {
            "board": exam.board,
            "classGrade": exam.class_grade,
            "subject": exam.subject,
            "difficulty": next_diff,
            "reason": reason_text,
        },
        "curatedStudyLinks": [
            {
                "title": f"{exam.board} {exam.subject} Curriculum Portal",
                "source": "Official Board Repository",
                "url": "https://ncert.nic.in/textbook.php",
                "description": "Official digital learning modules and exemplary problem solutions.",
                "type": "official_syllabus",
            },
            {
                "title": f"Khan Academy {exam.subject} Interactive Lessons",
                "source": "Khan Academy",
                "url": "https://www.khanacademy.org",
                "description": "Guided concept walkthroughs and step-by-step problem sets.",
                "type": "video",
            },
        ],
    }
