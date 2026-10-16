from utils.date_helper import now_ist
from datetime import date

from flask import g
from flask import g, request
from sqlalchemy import exists, or_
from sqlalchemy.orm import aliased, joinedload

from database.dbConnection import get_session
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import roles_required
from model.models import User, Student, Exam, ExamSubmission, Runbook, Role
from utils.constants import BOARDS, CLASS_GRADES
from utils.errors import AppError, NotFoundError
from utils.pagination import get_pagination_params, paginated_response
from utils.response import success
from utils.serializers import student_to_child_account


def statistics():
    """Public — matches the frontend's original unauthenticated GET /api/stats
    used by SuperAdminPanel's analytics tab and homepage counters."""
    with get_session() as session:
        total_generated = session.query(Exam).count()
        total_completed = session.query(ExamSubmission).count()
        total_runbooks = session.query(Runbook).filter(Runbook.status == "PUBLISHED").count()

        avg_row = session.query(ExamSubmission.accuracy_percentage).all()
        avg_score = (
            round(sum(float(r[0]) for r in avg_row) / len(avg_row) / 10, 2) if avg_row else 0
        )  # convert 0-100% back to an out-of-10 average, matching the frontend's displayed metric

        return success({
            "totalExamsGenerated": total_generated,
            "totalExamsCompleted": total_completed,
            "totalRunbooks": total_runbooks,
            "supportedBoards": BOARDS,
            "supportedGrades": CLASS_GRADES,
            "averagePlatformScore": avg_score,
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def admin_dashboard():
    from datetime import datetime, timedelta

    with get_session() as session:
        admin_roles = ["ADMIN", "SUPER_ADMIN"]
        total_users = session.query(User).outerjoin(Role).filter(
            or_(Role.role_name == None, ~Role.role_name.in_(admin_roles))
        ).count()
        total_students = session.query(Student).count()
        total_exams = session.query(Exam).count()
        total_submissions = session.query(ExamSubmission).count()
        total_runbooks = session.query(Runbook).count()

        avg_row = session.query(ExamSubmission.accuracy_percentage).all()
        avg_score = (
            round(sum(float(r[0]) for r in avg_row) / len(avg_row), 1) if avg_row else 0.0
        )

        # ── 1. Weekly Assessment Activity (Mon -> Sun) ──
        today = now_ist().date()
        start_of_week = today - timedelta(days=today.weekday())
        days_map = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        weekly_activity = []
        for i, day_name in enumerate(days_map):
            day_date = start_of_week + timedelta(days=i)
            day_start = datetime.combine(day_date, datetime.min.time())
            day_end = datetime.combine(day_date, datetime.max.time())

            gen_count = session.query(Exam).filter(Exam.created_at >= day_start, Exam.created_at <= day_end).count()
            sub_count = session.query(ExamSubmission).filter(ExamSubmission.submitted_at >= day_start, ExamSubmission.submitted_at <= day_end).count()

            weekly_activity.append({
                "day": day_name,
                "date": day_date.strftime("%b %d"),
                "generated": gen_count,
                "completed": sub_count,
            })

        # ── 2. Subject Performance Breakdown ──
        subjects_data = {}
        exams = session.query(Exam.id, Exam.subject).all()
        exam_subject_map = {e[0]: (e[1] or "General").strip().title() for e in exams}

        for e_id, subj in exam_subject_map.items():
            if subj not in subjects_data:
                subjects_data[subj] = {"subject": subj, "examsGenerated": 0, "submissions": 0, "totalAccuracy": 0.0}
            subjects_data[subj]["examsGenerated"] += 1

        submissions = session.query(ExamSubmission.exam_id, ExamSubmission.accuracy_percentage).all()
        for sub_exam_id, acc in submissions:
            subj = exam_subject_map.get(sub_exam_id, "General")
            if subj not in subjects_data:
                subjects_data[subj] = {"subject": subj, "examsGenerated": 0, "submissions": 0, "totalAccuracy": 0.0}
            subjects_data[subj]["submissions"] += 1
            subjects_data[subj]["totalAccuracy"] += float(acc or 0)

        subject_list = []
        for subj, item in subjects_data.items():
            avg_subj_acc = round(item["totalAccuracy"] / item["submissions"], 1) if item["submissions"] > 0 else 0.0
            subject_list.append({
                "subject": subj,
                "examsCount": item["examsGenerated"],
                "submissionsCount": item["submissions"],
                "averageAccuracy": avg_subj_acc,
            })
        subject_list.sort(key=lambda x: x["examsCount"], reverse=True)

        return success({
            "totalUsers": total_users,
            "totalStudents": total_students,
            "totalExamsGenerated": total_exams,
            "totalExamsCompleted": total_submissions,
            "totalRunbooks": total_runbooks,
            "averagePlatformScore": avg_score,
            "weeklyActivity": weekly_activity,
            "subjectBreakdown": subject_list[:6],
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def list_users():
    page, limit, offset = get_pagination_params()
    with get_session() as session:
        search = request.args.get("search", "").strip()
        admin_roles = ["ADMIN", "SUPER_ADMIN"]
        
        # Exclude administrative users (ADMIN, SUPER_ADMIN) so only platform end-users (Parents, Students, etc.) are listed
        query = session.query(User).outerjoin(Role).filter(
            or_(Role.role_name == None, ~Role.role_name.in_(admin_roles))
        )
        
        if search:
            search_pattern = f"%{search}%"
            student_user = aliased(User)
            student_role = aliased(Role)
            matching_child = exists().where(
                Student.parent_id == User.id,
                Student.id == student_user.id,
                student_user.role_id == student_role.id,
                or_(
                    student_user.name.ilike(search_pattern),
                    student_user.email.ilike(search_pattern),
                    student_role.role_name.ilike(search_pattern),
                ),
            )
            query = query.filter(or_(
                User.name.ilike(search_pattern),
                User.email.ilike(search_pattern),
                Role.role_name.ilike(search_pattern),
                matching_child,
            ))

        flat = request.args.get("flat", "").lower() in ["true", "1"]
        if flat:
            total = query.count()
            users = query.options(joinedload(User.role)).order_by(User.created_at.desc()).offset(offset).limit(limit).all()
            student_ids = [u.id for u in users]
            students_map = {
                s.id: s for s in session.query(Student).filter(Student.id.in_(student_ids)).all()
            } if student_ids else {}

            items = [
                {
                    "id": u.id,
                    "name": u.name or u.username or "User",
                    "username": u.username,
                    "email": u.email or "—",
                    "role": (u.role.role_name if u.role else "User").title(),
                    "roleName": (u.role.role_name if u.role else "USER").upper(),
                    "isActive": bool(u.is_active),
                    "status": "Active" if u.is_active else "Inactive",
                    "createdAt": u.created_at.isoformat() if u.created_at else None,
                    "classGrade": students_map[u.id].class_grade if u.id in students_map else None,
                    "targetBoard": students_map[u.id].target_board if u.id in students_map else None,
                    "avatar": students_map[u.id].avatar if u.id in students_map else None,
                }
                for u in users
            ]
            return success(paginated_response(items, total, page, limit))

        # Build the complete parent-child relationship before paginating top-level
        # rows. Student users are represented under their parent rather than as
        # duplicate standalone rows.
        all_users = query.order_by(User.created_at.desc()).all()
        students = session.query(Student).options(joinedload(Student.user)).order_by(
            Student.created_at.asc(), Student.id.asc()
        ).all()

        linked_students = {}
        student_user_ids = set()
        for student in students:
            if not student.user or student.id in student_user_ids:
                continue
            student_user_ids.add(student.id)
            is_active_val = bool(student.user.is_active) if student.user else True
            created_at_val = (student.user.created_at or student.created_at) if student.user else student.created_at
            linked_students.setdefault(student.parent_id, []).append({
                "id": student.id,
                "name": student.user.name or student.user.username or "Student",
                "username": student.user.username if student.user else "",
                "email": student.user.email or "",
                "classGrade": student.class_grade or "Class 10",
                "targetBoard": student.target_board or "CBSE",
                "schoolName": student.school_name or "",
                "avatar": student.avatar or "🧑‍🎓",
                "isActive": is_active_val,
                "status": "Active" if is_active_val else "Inactive",
                "createdAt": created_at_val.isoformat() if created_at_val else None,
                "role": "Student",
                "roleName": "STUDENT",
            })

        grouped_users = [user for user in all_users if user.id not in student_user_ids]
        total = len(grouped_users)
        users = grouped_users[offset:offset + limit]

        items = [
            {
                "id": u.id,
                "name": u.name or u.username or "User",
                "username": u.username,
                "email": u.email or "—",
                "role": (u.role.role_name if u.role else "User").title(),
                "roleName": (u.role.role_name if u.role else "USER").upper(),
                "isActive": bool(u.is_active),
                "status": "Active" if u.is_active else "Inactive",
                "createdAt": u.created_at.isoformat() if u.created_at else None,
                "linkedStudents": linked_students.get(u.id, []) if u.role and u.role.role_name.upper() == "PARENT" else None,
            }
            for u in users
        ]
        return success(paginated_response(items, total, page, limit))


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def update_user(user_id):
    payload = request.get_json(silent=True) or {}
    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            raise NotFoundError("User not found")

        if "name" in payload and payload["name"]:
            user.name = str(payload["name"]).strip()
        if "email" in payload:
            user.email = str(payload["email"]).strip()
        if "isActive" in payload:
            user.is_active = bool(payload["isActive"])
        if "role" in payload and payload["role"]:
            role = session.query(Role).filter(Role.role_name == str(payload["role"]).upper()).first()
            if not role:
                raise NotFoundError("Role not found")
            user.role = role

        # If user is a student, update student specific fields as well
        student = session.get(Student, user_id)
        if student:
            if "classGrade" in payload and payload["classGrade"]:
                student.class_grade = str(payload["classGrade"]).strip()
            if "targetBoard" in payload and payload["targetBoard"]:
                student.target_board = str(payload["targetBoard"]).strip()
            if "schoolName" in payload:
                student.school_name = str(payload["schoolName"]).strip()
            if "avatar" in payload and payload["avatar"]:
                student.avatar = str(payload["avatar"]).strip()

        session.commit()
        return success({
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "username": user.username,
            "isActive": user.is_active,
            "status": "Active" if user.is_active else "Inactive",
            "classGrade": student.class_grade if student else None,
            "targetBoard": student.target_board if student else None,
            "schoolName": student.school_name if student else None,
            "avatar": student.avatar if student else None,
            "role": user.role.role_name.title() if user.role else "User",
            "roleName": user.role.role_name.upper() if user.role else "USER",
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def delete_user(user_id):
    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            raise NotFoundError("User not found")
        if user.role and user.role.role_name.upper() in ["ADMIN", "SUPER_ADMIN"]:
            raise AppError("FORBIDDEN", "Admin accounts cannot be deleted from user management", 403)

        # If user is a Parent, also clean up all linked Student user accounts & student records
        linked_students = session.query(Student).filter(Student.parent_id == user.id).all()
        for st in linked_students:
            st_user = session.get(User, st.id)
            session.delete(st)
            if st_user:
                session.delete(st_user)

        session.delete(user)
        session.commit()
        return success({"deleted": True, "id": user_id})


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def list_students():
    page, limit, offset = get_pagination_params()
    with get_session() as session:
        total = session.query(Student).count()
        students = session.query(Student).order_by(Student.created_at.desc()).offset(offset).limit(limit).all()
        items = [student_to_child_account(s) for s in students]
        return success(paginated_response(items, total, page, limit))


@token_required
@roles_required("ADMIN", "SUPER_ADMIN", "PARENT")
def reset_quota(student_id):
    with get_session() as session:
        student = session.get(Student, student_id)
        if not student:
            raise NotFoundError("Student not found")
        if g.current_user_role == "PARENT" and student.parent_id != g.current_user_id:
            raise NotFoundError("Student not found")
        student.daily_exams_taken_today = 0
        student.last_exam_date = date.today()
        return success({"reset": True})


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def list_audit_logs():
    """Fetches paginated audit logs with optional filtering by action, user_id, or entity_type."""
    from flask import request
    from model.models import AuditLog

    page, limit, offset = get_pagination_params()
    action_filter = request.args.get("action")
    entity_filter = request.args.get("entityType") or request.args.get("entity_type")
    user_id_filter = request.args.get("userId") or request.args.get("user_id")

    with get_session() as session:
        query = session.query(AuditLog)
        if action_filter:
            query = query.filter(AuditLog.action.ilike(f"%{action_filter.strip()}%"))
        if entity_filter:
            query = query.filter(AuditLog.entity_type == entity_filter.strip().upper())
        if user_id_filter and str(user_id_filter).isdigit():
            query = query.filter(AuditLog.user_id == int(user_id_filter))

        total = query.count()
        logs = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()

        user_ids = {log.user_id for log in logs if log.user_id}
        user_map = {}
        if user_ids:
            users = session.query(User).filter(User.id.in_(user_ids)).all()
            user_map = {u.id: {"name": u.name, "username": u.username, "email": u.email} for u in users}

        items = [
            {
                "id": log.id,
                "userId": log.user_id,
                "userName": user_map.get(log.user_id, {}).get("name") if log.user_id else None,
                "userEmail": user_map.get(log.user_id, {}).get("email") if log.user_id else None,
                "action": log.action,
                "entityType": log.entity_type,
                "entityId": log.entity_id,
                "ipAddress": log.ip_address,
                "createdAt": f"{log.created_at.isoformat()}+05:30" if log.created_at else None,
                "createdAtFormatted": log.created_at.strftime("%d %b %Y, %I:%M:%S %p IST") if log.created_at else None,
            }
            for log in logs
        ]
        return success(paginated_response(items, total, page, limit))


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def list_test_submissions():
    """Fetches paginated student test submissions with filters using SP or ORM fallback."""
    from flask import request
    from sqlalchemy import text, or_
    import json

    page, limit, offset = get_pagination_params()
    search = request.args.get("search", "").strip()
    subject = request.args.get("subject", "").strip()
    board = request.args.get("board", "").strip()
    grade = request.args.get("classGrade") or request.args.get("grade", "").strip()

    with get_session() as session:
        try:
            # 1. Primary: Stored Procedure execution
            sp_res = session.execute(
                text("CALL sp_admin_get_test_submissions(:p_search, :p_subject, :p_board, :p_grade, :p_limit, :p_offset)"),
                {
                    "p_search": search or None,
                    "p_subject": subject or None,
                    "p_board": board or None,
                    "p_grade": grade or None,
                    "p_limit": limit,
                    "p_offset": offset,
                }
            ).mappings().all()

            total = 0
            items = []
            for row in sp_res:
                if total == 0 and "total_count" in row:
                    total = int(row["total_count"] or 0)

                sub_date = row.get("submitted_at")
                time_sec = int(row.get("time_taken_seconds") or 0)
                m, s = divmod(time_sec, 60)
                time_formatted = f"{m}m {s}s" if m > 0 else f"{s}s"

                items.append({
                    "submissionId": str(row.get("submission_id")),
                    "studentName": row.get("student_name") or "Student",
                    "studentEmail": row.get("student_email") or row.get("student_username") or "—",
                    "studentUsername": row.get("student_username"),
                    "classGrade": row.get("class_grade") or "—",
                    "targetBoard": row.get("target_board") or "—",
                    "examId": str(row.get("exam_id")),
                    "examTitle": row.get("exam_title") or "Mock Assessment",
                    "subject": (row.get("exam_subject") or "General").strip().title(),
                    "board": row.get("exam_board") or "—",
                    "difficulty": (row.get("exam_difficulty") or "medium").lower(),
                    "marksObtained": float(row.get("marks_obtained") or 0.0),
                    "totalMarks": int(row.get("total_marks") or 10),
                    "accuracyPercentage": float(row.get("accuracy_percentage") or 0.0),
                    "timeTakenSeconds": time_sec,
                    "timeTakenFormatted": time_formatted,
                    "submittedAt": sub_date.isoformat() if hasattr(sub_date, "isoformat") else str(sub_date) if sub_date else None,
                    "submittedAtFormatted": sub_date.strftime("%d %b %Y, %I:%M %p") if hasattr(sub_date, "strftime") else str(sub_date) if sub_date else None,
                })

            if total == 0 and items:
                total = len(items)

            res_data = paginated_response(items, total, page, limit)
            res_data["total"] = total
            return success(res_data)

        except Exception:
            # 2. Defensive Fallback to ORM
            query = session.query(
                ExamSubmission, Exam, Student, User
            ).join(
                Exam, ExamSubmission.exam_id == Exam.id
            ).join(
                Student, ExamSubmission.student_id == Student.id
            ).join(
                User, Student.id == User.id
            )

            if search:
                pattern = f"%{search}%"
                query = query.filter(or_(User.name.ilike(pattern), User.email.ilike(pattern), Exam.title.ilike(pattern)))
            if subject and subject.upper() != "ALL":
                query = query.filter(Exam.subject.ilike(subject))
            if board and board.upper() != "ALL":
                query = query.filter(Exam.board.ilike(board))
            if grade and grade.upper() != "ALL":
                query = query.filter(Student.class_grade.ilike(grade))

            total = query.count()
            rows = query.order_by(ExamSubmission.submitted_at.desc()).offset(offset).limit(limit).all()

            items = []
            for sub, ex, st, u in rows:
                time_sec = int(sub.time_taken_seconds or 0)
                m, s = divmod(time_sec, 60)
                time_formatted = f"{m}m {s}s" if m > 0 else f"{s}s"
                sub_date = sub.submitted_at
                items.append({
                    "submissionId": str(sub.id),
                    "studentName": u.name or u.username or "Student",
                    "studentEmail": u.email or u.username or "—",
                    "studentUsername": u.username,
                    "classGrade": st.class_grade or "—",
                    "targetBoard": st.target_board or "—",
                    "examId": str(ex.id),
                    "examTitle": ex.title or "Mock Assessment",
                    "subject": (ex.subject or "General").strip().title(),
                    "board": ex.board or "—",
                    "difficulty": (ex.difficulty or "medium").lower(),
                    "marksObtained": float(sub.marks_obtained or 0.0),
                    "totalMarks": int(sub.total_marks or 10),
                    "accuracyPercentage": float(sub.accuracy_percentage or 0.0),
                    "timeTakenSeconds": time_sec,
                    "timeTakenFormatted": time_formatted,
                    "submittedAt": sub_date.isoformat() if hasattr(sub_date, "isoformat") else str(sub_date) if sub_date else None,
                    "submittedAtFormatted": sub_date.strftime("%d %b %Y, %I:%M %p") if hasattr(sub_date, "strftime") else str(sub_date) if sub_date else None,
                })

            res_data = paginated_response(items, total, page, limit)
            res_data["total"] = total
            return success(res_data)


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def get_submission_details(submission_id):
    """Fetches full question-by-question answer sheet and diagnostic evaluation for a submission."""
    from sqlalchemy import text
    from model.models import QuestionEvaluation, Question, DiagnosticAnalysis
    import json

    with get_session() as session:
        try:
            # 1. Primary: Stored Procedure execution
            sp_res = session.execute(
                text("CALL sp_admin_get_submission_details(:p_submission_id)"),
                {"p_submission_id": str(submission_id)}
            ).mappings().all()

            questions = []
            diagnostic = None

            for r in sp_res:
                if diagnostic is None and r.get("overall_band"):
                    strengths = r.get("strengths")
                    areas = r.get("areas_to_improve")
                    if isinstance(strengths, str):
                        try:
                            strengths = json.loads(strengths)
                        except Exception:
                            pass
                    if isinstance(areas, str):
                        try:
                            areas = json.loads(areas)
                        except Exception:
                            pass

                    diagnostic = {
                        "overallBand": r.get("overall_band"),
                        "masteryScorePercentage": float(r.get("mastery_score_percentage") or 0.0),
                        "strengths": strengths or [],
                        "areasToImprove": areas or [],
                    }

                opts = r.get("options")
                if isinstance(opts, str):
                    try:
                        opts = json.loads(opts)
                    except Exception:
                        pass

                questions.append({
                    "questionNumber": r.get("question_number"),
                    "questionText": r.get("question_text"),
                    "options": opts or [],
                    "correctAnswer": r.get("correct_answer"),
                    "studentAnswer": r.get("student_answer"),
                    "isCorrect": bool(r.get("is_correct")),
                    "marksAwarded": float(r.get("marks_awarded") or 0.0),
                    "maxMarks": float(r.get("question_max_marks") or 1.0),
                    "explanation": r.get("explanation"),
                    "feedback": r.get("feedback"),
                    "timeSpentSeconds": int(r.get("time_spent_seconds") or 0),
                })

            if questions:
                return success({
                    "submissionId": str(submission_id),
                    "questions": questions,
                    "diagnostic": diagnostic,
                })
        except Exception:
            pass

        # 2. Defensive Fallback to ORM
        evals = session.query(QuestionEvaluation).filter(
            QuestionEvaluation.submission_id == str(submission_id)
        ).join(Question, QuestionEvaluation.question_id == Question.id).order_by(Question.question_number.asc()).all()

        diag = session.query(DiagnosticAnalysis).filter(
            DiagnosticAnalysis.submission_id == str(submission_id)
        ).first()

        diagnostic = None
        if diag:
            diagnostic = {
                "overallBand": diag.overall_band,
                "masteryScorePercentage": float(diag.mastery_score_percentage or 0.0),
                "strengths": diag.strengths or [],
                "areasToImprove": diag.areas_to_improve or [],
            }

        questions = []
        for qe in evals:
            q = qe.question
            questions.append({
                "questionNumber": q.question_number if q else 1,
                "questionText": q.question_text if q else "Question text unavailable",
                "options": q.options if q and q.options else [],
                "correctAnswer": q.correct_answer if q else "",
                "studentAnswer": qe.student_answer,
                "isCorrect": bool(qe.is_correct),
                "marksAwarded": float(qe.marks_awarded or 0.0),
                "maxMarks": float(q.marks or 1.0) if q else 1.0,
                "explanation": q.explanation if q else "",
                "feedback": qe.feedback,
                "timeSpentSeconds": int(qe.time_spent_seconds or 0),
            })

        return success({
            "submissionId": str(submission_id),
            "questions": questions,
            "diagnostic": diagnostic,
        })



