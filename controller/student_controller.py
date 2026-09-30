from flask import g, request

from database.dbConnection import get_session, engine
from helper.gamification_engine import calculate_and_sync_student_streak
from helper.mastery_engine import get_topic_mastery_map
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import roles_required
from model.models import Base, Student, ExamSubmission, LearningPathNode, StudentBadge, ScheduledExam, StudentWellbeingCheckin
from utils.errors import NotFoundError
from utils.response import success
from utils.serializers import student_to_child_account, submission_to_dict, learning_path_node_to_dict


@token_required
@roles_required("STUDENT")
def get_dashboard():
    """Consolidated Student Dashboard API:
    Returns Student Profile, Topic Mastery, Recent Exams, Learning Path, and Menu Permissions in ONE call.
    """
    with get_session() as session:
        student = session.get(Student, g.current_user_id)
        if not student:
            raise NotFoundError("Student not found")

        calculate_and_sync_student_streak(session, student)
        session.commit()

        from controller.auth_controller import get_page_access_for_role

        badge_ids = [r.badge_id for r in session.query(StudentBadge).filter(StudentBadge.student_id == student.id).all()]
        child_account = student_to_child_account(student, badge_ids)
        child_account["topicMastery"] = get_topic_mastery_map(session, student.id)

        from sqlalchemy.orm import joinedload
        recent = (
            session.query(ExamSubmission)
            .options(joinedload(ExamSubmission.exam))
            .filter(ExamSubmission.student_id == student.id)
            .order_by(ExamSubmission.submitted_at.desc())
            .limit(10)
            .all()
        )
        recent_exams = [submission_to_dict(s, include_details=False) for s in recent]

        nodes = session.query(LearningPathNode).filter(LearningPathNode.student_id == student.id).all()
        learning_nodes = [learning_path_node_to_dict(n) for n in nodes]

        page_access = get_page_access_for_role(session, "STUDENT")

        return success({
            "profile": child_account,
            "recentExams": recent_exams,
            "topicMastery": child_account["topicMastery"],
            "learningPath": learning_nodes,
            "pageAccess": page_access,
        })


@token_required
@roles_required("STUDENT")
def get_me():
    with get_session() as session:
        student = session.get(Student, g.current_user_id)
        if not student:
            raise NotFoundError("Student not found")
        calculate_and_sync_student_streak(session, student)
        session.commit()
        badge_ids = [r.badge_id for r in session.query(StudentBadge).filter(StudentBadge.student_id == student.id).all()]
        return success(student_to_child_account(student, badge_ids))


@token_required
@roles_required("STUDENT")
def my_overview():
    with get_session() as session:
        student = session.get(Student, g.current_user_id)
        if not student:
            raise NotFoundError("Student not found")
        calculate_and_sync_student_streak(session, student)
        session.commit()
        from sqlalchemy.orm import joinedload
        recent = (
            session.query(ExamSubmission)
            .options(joinedload(ExamSubmission.exam))
            .filter(ExamSubmission.student_id == student.id)
            .order_by(ExamSubmission.submitted_at.desc())
            .limit(10)
            .all()
        )
        return success({
            "child": student_to_child_account(student),
            "recentExams": [submission_to_dict(s, include_details=False) for s in recent],
            "topicMastery": get_topic_mastery_map(session, student.id),
        })


@token_required
@roles_required("STUDENT")
def my_learning_path():
    with get_session() as session:
        nodes = session.query(LearningPathNode).filter(LearningPathNode.student_id == g.current_user_id).all()
        return success([learning_path_node_to_dict(n) for n in nodes])


@token_required
@roles_required("STUDENT")
def get_assigned_exams():
    """Returns all pending/in-progress exams assigned by parent to this student."""
    with get_session() as session:
        assigned = (
            session.query(ScheduledExam)
            .filter(
                ScheduledExam.student_id == g.current_user_id,
                ScheduledExam.status.in_(["PENDING", "IN_PROGRESS"])
            )
            .order_by(ScheduledExam.created_at.desc())
            .all()
        )
        from controller.parent_controller import scheduled_exam_to_dict
        return success({"assignedExams": [scheduled_exam_to_dict(se) for se in assigned]})


@token_required
def submit_wellbeing_checkin():
    """Records student mental health, hobbies, support anchor, and pre-exam mindset."""
    try:
        Base.metadata.create_all(bind=engine, tables=[StudentWellbeingCheckin.__table__])
    except Exception:
        pass

    payload = request.get_json(silent=True) or {}
    student_id = payload.get("student_id") or getattr(g, "current_user_id", None)
    if not student_id:
        student_id = g.current_user_id

    mood = payload.get("mood", "")
    hobby = payload.get("hobby", "")
    hobby_detail = payload.get("hobby_detail", "")
    support_person = payload.get("support_person", "")
    exam_mindset = payload.get("exam_mindset", "")
    conversation_summary = payload.get("conversation_summary", "")
    exam_index = payload.get("exam_index", 0)
    raw_responses = payload.get("raw_responses", {})

    with get_session() as session:
        checkin = StudentWellbeingCheckin(
            student_id=student_id,
            mood=mood,
            hobby=hobby,
            hobby_detail=hobby_detail,
            support_person=support_person,
            exam_mindset=exam_mindset,
            conversation_summary=conversation_summary,
            raw_responses=raw_responses,
            exam_index=exam_index,
        )
        session.add(checkin)
        session.commit()
        return success({
            "message": "Wellbeing checkin recorded successfully",
            "checkinId": checkin.id,
            "recordedAt": checkin.created_at.isoformat() if checkin.created_at else None,
            "data": {
                "mood": mood,
                "hobby": hobby,
                "hobbyDetail": hobby_detail,
                "supportPerson": support_person,
                "examMindset": exam_mindset,
            }
        })


@token_required
def get_wellbeing_checkin():
    """Gets the latest wellbeing checkin and history for a student."""
    try:
        Base.metadata.create_all(bind=engine, tables=[StudentWellbeingCheckin.__table__])
    except Exception:
        pass

    student_id = request.args.get("student_id") or getattr(g, "current_user_id", None)
    if not student_id:
        student_id = g.current_user_id

    with get_session() as session:
        checkins = (
            session.query(StudentWellbeingCheckin)
            .filter(StudentWellbeingCheckin.student_id == student_id)
            .order_by(StudentWellbeingCheckin.created_at.desc())
            .limit(10)
            .all()
        )
        history = []
        for c in checkins:
            history.append({
                "id": c.id,
                "mood": c.mood,
                "hobby": c.hobby,
                "hobbyDetail": c.hobby_detail,
                "supportPerson": c.support_person,
                "examMindset": c.exam_mindset,
                "conversationSummary": c.conversation_summary,
                "examIndex": c.exam_index,
                "createdAt": c.created_at.isoformat() if c.created_at else None,
            })
        latest = history[0] if history else None
        return success({
            "studentId": student_id,
            "totalCheckins": len(history),
            "latest": latest,
            "history": history,
        })


def counselor_dialogue():
    """AI Child & Adolescent Mental Health Counselor dialogue API with LLM & class-calibration."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            from utils.security import decode_token
            token = auth_header.split(" ", 1)[1].strip()
            payload = decode_token(token)
            sub = payload.get("sub")
            g.current_user_id = int(sub) if str(sub).isdigit() else sub
            g.current_user_role = str(payload.get("role", "")).upper()
        except Exception:
            pass

    payload = request.get_json(silent=True) or {}
    student_name = payload.get("student_name", "Student")
    class_grade = payload.get("class_grade", "Class 7")
    board = payload.get("board", "CBSE")
    subject = payload.get("subject", "Mathematics")
    conversation_history = payload.get("conversation_history", [])
    previous_summary = payload.get("previous_summary")
    student_id = payload.get("student_id") or getattr(g, "current_user_id", None)

    if not previous_summary and student_id:
        try:
            with get_session() as session:
                last_checkin = (
                    session.query(StudentWellbeingCheckin)
                    .filter(StudentWellbeingCheckin.student_id == student_id)
                    .order_by(StudentWellbeingCheckin.created_at.desc())
                    .first()
                )
                if last_checkin:
                    count = session.query(StudentWellbeingCheckin).filter(StudentWellbeingCheckin.student_id == student_id).count()
                    previous_summary = {
                        "mood": last_checkin.mood,
                        "hobby": last_checkin.hobby_detail or last_checkin.hobby,
                        "support_person": last_checkin.support_person,
                        "exam_mindset": last_checkin.exam_mindset,
                        "checkin_number": count + 1
                    }
        except Exception:
            pass

    from helper.counselor_ai_engine import conduct_counselor_turn

    res = conduct_counselor_turn(
        student_name=student_name,
        class_grade=class_grade,
        board=board,
        subject=subject,
        conversation_history=conversation_history,
        previous_summary=previous_summary
    )
    return success(res)




