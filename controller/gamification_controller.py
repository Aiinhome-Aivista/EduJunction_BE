from flask import request, g

from database.dbConnection import get_session
from helper.gamification_engine import award_xp
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import assert_owns_student
from model.models import Badge, Student
from utils.errors import ValidationError
from utils.response import success
from utils.serializers import badge_to_dict
from utils.validators import require_fields


def list_badges():
    """Public catalog read — badge definitions aren't sensitive."""
    with get_session() as session:
        badges = session.query(Badge).all()
        return success([badge_to_dict(b) for b in badges])


@token_required
def award_xp_route():
    """Backs the frontend's Fun Zone mini-games (`onAwardXP`). The amount is
    client-reported with strict server-side configured caps per game:
      - Speed Math Duel: max 45 XP
      - Science Word Scramble: max 25 XP
      - Memory Matcher: max 20 XP
      - Brain Break Smile / Anecdotes: max 5 XP
    """
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["studentId", "amount", "reason"])

    amount = int(payload["amount"])
    reason = str(payload["reason"])[:190]
    reason_lower = reason.lower()

    if "speed math" in reason_lower or "duel" in reason_lower:
        max_allowed = 45
    elif "scramble" in reason_lower:
        max_allowed = 25
    elif "memory" in reason_lower:
        max_allowed = 20
    elif "smile" in reason_lower or "break" in reason_lower:
        max_allowed = 5
    else:
        max_allowed = 45

    if amount <= 0:
        raise ValidationError("XP award amount must be greater than 0")

    # Enforce maximum XP cap for the activity
    amount = min(amount, max_allowed)

    with get_session() as session:
        if g.current_user_role == "STUDENT":
            if payload["studentId"] != g.current_user_id:
                raise ValidationError("Students may only award XP to themselves")
            student = session.get(Student, g.current_user_id)
        else:
            student = assert_owns_student(session, payload["studentId"], g.current_user_id)

        award_xp(session, student, amount, reason)
        return success({"xp": student.xp, "level": student.level})

