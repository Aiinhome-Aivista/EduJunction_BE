from utils.date_helper import now_ist
import uuid
from datetime import datetime, timedelta
from flask import g, request

from database.dbConnection import get_session
from middleware.authMiddleware import token_required
from model.models import Notification, User, ScheduledExam
from utils.errors import NotFoundError
from utils.response import success


def create_notification(
    session,
    user_id: int,
    sender_id: int | None,
    notif_type: str,
    title: str,
    message: str,
    action_url: str | None = None,
    metadata_json: dict | None = None,
) -> Notification:
    """Helper to insert a notification into the DB."""
    notif = Notification(
        id=str(uuid.uuid4()),
        user_id=user_id,
        sender_id=sender_id,
        type=notif_type,
        title=title,
        message=message,
        action_url=action_url,
        metadata_json=metadata_json,
        is_read=False,
        created_at=now_ist(),
    )
    session.add(notif)
    session.flush()
    return notif


def notification_to_dict(notif: Notification, status_map: dict | None = None) -> dict:
    meta = dict(notif.metadata_json or {})
    seid = meta.get("scheduledExamId")
    
    if status_map and seid in status_map:
        meta["status"] = status_map[seid]["status"]
        if status_map[seid].get("submissionId"):
            meta["submissionId"] = status_map[seid]["submissionId"]
        if status_map[seid].get("examId"):
            meta["examId"] = status_map[seid]["examId"]
    elif not meta.get("status"):
        if notif.type in ("SCHEDULED_EXAM_COMPLETED", "EXAM_SUBMITTED"):
            meta["status"] = "SUBMITTED"
        elif notif.type == "EXAM_ASSIGNED":
            meta["status"] = "PENDING"

    return {
        "id": notif.id,
        "userId": notif.user_id,
        "senderId": notif.sender_id,
        "type": notif.type,
        "title": notif.title,
        "message": notif.message,
        "actionUrl": notif.action_url,
        "metadata": meta,
        "isRead": bool(notif.is_read),
        "createdAt": notif.created_at.isoformat() if notif.created_at else None,
    }


def sync_due_date_alerts(session, user_id: int):
    """
    Automatically checks for pending scheduled exams with due dates and triggers:
    1. 'Due in 24h' reminder for BOTH student and parent if due_date <= now + 24h and still pending.
    2. 'Overdue' alert for BOTH student and parent if due_date < now and still pending.
    
    Strict Rule: If NO due_date was provided (due_date is None), NO reminder or overdue alert is generated.
    """
    now = now_ist()
    # Query pending scheduled exams where the current user is either the parent or the student
    pending_scheduled = (
        session.query(ScheduledExam)
        .filter(
            (ScheduledExam.parent_id == user_id) | (ScheduledExam.student_id == user_id),
            ScheduledExam.status == "PENDING",
            ScheduledExam.due_date.isnot(None)
        )
        .all()
    )

    if not pending_scheduled:
        return

    for se in pending_scheduled:
        if not se.due_date:
            continue

        student_user = session.get(User, se.student_id)
        student_name = student_user.name if student_user else "Student"
        due_dt = se.due_date
        due_str = due_dt.strftime("%d %b, %I:%M %p")
        diff = due_dt - now

        # Case 1: OVERDUE ALERT (Due date has passed & exam is still pending)
        if diff < timedelta(seconds=0):
            # 1a. Student Overdue Alert
            found_st_overdue = any(
                n.metadata_json and n.metadata_json.get("scheduledExamId") == str(se.id)
                for n in session.query(Notification).filter(
                    Notification.user_id == se.student_id,
                    Notification.type == "EXAM_OVERDUE"
                ).all()
            )
            if not found_st_overdue:
                create_notification(
                    session=session,
                    user_id=se.student_id,
                    sender_id=se.parent_id,
                    notif_type="EXAM_OVERDUE",
                    title=f"⚠️ Exam Overdue: {se.subject}",
                    message=f"Your parent-assigned {se.subject} exam was due on {due_str}. Please complete it as soon as possible!",
                    action_url="/arena",
                    metadata_json={
                        "scheduledExamId": str(se.id),
                        "subject": se.subject,
                        "dueDate": se.due_date.isoformat(),
                        "status": "OVERDUE",
                    }
                )

            # 1b. Parent Overdue Alert
            if se.parent_id:
                found_pr_overdue = any(
                    n.metadata_json and n.metadata_json.get("scheduledExamId") == str(se.id)
                    for n in session.query(Notification).filter(
                        Notification.user_id == se.parent_id,
                        Notification.type == "EXAM_OVERDUE_PARENT"
                    ).all()
                )
                if not found_pr_overdue:
                    create_notification(
                        session=session,
                        user_id=se.parent_id,
                        sender_id=se.student_id,
                        notif_type="EXAM_OVERDUE_PARENT",
                        title=f"⚠️ Overdue Alert: {student_name}'s {se.subject} Exam",
                        message=f"{student_name}'s {se.subject} exam was due on {due_str} and has not been submitted yet.",
                        action_url="/schedule",
                        metadata_json={
                            "scheduledExamId": str(se.id),
                            "studentId": se.student_id,
                            "studentName": student_name,
                            "subject": se.subject,
                            "dueDate": se.due_date.isoformat(),
                            "status": "OVERDUE",
                        }
                    )

        # Case 2: DUE IN 24 HOURS REMINDER (Within 24 hours of deadline & not overdue)
        elif diff <= timedelta(hours=24):
            # 2a. Student 24h Reminder
            found_st_24h = any(
                n.metadata_json and n.metadata_json.get("scheduledExamId") == str(se.id)
                for n in session.query(Notification).filter(
                    Notification.user_id == se.student_id,
                    Notification.type == "EXAM_DUE_SOON"
                ).all()
            )
            if not found_st_24h:
                create_notification(
                    session=session,
                    user_id=se.student_id,
                    sender_id=se.parent_id,
                    notif_type="EXAM_DUE_SOON",
                    title=f"⏰ Due in 24h: {se.subject} Exam",
                    message=f"Reminder: Your parent-assigned {se.subject} sprint is due by {due_str}. Don't forget to take it!",
                    action_url="/arena",
                    metadata_json={
                        "scheduledExamId": str(se.id),
                        "subject": se.subject,
                        "dueDate": se.due_date.isoformat(),
                        "status": "DUE_SOON",
                    }
                )

            # 2b. Parent 24h Reminder
            if se.parent_id:
                found_pr_24h = any(
                    n.metadata_json and n.metadata_json.get("scheduledExamId") == str(se.id)
                    for n in session.query(Notification).filter(
                        Notification.user_id == se.parent_id,
                        Notification.type == "EXAM_DUE_SOON_PARENT"
                    ).all()
                )
                if not found_pr_24h:
                    create_notification(
                        session=session,
                        user_id=se.parent_id,
                        sender_id=se.student_id,
                        notif_type="EXAM_DUE_SOON_PARENT",
                        title=f"⏰ Due in 24h: {student_name}'s {se.subject} Exam",
                        message=f"Reminder: {student_name}'s {se.subject} assessment is due by {due_str} (Pending submission).",
                        action_url="/schedule",
                        metadata_json={
                            "scheduledExamId": str(se.id),
                            "studentId": se.student_id,
                            "studentName": student_name,
                            "subject": se.subject,
                            "dueDate": se.due_date.isoformat(),
                            "status": "DUE_SOON",
                        }
                    )

    session.flush()


@token_required
def get_notifications():
    """Returns recent notifications and unread count for current user."""
    user_id = g.current_user_id
    with get_session() as session:
        # Automatically sync due date reminders & overdue alerts
        try:
            sync_due_date_alerts(session, user_id)
            session.commit()
        except Exception as e:
            session.rollback()

        notifs = (
            session.query(Notification)
            .filter(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .limit(50)
            .all()
        )
        unread_count = (
            session.query(Notification)
            .filter(Notification.user_id == user_id, Notification.is_read == False)
            .count()
        )

        # Batch lookup scheduled exams to enrich live status
        scheduled_exam_ids = []
        for n in notifs:
            if n.metadata_json and isinstance(n.metadata_json, dict):
                seid = n.metadata_json.get("scheduledExamId")
                if seid:
                    scheduled_exam_ids.append(seid)

        status_map = {}
        if scheduled_exam_ids:
            sched_records = (
                session.query(ScheduledExam)
                .filter(ScheduledExam.id.in_(scheduled_exam_ids))
                .all()
            )
            for s in sched_records:
                status_map[s.id] = {
                    "status": s.status or "PENDING",
                    "submissionId": str(s.submission_id) if s.submission_id else None,
                    "examId": str(s.exam_id) if s.exam_id else None,
                }

        return success({
            "notifications": [notification_to_dict(n, status_map) for n in notifs],
            "unreadCount": unread_count,
        })


@token_required
def mark_as_read(notification_id: str):
    """Mark a single notification as read."""
    user_id = g.current_user_id
    with get_session() as session:
        notif = session.query(Notification).filter(
            Notification.id == notification_id,
            Notification.user_id == user_id
        ).first()
        if not notif:
            raise NotFoundError("Notification not found")

        notif.is_read = True
        session.flush()

        unread_count = (
            session.query(Notification)
            .filter(Notification.user_id == user_id, Notification.is_read == False)
            .count()
        )
        return success({
            "notification": notification_to_dict(notif),
            "unreadCount": unread_count,
        })


@token_required
def mark_all_as_read():
    """Mark all notifications as read for the logged in user."""
    user_id = g.current_user_id
    with get_session() as session:
        session.query(Notification).filter(
            Notification.user_id == user_id,
            Notification.is_read == False
        ).update({"is_read": True}, synchronize_session=False)

        return success({"unreadCount": 0})
