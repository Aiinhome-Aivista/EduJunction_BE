from flask import g

from database.dbConnection import get_session
from helper.mastery_engine import get_topic_mastery_map
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import roles_required
from model.models import Student, Misconception
from utils.errors import NotFoundError
from utils.response import success
from utils.serializers import student_to_child_account, misconception_to_dict


def _assert_teacher_owns_student(session, student_id: str, teacher_id: str) -> Student:
    student = session.get(Student, student_id)
    if not student or student.teacher_id != teacher_id:
        raise NotFoundError("Student not found")
    return student


@token_required
@roles_required("TEACHER")
def my_students():
    with get_session() as session:
        students = session.query(Student).filter(Student.teacher_id == g.current_user_id).all()
        return success([student_to_child_account(s) for s in students])


@token_required
@roles_required("TEACHER")
def student_performance(student_id):
    with get_session() as session:
        student = _assert_teacher_owns_student(session, student_id, g.current_user_id)
        return success(student_to_child_account(student))


@token_required
@roles_required("TEACHER")
def student_mastery(student_id):
    with get_session() as session:
        _assert_teacher_owns_student(session, student_id, g.current_user_id)
        return success(get_topic_mastery_map(session, student_id))


@token_required
@roles_required("TEACHER")
def student_diagnostics(student_id):
    with get_session() as session:
        _assert_teacher_owns_student(session, student_id, g.current_user_id)
        rows = session.query(Misconception).filter(Misconception.student_id == student_id).all()
        return success([misconception_to_dict(m) for m in rows])

