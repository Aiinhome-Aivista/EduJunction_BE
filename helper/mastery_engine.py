from utils.date_helper import now_ist
"""Student topic mastery tracking (master prompt §19). Upserts per-topic
rows and always increments attempt/correct counters rather than overwriting
history."""
from datetime import datetime

from sqlalchemy.orm import Session

from database import graph_db
from model.models import Mastery
from utils.config import config


def _status_for_score(score: float) -> str:
    adv = config.MASTERY_THRESHOLD_ADVANCED or 85.0
    prof = config.MASTERY_THRESHOLD_PROFICIENT or 70.0
    dev = config.MASTERY_THRESHOLD_DEVELOPING or 50.0
    if score >= adv:
        return "MASTERED"
    if score >= prof:
        return "DEVELOPING"
    if score >= dev:
        return "LEARNING"
    return "CRITICAL_GAP"


def recalculate_student_mastery_from_evaluations(session: Session, student_id: int):
    """Computes authentic topic mastery scores directly from all question evaluations for this student."""
    from collections import defaultdict
    from model.models import ExamSubmission, QuestionEvaluation, Question

    topic_stats = defaultdict(lambda: {"awarded": 0, "total": 0, "attempts": 0, "correct": 0})
    
    subs = session.query(ExamSubmission).filter(ExamSubmission.student_id == student_id).all()
    for sub in subs:
        evals = session.query(QuestionEvaluation).filter(QuestionEvaluation.submission_id == sub.id).all()
        for ev in evals:
            q = session.get(Question, ev.question_id)
            if not q or not q.topic:
                continue
            topic = q.topic.strip()
            marks_possible = q.marks or 1
            marks_awarded = ev.marks_awarded or (marks_possible if ev.is_correct else 0)
            topic_stats[topic]["awarded"] += marks_awarded
            topic_stats[topic]["total"] += marks_possible
            topic_stats[topic]["attempts"] += 1
            if ev.is_correct:
                topic_stats[topic]["correct"] += 1

    for topic, data in topic_stats.items():
        pct = round((data["awarded"] / data["total"]) * 100, 2) if data["total"] > 0 else 0
        status = _status_for_score(pct)
        
        row = session.query(Mastery).filter(
            Mastery.student_id == student_id, Mastery.topic == topic
        ).one_or_none()
        
        if row is None:
            row = Mastery(
                student_id=student_id,
                topic=topic,
                mastery_score=pct,
                confidence=pct,
                attempt_count=data["attempts"],
                correct_count=data["correct"],
                status=status,
                last_assessed_at=now_ist(),
            )
            session.add(row)
        else:
            row.mastery_score = pct
            row.confidence = pct
            row.attempt_count = data["attempts"]
            row.correct_count = data["correct"]
            row.status = status
            row.last_assessed_at = now_ist()
            
        graph_db.upsert_mastery_edge(str(student_id), topic, float(pct))

    session.flush()


def update_mastery_from_insights(session: Session, student_id: str, k_graph_insights: list[dict]):
    """Calculates and updates topic mastery from actual student question evaluations."""
    try:
        recalculate_student_mastery_from_evaluations(session, int(student_id))
    except Exception:
        pass


def get_topic_mastery_map(session: Session, student_id: str) -> dict[str, float]:
    """Fast indexed lookup of topic mastery. Only calculates if empty."""
    sid = int(student_id) if isinstance(student_id, str) and student_id.isdigit() else student_id
    rows = session.query(Mastery).filter(Mastery.student_id == sid).all()
    if not rows:
        try:
            recalculate_student_mastery_from_evaluations(session, int(sid))
            rows = session.query(Mastery).filter(Mastery.student_id == sid).all()
        except Exception:
            pass
    return {row.topic: float(row.mastery_score) for row in rows}
