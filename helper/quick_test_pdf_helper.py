"""Helper to generate individual PDF report attachments for quick demo tests.
Uses ReportLab to build high-quality printable scorecard reports with questions, student answers,
correct answers, and performance insights.
"""

import json
import re
from datetime import datetime
from sqlalchemy import text
from helper.pdf_report_generator import generate_exam_report_pdf


def clean_opt(val):
    if not val:
        return ""
    return re.sub(r'^(?:option\s+)?\(?[A-Da-d]\)?[\).\:\-]?\s*', '', str(val), flags=re.I).strip().lower()


def build_quick_test_pdf(test: dict, student_name: str, test_number: int) -> tuple[str, bytes]:
    """Generates an in-memory PDF report for a quick test attempt and returns (filename, pdf_bytes)."""
    subject_name = str(test.get("subject", "Science")).strip()
    board = str(test.get("board", "CBSE")).strip()
    class_grade = str(test.get("classGrade", "Class 10")).strip()
    score = float(test.get("score", 0.0))
    total_marks = float(test.get("totalMarks", 5.0))
    percentage = float(test.get("percentage", (score / total_marks * 100) if total_marks else 0.0))
    time_taken = int(test.get("timeTakenSeconds", 60))

    clean_subj = re.sub(r'[^a-zA-Z0-9_]', '_', subject_name)
    filename = f"EduJunction_Test_{test_number}_{clean_subj}_Report.pdf"

    # Exam date
    submitted_at = test.get("submittedAt")
    if submitted_at:
        try:
            dt = datetime.fromisoformat(str(submitted_at).replace("Z", "+00:00"))
            exam_date = dt.strftime("%b %d, %Y")
        except Exception:
            exam_date = datetime.now().strftime("%b %d, %Y")
    else:
        exam_date = datetime.now().strftime("%b %d, %Y")

    evaluations = []

    # Strategy A: Use reviews if present
    reviews = test.get("reviews") or []
    if reviews and isinstance(reviews, list) and len(reviews) > 0:
        for idx, rev in enumerate(reviews):
            evaluations.append({
                "questionText": rev.get("questionText", f"Question {idx + 1}"),
                "studentAnswer": rev.get("userAnswer") or rev.get("studentAnswer", "Not Answered"),
                "correctAnswer": rev.get("correctAnswer", "-"),
                "isCorrect": bool(rev.get("isCorrect", False)),
                "marksAwarded": 1.0 if rev.get("isCorrect") else 0.0,
                "explanation": rev.get("explanation", ""),
            })

    # Strategy B: If no reviews, lookup from question_master by question IDs in answers
    if not evaluations:
        raw_answers = test.get("answers") or {}
        raw_ids = [int(qid) for qid in raw_answers.keys() if str(qid).isdigit()]

        if raw_ids:
            try:
                from database.dbConnection import get_session
                with get_session() as session:
                    sql = text("""
                        SELECT id, question, options, correct_answer, explanation
                        FROM question_master
                        WHERE id IN :qids
                    """)
                    rows = session.execute(sql, {"qids": tuple(raw_ids)}).mappings().fetchall()
                    row_map = {r["id"]: r for r in rows}

                    for idx, qid in enumerate(raw_ids):
                        r = row_map.get(qid)
                        if not r:
                            continue

                        raw_options = r.get("options")
                        options_list = []
                        if isinstance(raw_options, list):
                            options_list = raw_options
                        elif isinstance(raw_options, str):
                            try:
                                parsed = json.loads(raw_options)
                                options_list = parsed if isinstance(parsed, list) else [raw_options]
                            except Exception:
                                options_list = [opt.strip() for opt in raw_options.split("|") if opt.strip()]

                        user_raw = str(raw_answers.get(str(qid), raw_answers.get(qid, ""))).strip()
                        db_correct = str(r["correct_answer"] or "").strip()

                        clean_user = clean_opt(user_raw)
                        clean_db = clean_opt(db_correct)

                        # Determine user index
                        user_idx = -1
                        if len(user_raw) == 1 and user_raw.upper() in "ABCD":
                            u_idx = ord(user_raw.upper()) - ord('A')
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

                        is_correct = False
                        if user_idx >= 0 and correct_idx >= 0:
                            is_correct = (user_idx == correct_idx)
                        elif clean_user and clean_db and clean_user == clean_db:
                            is_correct = True
                        elif user_raw.lower() == db_correct.lower():
                            is_correct = True

                        # Format student answer
                        if user_idx >= 0 and user_idx < len(options_list):
                            opt_str = options_list[user_idx].strip()
                            letter = chr(65 + user_idx)
                            formatted_user_ans = f"{letter}) {opt_str}" if not re.match(r'^[A-Da-d][\).\:\-]', opt_str) else opt_str
                        elif user_raw:
                            formatted_user_ans = user_raw
                        else:
                            formatted_user_ans = "Not Answered"

                        # Format correct answer
                        if correct_idx >= 0 and correct_idx < len(options_list):
                            opt_str = options_list[correct_idx].strip()
                            letter = chr(65 + correct_idx)
                            formatted_correct_ans = f"{letter}) {opt_str}" if not re.match(r'^[A-Da-d][\).\:\-]', opt_str) else opt_str
                        else:
                            formatted_correct_ans = db_correct

                        evaluations.append({
                            "questionText": r["question"],
                            "studentAnswer": formatted_user_ans,
                            "correctAnswer": formatted_correct_ans,
                            "isCorrect": is_correct,
                            "marksAwarded": 1.0 if is_correct else 0.0,
                            "explanation": r["explanation"] or "",
                        })
            except Exception as db_err:
                print(f"[!] Warning: Could not resolve questions from DB for PDF: {db_err}", flush=True)

    # Strategy C: Fallback if questions couldn't be loaded
    if not evaluations:
        evaluations.append({
            "questionText": f"{subject_name} Diagnostic Assessment ({board} {class_grade})",
            "studentAnswer": f"Overall Score: {score} / {total_marks}",
            "correctAnswer": f"Accuracy: {percentage}%",
            "isCorrect": percentage >= 60,
            "marksAwarded": score,
            "explanation": "Derived from standard curriculum textbook concepts.",
        })

    analysis = {
        "strengths": ["Core concept recall", "Problem solving"] if percentage >= 60 else ["Foundational effort"],
        "areasToImprove": ["Timed accuracy", "Revision of textbook rules"],
        "teacherParentNote": f"Completed {subject_name} Quick Assessment ({board} - {class_grade}) scoring {score}/{total_marks} marks ({percentage}%). Keep practicing to achieve full topic mastery!",
    }

    pdf_bytes = generate_exam_report_pdf(
        student_name=student_name or "Student",
        board=board,
        class_grade=class_grade,
        subject=subject_name,
        exam_title=f"{subject_name} Quick Assessment Report",
        exam_date=exam_date,
        marks_obtained=score,
        total_marks=total_marks,
        accuracy_percentage=percentage,
        time_taken_seconds=time_taken,
        evaluations=evaluations,
        analysis=analysis,
    )

    return filename, pdf_bytes
