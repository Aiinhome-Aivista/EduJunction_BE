from utils.date_helper import now_ist
"""XP, badges, and leaderboard. Ported from the frontend's original
App.tsx `handleExamComplete` / `handleAwardXP` — the key difference is that
here it runs server-side against persisted data, so the client can no longer
compute its own XP (master prompt §23, and see docs/FRONTEND_BACKEND_MAPPING.md
§2.5 for why the original client-side version was unsafe to trust)."""
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from model.models import Student, Badge, StudentBadge, XPEvent, ExamSubmission
from utils.constants import BADGE_IDS


def calculate_and_sync_student_streak(session: Session, student: Student) -> int:
    """Calculates student streak based on distinct consecutive exam submission calendar dates (IST)
    and synchronizes student.streak_days and student.last_exam_date."""
    today = now_ist().date()
    submissions = (
        session.query(ExamSubmission.submitted_at)
        .filter(ExamSubmission.student_id == student.id)
        .order_by(ExamSubmission.submitted_at.desc())
        .all()
    )
    if not submissions:
        student.streak_days = 0
        return 0

    distinct_dates = sorted(
        {sub.submitted_at.date() for sub in submissions if sub.submitted_at},
        reverse=True
    )
    if not distinct_dates:
        student.streak_days = 0
        return 0

    student.last_exam_date = distinct_dates[0]

    streak = 0
    most_recent = distinct_dates[0]
    if most_recent == today:
        current_check = today
    elif most_recent == today - timedelta(days=1):
        current_check = today - timedelta(days=1)
    else:
        # Most recent exam was before yesterday -> streak is 0
        student.streak_days = 0
        return 0

    for d in distinct_dates:
        if d == current_check:
            streak += 1
            current_check = current_check - timedelta(days=1)
        elif d < current_check:
            break

    student.streak_days = streak
    return streak


def compute_exam_xp(
    marks_obtained: float,
    total_marks: float,
    time_taken_seconds: int = 0,
    streak_days: int = 0,
) -> int:
    """Canonical EduPoints (XP) Calculation Rules:
    1. Correct Answers: 1% = 1 XP (up to 100 XP base score)
    2. Perfect 10/10 Bonus: +50 XP for scoring 100% full marks with zero errors
    3. Daily Streak Power: +30 XP bonus for active consecutive test streak (>= 1 day)
    4. Velocity Sprint: +25 XP speed bonus for finishing accurate sprints (>= 70%) in <= 6 mins (360s)
    """
    if not total_marks or total_marks <= 0:
        return 0

    percentage = (float(marks_obtained) / float(total_marks)) * 100
    base_xp = max(0, min(100, round(percentage)))

    # Perfect Score Bonus (+50 XP for full marks)
    perfect_bonus = 50 if percentage >= 99.9 else 0

    # Daily Streak Power (+30 XP if active streak >= 1 day)
    streak_bonus = 30 if streak_days >= 1 else 0

    # Velocity Sprint Speed Bonus (+25 XP if >= 70% accuracy in <= 6 mins / 360s)
    speed_bonus = 25 if (0 < time_taken_seconds <= 360 and percentage >= 70) else 0

    return base_xp + perfect_bonus + streak_bonus + speed_bonus


def award_xp(session: Session, student: Student, amount: int, reason: str) -> Student:
    current_xp = student.xp if student.xp is not None else 0
    student.xp = current_xp + amount
    student.level = (student.xp // 250) + 1
    session.add(XPEvent(id=str(uuid.uuid4()), student_id=student.id, amount=amount, reason=reason))
    session.flush()
    return student


def evaluate_badge_unlocks(
    session: Session,
    student: Student,
    marks_obtained: int,
    time_taken_seconds: int,
    difficulty: str,
) -> list[str]:
    """Returns newly-unlocked badge ids (empty if none). Ported unlock rules
    from App.tsx's `handleExamComplete`.
    Badges are status/achievement indicators only and award 0 XP."""
    existing_ids = {
        row.badge_id
        for row in session.query(StudentBadge).filter(StudentBadge.student_id == student.id).all()
    }

    to_unlock = {BADGE_IDS["PIONEER"]}
    if marks_obtained == 10:
        to_unlock.add(BADGE_IDS["PERFECT_10"])
    if time_taken_seconds < 360 and marks_obtained >= 8:
        to_unlock.add(BADGE_IDS["SPEED_DEMON"])
    if (student.streak_days or 0) + 1 >= 3:
        to_unlock.add(BADGE_IDS["STREAK_3"])
    if (student.streak_days or 0) + 1 >= 7:
        to_unlock.add(BADGE_IDS["STREAK_7"])
    if difficulty == "hard" and marks_obtained >= 9:
        to_unlock.add(BADGE_IDS["OLYMPIAD_THINKER"])

    newly_unlocked = [bid for bid in to_unlock if bid not in existing_ids]

    for badge_id in newly_unlocked:
        badge = session.get(Badge, badge_id)
        if badge is None:
            continue  # badge not seeded — skip rather than fail the whole submission
        session.add(StudentBadge(student_id=student.id, badge_id=badge_id, unlocked_at=now_ist()))
        # Badge unlocks award 0 XP in the Simple XP system

    session.flush()
    return newly_unlocked


def get_leaderboard(
    session: Session,
    period: str = "all_time",
    board: str = None,
    class_grade: str = None,
    limit: int = 500,
) -> list[dict]:
    """period: daily | weekly | monthly | all_time.
    Ranks students within the same batch (Target Board & Class Grade) or globally.
    Multi-dimensional ranking tie-breaker: XP -> Average Score -> Total Exams -> Streak -> Badges.
    """
    from sqlalchemy import func
    query = session.query(Student)
    if board and str(board).lower() != "all":
        query = query.filter(func.lower(Student.target_board) == func.lower(str(board).strip()))
    if class_grade and str(class_grade).lower() != "all":
        query = query.filter(func.lower(Student.class_grade) == func.lower(str(class_grade).strip()))

    students = query.all()

    if period == "all_time":
        scored = [(s, s.xp or 0) for s in students]
    else:
        window_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period, 3650)
        since = now_ist() - timedelta(days=window_days)
        scored = []
        for s in students:
            window_xp = (
                session.query(XPEvent)
                .filter(XPEvent.student_id == s.id, XPEvent.created_at >= since)
                .all()
            )
            scored.append((s, sum(e.amount for e in window_xp)))

    # Compute badge counts for tie-breaking
    student_badge_map = {}
    for s in students:
        cnt = session.query(StudentBadge).filter(StudentBadge.student_id == s.id).count()
        student_badge_map[s.id] = cnt

    # Multi-dimensional ranking (Batch Cohort aware)
    scored.sort(
        key=lambda pair: (
            pair[1],                                      # 1. XP
            float(pair[0].average_score or 0),           # 2. Average Accuracy / Score
            int(pair[0].total_exams_taken or 0),         # 3. Exams / Sprints Completed
            int(pair[0].streak_days or 0),               # 4. Active Daily Streak
            student_badge_map.get(pair[0].id, 0),        # 5. Badges Unlocked
            int(pair[0].level or 1),                     # 6. Academic Level
        ),
        reverse=True,
    )

    leaderboard = []
    for rank, (student, points) in enumerate(scored[:limit], start=1):
        leaderboard.append(
            {
                "rank": rank,
                "studentId": student.id,
                "studentName": student.user.name if student.user else "Student",
                "avatar": student.avatar,
                "classGrade": student.class_grade,
                "targetBoard": student.target_board,
                "schoolName": student.school_name,
                "xp": points,
                "level": student.level,
                "averageScore": float(student.average_score or 0),
                "examsCompleted": student.total_exams_taken,
                "streakDays": student.streak_days,
                "badgesCount": student_badge_map.get(student.id, 0),
            }
        )
    return leaderboard
