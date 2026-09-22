from utils.date_helper import now_ist
import json
import uuid

from flask import request, g
from sqlalchemy import text, func

from database.dbConnection import get_session
from helper.gamification_engine import calculate_and_sync_student_streak
from helper.mastery_engine import get_topic_mastery_map
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import roles_required, assert_owns_student
from datetime import datetime, timedelta
from model.models import Parent, Student, User, Role, ExamSubmission, LearningPathNode, StudentBadge, ScheduledExam, XPEvent
from utils.errors import AppError, NotFoundError
from utils.response import success
from utils.audit_helper import log_audit
from utils.security import hash_password
from utils.serializers import student_to_child_account, submission_to_dict, learning_path_node_to_dict
from utils.constants import BOARD_CLASS_MAPPING
from utils.validators import require_fields, validate_board, validate_class_grade, validate_board_class, validate_username, validate_email
from controller.email_controller import send_school_student_registered_email


def get_child_registration_options():
    """Fetches active boards and class grades directly from DB via Stored Procedure."""
    with get_session() as session:
        result = session.execute(
            text("CALL sp_get_child_registration_masters()")
        ).mappings().first()

        boards_data = []
        classes_data = []
        if result:
            raw_boards = result.get("boards")
            raw_classes = result.get("classes") or result.get("class_grades")
            if raw_boards:
                parsed_boards = json.loads(raw_boards) if isinstance(raw_boards, str) else raw_boards
                boards_data = [{"id": b["id"], "name": b["name"], "description": b.get("description", "")} for b in parsed_boards if isinstance(b, dict) and "id" in b and "name" in b]
            if raw_classes:
                parsed_classes = json.loads(raw_classes) if isinstance(raw_classes, str) else raw_classes
                classes_data = [{"id": c["id"], "name": c["name"]} for c in parsed_classes if isinstance(c, dict) and "id" in c and "name" in c]

        return success({
            "boards": boards_data,
            "classes": classes_data,
            "classGrades": classes_data,
            "boardClassesMap": BOARD_CLASS_MAPPING,
        })


def get_curriculum_options():
    """Fetches subjects, chapters, and topics mapped dynamically from the Database
    based on board and class_grade, or student_id.
    """
    board = request.args.get("board", "").strip()
    class_grade = request.args.get("classGrade", request.args.get("class_grade", "")).strip()
    student_id = request.args.get("studentId", request.args.get("student_id", "")).strip()

    with get_session() as session:
        # If student_id is provided, resolve student's board and class
        if student_id and (not board or not class_grade):
            try:
                student = session.get(Student, int(student_id))
                if student:
                    if not board and student.target_board:
                        board = student.target_board.strip()
                    if not class_grade and student.class_grade:
                        class_grade = student.class_grade.strip()
            except Exception as e:
                pass

        clean_class = class_grade.replace("Class ", "").strip() if class_grade else ""

        sql = text("""
            SELECT 
                s.id AS subject_id, s.subject_name,
                ch.id AS chapter_id, ch.chapter_name,
                t.id AS topic_id, t.topic_name
            FROM subject_master s
            JOIN board_master b ON s.board_id = b.id
            JOIN class_master c ON s.class_id = c.id
            LEFT JOIN chapter_master ch ON ch.subject_id = s.id AND ch.is_active = 1
            LEFT JOIN topic_master t ON t.chapter_id = ch.id AND t.is_active = 1
            WHERE s.is_active = 1
              AND (
                  :board = ''
                  OR LOWER(TRIM(b.board_name)) = LOWER(TRIM(:board))
                  OR LOWER(TRIM(b.board_name)) LIKE LOWER(TRIM(:board_like))
                  OR LOWER(TRIM(:board)) LIKE CONCAT('%', LOWER(TRIM(b.board_name)), '%')
              )
              AND (
                  :class_grade = ''
                  OR LOWER(TRIM(c.class_name)) = LOWER(TRIM(:class_grade))
                  OR LOWER(TRIM(c.class_name)) LIKE LOWER(TRIM(:class_like))
                  OR LOWER(TRIM(c.class_name)) = LOWER(TRIM(:clean_class))
                  OR LOWER(TRIM(:class_grade)) LIKE CONCAT('%', LOWER(TRIM(c.class_name)), '%')
              )
            ORDER BY s.subject_name, ch.id, t.id
        """)

        params = {
            "board": board,
            "board_like": f"%{board}%" if board else "",
            "class_grade": class_grade,
            "class_like": f"%{clean_class}%" if clean_class else "",
            "clean_class": clean_class,
        }

        rows = session.execute(sql, params).mappings().fetchall()

        # If no direct match found, fallback without board filter
        if not rows and class_grade:
            fallback_sql = text("""
                SELECT 
                    s.id AS subject_id, s.subject_name,
                    ch.id AS chapter_id, ch.chapter_name,
                    t.id AS topic_id, t.topic_name
                FROM subject_master s
                JOIN class_master c ON s.class_id = c.id
                LEFT JOIN chapter_master ch ON ch.subject_id = s.id AND ch.is_active = 1
                LEFT JOIN topic_master t ON t.chapter_id = ch.id AND t.is_active = 1
                WHERE s.is_active = 1
                  AND (
                      LOWER(TRIM(c.class_name)) = LOWER(TRIM(:class_grade))
                      OR LOWER(TRIM(c.class_name)) LIKE LOWER(TRIM(:class_like))
                      OR LOWER(TRIM(c.class_name)) = LOWER(TRIM(:clean_class))
                  )
                ORDER BY s.subject_name, ch.id, t.id
            """)
            rows = session.execute(fallback_sql, params).mappings().fetchall()

        # Build hierarchical structure
        subjects_dict = {}
        for r in rows:
            s_name = r["subject_name"].strip()
            if not s_name:
                continue
            if s_name not in subjects_dict:
                subjects_dict[s_name] = {
                    "id": r["subject_id"],
                    "name": s_name,
                    "chapters": {}
                }

            ch_id = r["chapter_id"]
            ch_name = r["chapter_name"]
            if ch_id and ch_name:
                ch_name = ch_name.strip()
                if ch_id not in subjects_dict[s_name]["chapters"]:
                    subjects_dict[s_name]["chapters"][ch_id] = {
                        "id": ch_id,
                        "name": ch_name,
                        "topics": []
                    }
                t_id = r["topic_id"]
                t_name = r["topic_name"]
                if t_id and t_name:
                    subjects_dict[s_name]["chapters"][ch_id]["topics"].append({
                        "id": t_id,
                        "name": t_name.strip()
                    })

        # Format into clean list
        subjects_list = []
        for s in subjects_dict.values():
            chap_list = []
            for ch in s["chapters"].values():
                chap_list.append(ch)
            subjects_list.append({
                "id": s["id"],
                "name": s["name"],
                "chapters": chap_list
            })

        # Fallback if still empty: distinct active subjects from database
        if not subjects_list:
            distinct_subs = session.execute(
                text("SELECT DISTINCT subject_name FROM subject_master WHERE is_active = 1 ORDER BY subject_name")
            ).fetchall()
            subjects_list = [{"id": idx + 1, "name": r[0], "chapters": []} for idx, r in enumerate(distinct_subs)]

        return success({
            "board": board,
            "classGrade": class_grade,
            "subjects": subjects_list,
        })


def _badge_ids_for(session, student_id: int) -> list[str]:
    return [
        sb.badge_id
        for sb in session.query(StudentBadge).filter(StudentBadge.student_id == student_id).all()
    ]


@token_required
@roles_required("PARENT")
def get_dashboard():
    """Consolidated Parent Dashboard API:
    Returns Parent Profile, Enriched Children (with Mastery & Recent Exams),
    Page Access (Menu Permissions), and Stats in ONE single round trip.
    """
    with get_session() as session:
        parent_user = session.get(User, g.current_user_id)
        if not parent_user:
            raise NotFoundError("Parent not found")

        children = (
            session.query(Student)
            .filter(Student.parent_id == g.current_user_id)
            .all()
        )

        all_recent_exams = []
        enriched_children = []

        for child in children:
            calculate_and_sync_student_streak(session, child)
            badge_ids = _badge_ids_for(session, child.id)
            child_dict = student_to_child_account(child, badge_ids)

            # Fetch Recent Exam Submissions for each child (sorted by most recent)
            submissions = (
                session.query(ExamSubmission)
                .filter(ExamSubmission.student_id == child.id)
                .order_by(ExamSubmission.submitted_at.desc())
                .limit(10)
                .all()
            )
            child_exams = [submission_to_dict(s) for s in submissions]
            child_dict["recentExams"] = child_exams
            all_recent_exams.extend(child_exams)

            # Topic Mastery Map directly from Mastery table
            child_dict["topicMastery"] = get_topic_mastery_map(session, child.id)

            enriched_children.append(child_dict)

        session.commit()

        # Sort all family exams globally by date
        all_recent_exams.sort(key=lambda x: x.get("submittedAt", ""), reverse=True)

        from controller.auth_controller import get_page_access_for_role
        # Dynamic Menu Permissions for PARENT role
        page_access = get_page_access_for_role(session, "PARENT")

        profile = {
            "id": parent_user.id,
            "name": parent_user.name,
            "username": parent_user.username,
            "email": parent_user.email,
            "role": "parent",
            "createdAt": parent_user.created_at.isoformat() if parent_user.created_at else None,
        }

        stats = {
            "totalChildren": len(children),
            "totalFamilyExams": len(all_recent_exams),
            "totalFamilyXP": sum(c.xp or 0 for c in children),
        }

        return success({
            "profile": profile,
            "children": enriched_children,
            "recentExams": all_recent_exams[:10],
            "pageAccess": page_access,
            "stats": stats,
        })


@token_required
@roles_required("PARENT")
def get_me():
    with get_session() as session:
        user = session.get(User, g.current_user_id)
        if not user:
            raise NotFoundError("User account not found")
        parent = session.get(Parent, g.current_user_id)
        if not parent:
            parent = Parent(id=user.id)
            session.add(parent)
            session.flush()
        return success({
            "id": user.id, "name": user.name, "email": user.email, "role": "parent",
            "createdAt": user.created_at.isoformat() if user.created_at else None,
        })


@token_required
@roles_required("PARENT")
def list_children():
    with get_session() as session:
        children = (
            session.query(Student)
            .filter(Student.parent_id == g.current_user_id)
            .all()
        )
        enriched = []
        for c in children:
            calculate_and_sync_student_streak(session, c)
            cd = student_to_child_account(c, _badge_ids_for(session, c.id))
            cd["topicMastery"] = get_topic_mastery_map(session, c.id)
            enriched.append(cd)
        session.commit()
        return success(enriched)


@token_required
@roles_required("PARENT")
def add_child():
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["name", "username", "classGrade", "targetBoard", "password"])

    username = payload["username"].strip()
    validate_username(username)

    password = payload["password"]
    password_hash = hash_password(password)
    name = payload["name"].strip()
    class_grade = payload["classGrade"].strip()
    target_board = payload["targetBoard"].strip()
    validate_board_class(target_board, class_grade)
    school_name = payload.get("schoolName", "").strip() or None
    school_email = payload.get("schoolEmail", "").strip() or None
    if school_email:
        validate_email(school_email)
    avatar = payload.get("avatar", "👦")
    
    with get_session() as session:
        # 1. Check global username uniqueness (case-insensitive)
        existing_user = session.query(User).filter(func.lower(User.username) == func.lower(username)).first()
        if existing_user:
            raise AppError("USERNAME_TAKEN", f"The username '{username}' is already taken. Please choose another username.", 409)

        # 2. Get parent user to assign parent's email to child
        parent_user = session.get(User, g.current_user_id)
        parent_email = parent_user.email if parent_user else None

        # 3. Get STUDENT role
        student_role = session.query(Role).filter(Role.role_name == "STUDENT").first()
        if not student_role:
            student_role = session.query(Role).filter(Role.id == 1).first()
        if not student_role:
            student_role = Role(role_name="STUDENT", is_active=True)
            session.add(student_role)
            session.flush()

        # 4. Create User for child
        child_user = User(
            name=name,
            username=username,
            email=parent_email,
            password_hash=password_hash,
            role_id=student_role.id,
            is_active=True,
            created_by=g.current_user_id,
        )
        session.add(child_user)
        session.flush()

        # 5. Create Student record
        student = Student(
            id=child_user.id,
            parent_id=g.current_user_id,
            avatar=avatar,
            class_grade=class_grade,
            target_board=target_board,
            school_name=school_name,
            school_email=school_email,
            xp=0,
            level=1,
            streak_days=0,
            total_exams_taken=0,
            average_score=0.0,
            daily_exams_taken_today=0,
        )
        session.add(student)
        session.flush()

        # Auto-assign active Mock Tests for this board and class
        from controller.mock_test_controller import auto_assign_mock_tests_for_new_student
        try:
            auto_assign_mock_tests_for_new_student(session, student)
        except Exception as e:
            from utils.logger import logger
            logger.warning(f"Auto-assign mock tests failed for student {student.id}: {e}")

        log_audit(
            session,
            action="CHILD_CREATED",
            user_id=g.current_user_id,
            entity_type="STUDENT_PROFILE",
            entity_id=str(student.id),
            request=request,
        )
        session.commit()

        # Send notification email to school if school_email provided
        if school_email:
            send_school_student_registered_email(
                to_school_email=school_email,
                student_name=name,
                class_grade=class_grade,
                target_board=target_board,
                school_name=school_name or "",
                parent_name=parent_user.name if parent_user else "",
                parent_email=parent_email or "",
            )

        return success(student_to_child_account(student, []), 201)


@token_required
@roles_required("PARENT")
def update_child(student_id):
    payload = request.get_json(force=True, silent=True) or {}
    s_id = int(student_id) if str(student_id).isdigit() else student_id

    with get_session() as session:
        student = assert_owns_student(session, s_id, g.current_user_id)

        new_class = payload.get("classGrade", student.class_grade)
        new_board = payload.get("targetBoard", student.target_board)
        if "classGrade" in payload or "targetBoard" in payload:
            validate_board_class(new_board, new_class)

        if "name" in payload and student.user:
            student.user.name = payload["name"]
        for field, attr in [
            ("avatar", "avatar"), ("classGrade", "class_grade"), ("targetBoard", "target_board"),
            ("schoolName", "school_name"), ("schoolEmail", "school_email"),
        ]:
            if field in payload:
                val = payload[field]
                if field == "schoolEmail" and val:
                    val = str(val).strip() or None
                    if val:
                        validate_email(val)
                elif field == "schoolName" and val:
                    val = str(val).strip() or None
                setattr(student, attr, val)

        log_audit(
            session,
            action="CHILD_UPDATED",
            user_id=g.current_user_id,
            entity_type="STUDENT_PROFILE",
            entity_id=str(student.id),
            request=request,
        )
        session.commit()

        return success(student_to_child_account(student, _badge_ids_for(session, student.id)))


@token_required
@roles_required("PARENT")
def delete_child(student_id):
    s_id = int(student_id) if str(student_id).isdigit() else student_id
    with get_session() as session:
        student = assert_owns_student(session, s_id, g.current_user_id)
        user = session.get(User, student.id)
        session.delete(student)
        if user:
            session.delete(user)
        log_audit(
            session,
            action="CHILD_DELETED",
            user_id=g.current_user_id,
            entity_type="STUDENT_PROFILE",
            entity_id=str(s_id),
            request=request,
        )
        session.commit()
        return success({"deleted": True})


@token_required
@roles_required("PARENT")
def child_overview(student_id):
    s_id = int(student_id) if str(student_id).isdigit() else student_id
    with get_session() as session:
        student = assert_owns_student(session, s_id, g.current_user_id)
        recent_submissions = (
            session.query(ExamSubmission)
            .filter(ExamSubmission.student_id == s_id)
            .order_by(ExamSubmission.submitted_at.desc())
            .limit(10)
            .all()
        )
        from helper.mastery_engine import get_topic_mastery_map

        return success({
            "child": student_to_child_account(student, _badge_ids_for(session, student.id)),
            "recentExams": [submission_to_dict(s) for s in recent_submissions],
            "topicMastery": get_topic_mastery_map(session, s_id),
        })


@token_required
@roles_required("PARENT")
def child_learning_path(student_id):
    s_id = int(student_id) if str(student_id).isdigit() else student_id
    with get_session() as session:
        assert_owns_student(session, s_id, g.current_user_id)
        nodes = session.query(LearningPathNode).filter(LearningPathNode.student_id == s_id).all()
        return success([learning_path_node_to_dict(n) for n in nodes])


def scheduled_exam_to_dict(se: ScheduledExam) -> dict:
    return {
        "id": se.id,
        "parentId": se.parent_id,
        "studentId": se.student_id,
        "studentName": se.student.user.name if se.student and se.student.user else "Student",
        "studentAvatar": se.student.avatar if se.student else "🧑‍🎓",
        "title": se.title,
        "subject": se.subject,
        "chapterTopic": se.chapter_topic,
        "board": se.board,
        "classGrade": se.class_grade,
        "difficulty": se.difficulty,
        "questionCount": se.question_count,
        "timeLimitMinutes": se.time_limit_minutes,
        "scheduledAt": se.scheduled_at.isoformat() if se.scheduled_at else None,
        "dueDate": se.due_date.isoformat() if se.due_date else None,
        "parentInstructions": se.parent_instructions,
        "status": se.status,
        "examId": se.exam_id,
        "submissionId": se.submission_id,
        "score": se.submission.marks_obtained if se.submission else None,
        "totalMarks": se.submission.total_marks if se.submission else None,
        "accuracy": float(se.submission.accuracy_percentage) if se.submission and se.submission.accuracy_percentage is not None else None,
        "createdAt": se.created_at.isoformat() if se.created_at else None,
    }


@token_required
@roles_required("PARENT")
def schedule_exam():
    """Parent schedules a customized exam for their child."""
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["studentId", "subject"])

    student_id = int(payload["studentId"])
    from utils.constants import normalize_subject
    from utils.validators import validate_subject
    subject = normalize_subject(str(payload["subject"]).strip())
    validate_subject(subject)
    chapter_topic = str(payload.get("chapterTopic", "")).strip() or None
    difficulty = str(payload.get("difficulty", "medium")).lower()
    if difficulty not in ["simple", "medium", "hard"]:
        difficulty = "medium"
    question_count = max(5, min(25, int(payload.get("questionCount", 10))))
    time_limit_minutes = max(5, min(60, int(payload.get("timeLimitMinutes", 15))))
    parent_instructions = str(payload.get("parentInstructions", "")).strip() or None

    scheduled_at_str = payload.get("scheduledAt")
    due_date_str = payload.get("dueDate")

    scheduled_at = None
    due_date = None
    if scheduled_at_str:
        try:
            scheduled_at = datetime.fromisoformat(scheduled_at_str.replace("Z", "+00:00"))
        except Exception:
            pass
    if due_date_str:
        try:
            due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00"))
        except Exception:
            pass

    with get_session() as session:
        student = assert_owns_student(session, student_id, g.current_user_id)
        student_name = student.user.name if student.user else "Student"

        title = payload.get("title") or f"{student_name}'s {subject} Assessment ({question_count} Questions)"

        scheduled_exam = ScheduledExam(
            id=str(uuid.uuid4()),
            parent_id=g.current_user_id,
            student_id=student.id,
            title=title,
            subject=subject,
            chapter_topic=chapter_topic,
            board=student.target_board,
            class_grade=student.class_grade,
            difficulty=difficulty,
            question_count=question_count,
            time_limit_minutes=time_limit_minutes,
            scheduled_at=scheduled_at,
            due_date=due_date,
            parent_instructions=parent_instructions,
            status="PENDING",
            created_at=now_ist(),
        )
        session.add(scheduled_exam)
        session.flush()

        # Terminal Log Banner for Parent Scheduling (Windows console safe)
        parent_user = session.get(User, g.current_user_id)
        parent_name = parent_user.name if parent_user else f"Parent #{g.current_user_id}"
        print("\n" + "=" * 78)
        print("[*] [PARENT EXAM SCHEDULED LOG]")
        print(f">> Assigned By : {parent_name} (Parent ID: {g.current_user_id})")
        print(f">> Assigned To : {student_name} (Class {student.class_grade} | {student.target_board})")
        print(f">> Subject     : {subject} (Topic: {chapter_topic or 'General Comprehensive'})")
        print(f">> Config      : {question_count} Questions | {time_limit_minutes} Mins | Difficulty: {difficulty.upper()}")
        print(f">> Due Date    : {due_date.strftime('%Y-%m-%d %H:%M') if due_date else 'No due date set'}")
        print(f">> Schedule ID : {scheduled_exam.id}")
        print("=" * 78 + "\n")

        # Send Real-Time Notification to Student
        from controller.notification_controller import create_notification
        create_notification(
            session=session,
            user_id=student.id,
            sender_id=g.current_user_id,
            notif_type="EXAM_ASSIGNED",
            title=f"New Exam Assigned by Parent 📝",
            message=f"Your parent scheduled an exam on '{subject}{' - ' + chapter_topic if chapter_topic else ''}' ({question_count} Marks, {difficulty.capitalize()}).",
            action_url="/arena",
            metadata_json={
                "scheduledExamId": scheduled_exam.id,
                "subject": subject,
                "chapterTopic": chapter_topic,
                "difficulty": difficulty,
                "questionCount": question_count,
            }
        )

        log_audit(
            session,
            action="EXAM_SCHEDULED_BY_PARENT",
            user_id=g.current_user_id,
            entity_type="SCHEDULED_EXAM",
            entity_id=str(scheduled_exam.id),
            request=request,
        )
        session.commit()

        return success(
            {"scheduledExam": scheduled_exam_to_dict(scheduled_exam)},
            201
        )


@token_required
@roles_required("PARENT")
def list_scheduled_exams():
    """List all scheduled exams created by the parent."""
    with get_session() as session:
        exams = (
            session.query(ScheduledExam)
            .filter(ScheduledExam.parent_id == g.current_user_id)
            .order_by(ScheduledExam.created_at.desc())
            .all()
        )
        return success({"scheduledExams": [scheduled_exam_to_dict(se) for se in exams]})


@token_required
@roles_required("PARENT")
def delete_scheduled_exam(scheduled_exam_id: str):
    """Delete or cancel a scheduled exam."""
    with get_session() as session:
        se = session.query(ScheduledExam).filter(
            ScheduledExam.id == scheduled_exam_id,
            ScheduledExam.parent_id == g.current_user_id
        ).first()
        if not se:
            raise NotFoundError("Scheduled exam not found")

        session.delete(se)
        session.commit()
        return success({"deleted": True})


@token_required
def get_student_activity_log():
    """
    Returns unified chronological activity timeline (Exams, Mind-breaks/Fun Zone, Badges, Assigned Tasks)
    for a student.
    Accessible by PARENT (for their children) and STUDENT (for themselves).
    """
    current_user_id = g.current_user_id
    current_role = getattr(g, "current_user_role", None) or getattr(g, "current_role", "")
    current_role = str(current_role).upper()

    student_id_param = request.args.get("studentId") or request.args.get("student_id")
    days_param = int(request.args.get("days", 7))
    days_param = max(1, min(60, days_param))

    with get_session() as session:
        if current_role == "STUDENT" or (not student_id_param and session.get(Student, current_user_id)):
            target_student_id = current_user_id
            student = session.get(Student, target_student_id)
            if not student:
                raise NotFoundError("Student record not found")
        else:
            # Parent role
            if not student_id_param:
                parent_obj = session.get(Parent, current_user_id)
                parent_id = parent_obj.id if parent_obj else current_user_id

                students = session.query(Student).filter(Student.parent_id == parent_id).all()
                if not students:
                    parent_user = session.get(User, current_user_id)
                    if parent_user and parent_user.students:
                        students = parent_user.students

                if not students:
                    return success({
                        "summary": {
                            "studentId": "",
                            "studentName": "",
                            "studentAvatar": "👦",
                            "classGrade": "",
                            "targetBoard": "",
                            "currentStreakDays": 0,
                            "totalExams": 0,
                            "totalMindBreaks": 0,
                            "totalStudyMinutes": 0,
                            "totalMindBreakMinutes": 0,
                            "totalXpEarned": 0,
                            "totalActivities": 0,
                        },
                        "activities": [],
                    })
                student = students[0]
                target_student_id = student.id
            else:
                target_student_id = int(student_id_param)
                student = assert_owns_student(session, target_student_id, current_user_id)

        student_name = student.user.name if student and student.user else "Student"
        now = now_ist()
        cutoff_date = now - timedelta(days=days_param)

        # 1. Query ScheduledExams to identify parent-assigned submissions
        scheduled_sub_ids = set(
            r[0] for r in session.query(ScheduledExam.submission_id)
            .filter(
                ScheduledExam.student_id == target_student_id,
                ScheduledExam.submission_id.isnot(None)
            ).all()
        )

        # 2. Query Exam Submissions
        exams = (
            session.query(ExamSubmission)
            .filter(
                ExamSubmission.student_id == target_student_id,
                ExamSubmission.submitted_at >= cutoff_date
            )
            .order_by(ExamSubmission.submitted_at.desc())
            .all()
        )

        # 3. Query XP Events (Fun Zone games, Practice rewards, Badges)
        xp_events = (
            session.query(XPEvent)
            .filter(
                XPEvent.student_id == target_student_id,
                XPEvent.created_at >= cutoff_date
            )
            .order_by(XPEvent.created_at.desc())
            .all()
        )

        activities = []

        def get_formatted_date(dt):
            if not dt:
                return "Recent"
            if dt.date() == now.date():
                return "Today"
            elif dt.date() == (now - timedelta(days=1)).date():
                return "Yesterday"
            else:
                return dt.strftime("%d %b %Y")

        def get_formatted_time(dt):
            if not dt:
                return ""
            time_str = dt.strftime("%I:%M %p")
            return time_str.lstrip("0")

        # Process Exams
        for ex in exams:
            sub_name = ex.exam.subject if (ex.exam and ex.exam.subject) else "Practice Exam"
            title_text = ex.exam.title if (ex.exam and ex.exam.title) else f"{sub_name} Practice Test"
            is_parent_assigned = ex.id in scheduled_sub_ids
            
            marks_obt = float(ex.marks_obtained) if ex.marks_obtained is not None else 0.0
            tot_marks = ex.total_marks or (ex.exam.total_marks if ex.exam else 15)
            
            if ex.accuracy_percentage is not None:
                acc = round(float(ex.accuracy_percentage), 1)
            else:
                acc = round((marks_obt / tot_marks) * 100, 1) if tot_marks > 0 else 0.0

            time_secs = ex.time_taken_seconds or 0
            dur_mins = max(1, round(time_secs / 60))
            xp_earned = max(0, min(100, round(acc)))

            dt = ex.submitted_at or now

            activities.append({
                "id": f"exam_{ex.id}",
                "type": "parent_assigned_exam" if is_parent_assigned else "exam",
                "category": "Parent Assignment" if is_parent_assigned else "Practice Test",
                "title": title_text,
                "subtitle": f"Scored {marks_obt:g}/{tot_marks} ({acc}%) in {time_secs // 60}m {time_secs % 60}s",
                "subject": sub_name,
                "difficulty": ex.exam.difficulty if ex.exam else "medium",
                "scorePct": acc,
                "marksObtained": marks_obt,
                "totalMarks": tot_marks,
                "durationMinutes": dur_mins,
                "durationSeconds": time_secs,
                "xpEarned": xp_earned,
                "timestamp": dt.isoformat(),
                "formattedDate": get_formatted_date(dt),
                "formattedTime": get_formatted_time(dt),
            })

        # Process XP Events (Mind breaks / Fun Zone / Badges)
        for xpe in xp_events:
            reason = xpe.reason or ""
            if reason.startswith("exam:"):
                continue

            dt = xpe.created_at or now
            is_badge = reason.startswith("badge:")
            is_streak = "streak" in reason.lower() and not any(k in reason.lower() for k in ["math", "memory", "scramble", "game", "smile", "duel"])

            if is_badge:
                clean_badge_name = reason.replace("badge:", "").replace("badge-", "").replace("_", " ").title()
                activities.append({
                    "id": f"badge_xp_{xpe.id}",
                    "type": "badge",
                    "category": "Milestone Trophy",
                    "title": f"Milestone: {clean_badge_name}",
                    "subtitle": f"Unlocked {clean_badge_name} trophy badge",
                    "subject": "Achievement",
                    "scorePct": None,
                    "marksObtained": None,
                    "totalMarks": None,
                    "durationMinutes": 0,
                    "durationSeconds": 0,
                    "xpEarned": 0,
                    "timestamp": dt.isoformat(),
                    "formattedDate": get_formatted_date(dt),
                    "formattedTime": get_formatted_time(dt),
                })
            elif is_streak:
                activities.append({
                    "id": f"streak_{xpe.id}",
                    "type": "badge",
                    "category": "Consistency Milestone",
                    "title": "Daily Practice Streak Active",
                    "subtitle": "Daily study continuity discipline",
                    "subject": "Learning Discipline",
                    "scorePct": None,
                    "marksObtained": None,
                    "totalMarks": None,
                    "durationMinutes": 0,
                    "durationSeconds": 0,
                    "xpEarned": 0,
                    "timestamp": dt.isoformat(),
                    "formattedDate": get_formatted_date(dt),
                    "formattedTime": get_formatted_time(dt),
                })
            else:
                # All other game/break activities (Speed Math, Memory Matcher, Word Scramble, Brain Break Smile, etc.)
                clean_game_name = reason.replace("game:", "").replace("fun:", "").replace("XP", "").replace("_", " ").strip().title()
                activities.append({
                    "id": f"fun_{xpe.id}",
                    "type": "mind_break",
                    "category": "Fun Zone Mind-Break",
                    "title": f"Mind-Break: {clean_game_name or 'Brain Boost'}",
                    "subtitle": f"Completed {clean_game_name or 'Cognitive'} relaxation session",
                    "subject": "Mind Refreshment",
                    "scorePct": None,
                    "marksObtained": None,
                    "totalMarks": None,
                    "durationMinutes": 5,
                    "durationSeconds": 300,
                    "xpEarned": xpe.amount or 15,
                    "timestamp": dt.isoformat(),
                    "formattedDate": get_formatted_date(dt),
                    "formattedTime": get_formatted_time(dt),
                })

        # Sort all activities newest first
        activities.sort(key=lambda x: x["timestamp"], reverse=True)

        # Aggregate Metrics
        total_exams = sum(1 for a in activities if a["type"] in ["exam", "parent_assigned_exam"])
        total_mind_breaks = sum(1 for a in activities if a["type"] == "mind_break")
        total_study_mins = sum((a.get("durationMinutes") or 0) for a in activities if a["type"] in ["exam", "parent_assigned_exam"])
        total_break_mins = sum((a.get("durationMinutes") or 0) for a in activities if a["type"] == "mind_break")
        total_xp = sum((a.get("xpEarned") or 0) for a in activities)

        summary_payload = {
            "studentId": str(target_student_id),
            "studentName": student_name,
            "studentAvatar": student.avatar or "👦",
            "classGrade": student.class_grade or "",
            "targetBoard": student.target_board or "",
            "currentStreakDays": student.streak_days or 0,
            "totalExams": total_exams,
            "totalMindBreaks": total_mind_breaks,
            "totalStudyMinutes": total_study_mins,
            "totalMindBreakMinutes": total_break_mins,
            "totalXpEarned": total_xp,
            "totalActivities": len(activities),
        }

        return success({
            "summary": summary_payload,
            "activities": activities,
        })

