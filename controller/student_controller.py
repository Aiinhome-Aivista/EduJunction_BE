from flask import g

from database.dbConnection import get_session
from helper.gamification_engine import calculate_and_sync_student_streak
from helper.mastery_engine import get_topic_mastery_map
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import roles_required
from model.models import Student, ExamSubmission, LearningPathNode, StudentBadge, ScheduledExam
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

        page_access = get_page_access_for_role(session, "STUDENT", student.id)

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
@roles_required("STUDENT")
def complete_onboarding():
    """Completes student onboarding after Google registration or initial sign-in by setting username, board, and class."""
    from flask import request
    from sqlalchemy import func
    from model.models import User
    from utils.errors import AppError
    from utils.validators import validate_username, validate_board_class

    payload = request.get_json(force=True, silent=True) or {}
    target_board = (payload.get("targetBoard") or payload.get("target_board") or payload.get("board") or "").strip()
    class_grade = (payload.get("classGrade") or payload.get("class_grade") or payload.get("class") or "").strip()
    provided_username = (payload.get("username") or "").strip()
    school_name = (payload.get("schoolName") or payload.get("school_name") or "").strip() or None

    if not target_board or not class_grade:
        raise AppError("MISSING_DATA", "Please select your Board and Class / Grade to continue.", 400)

    validate_board_class(target_board, class_grade)

    with get_session() as session:
        student = session.get(Student, g.current_user_id)
        if not student:
            raise NotFoundError("Student not found")

        user = session.get(User, g.current_user_id)
        if not user:
            raise NotFoundError("User not found")

        # Update username if provided and changed
        if provided_username and provided_username.lower() != user.username.lower():
            validate_username(provided_username)
            existing_user = session.query(User).filter(
                func.lower(User.username) == func.lower(provided_username),
                User.id != user.id
            ).first()
            if existing_user:
                raise AppError("USERNAME_TAKEN", f"The username '{provided_username}' is already taken. Please choose another username.", 409)
            user.username = provided_username

        student.target_board = target_board
        student.class_grade = class_grade
        if school_name:
            student.school_name = school_name

        # Auto-assign active Mock Tests for this board and class
        from controller.mock_test_controller import auto_assign_mock_tests_for_new_student
        try:
            auto_assign_mock_tests_for_new_student(session, student)
        except Exception as e:
            from utils.logger import logger
            logger.warning(f"Auto-assign mock tests failed for student {student.id}: {e}")

        session.commit()

        badge_ids = [r.badge_id for r in session.query(StudentBadge).filter(StudentBadge.student_id == student.id).all()]
        child_account = student_to_child_account(student, badge_ids)
        child_account["isOnboarded"] = True

        return success({
            "profile": child_account,
            "isOnboarded": True,
            "message": "Profile setup complete! Welcome to EduJunction."
        }, message="Profile setup complete! Welcome to EduJunction.")



