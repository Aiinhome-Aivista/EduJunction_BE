"""SQLAlchemy ORM models — one-to-one with sql/schema.sql."""
import uuid
from datetime import datetime, timezone, timedelta

# Indian Standard Time (IST: UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))


def get_ist_now() -> datetime:
    """Returns the current datetime in Indian Standard Time (IST)."""
    return datetime.now(IST).replace(tzinfo=None)

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, Date, ForeignKey, Enum, JSON,
    Numeric, Text, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ------------------------------------------------------------
# 1. Roles & Dynamic Page Access
# ------------------------------------------------------------
class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_name = Column(String(50), nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=get_ist_now)

    users = relationship("User", back_populates="role")
    menu_items = relationship("RolePageAccess", back_populates="role", cascade="all, delete-orphan")


class RolePageAccess(Base):
    __tablename__ = "role_page_access"
    __table_args__ = (UniqueConstraint("role_id", "page_route", name="uq_role_page"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    page_name = Column(String(100), nullable=False)
    page_route = Column(String(100), nullable=False)
    icon = Column(String(50), nullable=True)
    menu_order = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=get_ist_now)

    role = relationship("Role", back_populates="menu_items")


# ------------------------------------------------------------
# 2. Users & auth
# ------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False)
    username = Column(String(80), nullable=False, unique=True, index=True)
    email = Column(String(190), nullable=True, index=True)
    password_hash = Column(String(255), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=get_ist_now)
    created_by = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=get_ist_now, onupdate=get_ist_now)
    updated_by = Column(Integer, nullable=True)

    role = relationship("Role", back_populates="users")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=get_ist_now)


# ------------------------------------------------------------
# 3. Parent / Student / Teacher
# ------------------------------------------------------------
class Parent(Base):
    __tablename__ = "parents"

    id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    children = relationship("Student", back_populates="parent", cascade="all, delete-orphan")
    user = relationship("User", foreign_keys=[id])


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    parent_id = Column(Integer, ForeignKey("parents.id", ondelete="CASCADE"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    avatar = Column(String(20), default="🧑‍🎓")
    class_grade = Column(String(20), nullable=False)
    target_board = Column(String(20), nullable=False)
    school_name = Column(String(190), nullable=True)
    school_email = Column(String(190), nullable=True)
    daily_exams_taken_today = Column(Integer, default=0)
    last_exam_date = Column(Date, nullable=True)
    total_exams_taken = Column(Integer, default=0)
    average_score = Column(Numeric(4, 2), default=0)
    streak_days = Column(Integer, default=0)
    xp = Column(Integer, default=250)
    level = Column(Integer, default=1)
    created_at = Column(DateTime, default=get_ist_now)
    updated_at = Column(DateTime, default=get_ist_now, onupdate=get_ist_now)

    parent = relationship("Parent", back_populates="children")
    user = relationship("User", foreign_keys=[id])


class Teacher(Base):
    __tablename__ = "teachers"

    id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_title = Column(String(120), default="Subject Teacher")
    subject = Column(String(60), nullable=True)
    school_name = Column(String(190), nullable=False)
    phone = Column(String(30), nullable=True)
    verified = Column(Boolean, default=False)

    user = relationship("User", foreign_keys=[id])


# ------------------------------------------------------------
# 4. Curriculum / Runbooks
# ------------------------------------------------------------
class Runbook(Base):
    __tablename__ = "runbooks"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    board = Column(String(20), nullable=False)
    class_grade = Column(String(20), nullable=False)
    subject = Column(String(40), nullable=False)
    chapter_name = Column(String(190), nullable=False)
    core_concepts = Column(JSON, nullable=False)
    key_formulas_or_rules = Column(JSON, nullable=False)
    common_traps = Column(JSON, nullable=False)
    curated_reference_urls = Column(JSON, nullable=False)
    sample_question_archetypes = Column(JSON, nullable=False)
    difficulty_calibration = Column(JSON, nullable=False)
    status = Column(Enum("DRAFT", "PUBLISHED", "ARCHIVED", name="runbook_status"), default="PUBLISHED")
    version = Column(Integer, default=1)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=get_ist_now)
    updated_at = Column(DateTime, default=get_ist_now, onupdate=get_ist_now)


class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    runbook_id = Column(String(36), ForeignKey("runbooks.id", ondelete="SET NULL"), nullable=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    board = Column(String(20), nullable=True)
    class_grade = Column(String(20), nullable=True)
    subject = Column(String(40), nullable=True)
    uploaded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(Enum("PENDING", "PROCESSED", "FAILED", name="document_status"), default="PENDING")
    created_at = Column(DateTime, default=get_ist_now)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    vector_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=get_ist_now)


# ------------------------------------------------------------
# 5. Exams / Questions / Submissions
# ------------------------------------------------------------
class Exam(Base):
    __tablename__ = "exams"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    board = Column(String(20), nullable=False)
    class_grade = Column(String(20), nullable=False)
    subject = Column(String(40), nullable=False)
    difficulty = Column(Enum("simple", "medium", "hard", name="exam_difficulty"), nullable=False)
    total_marks = Column(Integer, default=10)
    question_count = Column(Integer, default=10)
    time_limit_minutes = Column(Integer, default=15)
    rag_knowledge_nodes_used = Column(JSON, nullable=True)
    source = Column(Enum("mistral-rag", "rag-engine-curated", name="exam_source"), nullable=False)
    status = Column(
        Enum("GENERATED", "IN_PROGRESS", "SUBMITTED", "EXPIRED", name="exam_status"),
        default="GENERATED",
    )
    created_at = Column(DateTime, default=get_ist_now)

    questions = relationship("Question", back_populates="exam", cascade="all, delete-orphan")


class Question(Base):
    __tablename__ = "questions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    exam_id = Column(String(36), ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    question_number = Column(Integer, nullable=False)
    type = Column(String(50), nullable=False, default="mcq")
    question_text = Column(Text, nullable=False)
    options = Column(JSON, nullable=True)
    correct_answer = Column(String(500), nullable=False)
    explanation = Column(Text, nullable=False)
    difficulty = Column(Enum("simple", "medium", "hard", name="question_difficulty"), nullable=False)
    marks = Column(Integer, default=1)
    topic = Column(String(190), nullable=False)
    reference_links = Column(JSON, nullable=True)
    hint = Column(Text, nullable=True)

    exam = relationship("Exam", back_populates="questions")


class ExamSubmission(Base):
    __tablename__ = "exam_submissions"
    __table_args__ = (UniqueConstraint("exam_id", name="uq_submission_per_exam"),)

    id = Column(String(36), primary_key=True, default=gen_uuid)
    exam_id = Column(String(36), ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    answers = Column(JSON, nullable=False)
    marks_obtained = Column(Numeric(5, 2), default=0.0, nullable=False)
    total_marks = Column(Integer, default=10)
    accuracy_percentage = Column(Numeric(5, 2), nullable=False)
    time_taken_seconds = Column(Integer, nullable=False)
    submitted_at = Column(DateTime, default=get_ist_now)

    evaluations = relationship("QuestionEvaluation", cascade="all, delete-orphan")
    analysis = relationship("DiagnosticAnalysis", uselist=False, cascade="all, delete-orphan")
    exam = relationship("Exam")
    student = relationship("Student")


class QuestionEvaluation(Base):
    __tablename__ = "question_evaluations"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    submission_id = Column(String(36), ForeignKey("exam_submissions.id", ondelete="CASCADE"), nullable=False)
    question_id = Column(String(36), ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    student_answer = Column(String(500), nullable=False)
    is_correct = Column(Boolean, nullable=False)
    marks_awarded = Column(Numeric(4, 2), default=0.0, nullable=False)
    misconception_identified = Column(String(255), nullable=True)
    feedback = Column(Text, nullable=True)

    question = relationship("Question")


class DiagnosticAnalysis(Base):
    __tablename__ = "diagnostic_analyses"
    __table_args__ = (UniqueConstraint("submission_id", name="uq_diag_per_submission"),)

    id = Column(String(36), primary_key=True, default=gen_uuid)
    submission_id = Column(String(36), ForeignKey("exam_submissions.id", ondelete="CASCADE"), nullable=False)
    overall_band = Column(
        Enum("Needs Foundation", "Developing", "Proficient", "Advanced Mastery", "Competitive Ready",
             name="diagnostic_band"),
        nullable=False,
    )
    mastery_score_percentage = Column(Numeric(5, 2), nullable=False)
    strengths = Column(JSON, nullable=False)
    areas_to_improve = Column(JSON, nullable=False)
    k_graph_insights = Column(JSON, nullable=False)
    evolutionary_roadmap = Column(Text, nullable=False)
    encouragement_note = Column(Text, nullable=False)
    recommended_next_exam = Column(JSON, nullable=False)
    curated_study_links = Column(JSON, nullable=False)
    source = Column(Enum("mistral", "fallback", name="diagnostic_source"), nullable=False)
    created_at = Column(DateTime, default=get_ist_now)


# ------------------------------------------------------------
# 6. Mastery / Misconceptions / Learning path
# ------------------------------------------------------------
class Mastery(Base):
    __tablename__ = "mastery"
    __table_args__ = (UniqueConstraint("student_id", "topic", name="uq_mastery_student_topic"),)

    id = Column(String(36), primary_key=True, default=gen_uuid)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    topic = Column(String(190), nullable=False)
    mastery_score = Column(Numeric(5, 2), default=0)
    confidence = Column(Numeric(5, 2), default=0)
    attempt_count = Column(Integer, default=0)
    correct_count = Column(Integer, default=0)
    status = Column(
        Enum("NOT_STARTED", "LEARNING", "DEVELOPING", "MASTERED", "CRITICAL_GAP", name="mastery_status"),
        default="NOT_STARTED",
    )
    last_assessed_at = Column(DateTime, nullable=True)


class Misconception(Base):
    __tablename__ = "misconceptions"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    topic = Column(String(190), nullable=False)
    description = Column(String(500), nullable=False)
    evidence = Column(Text, nullable=True)
    severity = Column(Enum("LOW", "MEDIUM", "HIGH", name="misconception_severity"), default="MEDIUM")
    status = Column(Enum("OPEN", "IMPROVING", "RESOLVED", name="misconception_status"), default="OPEN")
    created_at = Column(DateTime, default=get_ist_now)
    updated_at = Column(DateTime, default=get_ist_now, onupdate=get_ist_now)


class LearningPathNode(Base):
    __tablename__ = "learning_path_nodes"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    topic = Column(String(190), nullable=False)
    chapter_name = Column(String(190), nullable=False)
    subject = Column(String(40), nullable=False)
    class_grade = Column(String(20), nullable=False)
    board = Column(String(20), nullable=False)
    status = Column(
        Enum("locked", "available", "in_progress", "mastered", "remedial_needed", name="lp_status"),
        default="available",
    )
    mastery_percentage = Column(Numeric(5, 2), default=0)
    level = Column(Enum("foundational", "intermediate", "advanced_hots", name="lp_level"), default="foundational")
    prerequisites = Column(JSON, nullable=True)
    key_concepts = Column(JSON, nullable=True)
    common_misconceptions = Column(JSON, nullable=True)
    curated_resources = Column(JSON, nullable=True)
    practice_exam_config = Column(JSON, nullable=True)
    recommended_reason = Column(String(500), nullable=True)
    attempts_count = Column(Integer, default=0)
    last_score = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=get_ist_now, onupdate=get_ist_now)


# ------------------------------------------------------------
# 7. Gamification
# ------------------------------------------------------------
class Badge(Base):
    __tablename__ = "badges"

    id = Column(String(60), primary_key=True)
    title = Column(String(150), nullable=False)
    description = Column(String(255), nullable=False)
    icon = Column(String(20), nullable=False)
    tier = Column(Enum("bronze", "silver", "gold", "diamond", name="badge_tier"), nullable=False)
    category = Column(Enum("mastery", "streak", "score", "speed", "explorer", name="badge_category"), nullable=False)
    xp_reward = Column(Integer, default=0)
    requirement_text = Column(String(255), nullable=False)


class StudentBadge(Base):
    __tablename__ = "student_badges"

    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), primary_key=True)
    badge_id = Column(String(60), ForeignKey("badges.id", ondelete="CASCADE"), primary_key=True)
    unlocked_at = Column(DateTime, default=get_ist_now)


class XPEvent(Base):
    __tablename__ = "xp_events"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    amount = Column(Integer, nullable=False)
    reason = Column(String(190), nullable=False)
    created_at = Column(DateTime, default=get_ist_now)


# ------------------------------------------------------------
# 8. Parent-teacher communication
# ------------------------------------------------------------
class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("parent_id", "teacher_id", "student_id", name="uq_conv"),)

    id = Column(String(36), primary_key=True, default=gen_uuid)
    parent_id = Column(Integer, ForeignKey("parents.id", ondelete="CASCADE"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=get_ist_now)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan",
                             order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    conversation_id = Column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    sender_role = Column(Enum("parent", "teacher", name="sender_role"), nullable=False)
    sender_id = Column(Integer, nullable=False)
    message = Column(Text, nullable=False)
    attached_submission_id = Column(String(36), ForeignKey("exam_submissions.id", ondelete="SET NULL"), nullable=True)
    action_items = Column(JSON, nullable=True)
    status = Column(Enum("sent", "delivered", "read", "action_taken", name="message_status"), default="sent")
    created_at = Column(DateTime, default=get_ist_now)

    conversation = relationship("Conversation", back_populates="messages")


class SharedDossier(Base):
    __tablename__ = "shared_dossiers"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(Integer, ForeignKey("parents.id", ondelete="CASCADE"), nullable=False)
    share_token = Column(String(60), nullable=False, unique=True)
    notes = Column(Text, nullable=True)
    recipients = Column(JSON, nullable=False)
    included_submissions_count = Column(Integer, default=0)
    view_count = Column(Integer, default=0)
    last_viewed_at = Column(DateTime, nullable=True)
    status = Column(Enum("active", "revoked", name="dossier_status"), default="active")
    created_at = Column(DateTime, default=get_ist_now)
    expires_at = Column(DateTime, nullable=False)

    student = relationship("Student", foreign_keys=[student_id])
    parent = relationship("Parent", foreign_keys=[parent_id])


class PTMSchedule(Base):
    __tablename__ = "ptm_schedules"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    parent_id = Column(Integer, ForeignKey("parents.id", ondelete="CASCADE"), nullable=False)
    teacher_id = Column(Integer, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    scheduled_at = Column(DateTime, nullable=False)
    topic = Column(String(255), nullable=False)
    meeting_link = Column(String(255), nullable=True)
    status = Column(Enum("SCHEDULED", "COMPLETED", "CANCELLED", name="ptm_status"), default="SCHEDULED")
    created_at = Column(DateTime, default=get_ist_now)

    parent = relationship("Parent")
    teacher = relationship("Teacher")
    student = relationship("Student")


# ------------------------------------------------------------
# 9. Scheduled Exams & Notifications
# ------------------------------------------------------------
class ScheduledExam(Base):
    __tablename__ = "scheduled_exams"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    parent_id = Column(Integer, ForeignKey("parents.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(255), nullable=False)
    subject = Column(String(60), nullable=False)
    chapter_topic = Column(String(190), nullable=True)
    board = Column(String(20), nullable=False)
    class_grade = Column(String(20), nullable=False)
    difficulty = Column(Enum("simple", "medium", "hard", name="scheduled_difficulty"), default="medium")
    question_count = Column(Integer, default=10)
    time_limit_minutes = Column(Integer, default=15)
    scheduled_at = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    parent_instructions = Column(Text, nullable=True)
    status = Column(Enum("PENDING", "IN_PROGRESS", "SUBMITTED", "EXPIRED", name="scheduled_exam_status"), default="PENDING")
    exam_id = Column(String(36), ForeignKey("exams.id", ondelete="SET NULL"), nullable=True)
    submission_id = Column(String(36), ForeignKey("exam_submissions.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=get_ist_now)
    updated_at = Column(DateTime, default=get_ist_now, onupdate=get_ist_now)

    parent = relationship("Parent", foreign_keys=[parent_id])
    student = relationship("Student", foreign_keys=[student_id])
    exam = relationship("Exam", foreign_keys=[exam_id])
    submission = relationship("ExamSubmission", foreign_keys=[submission_id])


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    type = Column(String(50), nullable=False)  # 'EXAM_ASSIGNED', 'EXAM_SUBMITTED', 'SYSTEM'
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    action_url = Column(String(200), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    is_read = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=get_ist_now, index=True)

    user = relationship("User", foreign_keys=[user_id])
    sender = relationship("User", foreign_keys=[sender_id])


# ------------------------------------------------------------
# 10. Audit
# ------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(120), nullable=False)
    entity_type = Column(String(60), nullable=True)
    entity_id = Column(String(60), nullable=True)
    ip_address = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=get_ist_now)


# ------------------------------------------------------------
# 11. Master Tables
# ------------------------------------------------------------
class BoardMaster(Base):
    __tablename__ = "board_master"

    id = Column(Integer, primary_key=True, autoincrement=True)
    board_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=get_ist_now)
    updated_at = Column(DateTime, default=get_ist_now, onupdate=get_ist_now)


class ClassMaster(Base):
    __tablename__ = "class_master"

    id = Column(Integer, primary_key=True, autoincrement=True)
    class_name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=get_ist_now)
    updated_at = Column(DateTime, default=get_ist_now, onupdate=get_ist_now)

class AuthorMaster(Base):
    __tablename__ = "author_master"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=get_ist_now)
    updated_at = Column(DateTime, default=get_ist_now, onupdate=get_ist_now)


class CategoryMaster(Base):
    __tablename__ = "category_master"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=get_ist_now)
    updated_at = Column(DateTime, default=get_ist_now, onupdate=get_ist_now)


# ------------------------------------------------------------
# 12. Blogs
# ------------------------------------------------------------
class Blog(Base):
    __tablename__ = "blogs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    author_id = Column(Integer, ForeignKey("author_master.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("category_master.id"), nullable=False)
    introduction = Column(Text, nullable=True)
    content = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)
    is_pinned = Column(Boolean, default=False, nullable=False)
    tags = Column(JSON, nullable=True)
    meta_title = Column(String(255), nullable=True)
    meta_description = Column(Text, nullable=True)
    meta_keywords = Column(Text, nullable=True)
    canonical_url = Column(String(500), nullable=True)
    status = Column(Enum("Published", "Draft", name="blog_status"), default="Draft")
    shares_count = Column(Integer, default=0, nullable=False)
    date = Column(DateTime, default=get_ist_now)
    created_at = Column(DateTime, default=get_ist_now)
    updated_at = Column(DateTime, default=get_ist_now, onupdate=get_ist_now)

    author = relationship("AuthorMaster")
    category = relationship("CategoryMaster")


# ------------------------------------------------------------
# 13. Question Upload Batches & Ingestion Audit
# ------------------------------------------------------------
class QuestionUploadBatch(Base):
    __tablename__ = "question_upload_batches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_name = Column(String(255), nullable=False)
    file_size_bytes = Column(Integer, default=0)
    total_rows = Column(Integer, default=0)
    inserted_count = Column(Integer, default=0)
    updated_count = Column(Integer, default=0)
    duplicate_skipped_count = Column(Integer, default=0)
    status = Column(String(50), default="SUCCESS")
    uploaded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=get_ist_now)

    uploader = relationship("User", foreign_keys=[uploaded_by])