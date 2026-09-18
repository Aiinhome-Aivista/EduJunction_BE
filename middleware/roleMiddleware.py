"""Role-based access control. Always stacked *under* @token_required so
g.current_user_role is already populated."""
from functools import wraps

from flask import g

from utils.errors import ForbiddenError


def roles_required(*allowed_roles):
    normalized_allowed = {str(r).strip().upper() for r in allowed_roles}

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = str(getattr(g, "current_user_role", "")).strip().upper()
            if role not in normalized_allowed:
                raise ForbiddenError(f"This action requires one of: {', '.join(allowed_roles)}")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def assert_owns_student(session, student_id, parent_user_id):
    """Object-level authorization: a parent may only touch their own children."""
    from model.models import Student
    from utils.errors import ForbiddenError, NotFoundError

    s_id = int(student_id) if str(student_id).isdigit() else student_id
    p_id = int(parent_user_id) if str(parent_user_id).isdigit() else parent_user_id

    student = session.get(Student, s_id)
    if not student:
        raise NotFoundError("Student not found")
    if student.parent_id != p_id:
        raise ForbiddenError("You do not have access to this student")
    return student
