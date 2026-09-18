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

        recent = (
            session.query(ExamSubmission)
            .filter(ExamSubmission.student_id == student.id)
            .order_by(ExamSubmission.submitted_at.desc())
            .limit(10)
            .all()
        )
        recent_exams = [submission_to_dict(s) for s in recent]

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
        recent = (
            session.query(ExamSubmission)
            .filter(ExamSubmission.student_id == student.id)
            .order_by(ExamSubmission.submitted_at.desc())
            .limit(10)
            .all()
        )
        return success({
            "child": student_to_child_account(student),
            "recentExams": [submission_to_dict(s) for s in recent],
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


