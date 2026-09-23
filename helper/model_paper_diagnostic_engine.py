"""Diagnostic engine for generating score-calibrated, dynamic, topic-wise and section-wise
Teacher/Parent notes and diagnostic insights for full-length 2027 specimen model examination papers."""
import re
from typing import Any
from model import mistral_client
from prompts import model_paper_diagnostic_prompt
from utils.logger import logger


def _clean_topic_name(raw_topic: str | None, question_text: str = "", default_subject: str = "") -> str:
    """Extracts a clean, human-readable chapter/concept topic name from question data or text."""
    if raw_topic and len(raw_topic.strip()) > 2 and not raw_topic.lower().startswith("section "):
        # If raw_topic is already a concept name (not just 'Section B')
        clean = re.sub(r"<.*?>", "", raw_topic).strip()
        if len(clean) > 2:
            return clean

    # Look for bold tags in question text: <b>Topic Name</b>
    if question_text:
        matches = re.findall(r"<b>(.*?)</b>", question_text)
        for m in matches:
            m_clean = m.strip()
            # Ignore structural bold markers
            if not any(m_clean.startswith(prefix) for prefix in ("Assertion", "Reason", "Q", "Note", "Case", "Section", "OR")):
                if len(m_clean) >= 3:
                    return m_clean

    # Fallback to subject or default
    return f"{default_subject} Core Concepts" if default_subject else "Core Concepts"


def generate_model_paper_diagnostic(
    student_name: str,
    board: str,
    class_grade: str,
    subject: str,
    set_num: int | str,
    marks_obtained: float,
    max_marks: float,
    time_spent_seconds: int,
    evaluations: list[dict[str, Any]],
    section_breakdown: list[dict[str, Any]] | None = None,
    total_allowed_mins: int = 180,
) -> dict[str, Any]:
    """Generates dynamic diagnostic analysis and Teacher/Parent Note using LLM with deterministic fallback."""
    accuracy_percentage = round((marks_obtained / max(max_marks, 1.0)) * 100, 1)

    # Group topics by section and performance
    mastered_topics_by_section: dict[str, list[str]] = {}
    missed_topics_by_section: dict[str, list[str]] = {}

    all_correct_topics: list[str] = []
    all_weak_topics: list[str] = []

    for item in evaluations:
        sec_name = item.get("sectionName") or "Section A"
        # Extract meaningful concept topic
        q_text = item.get("questionText") or item.get("question") or ""
        raw_topic = item.get("topic")
        topic = _clean_topic_name(raw_topic, q_text, subject)

        marks_awarded = item.get("marksAwarded", 0.0)
        q_max = item.get("questionMarks", 1.0)
        is_correct = marks_awarded >= (q_max * 0.75)

        if is_correct:
            if sec_name not in mastered_topics_by_section:
                mastered_topics_by_section[sec_name] = []
            if topic not in mastered_topics_by_section[sec_name]:
                mastered_topics_by_section[sec_name].append(topic)
            if topic not in all_correct_topics:
                all_correct_topics.append(topic)
        else:
            if sec_name not in missed_topics_by_section:
                missed_topics_by_section[sec_name] = []
            if topic not in missed_topics_by_section[sec_name] and topic not in (mastered_topics_by_section.get(sec_name) or []):
                missed_topics_by_section[sec_name].append(topic)
            if topic not in all_weak_topics and topic not in all_correct_topics:
                all_weak_topics.append(topic)

    # Summarize section-wise performance
    sec_lines = []
    if section_breakdown:
        for s in section_breakdown:
            s_name = s.get("name") or s.get("title") or "Section"
            s_obt = s.get("marksObtained", 0.0)
            s_max = s.get("maxMarks") or s.get("targetMaxMarks") or 20.0
            s_pct = round((s_obt / max(s_max, 1.0)) * 100, 1)
            sec_lines.append(f"- {s_name}: {s_obt}/{s_max} Marks ({s_pct}%)")
    section_summary_str = "\n".join(sec_lines)

    # 1. Attempt LLM synthesis
    if mistral_client.is_configured():
        try:
            user_prompt = model_paper_diagnostic_prompt.build_model_paper_diagnostic_user_prompt(
                student_name=student_name,
                board=board,
                class_grade=class_grade,
                subject=subject,
                set_num=set_num,
                marks_obtained=marks_obtained,
                total_marks=max_marks,
                accuracy_percentage=accuracy_percentage,
                time_taken_seconds=time_spent_seconds,
                total_allowed_mins=total_allowed_mins,
                attempted_count=len(evaluations) - len([e for e in evaluations if e.get("studentAnswer", "").strip() in ("", "(Not Answered)")]),
                total_questions=len(evaluations),
                correct_count=len([e for e in evaluations if e.get("marksAwarded", 0.0) >= (e.get("questionMarks", 1.0) * 0.75)]),
                partial_count=len([e for e in evaluations if 0.0 < e.get("marksAwarded", 0.0) < (e.get("questionMarks", 1.0) * 0.75)]),
                incorrect_count=len([e for e in evaluations if e.get("marksAwarded", 0.0) == 0.0]),
                section_breakdown_summary=section_summary_str,
                mastered_topics_by_section=mastered_topics_by_section,
                missed_topics_by_section=missed_topics_by_section,
            )

            raw = mistral_client.generate_json(
                model_paper_diagnostic_prompt.SYSTEM_PROMPT,
                user_prompt
            )

            if isinstance(raw, dict) and "strengths" in raw and "areasToImprove" in raw:
                note = raw.get("teacherParentNote") or raw.get("encouragementNote") or ""
                return {
                    "overallBand": _get_band_name(accuracy_percentage),
                    "masteryScorePercentage": accuracy_percentage,
                    "strengths": raw.get("strengths", []),
                    "areasToImprove": raw.get("areasToImprove", []),
                    "encouragementNote": note,
                    "teacherParentNote": note,
                    "evolutionaryRoadmap": raw.get("evolutionaryRoadmap") or f"Target next revision milestone in {subject} to improve board exam readiness.",
                }
        except Exception as exc:
            logger.warning(f"[DIAGNOSTIC] LLM diagnostic generation failed, using calibrated fallback: {exc}")

    # 2. Score-calibrated & Topic-aware fallback synthesis
    return _synthesize_model_paper_fallback(
        student_name=student_name,
        board=board,
        class_grade=class_grade,
        subject=subject,
        set_num=set_num,
        marks_obtained=marks_obtained,
        max_marks=max_marks,
        accuracy_percentage=accuracy_percentage,
        time_spent_seconds=time_spent_seconds,
        evaluations=evaluations,
        mastered_topics_by_section=mastered_topics_by_section,
        missed_topics_by_section=missed_topics_by_section,
        all_correct_topics=all_correct_topics,
        all_weak_topics=all_weak_topics,
    )


def _get_band_name(accuracy: float) -> str:
    if accuracy >= 90.0:
        return "Mastery / Grade A+"
    elif accuracy >= 70.0:
        return "Proficient / Grade A"
    elif accuracy >= 40.0:
        return "Developing / Grade B"
    else:
        return "Critical Foundation Needed"


def _synthesize_model_paper_fallback(
    student_name: str,
    board: str,
    class_grade: str,
    subject: str,
    set_num: int | str,
    marks_obtained: float,
    max_marks: float,
    accuracy_percentage: float,
    time_spent_seconds: int,
    evaluations: list[dict[str, Any]],
    mastered_topics_by_section: dict[str, list[str]],
    missed_topics_by_section: dict[str, list[str]],
    all_correct_topics: list[str],
    all_weak_topics: list[str],
) -> dict[str, Any]:
    """Generates calibrated, realistic fallback feedback with topic-specific and section-specific focus."""
    total_q = len(evaluations)
    correct_count = len([e for e in evaluations if e.get("marksAwarded", 0.0) >= (e.get("questionMarks", 1.0) * 0.75)])
    time_mins = time_spent_seconds // 60
    is_rushed = time_mins < 10

    band = _get_band_name(accuracy_percentage)

    # Format topic mentions
    sec_a_correct = ", ".join(mastered_topics_by_section.get("Section A", [])[:2])
    sec_bc_weak = ", ".join((missed_topics_by_section.get("Section B", []) + missed_topics_by_section.get("Section C", []))[:3]) or ", ".join(all_weak_topics[:3])

    if accuracy_percentage < 40.0:
        # Band 1: Needs Foundation (< 40%)
        strengths = [
            f"Demonstrated initial familiarity with {subject} concepts: {', '.join(all_correct_topics[:2])}." if all_correct_topics else f"Participated in the full-length {subject} 2027 specimen examination drill.",
            f"Attempted {total_q} questions under standard {board} examination conditions.",
            "Highlighted precise concept bottlenecks that need immediate textbook revision."
        ]

        areas_to_improve = [
            f"Urgent revision required in {sec_bc_weak} (revisit core definitions, formulas, and textbook derivations)." if sec_bc_weak else f"Re-read fundamental chapters in {subject} before attempting timed mock tests.",
            f"Practice writing out complete step-by-step solutions with proper units and standard notations in descriptive sections.",
            "Avoid rushing through questions; allocate sufficient time to read each problem carefully." if is_rushed else "Practice basic 1-mark and 2-mark questions to rebuild confidence and accuracy."
        ]

        if is_rushed:
            note = (
                f"{student_name} completed this 80-mark test very quickly in {time_mins} minutes and scored {marks_obtained}/{max_marks} ({accuracy_percentage}%). "
                f"We strongly recommend that {student_name} takes time to read problem statements thoroughly and revises chapters in {sec_bc_weak or subject} before the next mock."
            )
        else:
            note = (
                f"{student_name} scored {marks_obtained}/{max_marks} ({accuracy_percentage}%) on this model test, indicating significant conceptual gaps in {sec_bc_weak or subject}. "
                f"We recommend regular revision of textbook theory and un-timed practice problem sets to build a stronger foundation in {subject}."
            )

    elif accuracy_percentage < 70.0:
        # Band 2: Developing (40% - 69%)
        strengths = [
            f"Solid conceptual understanding in {sec_a_correct or ', '.join(all_correct_topics[:2]) or subject}." if (sec_a_correct or all_correct_topics) else f"Demonstrated a working conceptual foundation across key {subject} units.",
            f"Successfully answered {correct_count} out of {total_q} questions with accurate reasoning.",
            "Maintained consistent engagement throughout the examination."
        ]

        areas_to_improve = [
            f"Reinforce multi-step derivations and problem-solving in: {sec_bc_weak}." if sec_bc_weak else "Review step-marking criteria for Section B & C subjective explanations.",
            f"Practice numerical calculations and precision definitions in {subject} to prevent avoidable deduction of marks.",
            "Allocate time carefully between short objective questions and detailed descriptive answers."
        ]

        note = (
            f"Good effort by {student_name} with a score of {marks_obtained}/{max_marks} ({accuracy_percentage}%). "
            f"With targeted practice on multi-step questions in {sec_bc_weak or subject} and careful review of step-marking rubrics, {student_name} can comfortably advance into the Proficient band."
        )

    elif accuracy_percentage < 90.0:
        # Band 3: Proficient (70% - 89%)
        strengths = [
            f"High conceptual clarity and accurate step execution in: {', '.join(all_correct_topics[:3]) or subject}.",
            f"Successfully answered {correct_count} questions with clean mathematical/scientific steps.",
            "Good pacing and systematic coverage of the 2027 specimen blueprint."
        ]

        areas_to_improve = [
            f"Fine-tune edge-case topics and complex application questions in: {sec_bc_weak or ', '.join(all_weak_topics[:2])}.",
            "Work on concise diagram drawing and structured final answer presentation.",
            "Practice speed optimization to allow 15 minutes for final revision at the end of the exam."
        ]

        note = (
            f"Very commendable performance! {student_name} demonstrated strong subject competence with {marks_obtained}/{max_marks} ({accuracy_percentage}%). "
            f"Polishing step presentation in {sec_bc_weak or subject} will help {student_name} achieve 90%+ in the final board examinations."
        )

    else:
        # Band 4: Mastery (>= 90%)
        strengths = [
            f"Exceptional accuracy and comprehensive mastery across all tested units: {', '.join(all_correct_topics[:3]) or subject}.",
            f"Flawless step execution with top-tier presentation across {board} marking rubrics.",
            "Outstanding examination discipline, accuracy, and depth of understanding."
        ]

        areas_to_improve = [
            "Maintain peak performance by practicing advanced High Order Thinking Skills (HOTS) and specimen papers.",
            "Review final step presentation to secure a 100% centum score in the board examinations."
        ]

        note = (
            f"Outstanding performance! {student_name} scored an impressive {marks_obtained}/{max_marks} ({accuracy_percentage}%). "
            f"{student_name} is on track for top honors in the {board} {class_grade} {subject} board examinations. Keep up the brilliant consistency!"
        )

    return {
        "overallBand": band,
        "masteryScorePercentage": accuracy_percentage,
        "strengths": strengths,
        "areasToImprove": areas_to_improve,
        "encouragementNote": note,
        "teacherParentNote": note,
        "evolutionaryRoadmap": f"Completed 2027 Model Paper Set {set_num} ({board} {class_grade} {subject}) scoring {round(marks_obtained, 1)}/{max_marks} ({accuracy_percentage}%).",
    }
