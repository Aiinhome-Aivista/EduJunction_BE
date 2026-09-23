"""Prompt construction for post-exam diagnostic analysis.
Produces 100% dynamic, score-calibrated pedagogical insights grounded in live student submissions,
including question-level time pacing and topic speed analysis.
"""
import json

SYSTEM_PROMPT = """You are a Senior Academic Assessor & Child Pedagogy Specialist.
You analyze a student's actual diagnostic exam performance and generate an honest, evidence-based, score-calibrated diagnostic learning report.

CRITICAL ASSESSMENT RULES (MANDATORY):
1. STRICT TRUTHFULNESS & ANTI-HALLUCINATION:
   - If Correct Questions > 0 (or Marks Scored > 0), you are STRICTLY PROHIBITED from saying "None of the questions were answered correctly" or "No strengths can be identified".
   - You MUST explicitly reference the student's actual mastered topics from the CORRECT QUESTIONS list.
   - If Correct Questions == 0, state honestly that foundational concepts across the syllabus need initial review.

2. TIME PACING & SPEED ANALYSIS:
   - Analyze time spent per question and topic:
     * Fast & Accurate (High Speed & Fluency): Topics solved correctly in optimal time.
     * Pacing Friction / Time Bottlenecks: Questions/topics where the student spent excessive time (e.g. >40s) but arrived at an incorrect/incomplete step.
     * Rushed or Skipped: Questions left blank, skipped, or answered in <5s without thorough working.
   - Include pacing advice in the action plan (e.g., calculation speed drills vs reading problem statements carefully).

3. SCORE-TIER CALIBRATION:
   - Score < 40% (Needs Foundation): Strictly NO false praise. Acknowledge effort on attempted questions. Emphasize step-by-step textbook reading and formula fundamentals.
   - Score 40% - 69% (Developing): Highlight genuine strengths from the correctly solved topics and fast-paced areas. Pinpoint multi-step calculation traps and time-sink areas for revision.
   - Score >= 70% (Proficient / Advanced Mastery): Commend analytical precision, speed, and concept application. Recommend advancing to complex application problems (HOTS) and higher difficulty.

Always respond with a single valid JSON object and nothing else.
"""

RESPONSE_SCHEMA_HINT = {
    "overallBand": "Needs Foundation | Developing | Proficient | Advanced Mastery | Competitive Ready",
    "strengths": [
        "string (Topic mastery / fast conceptual speed grounded in actual correct questions)",
        "string (Specific question-type or problem-solving capability demonstrated)",
        "string (Pacing or curriculum engagement strength)"
    ],
    "areasToImprove": [
        "string (Specific missed topic / concept with calculation or formula trap identified)",
        "string (Pacing / time bottleneck or skipped question pattern to address)",
        "string (Actionable study/revision recommendation from official textbook syllabus)"
    ],
    "kGraphInsights": [
        {
            "topic": "string",
            "masteryPercentage": "integer 0-100",
            "status": "mastered | reinforce | critical_gap",
            "recommendedAction": "string",
        }
    ],
    "evolutionaryRoadmap": "string (concrete 2-3 sentence progress and pacing roadmap)",
    "encouragementNote": "string (realistic, score-calibrated, supportive note for child and parent)",
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
    marks_obtained: float | int,
    total_marks: float | int,
    accuracy_percentage: float,
    time_taken_seconds: int,
    evaluations: list[dict],
) -> str:
    correct_items = [e for e in evaluations if e.get("isCorrect")]
    incorrect_items = [e for e in evaluations if not e.get("isCorrect")]

    # Build structured list of correct questions
    correct_lines = []
    for idx, e in enumerate(correct_items):
        q_num = e.get("questionNumber") or (idx + 1)
        topic = e.get("topic") or subject
        t_sec = e.get("timeSpentSeconds", 0)
        marks = e.get("marksAwarded", 0)
        correct_lines.append(f"  - Q{q_num} [{topic}]: +{marks} marks (Time: {t_sec}s) - Answered Correctly")

    # Build structured list of incorrect/skipped questions
    incorrect_lines = []
    for idx, e in enumerate(incorrect_items):
        q_num = e.get("questionNumber") or (idx + 1)
        topic = e.get("topic") or subject
        t_sec = e.get("timeSpentSeconds", 0)
        ans = str(e.get("studentAnswer") or "Not Answered")
        if len(ans) > 40:
            ans = ans[:37] + "..."
        issue = e.get("misconceptionIdentified") or e.get("feedback") or "Incorrect / Incomplete"
        incorrect_lines.append(f"  - Q{q_num} [{topic}]: 0 marks (Time: {t_sec}s | Answer: '{ans}') -> Issue: {issue}")

    # Pacing insights summary
    fast_correct = [e.get("topic") or subject for e in correct_items if 0 < e.get("timeSpentSeconds", 0) <= 25]
    time_bottlenecks = [
        f"{e.get('topic') or subject} (Q{e.get('questionNumber', '?')}, {e.get('timeSpentSeconds', 0)}s)"
        for e in evaluations if e.get("timeSpentSeconds", 0) >= 35 and not e.get("isCorrect")
    ]
    skipped_topics = [
        f"{e.get('topic') or subject} (Q{e.get('questionNumber', '?')})"
        for e in incorrect_items if e.get("timeSpentSeconds", 0) <= 5 or str(e.get("studentAnswer", "")).strip() in ("(Not Answered)", "NA", "null", "")
    ]

    pacing_summary = []
    if fast_correct:
        pacing_summary.append(f"• High Speed & Accuracy in: {', '.join(list(dict.fromkeys(fast_correct)))}")
    if time_bottlenecks:
        pacing_summary.append(f"• Time Bottlenecks (High Time Spent but Incorrect): {', '.join(time_bottlenecks)}")
    if skipped_topics:
        pacing_summary.append(f"• Skipped / Unattempted Questions: {', '.join(skipped_topics)}")
    if not pacing_summary:
        pacing_summary.append("• Steady overall pacing across attempted questions.")

    correct_str = "\n".join(correct_lines) if correct_lines else "  None (0 questions correct)"
    incorrect_str = "\n".join(incorrect_lines) if incorrect_lines else "  None (All questions answered correctly!)"
    pacing_str = "\n".join(pacing_summary)

    return f"""Student Assessment Overview:
- Student Name: {student_name}
- Board & Grade: {board} - {class_grade} | Subject: {subject} | Difficulty: {difficulty}
- Score: {marks_obtained} / {total_marks} ({accuracy_percentage}% Accuracy)
- Total Time Taken: {time_taken_seconds}s ({time_taken_seconds // 60}m {time_taken_seconds % 60}s)
- Questions Summary: {len(correct_items)} Correct / {len(incorrect_items)} Incorrect or Skipped (Total: {len(evaluations)} Questions)

=== CORRECT QUESTIONS (VERIFIED STRENGTHS) ===
{correct_str}

=== INCORRECT / SKIPPED QUESTIONS (AREAS TO FOCUS) ===
{incorrect_str}

=== TIME PACING BREAKDOWN ===
{pacing_str}

INSTRUCTIONS FOR DIAGNOSTIC ANALYSIS:
1. Strengths: Ground them directly in the {len(correct_items)} verified correct topics above. DO NOT claim 0 correct answers when {len(correct_items)} questions are correct. Mention speed/fluency if applicable.
2. Areas to Focus: Point out the specific missed topics and address time bottlenecks or skipped questions from the pacing breakdown above.
3. Teacher/Parent Note: Give realistic, encouraging, score-calibrated advice ({accuracy_percentage}% band).
4. Return strictly a single valid JSON object following this schema:
{json.dumps(RESPONSE_SCHEMA_HINT, indent=2)}
"""
