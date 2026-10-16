"""Helper for syncing and evaluating guest test submissions so full question-by-question
reviews, options, explanations, and scores are permanently available in the reports.
"""

import json
import re
import uuid
from decimal import Decimal
from sqlalchemy import text
from model.models import Question, QuestionEvaluation, DiagnosticAnalysis, get_ist_now


def clean_opt(val):
    if not val:
        return ""
    return re.sub(r'^(?:option\s+)?\(?[A-Da-d]\)?[\).\:\-]?\s*', '', str(val), flags=re.I).strip().lower()


def populate_guest_exam_evaluations(session, exam, submission, raw_answers: dict = None, reviews: list = None):
    """Creates Question, QuestionEvaluation, and DiagnosticAnalysis records for a guest exam submission."""
    if not exam or not submission:
        return

    # Check if evaluations already exist
    existing_count = session.query(QuestionEvaluation).filter(
        QuestionEvaluation.submission_id == submission.id
    ).count()
    if existing_count > 0:
        return

    raw_answers = raw_answers or submission.answers or {}
    subject_name = exam.subject or "General"

    # Case 1: reviews list is provided (from evaluateQuickDemo API)
    if reviews and isinstance(reviews, list) and len(reviews) > 0:
        for idx, rev in enumerate(reviews):
            qid = rev.get("questionId")
            q_text = rev.get("questionText", f"Question {idx + 1}")
            opts = rev.get("options", [])
            user_ans = rev.get("userAnswer", "")
            corr_ans = rev.get("correctAnswer", "")
            is_corr = bool(rev.get("isCorrect", False))
            expl = rev.get("explanation", "Derived from standard curriculum textbook concepts.")
            topic = rev.get("topic") or subject_name

            q_obj = Question(
                id=str(uuid.uuid4()),
                exam_id=exam.id,
                question_number=idx + 1,
                type="mcq",
                question_text=q_text,
                options=opts,
                correct_answer=corr_ans,
                explanation=expl,
                difficulty="medium",
                marks=1,
                topic=topic,
                reference_links=[],
                hint=f"Focus on {topic} fundamentals.",
            )
            session.add(q_obj)
            session.flush()

            q_eval = QuestionEvaluation(
                id=str(uuid.uuid4()),
                submission_id=submission.id,
                question_id=q_obj.id,
                student_answer=user_ans or "Not Attempted",
                time_spent_seconds=0,
                is_correct=is_corr,
                marks_awarded=1.0 if is_corr else 0.0,
                misconception_identified=None if is_corr else f"Review concepts on {topic}",
                feedback="Correct! Excellent conceptual grasp." if is_corr else f"Incorrect. Review the core rules of {topic}.",
            )
            session.add(q_eval)

    # Case 2: We have raw_answers mapping question_master IDs -> student answer choice
    elif raw_answers and isinstance(raw_answers, dict):
        raw_ids = [int(qid) for qid in raw_answers.keys() if str(qid).isdigit()]
        if not raw_ids:
            return

        query_sql = text("""
            SELECT q.id, q.question AS question_text, q.options, q.correct_answer, q.explanation, q.marks, q.image_url,
                   COALESCE(t.topic_name, ch.chapter_name, :default_subj) AS topic_name
            FROM question_master q
            LEFT JOIN topic_master t ON q.topic_id = t.id
            LEFT JOIN chapter_master ch ON t.chapter_id = ch.id
            WHERE q.id IN :q_ids
        """)
        rows = session.execute(query_sql, {"q_ids": tuple(raw_ids), "default_subj": subject_name}).mappings().fetchall()
        row_map = {r["id"]: r for r in rows}

        for idx, qid in enumerate(raw_ids):
            r = row_map.get(qid)
            if not r:
                continue

            raw_options = r.get("options")
            options_list = []
            if raw_options:
                if isinstance(raw_options, list):
                    options_list = raw_options
                elif isinstance(raw_options, str):
                    try:
                        parsed = json.loads(raw_options)
                        if isinstance(parsed, list):
                            options_list = parsed
                        elif isinstance(parsed, dict):
                            options_list = [f"{k}) {v}" for k, v in parsed.items()]
                        else:
                            options_list = [raw_options]
                    except Exception:
                        options_list = [opt.strip() for opt in raw_options.split("|") if opt.strip()]

            user_raw_ans = str(raw_answers.get(str(qid), raw_answers.get(qid, ""))).strip()
            db_correct = str(r["correct_answer"] or "").strip()

            clean_user = clean_opt(user_raw_ans)
            clean_db = clean_opt(db_correct)

            # Determine user index
            user_idx = -1
            if len(user_raw_ans) == 1 and user_raw_ans.upper() in "ABCD":
                u_idx = ord(user_raw_ans.upper()) - ord('A')
                if 0 <= u_idx < len(options_list):
                    user_idx = u_idx
            if user_idx == -1 and clean_user:
                for o_idx, opt in enumerate(options_list):
                    if clean_opt(opt) == clean_user:
                        user_idx = o_idx
                        break

            # Determine correct index
            correct_idx = -1
            if len(db_correct) == 1 and db_correct.upper() in "ABCD":
                c_idx = ord(db_correct.upper()) - ord('A')
                if 0 <= c_idx < len(options_list):
                    correct_idx = c_idx
            if correct_idx == -1 and clean_db:
                for o_idx, opt in enumerate(options_list):
                    c_opt = clean_opt(opt)
                    if c_opt == clean_db or clean_db == c_opt or (len(clean_db) > 2 and clean_db in c_opt):
                        correct_idx = o_idx
                        break

            # Check correctness
            is_correct = False
            if user_idx >= 0 and correct_idx >= 0:
                is_correct = (user_idx == correct_idx)
            elif clean_user and clean_db and clean_user == clean_db:
                is_correct = True
            elif user_raw_ans.lower() == db_correct.lower():
                is_correct = True
            elif user_idx >= 0 and clean_opt(options_list[user_idx]) == clean_db:
                is_correct = True
            elif correct_idx >= 0 and clean_opt(options_list[correct_idx]) == clean_user:
                is_correct = True

            # Formatted student answer
            if user_idx >= 0 and user_idx < len(options_list):
                opt_str = options_list[user_idx].strip()
                letter = chr(65 + user_idx)
                formatted_user_ans = f"{letter}) {opt_str}" if not re.match(r'^[A-Da-d][\).\:\-]', opt_str) else opt_str
            elif user_raw_ans:
                formatted_user_ans = user_raw_ans
            else:
                formatted_user_ans = "Not Attempted"

            # Formatted correct answer
            if correct_idx >= 0 and correct_idx < len(options_list):
                opt_str = options_list[correct_idx].strip()
                letter = chr(65 + correct_idx)
                formatted_correct_ans = f"{letter}) {opt_str}" if not re.match(r'^[A-Da-d][\).\:\-]', opt_str) else opt_str
            else:
                formatted_correct_ans = db_correct

            topic = r["topic_name"] or subject_name
            q_obj = Question(
                id=str(uuid.uuid4()),
                exam_id=exam.id,
                question_number=idx + 1,
                type="mcq",
                question_text=r["question_text"],
                options=options_list,
                correct_answer=formatted_correct_ans,
                explanation=r["explanation"] or "Derived from standard curriculum textbook concepts.",
                difficulty="medium",
                marks=1,
                topic=topic,
                reference_links=[],
                hint=f"Focus on {topic} fundamentals.",
                image_url=r.get("image_url")
            )
            session.add(q_obj)
            session.flush()

            q_eval = QuestionEvaluation(
                id=str(uuid.uuid4()),
                submission_id=submission.id,
                question_id=q_obj.id,
                student_answer=formatted_user_ans,
                time_spent_seconds=0,
                is_correct=is_correct,
                marks_awarded=1.0 if is_correct else 0.0,
                misconception_identified=None if is_correct else f"Review concepts on {topic}",
                feedback="Correct! Excellent conceptual grasp." if is_correct else f"Incorrect. Review the core rules of {topic}.",
            )
            session.add(q_eval)

    # Also ensure DiagnosticAnalysis exists
    if not submission.analysis:
        existing_diag = session.query(DiagnosticAnalysis).filter(
            DiagnosticAnalysis.submission_id == submission.id
        ).first()
        if not existing_diag:
            pct = float(submission.accuracy_percentage or 0.0)
            diag = DiagnosticAnalysis(
                id=str(uuid.uuid4()),
                submission_id=submission.id,
                overall_band="Proficient" if pct >= 60 else "Developing",
                mastery_score_percentage=pct,
                strengths=["Core conceptual understanding", "Grounded problem solving"],
                areas_to_improve=["Timed speed", "Complex multi-step questions"],
                k_graph_insights=[],
                evolutionary_roadmap=f"Continue regular diagnostic practice in {exam.subject} to maintain mastery.",
                encouragement_note=f"Great effort on completing the {exam.subject} Quick Assessment!",
                recommended_next_exam={
                    "board": exam.board or "CBSE",
                    "classGrade": exam.class_grade or "Class 10",
                    "subject": exam.subject or "Science",
                    "difficulty": "medium",
                    "reason": "Reinforce conceptual foundations from diagnostic insights."
                },
                curated_study_links=[],
                source="fallback"
            )
            session.add(diag)
            session.flush()
