import json
import random
import uuid
from datetime import datetime
from flask import request, g
from sqlalchemy import text, func, and_, or_
from sqlalchemy.orm import Session

from database.dbConnection import get_session, engine
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import roles_required
from model.models import (
    Base, ExamBlueprintMaster, MockTestMaster, Student, ScheduledExam, Notification, User,
    BoardMaster, ClassMaster
)
from utils.date_helper import now_ist
from utils.errors import AppError, NotFoundError, ValidationError
from utils.logger import logger
from utils.response import success


def init_mock_test_tables():
    """Ensure tables exist, schema is up-to-date and seed initial blueprint configurations."""
    try:
        Base.metadata.create_all(bind=engine, tables=[
            ExamBlueprintMaster.__table__,
            MockTestMaster.__table__
        ])
        # Ensure parent_id can be NULL for independent students in scheduled_exams
        try:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE scheduled_exams MODIFY COLUMN parent_id INT NULL"))
                conn.commit()
        except Exception:
            pass

        with get_session() as session:
            count = session.query(ExamBlueprintMaster).count()
            if count == 0:
                default_blueprints = [
                    ExamBlueprintMaster(
                        tier_name="Kids Tier",
                        class_grade="Class 1-4",
                        total_questions=5,
                        mcq_count=5,
                        saq_count=0,
                        marks_per_mcq=1,
                        marks_per_saq=0,
                        total_marks=5,
                        duration_minutes=10,
                        description="Foundational diagnostic: 5 MCQs @ 1 Mark each"
                    ),
                    ExamBlueprintMaster(
                        tier_name="Secondary Tier",
                        class_grade="Class 5-10",
                        total_questions=10,
                        mcq_count=5,
                        saq_count=5,
                        marks_per_mcq=1,
                        marks_per_saq=2,
                        total_marks=15,
                        duration_minutes=20,
                        description="Comprehensive assessment: 5 MCQs @ 1M + 5 SAQs @ 2M"
                    ),
                    ExamBlueprintMaster(
                        tier_name="Senior Tier",
                        class_grade="Class 11-12",
                        total_questions=10,
                        mcq_count=0,
                        saq_count=10,
                        marks_per_mcq=0,
                        marks_per_saq=2,
                        total_marks=20,
                        duration_minutes=25,
                        description="Advanced concepts: 10 Rigorous Questions @ 2M each"
                    ),
                ]
                session.add_all(default_blueprints)
                session.commit()
    except Exception as e:
        logger.warning(f"Error initializing mock test tables: {e}")


# Initialize tables on import
init_mock_test_tables()


# ─────────────────────────────────────────────────────────────
# 1. Blueprint APIs
# ─────────────────────────────────────────────────────────────

@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def get_blueprints():
    with get_session() as session:
        blueprints = session.query(ExamBlueprintMaster).order_by(ExamBlueprintMaster.id).all()
        return success({
            "blueprints": [
                {
                    "id": b.id,
                    "tierName": b.tier_name,
                    "classGrade": b.class_grade,
                    "totalQuestions": b.total_questions,
                    "mcqCount": b.mcq_count,
                    "saqCount": b.saq_count,
                    "marksPerMcq": b.marks_per_mcq,
                    "marksPerSaq": b.marks_per_saq,
                    "totalMarks": b.total_marks,
                    "durationMinutes": b.duration_minutes,
                    "description": b.description,
                    "isActive": b.is_active,
                }
                for b in blueprints
            ]
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def update_blueprint(blueprint_id: int):
    payload = request.get_json(force=True, silent=True) or {}
    with get_session() as session:
        bp = session.get(ExamBlueprintMaster, blueprint_id)
        if not bp:
            raise NotFoundError("Blueprint not found")

        if "totalQuestions" in payload:
            bp.total_questions = int(payload["totalQuestions"])
        if "mcqCount" in payload:
            bp.mcq_count = int(payload["mcqCount"])
        if "saqCount" in payload:
            bp.saq_count = int(payload["saqCount"])
        if "marksPerMcq" in payload:
            bp.marks_per_mcq = int(payload["marksPerMcq"])
        if "marksPerSaq" in payload:
            bp.marks_per_saq = int(payload["marksPerSaq"])
        if "totalMarks" in payload:
            bp.total_marks = int(payload["totalMarks"])
        if "durationMinutes" in payload:
            bp.duration_minutes = int(payload["durationMinutes"])
        if "isActive" in payload:
            bp.is_active = bool(payload["isActive"])

        bp.updated_at = now_ist()
        session.commit()

        return success({"message": "Blueprint updated successfully"})


# ─────────────────────────────────────────────────────────────
# 2. Mock Test Generator & Manager
# ─────────────────────────────────────────────────────────────

def _resolve_blueprint_for_class(session: Session, class_grade: str) -> ExamBlueprintMaster | None:
    cg = (class_grade or "").lower().strip()
    import re
    match = re.search(r'(?:class|grade)?\s*(\d+)', cg)
    cnum = int(match.group(1)) if match else 5

    if 1 <= cnum <= 4:
        return session.query(ExamBlueprintMaster).filter(ExamBlueprintMaster.tier_name.ilike("%kid%")).first()
    elif 5 <= cnum <= 10:
        return session.query(ExamBlueprintMaster).filter(ExamBlueprintMaster.tier_name.ilike("%secondary%")).first()
    else:
        return session.query(ExamBlueprintMaster).filter(ExamBlueprintMaster.tier_name.ilike("%senior%")).first()


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def generate_mock_test():
    payload = request.get_json(force=True, silent=True) or {}
    board = str(payload.get("board", "")).strip()
    class_grade = str(payload.get("classGrade", "")).strip()
    subject = str(payload.get("subject", "")).strip()
    chapter_id = payload.get("chapterId")
    chapter_name = payload.get("chapterName")
    topic_id = payload.get("topicId")
    topic_name = payload.get("topicName")
    academic_year = str(payload.get("academicYear", "2026-2027")).strip()
    session_type = str(payload.get("sessionType", "CURRENT")).strip().upper()
    difficulty = str(payload.get("difficulty", "medium")).strip().lower()
    is_auto_assign = bool(payload.get("isAutoAssign", True))

    if not board or not class_grade or not subject:
        raise ValidationError("Board, Class, and Subject are required")

    with get_session() as session:
        # Resolve blueprint
        bp = _resolve_blueprint_for_class(session, class_grade)
        target_mcq_count = bp.mcq_count if bp else 5
        target_saq_count = bp.saq_count if bp else 5
        marks_per_mcq = bp.marks_per_mcq if bp else 1
        marks_per_saq = bp.marks_per_saq if bp else 2
        total_duration = bp.duration_minutes if bp else 20

        # Query question bank matching board, class, subject
        query_sql = """
            SELECT 
                q.id AS question_id,
                q.question AS question_text,
                q.options,
                q.correct_answer,
                q.explanation,
                q.marks,
                q.image_url,
                COALESCE(qt.question_type_name, 'MCQ') AS question_type,
                COALESCE(dl.difficulty_level_name, 'medium') AS difficulty,
                s.subject_name,
                ch.id AS chapter_id,
                ch.chapter_name,
                t.id AS topic_id,
                t.topic_name,
                b.board_name,
                c.class_name
            FROM question_master q
            JOIN topic_master t ON q.topic_id = t.id
            JOIN chapter_master ch ON t.chapter_id = ch.id
            JOIN subject_master s ON ch.subject_id = s.id
            JOIN board_master b ON s.board_id = b.id
            JOIN class_master c ON s.class_id = c.id
            LEFT JOIN question_type_master qt ON q.question_type_id = qt.id
            LEFT JOIN difficulty_level_master dl ON q.difficulty_level_id = dl.id
            WHERE q.is_active = 1
              AND (LOWER(b.board_name) LIKE LOWER(:board_pattern) OR LOWER(:board_pattern) LIKE CONCAT('%', LOWER(b.board_name), '%'))
              AND (LOWER(c.class_name) LIKE LOWER(:class_pattern) OR LOWER(:class_pattern) LIKE CONCAT('%', LOWER(c.class_name), '%'))
              AND (LOWER(s.subject_name) LIKE LOWER(:subject_pattern) OR LOWER(:subject_pattern) LIKE CONCAT('%', LOWER(s.subject_name), '%'))
        """
        params = {
            "board_pattern": f"%{board}%",
            "class_pattern": f"%{class_grade}%",
            "subject_pattern": f"%{subject}%",
        }

        if chapter_id:
            query_sql += " AND ch.id = :chapter_id"
            params["chapter_id"] = int(chapter_id)
        elif chapter_name:
            query_sql += " AND LOWER(ch.chapter_name) LIKE LOWER(:chapter_pattern)"
            params["chapter_pattern"] = f"%{chapter_name}%"

        if topic_id:
            query_sql += " AND t.id = :topic_id"
            params["topic_id"] = int(topic_id)
        elif topic_name:
            query_sql += " AND LOWER(t.topic_name) LIKE LOWER(:topic_pattern)"
            params["topic_pattern"] = f"%{topic_name}%"

        query_sql += " ORDER BY RAND() LIMIT 100"

        rows = session.execute(text(query_sql), params).mappings().fetchall()

        mcq_pool = []
        saq_pool = []

        for r in rows:
            raw_type = str(r.get("question_type", "mcq")).lower()
            raw_options = r.get("options")
            options_list = None
            if raw_options:
                if isinstance(raw_options, list):
                    options_list = raw_options
                elif isinstance(raw_options, str):
                    try:
                        parsed = json.loads(raw_options)
                        if isinstance(parsed, list):
                            options_list = parsed
                        elif isinstance(parsed, dict):
                            options_list = [f"{k}) {v}" for k, v in parsed.items()]
                    except Exception:
                        options_list = [opt.strip() for opt in raw_options.split("|") if opt.strip()]

            img_url = r.get("image_url") or None
            q_obj = {
                "questionId": r.get("question_id"),
                "questionText": r.get("question_text"),
                "options": options_list,
                "correctAnswer": str(r.get("correct_answer", "A")),
                "explanation": r.get("explanation") or "Standard curriculum concept explanation.",
                "chapterName": r.get("chapter_name"),
                "topicName": r.get("topic_name"),
                "difficulty": r.get("difficulty") or difficulty,
                "imageUrl": img_url,
                "image_url": img_url,
            }

            if "saq" in raw_type or "short" in raw_type or int(r.get("marks", 1)) == 2:
                q_obj["type"] = "saq"
                q_obj["marks"] = marks_per_saq
                saq_pool.append(q_obj)
            else:
                q_obj["type"] = "mcq"
                q_obj["marks"] = marks_per_mcq
                mcq_pool.append(q_obj)

        # Build final question list matching the blueprint
        selected_questions = []
        
        # Pick MCQs
        random.shuffle(mcq_pool)
        selected_questions.extend(mcq_pool[:target_mcq_count])
        
        # Pick SAQs
        random.shuffle(saq_pool)
        selected_questions.extend(saq_pool[:target_saq_count])

        # If pool has deficit, backfill from available questions
        if len(selected_questions) < (target_mcq_count + target_saq_count):
            remaining_needed = (target_mcq_count + target_saq_count) - len(selected_questions)
            remaining_pool = [q for q in (mcq_pool + saq_pool) if q not in selected_questions]
            selected_questions.extend(remaining_pool[:remaining_needed])

        # If still empty (e.g. no questions in DB yet), generate fallback questions
        if not selected_questions:
            from helper.fallback_exam_bank import build_fallback_questions
            fallback_list = build_fallback_questions(
                board=board,
                subject=subject,
                difficulty=difficulty,
                ref_links=[],
                class_grade=class_grade,
                limit=target_mcq_count + target_saq_count,
            )
            for idx, fq in enumerate(fallback_list):
                fq_type = "mcq" if idx < target_mcq_count else "saq"
                selected_questions.append({
                    "questionId": None,
                    "questionText": fq.get("questionText", f"Mock Question {idx + 1}"),
                    "options": fq.get("options") if fq_type == "mcq" else None,
                    "correctAnswer": fq.get("correctAnswer", "A"),
                    "explanation": fq.get("explanation", "Reference textbook explanation"),
                    "chapterName": chapter_name or "General Topic",
                    "topicName": topic_name or subject,
                    "difficulty": difficulty,
                    "type": fq_type,
                    "marks": marks_per_mcq if fq_type == "mcq" else marks_per_saq,
                })

        # Number questions
        for idx, q in enumerate(selected_questions):
            q["questionNumber"] = idx + 1

        calc_total_marks = sum(int(q.get("marks", 1)) for q in selected_questions)
        calc_mcq_count = sum(1 for q in selected_questions if q.get("type") == "mcq")
        calc_saq_count = sum(1 for q in selected_questions if q.get("type") == "saq")

        title_suffix = f": {chapter_name}" if chapter_name else " Comprehensive"
        mock_title = payload.get("title") or f"{board} {class_grade} {subject}{title_suffix} Mock Test ({academic_year})"

        mock_test = MockTestMaster(
            id=str(uuid.uuid4()),
            title=mock_title,
            board=board,
            class_grade=class_grade,
            subject=subject,
            chapter_id=chapter_id,
            chapter_name=chapter_name,
            topic_id=topic_id,
            topic_name=topic_name,
            academic_year=academic_year,
            session_type=session_type,
            blueprint_id=bp.id if bp else None,
            difficulty=difficulty,
            total_questions=len(selected_questions),
            mcq_count=calc_mcq_count,
            saq_count=calc_saq_count,
            total_marks=calc_total_marks,
            duration_minutes=total_duration,
            questions_json=selected_questions,
            is_auto_assign=is_auto_assign,
            status="ACTIVE",
            created_by=g.current_user_id,
            created_at=now_ist(),
        )

        session.add(mock_test)
        session.flush()

        # Optional Bulk assign to existing students of this board & class if requested
        bulk_assigned_count = 0
        if payload.get("assignToExistingStudents"):
            bulk_assigned_count = _bulk_assign_mock_to_students(session, mock_test)

        session.commit()

        return success({
            "message": "Mock Test generated and published successfully",
            "mockTest": {
                "id": mock_test.id,
                "title": mock_test.title,
                "board": mock_test.board,
                "classGrade": mock_test.class_grade,
                "subject": mock_test.subject,
                "academicYear": mock_test.academic_year,
                "sessionType": mock_test.session_type,
                "totalQuestions": mock_test.total_questions,
                "mcqCount": mock_test.mcq_count,
                "saqCount": mock_test.saq_count,
                "totalMarks": mock_test.total_marks,
                "durationMinutes": mock_test.duration_minutes,
                "isAutoAssign": mock_test.is_auto_assign,
                "assignedCount": mock_test.assigned_count,
                "bulkAssignedNow": bulk_assigned_count,
                "status": mock_test.status,
                "createdAt": mock_test.created_at.isoformat() if mock_test.created_at else None,
            }
        }, 201)


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def list_mock_tests():
    board = request.args.get("board")
    class_grade = request.args.get("classGrade")
    subject = request.args.get("subject")
    academic_year = request.args.get("academicYear")

    with get_session() as session:
        query = session.query(MockTestMaster).filter(MockTestMaster.status != "DELETED")
        if board:
            query = query.filter(MockTestMaster.board == board)
        if class_grade:
            query = query.filter(MockTestMaster.class_grade == class_grade)
        if subject:
            query = query.filter(MockTestMaster.subject == subject)
        if academic_year:
            query = query.filter(MockTestMaster.academic_year == academic_year)

        tests = query.order_by(MockTestMaster.created_at.desc()).all()

        return success({
            "mockTests": [
                {
                    "id": t.id,
                    "title": t.title,
                    "board": t.board,
                    "classGrade": t.class_grade,
                    "subject": t.subject,
                    "chapterName": t.chapter_name,
                    "topicName": t.topic_name,
                    "academicYear": t.academic_year,
                    "sessionType": t.session_type,
                    "totalQuestions": t.total_questions,
                    "mcqCount": t.mcq_count,
                    "saqCount": t.saq_count,
                    "totalMarks": t.total_marks,
                    "durationMinutes": t.duration_minutes,
                    "isAutoAssign": t.is_auto_assign,
                    "assignedCount": t.assigned_count,
                    "status": t.status,
                    "questions": t.questions_json,
                    "questionsCount": len(t.questions_json) if t.questions_json else t.total_questions,
                    "createdAt": t.created_at.isoformat() if t.created_at else None,
                }
                for t in tests
            ]
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def toggle_auto_assign(test_id: str):
    with get_session() as session:
        mt = session.get(MockTestMaster, test_id)
        if not mt:
            raise NotFoundError("Mock test not found")
        mt.is_auto_assign = not mt.is_auto_assign
        mt.updated_at = now_ist()
        session.commit()
        return success({
            "id": mt.id,
            "isAutoAssign": mt.is_auto_assign,
            "message": f"Auto-assign {'enabled' if mt.is_auto_assign else 'disabled'}"
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def bulk_assign(test_id: str):
    with get_session() as session:
        mt = session.get(MockTestMaster, test_id)
        if not mt:
            raise NotFoundError("Mock test not found")
        count = _bulk_assign_mock_to_students(session, mt)
        session.commit()
        return success({
            "assignedCount": count,
            "message": f"Mock Test successfully assigned to {count} existing students of {mt.board} {mt.class_grade}"
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def delete_mock_test(test_id: str):
    with get_session() as session:
        mt = session.get(MockTestMaster, test_id)
        if not mt:
            raise NotFoundError("Mock test not found")
        mt.status = "DELETED"
        mt.is_auto_assign = False
        mt.updated_at = now_ist()
        session.commit()
        return success({"message": "Mock test deleted successfully"})


# ─────────────────────────────────────────────────────────────
# 3. Auto-Assign Hook (for Registration & Bulk Assignment)
# ─────────────────────────────────────────────────────────────

def _bulk_assign_mock_to_students(session: Session, mock_test: MockTestMaster) -> int:
    """Assigns mock test to all matching registered students."""
    clean_board = mock_test.board.strip().lower()
    clean_class = mock_test.class_grade.strip().lower()

    students = session.query(Student).filter(
        or_(
            func.lower(Student.target_board) == clean_board,
            func.lower(Student.target_board).contains(clean_board),
            func.lower(mock_test.board).contains(func.lower(Student.target_board))
        ),
        or_(
            func.lower(Student.class_grade) == clean_class,
            func.lower(Student.class_grade).contains(clean_class),
            func.lower(mock_test.class_grade).contains(func.lower(Student.class_grade))
        )
    ).all()

    assigned_count = 0
    for student in students:
        existing = session.query(ScheduledExam).filter(
            ScheduledExam.student_id == student.id,
            ScheduledExam.title == mock_test.title,
            ScheduledExam.status.in_(["PENDING", "IN_PROGRESS", "SUBMITTED"])
        ).first()

        if not existing:
            scheduled_exam = ScheduledExam(
                id=str(uuid.uuid4()),
                parent_id=student.parent_id,
                student_id=student.id,
                title=mock_test.title,
                subject=mock_test.subject,
                chapter_topic=mock_test.chapter_name or mock_test.topic_name or "Comprehensive Mock Test",
                board=student.target_board or mock_test.board,
                class_grade=student.class_grade or mock_test.class_grade,
                difficulty=mock_test.difficulty or "medium",
                question_count=mock_test.total_questions,
                time_limit_minutes=mock_test.duration_minutes,
                parent_instructions=f"Official Academic Mock Test ({mock_test.academic_year}). Auto-assigned by EduJunction.",
                status="PENDING",
                created_at=now_ist(),
            )
            session.add(scheduled_exam)

            notification = Notification(
                user_id=student.id,
                sender_id=mock_test.created_by,
                type="EXAM_ASSIGNED",
                title=f"New Official Mock Test Assigned 📝",
                message=f"You have been assigned '{mock_test.title}' ({mock_test.total_marks} Marks, {mock_test.duration_minutes} Mins).",
                action_url="/arena",
                metadata_json={
                    "scheduledExamId": scheduled_exam.id,
                    "subject": mock_test.subject,
                    "isMockTest": True,
                    "academicYear": mock_test.academic_year,
                },
                created_at=now_ist(),
            )
            session.add(notification)
            assigned_count += 1

    mock_test.assigned_count = (mock_test.assigned_count or 0) + assigned_count
    return assigned_count


def auto_assign_mock_tests_for_new_student(session: Session, student: Student):
    """Called when a new student/child is registered to automatically assign matching active mock tests."""
    if not student or not student.target_board or not student.class_grade:
        return

    clean_board = student.target_board.strip().lower()
    clean_class = student.class_grade.strip().lower()

    # Find active auto-assign mock tests
    matching_mock_tests = session.query(MockTestMaster).filter(
        MockTestMaster.status == "ACTIVE",
        MockTestMaster.is_auto_assign == True,
    ).all()

    for mt in matching_mock_tests:
        mt_board = (mt.board or "").strip().lower()
        mt_class = (mt.class_grade or "").strip().lower()

        board_match = clean_board in mt_board or mt_board in clean_board
        class_match = clean_class in mt_class or mt_class in clean_class

        if board_match and class_match:
            existing = session.query(ScheduledExam).filter(
                ScheduledExam.student_id == student.id,
                ScheduledExam.title == mt.title,
            ).first()

            if not existing:
                se = ScheduledExam(
                    id=str(uuid.uuid4()),
                    parent_id=student.parent_id,
                    student_id=student.id,
                    title=mt.title,
                    subject=mt.subject,
                    chapter_topic=mt.chapter_name or mt.topic_name or "Comprehensive Mock Test",
                    board=student.target_board,
                    class_grade=student.class_grade,
                    difficulty=mt.difficulty or "medium",
                    question_count=mt.total_questions,
                    time_limit_minutes=mt.duration_minutes,
                    parent_instructions=f"Official Academic Mock Test ({mt.academic_year}). Auto-assigned upon registration.",
                    status="PENDING",
                    created_at=now_ist(),
                )
                session.add(se)

                notif = Notification(
                    user_id=student.id,
                    sender_id=mt.created_by,
                    type="EXAM_ASSIGNED",
                    title=f"Welcome Mock Test Ready 🎯",
                    message=f"Welcome! Start your journey with '{mt.title}' ({mt.total_marks} Marks, {mt.duration_minutes} Mins).",
                    action_url="/arena",
                    metadata_json={
                        "scheduledExamId": se.id,
                        "subject": mt.subject,
                        "isMockTest": True,
                        "academicYear": mt.academic_year,
                    },
                    created_at=now_ist(),
                )
                session.add(notif)
                mt.assigned_count = (mt.assigned_count or 0) + 1


def generate_free_mock_test():
    """Generates a Free 10-Mark Subject-wise Mock Test for CBSE, ICSE, ISC (Classes 5 to 10)."""
    payload = request.get_json(force=True, silent=True) or {}
    board = str(payload.get("board", "CBSE")).strip()
    class_grade = str(payload.get("classGrade", "Class 10")).strip()
    subject = str(payload.get("subject", "Mathematics")).strip()
    student_id = payload.get("studentId")

    from helper import exam_generator
    with get_session() as session:
        resolved_student_id = 1
        student_name = "Guest Student"
        if getattr(g, "current_user_role", None) == "STUDENT":
            resolved_student_id = g.current_user_id
            st = session.get(Student, resolved_student_id)
            if st and st.user:
                student_name = st.user.name
        elif student_id:
            resolved_student_id = int(student_id)
            st = session.get(Student, resolved_student_id)
            if st and st.user:
                student_name = st.user.name

        exam = exam_generator.generate_exam(
            session,
            student_id=resolved_student_id,
            student_name=student_name,
            board=board,
            class_grade=class_grade,
            subject=subject,
            difficulty="medium",
            question_count=10,
            time_limit_minutes=15,
            title=f"Free {class_grade} {board} {subject} Mock Test (10 Marks)",
            is_assigned=False,
        )

        session.commit()

        return success({
            "exam": exam_generator.exam_to_public_dict(exam),
            "is_free": True,
            "total_marks": 10,
            "message": "Free 10-Mark Subject Mock Test generated successfully!"
        }, 201)


def get_quick_demo_questions():
    """Fetches exactly 5 active MCQs mapped to Board, Class, Subject from question_master.
    Zero database write operations. Supports domain branch filtering (Physics, Chemistry, Biology) for Science.
    """
    import time
    t_start = time.perf_counter()
    from utils.constants import SCIENCE_BRANCH_KEYWORDS

    board = str(request.args.get("board", "CBSE")).strip()
    class_grade = str(request.args.get("classGrade", "Class 10")).strip()
    subject = str(request.args.get("subject", "Mathematics")).strip()
    branch = str(request.args.get("branch", "all")).strip()

    clean_subj = subject.lower().strip()
    is_science_branch = (clean_subj == "science" and branch in ["Physics", "Chemistry", "Biology"])
    branch_keywords = SCIENCE_BRANCH_KEYWORDS.get(branch, []) if is_science_branch else []

    with get_session() as session:
        branch_filter_sql = ""
        branch_params = {}
        if is_science_branch and branch_keywords:
            b_conds = [f"(LOWER(ch.chapter_name) LIKE :kw_{i} OR LOWER(t.topic_name) LIKE :kw_{i} OR LOWER(q.question) LIKE :kw_{i})" for i in range(len(branch_keywords))]
            branch_filter_sql = "AND (" + " OR ".join(b_conds) + ")"
            for i, kw in enumerate(branch_keywords):
                branch_params[f"kw_{i}"] = f"%{kw}%"

        query_sql = f"""
            SELECT 
                q.id,
                q.question AS question_text,
                q.options,
                q.image_url,
                q.marks,
                COALESCE(dl.difficulty_level_name, 'medium') AS difficulty,
                t.topic_name,
                ch.chapter_name,
                s.subject_name,
                b.board_name,
                c.class_name
            FROM question_master q
            JOIN topic_master t ON q.topic_id = t.id
            JOIN chapter_master ch ON t.chapter_id = ch.id
            JOIN subject_master s ON ch.subject_id = s.id
            JOIN board_master b ON s.board_id = b.id
            JOIN class_master c ON s.class_id = c.id
            LEFT JOIN question_type_master qt ON q.question_type_id = qt.id
            LEFT JOIN difficulty_level_master dl ON q.difficulty_level_id = dl.id
            WHERE q.is_active = 1
              AND (LOWER(qt.question_type_name) = 'mcq' OR q.options IS NOT NULL)
              AND (LOWER(b.board_name) LIKE LOWER(:board_pattern) OR LOWER(:board_pattern) LIKE CONCAT('%', LOWER(b.board_name), '%'))
              AND (LOWER(c.class_name) LIKE LOWER(:class_pattern) OR LOWER(:class_pattern) LIKE CONCAT('%', LOWER(c.class_name), '%'))
              AND (LOWER(s.subject_name) LIKE LOWER(:subject_pattern) OR LOWER(:subject_pattern) LIKE CONCAT('%', LOWER(s.subject_name), '%'))
              {branch_filter_sql}
            ORDER BY RAND()
            LIMIT 15
        """
        params = {
            "board_pattern": f"%{board}%",
            "class_pattern": f"%{class_grade.replace('Class', '').strip()}%" if "Class" in class_grade else f"%{class_grade}%",
            "subject_pattern": f"%{subject}%",
            **branch_params
        }

        rows = session.execute(text(query_sql), params).mappings().fetchall()
        is_fallback = False

        # Fallback if specific board/class combination is sparse: fall back to subject and class
        if len(rows) < 5:
            is_fallback = True
            fallback_sql = f"""
                SELECT 
                    q.id,
                    q.question AS question_text,
                    q.options,
                    q.image_url,
                    q.marks,
                    COALESCE(dl.difficulty_level_name, 'medium') AS difficulty,
                    t.topic_name,
                    ch.chapter_name,
                    s.subject_name,
                    b.board_name,
                    c.class_name
                FROM question_master q
                JOIN topic_master t ON q.topic_id = t.id
                JOIN chapter_master ch ON t.chapter_id = ch.id
                JOIN subject_master s ON ch.subject_id = s.id
                JOIN board_master b ON s.board_id = b.id
                JOIN class_master c ON s.class_id = c.id
                LEFT JOIN question_type_master qt ON q.question_type_id = qt.id
                LEFT JOIN difficulty_level_master dl ON q.difficulty_level_id = dl.id
                WHERE q.is_active = 1
                  AND (LOWER(qt.question_type_name) = 'mcq' OR q.options IS NOT NULL)
                  AND (LOWER(s.subject_name) LIKE LOWER(:subject_pattern) OR LOWER(:subject_pattern) LIKE CONCAT('%', LOWER(s.subject_name), '%'))
                  {branch_filter_sql}
                ORDER BY RAND()
                LIMIT 15
            """
            fallback_params = {"subject_pattern": f"%{subject}%", **branch_params}
            rows = session.execute(text(fallback_sql), fallback_params).mappings().fetchall()

            # If branch-specific questions are still sparse, relax branch filter so student is never blocked
            if len(rows) < 5 and is_science_branch:
                relaxed_sql = """
                    SELECT 
                        q.id,
                        q.question AS question_text,
                        q.options,
                        q.image_url,
                        q.marks,
                        COALESCE(dl.difficulty_level_name, 'medium') AS difficulty,
                        t.topic_name,
                        ch.chapter_name,
                        s.subject_name,
                        b.board_name,
                        c.class_name
                    FROM question_master q
                    JOIN topic_master t ON q.topic_id = t.id
                    JOIN chapter_master ch ON t.chapter_id = ch.id
                    JOIN subject_master s ON ch.subject_id = s.id
                    JOIN board_master b ON s.board_id = b.id
                    JOIN class_master c ON s.class_id = c.id
                    LEFT JOIN question_type_master qt ON q.question_type_id = qt.id
                    LEFT JOIN difficulty_level_master dl ON q.difficulty_level_id = dl.id
                    WHERE q.is_active = 1
                      AND (LOWER(qt.question_type_name) = 'mcq' OR q.options IS NOT NULL)
                      AND (LOWER(s.subject_name) LIKE LOWER(:subject_pattern) OR LOWER(:subject_pattern) LIKE CONCAT('%', LOWER(s.subject_name), '%'))
                    ORDER BY RAND()
                    LIMIT 10
                """
                relaxed_rows = session.execute(text(relaxed_sql), {"subject_pattern": f"%{subject}%"}).mappings().fetchall()
                if len(relaxed_rows) > len(rows):
                    rows = relaxed_rows
                    print(f">> Fallback Note      : Blended general science questions to satisfy full 5-question quota", flush=True)

        if is_fallback:
            print(f">> Query Strategy     : [SUBJECT/DOMAIN FALLBACK] ({len(rows)} candidate rows fetched for subject='{subject}')", flush=True)
        else:
            print(f">> Query Strategy     : [EXACT BLUEPRINT MATCH] ({len(rows)} candidate rows fetched)", flush=True)

        # Format questions for client (omitting correct_answer and explanation to prevent cheating)
        questions = []
        for idx, r in enumerate(rows):
            raw_options = r.get("options")
            options_list = []
            if raw_options:
                if isinstance(raw_options, list):
                    options_list = raw_options
                elif isinstance(raw_options, str):
                    try:
                        parsed = json.loads(raw_options)
                        if isinstance(parsed, list):
                            options_list = parsed
                        elif isinstance(parsed, dict):
                            options_list = [f"{k}) {v}" for k, v in parsed.items()]
                        else:
                            options_list = [raw_options]
                    except Exception:
                        options_list = [opt.strip() for opt in raw_options.split("|") if opt.strip()]

            # Require at least 2 valid options for a valid MCQ
            if not options_list or len(options_list) < 2:
                continue

            questions.append({
                "id": r["id"],
                "questionNumber": len(questions) + 1,
                "questionText": r["question_text"],
                "options": options_list,
                "imageUrl": r["image_url"],
                "marks": 1,
                "difficulty": r["difficulty"] or "medium",
                "topic": r["topic_name"] or r["chapter_name"] or subject,
            })

            if len(questions) >= 5:
                break

        target_display = f"{board} | {class_grade} | {subject}"
        if is_science_branch:
            target_display += f" ({branch})"
        target_display += " (Difficulty: simple)"

        load_time = round(time.perf_counter() - t_start, 2)
        load_time_str = f"{load_time:.2f}s" if load_time >= 0.01 else "0.03s"

        final_db_count = len(questions)
        final_fallback_count = 0 if not is_fallback else (5 - len(questions) if len(questions) < 5 else 0)
        total_q_count = len(questions)

        print("\n" + "=" * 78, flush=True)
        print("[*] [EXAM GENERATION LOG]", flush=True)
        print(f">> Target    : {target_display}", flush=True)
        print(f">> Mode      : QUICK DEMO TEST BLUEPRINT", flush=True)
        print(f">> SOURCE    : >>> DATABASE ({final_db_count}/{total_q_count} from question_master) <<<", flush=True)
        print(f">> Quality   : >>> 100% VERIFIED DATABASE CURRICULUM (Instant {load_time_str} Load) <<<", flush=True)
        print(f">> Breakdown : Database: {final_db_count} Qs | Fallback: {final_fallback_count} Qs | Total: {total_q_count} Qs", flush=True)
        print(f">> Types     : {final_db_count} MCQs @ 1M", flush=True)
        print(f">> Marks     : {final_db_count} Marks Total | Time: 5 Mins", flush=True)
        for q in questions:
            print(f"   * [Q#{q['questionNumber']}] DB_ID: {q['id']} | Topic: '{q['topic']}' | Diff: {q['difficulty'].upper()}", flush=True)
        print("=" * 78 + "\n", flush=True)

        branch_title = f" ({branch})" if is_science_branch else ""
        return success({
            "title": f"Quick Demo Mock Test — {class_grade} {board} {subject}{branch_title}",
            "board": board,
            "classGrade": class_grade,
            "subject": subject,
            "branch": branch if is_science_branch else None,
            "totalQuestions": len(questions),
            "totalMarks": len(questions),
            "timeLimitMinutes": 5,
            "questions": questions,
        }, 200)


def evaluate_quick_demo_test():
    """Pure Python instantaneous evaluation of submitted MCQs.
    Zero LLM calls, zero DB writes. Returns scorecard with textbook explanations.
    """
    payload = request.get_json(force=True, silent=True) or {}
    user_answers = payload.get("answers", {})

    if not user_answers or not isinstance(user_answers, dict):
        return success({
            "score": 0,
            "totalMarks": 0,
            "percentage": 0,
            "review": [],
            "message": "No answers provided."
        }, 200)

    try:
        raw_ids = [int(qid) for qid in user_answers.keys() if str(qid).isdigit()]
    except Exception:
        raw_ids = []

    if not raw_ids:
        return success({
            "score": 0,
            "totalMarks": 0,
            "percentage": 0,
            "review": [],
        }, 200)

    with get_session() as session:
        sql = text("""
            SELECT id, question, options, correct_answer, explanation, marks
            FROM question_master
            WHERE id IN :q_ids
        """)
        rows = session.execute(sql, {"q_ids": tuple(raw_ids)}).mappings().fetchall()

        score = 0
        review = []

        import re

        def clean_opt(val):
            if not val:
                return ""
            return re.sub(r'^(?:option\s+)?\(?[A-Da-d]\)?[\).\:\-]?\s*', '', str(val), flags=re.I).strip().lower()

        for row in rows:
            q_id = row["id"]
            user_raw_ans = str(user_answers.get(str(q_id), user_answers.get(q_id, ""))).strip()
            db_correct = str(row["correct_answer"] or "").strip()

            raw_options = row.get("options")
            options_list = []
            if raw_options:
                if isinstance(raw_options, list):
                    options_list = raw_options
                elif isinstance(raw_options, str):
                    try:
                        parsed = json.loads(raw_options)
                        if isinstance(parsed, list):
                            options_list = parsed
                        elif isinstance(parsed, dict):
                            options_list = [f"{k}) {v}" for k, v in parsed.items()]
                        else:
                            options_list = [raw_options]
                    except Exception:
                        options_list = [opt.strip() for opt in raw_options.split("|") if opt.strip()]

            clean_user = clean_opt(user_raw_ans)
            clean_db = clean_opt(db_correct)

            # 1. Determine user selected option index (0 to len-1)
            user_idx = -1
            if len(user_raw_ans) == 1 and user_raw_ans.upper() in "ABCD":
                u_idx = ord(user_raw_ans.upper()) - ord('A')
                if 0 <= u_idx < len(options_list):
                    user_idx = u_idx
            if user_idx == -1 and clean_user:
                for idx, opt in enumerate(options_list):
                    if clean_opt(opt) == clean_user:
                        user_idx = idx
                        break

            # 2. Determine correct option index (0 to len-1)
            correct_idx = -1
            if len(db_correct) == 1 and db_correct.upper() in "ABCD":
                c_idx = ord(db_correct.upper()) - ord('A')
                if 0 <= c_idx < len(options_list):
                    correct_idx = c_idx
            if correct_idx == -1 and clean_db:
                for idx, opt in enumerate(options_list):
                    c_opt = clean_opt(opt)
                    if c_opt == clean_db or clean_db == c_opt or (len(clean_db) > 2 and clean_db in c_opt):
                        correct_idx = idx
                        break

            # 3. Determine correctness
            is_correct = False
            if user_idx >= 0 and correct_idx >= 0:
                is_correct = (user_idx == correct_idx)
            elif clean_user and clean_db and clean_user == clean_db:
                is_correct = True
            elif user_raw_ans.lower() == db_correct.lower():
                is_correct = True
            elif user_idx >= 0 and clean_opt(options_list[user_idx]) == clean_db:
                is_correct = True
            elif correct_idx >= 0 and clean_opt(options_list[correct_idx]) == clean_user:
                is_correct = True

            # 4. Formatted Display Strings (e.g., 'C) Prime numbers' and 'D) Triangular numbers')
            if user_idx >= 0 and user_idx < len(options_list):
                opt_str = options_list[user_idx].strip()
                letter = chr(65 + user_idx)
                if not re.match(r'^[A-Da-d][\).\:\-]', opt_str):
                    formatted_user_ans = f"{letter}) {opt_str}"
                else:
                    formatted_user_ans = opt_str
                user_letter = letter
            elif user_raw_ans:
                formatted_user_ans = user_raw_ans
                user_letter = user_raw_ans if len(user_raw_ans) == 1 else None
            else:
                formatted_user_ans = "Not Attempted"
                user_letter = None

            if correct_idx >= 0 and correct_idx < len(options_list):
                opt_str = options_list[correct_idx].strip()
                letter = chr(65 + correct_idx)
                if not re.match(r'^[A-Da-d][\).\:\-]', opt_str):
                    formatted_correct_ans = f"{letter}) {opt_str}"
                else:
                    formatted_correct_ans = opt_str
                corr_letter = letter
            else:
                formatted_correct_ans = db_correct
                corr_letter = db_correct if len(db_correct) == 1 else None

            if is_correct:
                score += 1

            review.append({
                "questionId": q_id,
                "questionText": row["question"],
                "options": options_list,
                "userAnswer": formatted_user_ans,
                "userAnswerLetter": user_letter,
                "correctAnswer": formatted_correct_ans,
                "correctAnswerLetter": corr_letter,
                "isCorrect": is_correct,
                "explanation": row["explanation"] or "Derived from standard curriculum textbook concepts.",
            })

        total = len(review)
        percentage = round((score / total) * 100, 1) if total > 0 else 0

        print("\n" + "=" * 78, flush=True)
        print("⚡ [QUICK DEMO MOCK TEST - PYTHON EVALUATION RESULT]", flush=True)
        print(f">> Questions Attempted: {len(user_answers)} / {total} | Raw DB IDs: {raw_ids}", flush=True)
        print(f">> Grading Engine     : In-Memory Python Rubric (Zero LLM, Zero DB Writes)", flush=True)
        print(f">> Score Outcome      : {score} / {total} ({percentage}%) | Status: {'PASSED (>=60%)' if percentage >= 60 else 'FAILED (<60%)'}", flush=True)
        for r in review:
            icon = "✓ Correct" if r["isCorrect"] else "✗ Incorrect"
            print(f"   * [{icon}] DB_ID: {r['questionId']} | User Answer: '{r['userAnswer']}' | Correct Answer: '{r['correctAnswer']}'", flush=True)
        print("=" * 78 + "\n", flush=True)

        return success({
            "score": score,
            "totalMarks": total,
            "percentage": percentage,
            "passed": percentage >= 60,
            "review": review,
        }, 200)


