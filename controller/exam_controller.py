from utils.date_helper import now_ist
import json
import re
import uuid
from datetime import date, datetime, timedelta

from flask import request, g
from sqlalchemy import text

from database.dbConnection import get_session
from helper import diagnostic_engine, exam_generator, gamification_engine, mastery_engine, misconception_engine
from helper.adaptive_learning_engine import update_learning_path_after_submission
from helper.evaluation_engine import evaluate_exam
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import assert_owns_student
from model.models import Exam, ExamSubmission, QuestionEvaluation, DiagnosticAnalysis, Student, Parent, ScheduledExam, Notification, XPEvent
from controller.notification_controller import create_notification
from utils.errors import AppError, NotFoundError, ValidationError
from utils.response import success
from utils.audit_helper import log_audit
from utils.serializers import submission_to_dict
from utils.validators import require_fields, validate_board, validate_class_grade, validate_board_class, validate_subject, validate_difficulty



def _resolve_student_for_request(session, payload: dict) -> Student:
    """A parent generates an exam on behalf of a named child; a student
    token (from /auth/child-login) generates it for themselves."""
    if g.current_user_role == "STUDENT":
        student = session.get(Student, g.current_user_id)
        if not student:
            raise NotFoundError("Student profile not found")
        return student

    require_fields(payload, ["studentId"])
    return assert_owns_student(session, payload["studentId"], g.current_user_id)


def _reset_daily_quota_if_new_day(student: Student):
    today = date.today()
    if student.last_exam_date != today:
        student.daily_exams_taken_today = 0


@token_required
def generate_exam():
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["board", "subject", "difficulty"])
    from utils.constants import normalize_subject
    raw_subject = str(payload.get("subject", "")).strip()
    normalized_sub = normalize_subject(raw_subject)
    payload["subject"] = normalized_sub

    validate_board(payload["board"])
    if payload.get("classGrade"):
        validate_class_grade(payload["classGrade"])
    validate_subject(payload["subject"])
    validate_difficulty(payload["difficulty"])

    with get_session() as session:
        student = _resolve_student_for_request(session, payload)
        target_class = payload.get("classGrade", student.class_grade)
        validate_board_class(payload["board"], target_class)

        scheduled_exam_id = payload.get("scheduledExamId")
        scheduled_exam = None
        if scheduled_exam_id:
            scheduled_exam = session.get(ScheduledExam, scheduled_exam_id)

        # Dynamic Question Count & Duration
        req_q_count = (scheduled_exam.question_count if scheduled_exam else None) or payload.get("questionCount")
        req_duration = (scheduled_exam.time_limit_minutes if scheduled_exam else None) or payload.get("timeLimitMinutes")
        req_topic = payload.get("chapterTopic") or payload.get("topic") or (scheduled_exam.chapter_topic if scheduled_exam else None)
        title = scheduled_exam.title if scheduled_exam else payload.get("title")

        is_assigned_flag = bool(scheduled_exam)

        exam = exam_generator.generate_exam(
            session,
            student_id=student.id,
            student_name=student.user.name if student.user else "Student",
            board=payload["board"],
            class_grade=target_class,
            subject=payload["subject"],
            difficulty=payload["difficulty"],
            question_count=int(req_q_count) if req_q_count else None,
            time_limit_minutes=int(req_duration) if req_duration else None,
            title=title,
            is_assigned=is_assigned_flag,
            chapter_topic=req_topic,
        )

        if scheduled_exam:
            scheduled_exam.exam_id = exam.id
            scheduled_exam.status = "IN_PROGRESS"
            session.flush()

        student.daily_exams_taken_today = (student.daily_exams_taken_today or 0) + 1

        log_audit(
            session,
            action="EXAM_GENERATED",
            user_id=g.current_user_id,
            entity_type="EXAM",
            entity_id=str(exam.id),
            request=request,
        )
        session.commit()

        public_exam = exam_generator.exam_to_public_dict(exam)
        if scheduled_exam:
            public_exam["scheduledExamId"] = scheduled_exam.id

        return success(
            {"exam": public_exam},
            201,
            source=exam.source,
        )


@token_required
def generate_quick_test():
    """Generates a diagnostic test directly from DB or Engine matching
    the student's registered Curriculum Board, Class Grade, and exact Subject/Question Count."""
    payload = request.get_json(force=True, silent=True) or {}
    if not payload.get("studentId") and request.args.get("studentId"):
        payload["studentId"] = request.args.get("studentId")

    scheduled_exam_id = payload.get("scheduledExamId")

    with get_session() as session:
        student = _resolve_student_for_request(session, payload)

        # Tier determination using regex
        cg_clean = (student.class_grade or '').strip().lower()
        is_senior = any(k in cg_clean for k in ['class 11', 'class 12', 'grade 11', 'grade 12', 'neet', 'iit', 'jee'])
        match_cg = re.search(r'(?:class|grade)?\s*(\d+)', cg_clean)
        cnum = int(match_cg.group(1)) if match_cg else 5
        is_kid = (1 <= cnum <= 4) and not is_senior
        if cnum >= 11:
            is_senior = True

        default_limit = 5 if is_kid else 10
        limit = int(payload.get("limit", default_limit))
        from utils.constants import normalize_subject
        requested_subject = normalize_subject(str(payload.get("subject", "")).strip()) if payload.get("subject") else ""
        requested_diff = str(payload.get("difficulty", "simple" if is_kid else "medium")).lower()
        requested_topic = str(payload.get("chapterTopic") or payload.get("topic") or "").strip() or None

        scheduled_exam = None
        if scheduled_exam_id:
            scheduled_exam = session.get(ScheduledExam, scheduled_exam_id)
            if scheduled_exam:
                limit = scheduled_exam.question_count
                requested_subject = normalize_subject(scheduled_exam.subject)
                requested_diff = scheduled_exam.difficulty
                requested_topic = scheduled_exam.chapter_topic or requested_topic

        # If not specified, look for active pending scheduled exam for this student
        if not scheduled_exam and not requested_subject:
            scheduled_exam = (
                session.query(ScheduledExam)
                .filter(
                    ScheduledExam.student_id == student.id,
                    ScheduledExam.status.in_(["PENDING", "IN_PROGRESS"])
                )
                .order_by(ScheduledExam.created_at.desc())
                .first()
            )
            if scheduled_exam:
                limit = scheduled_exam.question_count
                requested_subject = scheduled_exam.subject
                requested_diff = scheduled_exam.difficulty
                requested_topic = scheduled_exam.chapter_topic or requested_topic

        sp_rows = []
        # Try fetching questions for specific subject if requested
        if requested_subject:
            try:
                sp_rows = session.execute(
                    text("CALL sp_generate_exam_from_db(:board, :class_grade, :subject, :difficulty)"),
                    {
                        "board": student.target_board,
                        "class_grade": student.class_grade,
                        "subject": requested_subject,
                        "difficulty": requested_diff or ("simple" if is_kid else "medium"),
                    }
                ).mappings().fetchall()
            except Exception:
                sp_rows = []

        # If sp_rows is empty or doesn't have enough questions for the requested limit,
        # fallback to the smart curriculum/fallback exam generator to guarantee exact count and subject
        if not sp_rows or len(sp_rows) < limit or requested_topic:
            exam_title = scheduled_exam.title if scheduled_exam else None
            time_limit = scheduled_exam.time_limit_minutes if scheduled_exam else (10 if is_kid else (25 if is_senior else 15))
            exam = exam_generator.generate_exam(
                session,
                student_id=student.id,
                student_name=student.user.name if student.user else "Student",
                board=student.target_board,
                class_grade=student.class_grade,
                subject=requested_subject or ("General Science" if is_kid else "Mathematics"),
                difficulty=requested_diff or ("simple" if is_kid else "medium"),
                question_count=limit,
                time_limit_minutes=time_limit,
                title=exam_title,
                is_assigned=bool(scheduled_exam),
                chapter_topic=requested_topic,
            )
            if scheduled_exam:
                scheduled_exam.exam_id = exam.id
                scheduled_exam.status = "IN_PROGRESS"
                session.flush()

            student.daily_exams_taken_today = (student.daily_exams_taken_today or 0) + 1

            log_audit(
                session,
                action="QUICK_EXAM_GENERATED",
                user_id=g.current_user_id,
                entity_type="EXAM",
                entity_id=str(exam.id),
                request=request,
            )
            session.commit()
            return success(
                {
                    "exam": {
                        **exam_generator.exam_to_public_dict(exam),
                        "scheduledExamId": scheduled_exam.id if scheduled_exam else None,
                    },
                    "student": {
                        "id": student.id,
                        "name": student.user.name if student.user else "",
                        "avatar": student.avatar,
                        "classGrade": student.class_grade,
                        "targetBoard": student.target_board,
                    }
                },
                201,
                source="rag-engine-curated"
            )

        # Slice to exact limit
        sp_rows = list(sp_rows)[:limit]
        
        # Calculate per-question marks & total marks
        row_marks = []
        for idx, row in enumerate(sp_rows):
            if row.get("marks"):
                row_marks.append(int(row.get("marks")))
            elif is_kid:
                row_marks.append(1)
            elif is_senior:
                row_marks.append(2)
            else:
                row_marks.append(1 if idx < 5 else 2)

        total_exam_marks = sum(row_marks)
        primary_subject = requested_subject or sp_rows[0].get("subject_name") or "General Assessment"
        
        if is_kid:
            title = scheduled_exam.title if scheduled_exam else f"{student.class_grade} {student.target_board} Adventure Challenge ({total_exam_marks} Marks)"
            time_limit = (scheduled_exam.time_limit_minutes if scheduled_exam else 10)
        elif is_senior:
            title = scheduled_exam.title if scheduled_exam else f"{student.class_grade} {student.target_board} {primary_subject} ({requested_diff.upper()}) Diagnostic {total_exam_marks}-Mark Exam"
            time_limit = (scheduled_exam.time_limit_minutes if scheduled_exam else 25)
        else:
            title = scheduled_exam.title if scheduled_exam else f"{student.class_grade} {student.target_board} Quick Diagnostic Assessment ({total_exam_marks} Marks)"
            time_limit = (scheduled_exam.time_limit_minutes if scheduled_exam else 15)

        from model.models import Question
        exam = Exam(
            id=str(uuid.uuid4()),
            student_id=student.id,
            title=title,
            board=student.target_board,
            class_grade=student.class_grade,
            subject=primary_subject,
            difficulty=requested_diff if requested_diff in ["simple", "medium", "hard"] else ("simple" if is_kid else "medium"),
            total_marks=total_exam_marks,
            question_count=len(sp_rows),
            time_limit_minutes=time_limit,
            rag_knowledge_nodes_used=list({r.get("chapter_name") for r in sp_rows if r.get("chapter_name")}),
            source="rag-engine-curated",
            status="GENERATED",
            created_at=now_ist(),
        )
        session.add(exam)
        session.flush()

        for idx, row in enumerate(sp_rows):
            raw_options = row.get("options")
            parsed_options = None
            if isinstance(raw_options, str):
                try:
                    parsed_options = json.loads(raw_options)
                except Exception:
                    parsed_options = [raw_options]
            elif isinstance(raw_options, list):
                parsed_options = raw_options

            raw_type = (row.get("question_type") or "").lower()
            if parsed_options and len(parsed_options) > 1:
                q_type = "mcq"
            elif "num" in raw_type or "math" in raw_type:
                q_type = "numerical"
            elif "logic" in raw_type:
                q_type = "logical"
            elif "saq" in raw_type or "short" in raw_type:
                q_type = "saq"
            else:
                q_type = "objective"

            raw_diff = (row.get("difficulty") or requested_diff or "medium").lower()
            if "easy" in raw_diff or "sim" in raw_diff:
                q_diff = "simple"
            elif "hard" in raw_diff or "adv" in raw_diff:
                q_diff = "hard"
            else:
                q_diff = "medium"

            exam.questions.append(
                Question(
                    id=str(uuid.uuid4()),
                    question_number=idx + 1,
                    type=q_type,
                    question_text=row.get("question_text") or f"Question {idx + 1}",
                    options=parsed_options,
                    correct_answer=str(row.get("correct_answer") or ""),
                    explanation=row.get("explanation") or "Step-by-step diagnostic solution.",
                    difficulty=q_diff,
                    marks=row_marks[idx],
                    topic=row.get("topic_name") or primary_subject,
                    reference_links=[],
                    hint=f"Focus on {row.get('topic_name') or primary_subject} fundamentals.",
                )
            )

        if scheduled_exam:
            scheduled_exam.exam_id = exam.id
            scheduled_exam.status = "IN_PROGRESS"
            session.flush()

        student.daily_exams_taken_today = (student.daily_exams_taken_today or 0) + 1

        log_audit(
            session,
            action="QUICK_EXAM_GENERATED",
            user_id=g.current_user_id,
            entity_type="EXAM",
            entity_id=str(exam.id),
            request=request,
        )
        session.commit()

        return success(
            {
                "exam": {
                    **exam_generator.exam_to_public_dict(exam),
                    "scheduledExamId": scheduled_exam.id if scheduled_exam else None,
                },
                "student": {
                    "id": student.id,
                    "name": student.user.name if student.user else "",
                    "avatar": student.avatar,
                    "classGrade": student.class_grade,
                    "targetBoard": student.target_board,
                }
            },
            201,
            source="mysql-stored-procedure"
        )


@token_required
def submit_exam(exam_id):
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["answers"])
    answers = payload["answers"]
    if not isinstance(answers, dict):
        raise ValidationError("'answers' must be an object of {questionId: answerText}")
    time_taken_seconds = max(10, int(payload.get("timeTakenSeconds", 10)))

    with get_session() as session:
        exam = session.get(Exam, exam_id)
        if not exam:
            raise NotFoundError("Exam not found")

        current_uid = int(g.current_user_id) if str(g.current_user_id).isdigit() else g.current_user_id

        if g.current_user_role == "STUDENT" and exam.student_id != current_uid:
            raise AppError("FORBIDDEN", "This exam does not belong to you", 403)
        elif g.current_user_role == "PARENT":
            assert_owns_student(session, exam.student_id, current_uid)

        if exam.status == "SUBMITTED":
            raise AppError("ALREADY_SUBMITTED", "This exam has already been submitted", 409)

        evaluations, marks_obtained = evaluate_exam(
            exam.questions,
            answers,
            board=exam.board,
            class_grade=exam.class_grade,
            subject=exam.subject,
        )
        accuracy_percentage = round((marks_obtained / exam.total_marks) * 100, 2)

        student = session.get(Student, exam.student_id)
        student_name = student.user.name if student and student.user else "Student"

        analysis, analysis_source = diagnostic_engine.generate_diagnostic_analysis(
            exam, marks_obtained, evaluations, time_taken_seconds, student_name
        )

        submission = ExamSubmission(
            id=str(uuid.uuid4()), exam_id=exam.id, student_id=exam.student_id, answers=answers,
            marks_obtained=marks_obtained, total_marks=exam.total_marks,
            accuracy_percentage=accuracy_percentage, time_taken_seconds=time_taken_seconds,
            submitted_at=now_ist(),
        )
        session.add(submission)
        session.flush()

        per_q_time = payload.get("timeSpentPerQuestion") or {}
        for ev in evaluations:
            q_time = per_q_time.get(str(ev["questionId"])) or per_q_time.get(ev["questionId"]) or 0
            session.add(
                QuestionEvaluation(
                    id=str(uuid.uuid4()), submission_id=submission.id, question_id=ev["questionId"],
                    student_answer=ev["studentAnswer"],
                    time_spent_seconds=int(q_time) if str(q_time).isdigit() else 0,
                    is_correct=ev["isCorrect"],
                    marks_awarded=ev["marksAwarded"], misconception_identified=ev["misconceptionIdentified"],
                    feedback=ev.get("feedback"),
                )
            )

        session.add(
            DiagnosticAnalysis(
                id=str(uuid.uuid4()), submission_id=submission.id,
                overall_band=analysis["overallBand"], mastery_score_percentage=analysis["masteryScorePercentage"],
                strengths=analysis["strengths"], areas_to_improve=analysis["areasToImprove"],
                k_graph_insights=analysis["kGraphInsights"], evolutionary_roadmap=analysis["evolutionaryRoadmap"],
                encouragement_note=analysis["encouragementNote"],
                recommended_next_exam=analysis["recommendedNextExam"],
                curated_study_links=analysis["curatedStudyLinks"], source=analysis_source,
            )
        )

        exam.status = "SUBMITTED"

        # Rolling average percentage (0-100%) + streak + mastery + misconceptions + learning path.
        updated_total = (student.total_exams_taken or 0) + 1
        student.average_score = round(
            ((float(student.average_score or 0) * (student.total_exams_taken or 0)) + accuracy_percentage) / updated_total, 2
        )
        student.total_exams_taken = updated_total

        # Daily Streak Logic: Based on distinct consecutive exam submission calendar dates (IST)
        gamification_engine.calculate_and_sync_student_streak(session, student)

        # Server-side XP/badges (Canonical Simple XP: 1% exam percentage = 1 XP)
        xp_earned = gamification_engine.compute_exam_xp(marks_obtained, exam.total_marks or 15)
        newly_unlocked_badges = gamification_engine.evaluate_badge_unlocks(
            session, student, marks_obtained, time_taken_seconds, exam.difficulty
        )
        
        # Duplicate Prevention (Idempotency): Ensure one exam attempt generates XP only once
        existing_xp = (
            session.query(XPEvent)
            .filter(XPEvent.student_id == student.id, XPEvent.reason == f"exam:{exam.id}")
            .first()
        )
        if not existing_xp and xp_earned > 0:
            gamification_engine.award_xp(session, student, xp_earned, f"exam:{exam.id}")

        mastery_engine.update_mastery_from_insights(session, student.id, analysis["kGraphInsights"])
        misconception_engine.record_misconceptions_from_evaluations(session, student.id, evaluations)
        update_learning_path_after_submission(
            session, student.id, exam.subject, marks_obtained, analysis["kGraphInsights"]
        )

        # Check if this matches a parent-scheduled exam
        scheduled_exam_id = payload.get("scheduledExamId")
        scheduled_exam = None
        if scheduled_exam_id:
            scheduled_exam = session.get(ScheduledExam, scheduled_exam_id)
        
        if not scheduled_exam:
            # Check if this exam was generated specifically for a scheduled exam record
            scheduled_exam = (
                session.query(ScheduledExam)
                .filter(ScheduledExam.exam_id == exam.id)
                .first()
            )

        if scheduled_exam:
            scheduled_exam.status = "SUBMITTED"
            scheduled_exam.submission_id = submission.id
            scheduled_exam.exam_id = exam.id

            # Mark student's assigned, due soon, and overdue notifications as read
            session.query(Notification).filter(
                Notification.user_id == student.id,
                Notification.type.in_(["EXAM_ASSIGNED", "EXAM_DUE_SOON", "EXAM_OVERDUE"]),
                Notification.is_read == False
            ).update({"is_read": True}, synchronize_session=False)

            # Send Real-Time Notification to Parent ONLY for Parent-Scheduled Exams
            if student.parent_id:
                notif_title = f"{student_name} completed assigned {exam.subject} Exam! 📝"
                create_notification(
                    session=session,
                    user_id=student.parent_id,
                    sender_id=student.id,
                    notif_type="SCHEDULED_EXAM_COMPLETED",
                    title=notif_title,
                    message=f"{student_name} completed your assigned {exam.subject} test and scored {marks_obtained}/{exam.total_marks} ({accuracy_percentage}%).",
                    action_url="/reports",
                    metadata_json={
                        "scheduledExamId": scheduled_exam.id,
                        "submissionId": str(submission.id),
                        "examId": str(exam.id),
                        "studentId": student.id,
                        "studentName": student_name,
                        "subject": exam.subject,
                        "marksObtained": marks_obtained,
                        "totalMarks": exam.total_marks,
                        "accuracy": accuracy_percentage,
                    }
                )

        # Automatic PDF Report Generation & Parent Email Dispatch
        parent_email = None
        if student and student.parent and student.parent.user:
            parent_email = student.parent.user.email
        elif student and student.user:
            parent_email = student.user.email

        if parent_email:
            try:
                from helper.pdf_report_generator import generate_exam_report_pdf
                from controller.email_controller import send_student_exam_report_email

                sub_date_str = submission.submitted_at.strftime("%d %b %Y, %I:%M %p") if submission.submitted_at else "Today"
                pdf_bytes = generate_exam_report_pdf(
                    student_name=student_name,
                    board=exam.board,
                    class_grade=exam.class_grade,
                    subject=exam.subject,
                    exam_title=exam.title or "Adaptive Diagnostic Test",
                    exam_date=sub_date_str,
                    marks_obtained=marks_obtained,
                    total_marks=exam.total_marks,
                    accuracy_percentage=accuracy_percentage,
                    time_taken_seconds=time_taken_seconds,
                    evaluations=evaluations,
                    analysis=analysis,
                )

                send_student_exam_report_email(
                    to_email=parent_email,
                    student_name=student_name,
                    board=exam.board,
                    class_grade=exam.class_grade,
                    subject_name=exam.subject,
                    exam_title=exam.title or "Adaptive Diagnostic Test",
                    exam_date=sub_date_str,
                    marks_obtained=marks_obtained,
                    total_marks=exam.total_marks,
                    accuracy_percentage=accuracy_percentage,
                    pdf_bytes=pdf_bytes,
                )
            except Exception as email_err:
                logger.warning(f"Failed to generate/email exam report PDF: {email_err}")

        log_audit(
            session,
            action="EXAM_SUBMITTED",
            user_id=g.current_user_id,
            entity_type="EXAM_SUBMISSION",
            entity_id=str(submission.id),
            request=request,
        )
        session.commit()


        return success({
            "submission": {
                **submission_to_dict(submission, include_details=True),
                "examTitle": exam.title, "board": exam.board, "classGrade": exam.class_grade,
                "subject": exam.subject, "difficulty": exam.difficulty, "studentName": student_name,
                "evaluations": evaluations, "analysis": analysis,
            },
            "xpEarned": xp_earned,
            "newlyUnlockedBadges": newly_unlocked_badges,
        })


@token_required
def get_submission(submission_id):
    with get_session() as session:
        submission = session.get(ExamSubmission, submission_id)
        if not submission:
            raise NotFoundError("Submission not found")
        
        current_uid = int(g.current_user_id) if str(g.current_user_id).isdigit() else g.current_user_id
        if g.current_user_role == "STUDENT" and submission.student_id != current_uid:
            raise AppError("FORBIDDEN", "This report does not belong to you", 403)
        elif g.current_user_role == "PARENT":
            assert_owns_student(session, submission.student_id, current_uid)

        return success(submission_to_dict(submission, include_details=True))

