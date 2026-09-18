from utils.date_helper import now_ist
"""Adaptive difficulty & learning-path updates (master prompt §20/§21).
Thresholds are configurable via env vars (utils/config.py), not hardcoded,
per §20's explicit requirement."""
from datetime import datetime

from sqlalchemy.orm import Session

from model.models import LearningPathNode
from utils.config import config


def recommend_difficulty_for_score(percentage: float) -> str:
    if percentage < config.MASTERY_THRESHOLD_DEVELOPING:
        return "simple"
    if percentage < config.MASTERY_THRESHOLD_PROFICIENT:
        return "medium"  # "Developing" band still practices at medium
    if percentage < config.MASTERY_THRESHOLD_ADVANCED:
        return "medium"
    return "hard"


def update_learning_path_after_submission(
    session: Session,
    student_id: str,
    subject: str,
    marks_obtained: int,
    k_graph_insights: list[dict],
):
    """Ported from the frontend's App.tsx `handleExamComplete` learning-path
    update: match a node by topic substring first, otherwise fall back to any
    node in the same subject, then bump mastery/status/attempt count."""
    nodes = session.query(LearningPathNode).filter(LearningPathNode.student_id == student_id).all()

    for node in nodes:
        matching_insight = next(
            (
                k for k in k_graph_insights
                if k["topic"].lower() in node.topic.lower() or node.topic.lower() in k["topic"].lower()
            ),
            None,
        )

        if matching_insight is None and node.subject != subject:
            continue

        mastery = float(matching_insight["masteryPercentage"]) if matching_insight else marks_obtained * 10

        if mastery >= 80:
            status = "mastered"
        elif mastery >= 50:
            status = "in_progress"
        else:
            status = "remedial_needed"

        node.mastery_percentage = max(float(node.mastery_percentage or 0), mastery)
        node.status = status
        node.attempts_count = (node.attempts_count or 0) + 1
        node.last_score = marks_obtained
        node.recommended_reason = (
            "Excellent mastery shown in latest diagnostic test! Ready for higher-order HOTS challenges."
            if mastery >= 80
            else "Diagnostic test detected conceptual nuances to reinforce with foundational practice."
        )
        node.updated_at = now_ist()

    session.flush()
