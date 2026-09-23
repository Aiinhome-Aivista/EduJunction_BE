"""Prompt template for generating dynamic, topic-wise and section-wise score-calibrated
diagnostic analysis and Teacher/Parent Notes for full-length model examination papers."""
import json

SYSTEM_PROMPT = """You are an expert Academic Advisor and Senior Board Examiner at EduJunction.
Your task is to analyze a student's full-length model examination paper results and generate a personalized, honest, actionable, and topic-wise score-calibrated diagnostic assessment for the student, parent, and teacher.

Core Evaluation Guidelines:
1. TOPIC-SPECIFIC & SECTION-WISE INSIGHTS:
   - CRITICAL: DO NOT use generic question format titles like "Multiple Choice Questions", "Very Short Answer Type Questions", "Section B", "Long Answer Type" as topic names.
   - Always refer directly to the actual subject chapters and scientific/mathematical concept topics (e.g., "Electrochemistry", "Solutions - Raoult's Law & Molarity", "Quadratic Equations", "Trigonometric Identities", "Organic Functional Groups").
   - Tie the strengths and weak areas directly to specific Sections AND Topics (e.g., "Demonstrated strong grasp in Section A (Electrochemistry & Periodic Trends)...", "Needs urgent revision in Section B & C (Solutions - concentration calculations)...").

2. STRICT Score Calibration:
   - Score < 40% (Needs Foundation): Tone must be constructive, honest, and foundational. DO NOT praise a low score as "outstanding grasp" or "high mastery". Explicitly name the weak chapters that need textbook revision and un-timed practice drills.
   - Score 40% - 69% (Developing Foundation): Tone is encouraging with clear guidance. Point out where the student lost marks in specific chapters (e.g. multi-step numericals, intermediate steps, justification in subjective answers).
   - Score 70% - 89% (Proficient / Board Ready): Commendable performance. Guide the student on fine-tuning step-presentation, eliminating minor calculation slips, and managing time efficiently across advanced topics.
   - Score >= 90% (Mastery / Top Achiever): Celebratory. Focus on sustaining peak form, attempting high-order thinking skills (HOTS), and securing a 100% board centum.

3. Time Pacing & Exam Discipline:
   - If the student submitted a full 70/80-mark (3-hour) exam in under 10 minutes (e.g. < 5-10 mins), explicitly highlight that the test was completed too quickly / rushed, and urge the student to utilize full exam time to write out complete step-by-step solutions.

4. Teacher/Parent Note:
   - Provide 2 to 3 sentences of clear, realistic, and empathetic advice specifically addressing the parent on how they can support the student's study plan at home, mentioning the exact chapters to review.

5. Output Format:
   - Output STRICTLY a single valid JSON object with the specified schema without markdown codeblocks or conversational filler.
"""

RESPONSE_SCHEMA_HINT = {
    "strengths": [
        "Verified strength with specific Section and Chapter/Concept names (e.g., Solid conceptual clarity in Section A: Electrochemistry & Chemical Bonding...)",
        "Pacing / engagement observation with subject context"
    ],
    "areasToImprove": [
        "Specific weak chapter/topic with Section context and actionable advice (e.g., Urgent revision needed in Section B & C: Solutions (Raoult's Law & numerical conversions)...)",
        "Actionable exam technique or step-marking improvement for specific question formats"
    ],
    "teacherParentNote": "Realistic, score-calibrated 2-3 sentence advice for the parent/teacher citing specific chapters to reinforce at home.",
    "evolutionaryRoadmap": "Brief 1-2 sentence academic milestone summary."
}


def build_model_paper_diagnostic_user_prompt(
    student_name: str,
    board: str,
    class_grade: str,
    subject: str,
    set_num: int | str,
    marks_obtained: float,
    total_marks: float,
    accuracy_percentage: float,
    time_taken_seconds: int,
    total_allowed_mins: int,
    attempted_count: int,
    total_questions: int,
    correct_count: int,
    partial_count: int,
    incorrect_count: int,
    section_breakdown_summary: str = "",
    mastered_topics_by_section: dict[str, list[str]] | None = None,
    missed_topics_by_section: dict[str, list[str]] | None = None,
) -> str:
    """Constructs the rich, topic-wise diagnostic prompt payload for LLM analysis."""
    mins_taken = time_taken_seconds // 60
    secs_taken = time_taken_seconds % 60
    time_taken_str = f"{mins_taken}m {secs_taken}s" if mins_taken > 0 else f"{secs_taken}s"

    # Format section-wise topic lines
    sec_topic_lines = []
    if mastered_topics_by_section or missed_topics_by_section:
        all_sec_names = list(dict.fromkeys(
            list((mastered_topics_by_section or {}).keys()) +
            list((missed_topics_by_section or {}).keys())
        ))
        for sname in all_sec_names:
            m_topics = (mastered_topics_by_section or {}).get(sname, [])
            w_topics = (missed_topics_by_section or {}).get(sname, [])
            m_str = ", ".join(m_topics[:4]) if m_topics else "None"
            w_str = ", ".join(w_topics[:4]) if w_topics else "None"
            sec_topic_lines.append(f"- {sname}:\n  * Mastered/Correct Concepts: {m_str}\n  * Missed/Weak Concepts: {w_str}")
    
    sec_topics_formatted = "\n".join(sec_topic_lines) if sec_topic_lines else "General subject chapters."

    return f"""Student Examination Result Summary:
- Student Name: {student_name}
- Examination: {board} - {class_grade} | {subject} | 2027 Specimen Model Paper (Set {set_num})
- Total Marks: {marks_obtained} / {total_marks} ({accuracy_percentage}% Accuracy)
- Time Taken: {time_taken_str} (Allocated: {total_allowed_mins} Minutes)
- Question Attempts: {attempted_count} Attempted out of {total_questions} Questions ({correct_count} Correct, {partial_count} Partial Credit, {incorrect_count} Incorrect/Skipped)

Section-wise Score Breakdown:
{section_breakdown_summary or "Standard multi-section 2027 board pattern."}

Section-wise Conceptual Topic Mapping:
{sec_topics_formatted}

REQUIRED TASK:
Generate the diagnostic analysis JSON.
Ensure you mention specific CHAPTER & CONCEPT names (e.g. Solutions, Electrochemistry, Trigonometry) alongside Section letters (Section A, B, C, D, E) in the strengths, areasToImprove, and teacherParentNote. Do NOT use generic phrases like "Very Short Answer Type".
Adhere strictly to the student's {accuracy_percentage}% score band and time pacing ({time_taken_str}).

Schema:
{json.dumps(RESPONSE_SCHEMA_HINT, indent=2)}
"""
