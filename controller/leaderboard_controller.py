from flask import request

from database.dbConnection import get_session
from helper.gamification_engine import get_leaderboard
from utils.errors import ValidationError
from utils.response import success

VALID_PERIODS = {"daily", "weekly", "monthly", "all_time"}


def leaderboard():
    period = request.args.get("period", "all_time")
    board = request.args.get("board")
    class_grade = request.args.get("classGrade") or request.args.get("class")
    if period not in VALID_PERIODS:
        raise ValidationError(f"period must be one of {sorted(VALID_PERIODS)}")

    with get_session() as session:
        return success(get_leaderboard(session, period=period, board=board, class_grade=class_grade))

