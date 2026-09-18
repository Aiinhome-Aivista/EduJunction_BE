"""Lightweight recommendation helper (master prompt §22). Derives a short
list of suggested next actions from mastery + misconception state — used by
the dashboard aggregation endpoint alongside the AI-generated diagnostic
roadmap (which already covers the primary recommendation)."""
from sqlalchemy.orm import Session

from model.models import Mastery, Misconception


def recommend_next_actions(session: Session, student_id: str, limit: int = 5) -> list[str]:
    actions = []

    critical_topics = (
        session.query(Mastery)
        .filter(Mastery.student_id == student_id, Mastery.status == "CRITICAL_GAP")
        .order_by(Mastery.mastery_score.asc())
        .limit(3)
        .all()
    )
    for row in critical_topics:
        actions.append(f"Review concept fundamentals: {row.topic}")

    open_misconceptions = (
        session.query(Misconception)
        .filter(Misconception.student_id == student_id, Misconception.status == "OPEN")
        .order_by(Misconception.severity.desc())
        .limit(3)
        .all()
    )
    for row in open_misconceptions:
        actions.append(f"Targeted practice for: {row.topic} ({row.description})")

    mastered_topics = (
        session.query(Mastery)
        .filter(Mastery.student_id == student_id, Mastery.status == "MASTERED")
        .limit(2)
        .all()
    )
    for row in mastered_topics:
        actions.append(f"Attempt HOTS/Olympiad-level questions in: {row.topic}")

    if not actions:
        actions.append("Take a diagnostic exam to generate your first mastery profile.")

    return actions[:limit]
