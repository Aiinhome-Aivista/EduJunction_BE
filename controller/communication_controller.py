from utils.date_helper import now_ist
import secrets
import uuid
from datetime import datetime, timedelta

from flask import request, g

from database.dbConnection import get_session
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import roles_required, assert_owns_student
from model.models import Teacher, Conversation, Message, SharedDossier, ExamSubmission, PTMSchedule, Student, User, Mastery
from utils.errors import NotFoundError, ValidationError
from utils.response import success
from utils.serializers import submission_to_dict
from utils.validators import require_fields



def _teacher_to_dict(teacher: Teacher) -> dict:
    user = getattr(teacher, "user", None)
    return {
        "id": teacher.id,
        "name": user.name if user else "",
        "role": teacher.role_title,
        "subject": teacher.subject,
        "schoolName": teacher.school_name,
        "email": user.email if user else "",
        "phone": teacher.phone,
        "verified": bool(teacher.verified),
    }


def _message_to_dict(message: Message) -> dict:
    return {
        "id": message.id,
        "conversationId": message.conversation_id,
        "senderRole": message.sender_role,
        "senderId": message.sender_id,
        "message": message.message,
        "timestamp": message.created_at.isoformat(),
        "attachedSubmissionId": message.attached_submission_id,
        "actionItems": message.action_items or [],
        "status": message.status,
    }


def _dossier_to_dict(d: SharedDossier) -> dict:
    student_user = d.student.user if d.student and d.student.user else None
    parent_user = d.parent.user if d.parent and d.parent.user else None
    return {
        "id": d.id,
        "studentId": d.student_id,
        "childId": str(d.student_id),
        "childName": student_user.name if student_user else "Student",
        "parentName": parent_user.name if parent_user else "Parent",
        "shareToken": d.share_token,
        "createdAt": d.created_at.isoformat(),
        "expiresAt": d.expires_at.isoformat(),
        "notes": d.notes,
        "recipients": d.recipients,
        "includedSubmissionsCount": d.included_submissions_count,
        "viewCount": getattr(d, 'view_count', 0) or 0,
        "lastViewedAt": d.last_viewed_at.isoformat() if getattr(d, 'last_viewed_at', None) else None,
        "status": d.status,
    }


@token_required
def list_teachers():
    with get_session() as session:
        teachers = session.query(Teacher).all()
        return success([_teacher_to_dict(t) for t in teachers])


@token_required
@roles_required("PARENT")
def list_conversations():
    with get_session() as session:
        conversations = session.query(Conversation).filter(Conversation.parent_id == g.current_user_id).all()
        return success([
            {
                "id": c.id, "teacherId": c.teacher_id, "studentId": c.student_id,
                "createdAt": c.created_at.isoformat(),
                "messages": [_message_to_dict(m) for m in c.messages],
            }
            for c in conversations
        ])


@token_required
def get_conversation(conversation_id):
    with get_session() as session:
        conversation = session.get(Conversation, conversation_id)
        if not conversation:
            raise NotFoundError("Conversation not found")
        if g.current_user_role == "PARENT" and conversation.parent_id != g.current_user_id:
            raise NotFoundError("Conversation not found")
        if g.current_user_role == "TEACHER" and conversation.teacher_id != g.current_user_id:
            raise NotFoundError("Conversation not found")
        return success([_message_to_dict(m) for m in conversation.messages])


@token_required
@roles_required("PARENT")
def create_or_get_conversation():
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["teacherId", "studentId"])

    teacher_id = int(payload["teacherId"]) if str(payload["teacherId"]).isdigit() else payload["teacherId"]
    student_id = int(payload["studentId"]) if str(payload["studentId"]).isdigit() else payload["studentId"]

    with get_session() as session:
        assert_owns_student(session, student_id, g.current_user_id)
        teacher = session.get(Teacher, teacher_id)
        if not teacher:
            raise NotFoundError("Teacher not found")

        conversation = (
            session.query(Conversation)
            .filter(
                Conversation.parent_id == g.current_user_id,
                Conversation.teacher_id == teacher_id,
                Conversation.student_id == student_id,
            )
            .one_or_none()
        )
        if not conversation:
            conversation = Conversation(
                id=str(uuid.uuid4()), parent_id=g.current_user_id,
                teacher_id=teacher_id, student_id=student_id,
            )
            session.add(conversation)
            session.flush()
        return success({"id": conversation.id}, 201)


@token_required
def send_message(conversation_id):
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["message"])

    with get_session() as session:
        conversation = session.get(Conversation, conversation_id)
        if not conversation:
            raise NotFoundError("Conversation not found")

        if g.current_user_role == "PARENT":
            if conversation.parent_id != g.current_user_id:
                raise NotFoundError("Conversation not found")
            sender_role = "parent"
        elif g.current_user_role == "TEACHER":
            if conversation.teacher_id != g.current_user_id:
                raise NotFoundError("Conversation not found")
            sender_role = "teacher"
        else:
            raise ValidationError("Only parents or teachers may send messages")

        message = Message(
            id=str(uuid.uuid4()), conversation_id=conversation_id, sender_role=sender_role,
            sender_id=g.current_user_id, message=payload["message"],
            attached_submission_id=payload.get("attachedSubmissionId"),
            action_items=payload.get("actionItems"), status="sent",
        )
        session.add(message)
        session.flush()
        return success(_message_to_dict(message), 201)


@token_required
def mark_message_read(message_id):
    with get_session() as session:
        message = session.get(Message, message_id)
        if not message:
            raise NotFoundError("Message not found")
        message.status = "read"
        return success(_message_to_dict(message))


@token_required
@roles_required("PARENT")
def create_dossier():
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["studentId", "recipients"])

    student_id = int(payload["studentId"]) if str(payload["studentId"]).isdigit() else payload["studentId"]

    with get_session() as session:
        student = assert_owns_student(session, student_id, g.current_user_id)
        submissions_count = session.query(ExamSubmission).filter(ExamSubmission.student_id == student.id).count()

        dossier = SharedDossier(
            id=str(uuid.uuid4()), student_id=student.id, parent_id=g.current_user_id,
            share_token=f"ACU-SHARE-{secrets.token_hex(4).upper()}",
            notes=payload.get("notes", ""), recipients=payload["recipients"],
            included_submissions_count=submissions_count, status="active",
            created_at=now_ist(), expires_at=now_ist() + timedelta(days=30),
        )
        session.add(dossier)
        session.flush()
        return success(_dossier_to_dict(dossier), 201)


@token_required
@roles_required("PARENT")
def list_dossiers():
    with get_session() as session:
        dossiers = session.query(SharedDossier).filter(SharedDossier.parent_id == g.current_user_id).all()
        return success([_dossier_to_dict(d) for d in dossiers])


def get_public_dossier(share_token):
    with get_session() as session:
        dossier = (
            session.query(SharedDossier)
            .filter(SharedDossier.share_token == share_token)
            .one_or_none()
        )
        if not dossier:
            raise NotFoundError("Academic dossier not found or link has expired")
        if dossier.expires_at and dossier.expires_at < now_ist():
            raise NotFoundError("This academic dossier share link has expired")

        student = session.get(Student, dossier.student_id)
        if not student:
            raise NotFoundError("Student record not found")

        student_user = session.get(User, student.id)
        parent_user = session.get(User, dossier.parent_id)

        submissions = (
            session.query(ExamSubmission)
            .filter(ExamSubmission.student_id == student.id)
            .order_by(ExamSubmission.submitted_at.desc())
            .limit(10)
            .all()
        )

        mastery_rows = (
            session.query(Mastery)
            .filter(Mastery.student_id == str(student.id))
            .all()
        )
        topic_mastery = {m.topic: float(m.mastery_score) for m in mastery_rows}

        # Increment view count
        dossier.view_count = (getattr(dossier, 'view_count', 0) or 0) + 1
        dossier.last_viewed_at = now_ist()
        session.flush()

        return success({
            "dossier": _dossier_to_dict(dossier),
            "student": {
                "id": student.id,
                "name": student_user.name if student_user else "Student",
                "avatar": student.avatar,
                "classGrade": student.class_grade,
                "targetBoard": student.target_board,
                "schoolName": student.school_name,
                "totalExamsTaken": student.total_exams_taken,
                "averageScore": float(student.average_score or 0),
                "streakDays": student.streak_days,
                "xp": student.xp,
                "level": student.level,
            },
            "parent": {
                "name": parent_user.name if parent_user else "Parent",
                "email": parent_user.email if parent_user else "",
            },
            "recentSubmissions": [submission_to_dict(s) for s in submissions],
            "topicMastery": topic_mastery,
        })


@token_required
@roles_required("PARENT")
def delete_dossier(dossier_id):
    with get_session() as session:
        dossier = session.get(SharedDossier, dossier_id)
        if not dossier:
            raise NotFoundError("Academic dossier not found")
        if dossier.parent_id != g.current_user_id:
            raise ValidationError("You may only revoke dossiers created by your account")
        
        session.delete(dossier)
        session.flush()
        return success({"deletedId": dossier_id, "message": "Academic dossier revoked successfully"})


@token_required
@roles_required("PARENT")
def preview_student_dossier(student_id):
    sid = int(student_id) if str(student_id).isdigit() else student_id
    with get_session() as session:
        student = assert_owns_student(session, sid, g.current_user_id)
        submissions = (
            session.query(ExamSubmission)
            .filter(ExamSubmission.student_id == student.id)
            .order_by(ExamSubmission.submitted_at.desc())
            .limit(5)
            .all()
        )
        mastery_rows = session.query(Mastery).filter(Mastery.student_id == str(student.id)).all()
        topic_mastery = {m.topic: float(m.mastery_score) for m in mastery_rows}

        return success({
            "studentId": student.id,
            "name": student.user.name if student.user else "Student",
            "avatar": student.avatar,
            "classGrade": student.class_grade,
            "targetBoard": student.target_board,
            "totalExamsTaken": student.total_exams_taken,
            "averageScore": float(student.average_score or 0),
            "topicMastery": topic_mastery,
            "recentExamsCount": len(submissions),
        })


def _ptm_to_dict(ptm: PTMSchedule) -> dict:
    teacher_user = ptm.teacher.user if ptm.teacher and ptm.teacher.user else None
    student_user = ptm.student.user if ptm.student and ptm.student.user else None
    return {
        "id": ptm.id,
        "parentId": ptm.parent_id,
        "teacherId": ptm.teacher_id,
        "teacherName": teacher_user.name if teacher_user else "Teacher",
        "studentId": ptm.student_id,
        "studentName": student_user.name if student_user else "Student",
        "scheduledAt": ptm.scheduled_at.isoformat(),
        "topic": ptm.topic,
        "meetingLink": ptm.meeting_link or f"https://meet.google.com/acu-ptm-{ptm.id[:8]}",
        "status": ptm.status,
        "createdAt": ptm.created_at.isoformat(),
    }


@token_required
@roles_required("PARENT")
def schedule_ptm():
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["teacherId", "studentId", "scheduledAt", "topic"])

    teacher_id = int(payload["teacherId"]) if str(payload["teacherId"]).isdigit() else payload["teacherId"]
    student_id = int(payload["studentId"]) if str(payload["studentId"]).isdigit() else payload["studentId"]

    try:
        scheduled_dt = datetime.fromisoformat(payload["scheduledAt"].replace("Z", "+00:00"))
    except Exception:
        scheduled_dt = now_ist() + timedelta(days=1)

    meeting_code = secrets.token_hex(3)
    meeting_link = f"https://meet.google.com/acu-{meeting_code[:3]}-{meeting_code[3:]}"

    with get_session() as session:
        student = assert_owns_student(session, student_id, g.current_user_id)
        teacher = session.get(Teacher, teacher_id)
        if not teacher:
            raise NotFoundError("Teacher not found")

        ptm = PTMSchedule(
            id=str(uuid.uuid4()),
            parent_id=g.current_user_id,
            teacher_id=teacher_id,
            student_id=student.id,
            scheduled_at=scheduled_dt,
            topic=payload["topic"][:250],
            meeting_link=meeting_link,
            status="SCHEDULED",
            created_at=now_ist(),
        )
        session.add(ptm)
        session.flush()
        return success(_ptm_to_dict(ptm), 201)


@token_required
def list_ptm_schedules():
    with get_session() as session:
        if g.current_user_role == "PARENT":
            ptms = session.query(PTMSchedule).filter(PTMSchedule.parent_id == g.current_user_id).order_by(PTMSchedule.scheduled_at.asc()).all()
        elif g.current_user_role == "TEACHER":
            ptms = session.query(PTMSchedule).filter(PTMSchedule.teacher_id == g.current_user_id).order_by(PTMSchedule.scheduled_at.asc()).all()
        else:
            ptms = session.query(PTMSchedule).order_by(PTMSchedule.scheduled_at.asc()).all()
        return success([_ptm_to_dict(p) for p in ptms])
