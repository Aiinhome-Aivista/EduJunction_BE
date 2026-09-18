from utils.date_helper import now_ist
"""Misconception tracking (master prompt §18). Records what an incorrect
answer suggests the student misunderstood, and closes the loop when later
performance on the same topic improves."""
from datetime import datetime

from sqlalchemy.orm import Session

from database import graph_db
from model.models import Misconception


def record_misconceptions_from_evaluations(session: Session, student_id: str, evaluations: list[dict]):
    for ev in evaluations:
        if ev["isCorrect"] or not ev.get("misconceptionIdentified"):
            continue

        existing = (
            session.query(Misconception)
            .filter(
                Misconception.student_id == student_id,
                Misconception.topic == ev["topic"],
                Misconception.description == ev["misconceptionIdentified"],
                Misconception.status != "RESOLVED",
            )
            .one_or_none()
        )
        if existing:
            existing.evidence = f"Repeated on question: {ev['questionText'][:200]}"
            existing.updated_at = now_ist()
            # Escalate severity on repeat occurrences
            if existing.severity == "LOW":
                existing.severity = "MEDIUM"
            elif existing.severity == "MEDIUM":
                existing.severity = "HIGH"
        else:
            session.add(
                Misconception(
                    student_id=student_id,
                    topic=ev["topic"],
                    description=ev["misconceptionIdentified"],
                    evidence=f"First observed on question: {ev['questionText'][:200]}",
                    severity="MEDIUM",
                    status="OPEN",
                )
            )
            graph_db.upsert_misconception_edge(student_id, ev["topic"], ev["misconceptionIdentified"], "MEDIUM")

    # Mark previously OPEN/IMPROVING misconceptions as IMPROVING when the
    # student answers correctly on the same topic in this submission.
    correct_topics = {ev["topic"] for ev in evaluations if ev["isCorrect"]}
    if correct_topics:
        open_rows = (
            session.query(Misconception)
            .filter(
                Misconception.student_id == student_id,
                Misconception.topic.in_(correct_topics),
                Misconception.status == "OPEN",
            )
            .all()
        )
        for row in open_rows:
            row.status = "IMPROVING"
            row.updated_at = now_ist()

    session.flush()
