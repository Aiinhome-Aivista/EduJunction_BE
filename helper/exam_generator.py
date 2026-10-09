from utils.date_helper import now_ist
import json
import random
import uuid
from datetime import datetime

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from helper import fallback_exam_bank, rag_engine
from helper.question_quality_guard import llm_audit_and_curate_questions, filter_valid_questions
from model import mistral_client
from model.models import Exam, Question, Mastery, ExamConfig, QuestionEvaluation, ExamSubmission
from prompts import exam_generation_prompt
from utils.ai_schemas import GeneratedExamSchema
from utils.constants import (
    DEFAULT_EXAM_QUESTION_COUNT, DEFAULT_EXAM_TOTAL_MARKS, DEFAULT_EXAM_TIME_LIMIT_MINUTES,
)
from utils.logger import logger


def get_exam_config_for_class(session: Session, class_grade: str = "ALL") -> dict:
    """Fetches total_marks, duration_minutes, total_questions from exam_config table."""
    try:
        config = session.query(ExamConfig).filter(
            (ExamConfig.class_grade == class_grade) | (ExamConfig.class_grade == "ALL")
        ).order_by(
            (ExamConfig.class_grade == class_grade).desc()
        ).first()
        if config:
            return {
                "total_marks": config.total_marks or 10,
                "duration_minutes": config.duration_minutes or 15,
                "total_questions": config.total_questions or 10,
            }
    except Exception as e:
        logger.warning(f"Could not fetch exam_config from DB: {e}")

    return {
        "total_marks": 10,
        "duration_minutes": 15,
        "total_questions": 10,
    }


def get_student_weak_chapter_or_topic(session: Session, student_id: int | str, subject: str = None, board: str = None, class_grade: str = None) -> tuple[str | None, str | None]:
    """Finds the most recent chapter/topic and difficulty where the student answered incorrectly or struggled,
    strictly verifying that the topic genuinely belongs to the requested subject, class and board in topic_master."""
    if not subject:
        return None, None

    try:
        # Fetch genuine topics for this subject from taxonomy
        valid_topics = session.execute(
            text("""
                SELECT t.topic_name
                FROM topic_master t
                JOIN chapter_master ch ON t.chapter_id = ch.id
                JOIN subject_master s ON ch.subject_id = s.id
                JOIN class_master c ON s.class_id = c.id
                JOIN board_master b ON s.board_id = b.id
                WHERE LOWER(s.subject_name) LIKE LOWER(:subj_pattern)
                  AND (LOWER(b.board_name) LIKE LOWER(:board_pattern) OR :clean_board = '')
                  AND (LOWER(c.class_name) LIKE LOWER(:class_pattern) OR :clean_class = '')
            """),
            {
                "subj_pattern": f"%{subject}%",
                "board_pattern": f"%{board}%" if board else "",
                "class_pattern": f"%{class_grade.replace('Class', '').strip()}%" if class_grade else "",
                "clean_board": board or "",
                "clean_class": class_grade or "",
            }
        ).fetchall()

        valid_topic_set = {row[0].strip().lower() for row in valid_topics if row[0]}
        if not valid_topic_set:
            return None, None

        # 1. Check recent incorrect questions matching genuine taxonomy topic
        subquery = session.execute(
            text("""
                SELECT q.topic, q.difficulty
                FROM question_evaluations qe
                JOIN exam_submissions es ON qe.submission_id = es.id
                JOIN exams e ON es.exam_id = e.id
                JOIN questions q ON qe.question_id = q.id
                WHERE es.student_id = :stu_id
                  AND qe.is_correct = 0
                  AND LOWER(e.subject) LIKE LOWER(:subj_pattern)
                ORDER BY es.submitted_at DESC
                LIMIT 15
            """),
            {"stu_id": student_id, "subj_pattern": f"%{subject}%"}
        ).fetchall()

        for row in subquery:
            if row[0] and row[0].strip().lower() in valid_topic_set:
                return row[0].strip(), row[1] or "simple"

        # 2. Check student mastery records matching genuine taxonomy topic
        mastery_rows = session.execute(
            text("""
                SELECT topic, mastery_score
                FROM mastery
                WHERE student_id = :stu_id
                  AND mastery_score < 60
                ORDER BY mastery_score ASC
                LIMIT 10
            """),
            {"stu_id": student_id}
        ).fetchall()

        for row in mastery_rows:
            if row[0] and row[0].strip().lower() in valid_topic_set:
                return row[0].strip(), "simple"

    except Exception as e:
        logger.warning(f"Error resolving student weakness: {e}")

    return None, None


def get_weak_topics(session: Session, student_id: str, threshold: float = 75.0) -> list[str]:
    rows = session.query(Mastery).filter(
        Mastery.student_id == student_id, Mastery.mastery_score < threshold
    ).all()
    return [row.topic for row in rows]


from helper.question_quality_guard import filter_valid_questions


def get_student_seen_question_ids(session: Session, student_id: str | int) -> set:
    """Returns set of question IDs or texts the student has already answered in past exams."""
    try:
        from model.models import QuestionEvaluation, ExamSubmission, Student
        stu = session.query(Student).filter((Student.id == student_id) | (Student.user_id == student_id)).first()
        if not stu:
            return set()
        
        seen = set()
        evals = session.query(QuestionEvaluation.question_id).join(
            ExamSubmission, ExamSubmission.id == QuestionEvaluation.submission_id
        ).filter(ExamSubmission.student_id == stu.id).all()
        for row in evals:
            if row[0]:
                seen.add(str(row[0]))
        return seen
    except Exception as e:
        logger.debug(f"Failed to fetch student seen question IDs: {e}")
        return set()


def get_student_weak_question_ids(session: Session, student_id: str | int) -> set:
    """Returns set of question IDs where student made mistakes (is_correct == False) in past exams."""
    try:
        from model.models import QuestionEvaluation, ExamSubmission, Student
        stu = session.query(Student).filter((Student.id == student_id) | (Student.user_id == student_id)).first()
        if not stu:
            return set()
        
        weak = set()
        evals = session.query(QuestionEvaluation.question_id).join(
            ExamSubmission, ExamSubmission.id == QuestionEvaluation.submission_id
        ).filter(ExamSubmission.student_id == stu.id, QuestionEvaluation.is_correct == False).all()
        for row in evals:
            if row[0]:
                weak.add(str(row[0]))
        return weak
    except Exception as e:
        logger.debug(f"Failed to fetch student weak question IDs: {e}")
        return set()


def _fetch_questions_from_db(
    session: Session,
    *,
    board: str,
    class_grade: str,
    subject: str,
    difficulty: str,
    chapter_topic: str | None = None,
    branch: str | None = None,
    chapter_ids: list | None = None,
    student_id: str | int | None = None,
    target_count: int = 10,
) -> list[dict]:
    """Fetches real-time curriculum questions from question_master, prioritizing
    high-importance, unique (unseen) questions with quality guardrails.
    """
    clean_board = (board or "").strip()
    clean_class = (class_grade or "").strip()
    clean_subj = (subject or "").strip()
    clean_diff = (difficulty or "medium").strip()
    clean_topic = (chapter_topic or "").strip()
    clean_branch = (branch or "").strip()

    seen_ids = get_student_seen_question_ids(session, student_id) if student_id else set()
    weak_ids = get_student_weak_question_ids(session, student_id) if student_id else set()

    sp_rows = []

    # 0. Branch-specific query for CBSE Science (Physics, Chemistry, Biology)
    if clean_branch in ["Physics", "Chemistry", "Biology"] and clean_subj.lower().strip() == "science":
        try:
            from utils.constants import SCIENCE_BRANCH_KEYWORDS
            keywords = SCIENCE_BRANCH_KEYWORDS.get(clean_branch, [])

            if chapter_ids and isinstance(chapter_ids, (list, tuple)) and len(chapter_ids) > 0:
                branch_sql = text("""
                    SELECT 
                        q.id AS question_id,
                        q.question AS question_text,
                        q.options,
                        q.correct_answer,
                        q.explanation,
                        q.marks,
                        q.image_url,
                        COALESCE(q.importance_score, 7.00) AS importance_score,
                        COALESCE(qt.question_type_name, 'MCQ') AS question_type,
                        COALESCE(dl.difficulty_level_name, 'medium') AS difficulty,
                        s.subject_name,
                        ch.chapter_name,
                        t.topic_name,
                        b.board_name,
                        c.class_name
                    FROM question_master q
                    JOIN topic_master t ON q.topic_id = t.id
                    JOIN chapter_master ch ON t.chapter_id = ch.id
                    JOIN subject_master s ON ch.subject_id = s.id
                    JOIN board_master b ON s.board_id = b.id
                    JOIN class_master c ON s.class_id = c.id
                    JOIN question_type_master qt ON q.question_type_id = qt.id
                    LEFT JOIN difficulty_level_master dl ON q.difficulty_level_id = dl.id
                    WHERE q.is_active = 1
                      AND ch.id IN :ch_ids
                    ORDER BY 
                      COALESCE(q.importance_score, 7.00) DESC,
                      RAND()
                    LIMIT 50
                """)
                branch_rows = session.execute(branch_sql, {"ch_ids": tuple(chapter_ids)}).mappings().fetchall()
                if branch_rows:
                    sp_rows = branch_rows
            elif keywords:
                like_clauses = " OR ".join([f"LOWER(ch.chapter_name) LIKE :kw_{i} OR LOWER(t.topic_name) LIKE :kw_{i}" for i in range(len(keywords))])
                params = {
                    "clean_board": f"%{clean_board}%" if clean_board else "",
                    "clean_class": f"%{clean_class.replace('Class', '').strip()}%" if clean_class else "",
                    "subject_pattern": f"%{clean_subj}%",
                }
                for i, kw in enumerate(keywords):
                    params[f"kw_{i}"] = f"%{kw}%"

                branch_sql = text(f"""
                    SELECT 
                        q.id AS question_id,
                        q.question AS question_text,
                        q.options,
                        q.correct_answer,
                        q.explanation,
                        q.marks,
                        q.image_url,
                        COALESCE(q.importance_score, 7.00) AS importance_score,
                        COALESCE(qt.question_type_name, 'MCQ') AS question_type,
                        COALESCE(dl.difficulty_level_name, 'medium') AS difficulty,
                        s.subject_name,
                        ch.chapter_name,
                        t.topic_name,
                        b.board_name,
                        c.class_name
                    FROM question_master q
                    JOIN topic_master t ON q.topic_id = t.id
                    JOIN chapter_master ch ON t.chapter_id = ch.id
                    JOIN subject_master s ON ch.subject_id = s.id
                    JOIN board_master b ON s.board_id = b.id
                    JOIN class_master c ON s.class_id = c.id
                    JOIN question_type_master qt ON q.question_type_id = qt.id
                    LEFT JOIN difficulty_level_master dl ON q.difficulty_level_id = dl.id
                    WHERE q.is_active = 1
                      AND (LOWER(s.subject_name) LIKE LOWER(:subject_pattern))
                      AND (LOWER(b.board_name) LIKE LOWER(:clean_board) OR :clean_board = '')
                      AND (LOWER(c.class_name) LIKE LOWER(:clean_class) OR :clean_class = '')
                      AND ({like_clauses})
                    ORDER BY 
                      COALESCE(q.importance_score, 7.00) DESC,
                      RAND()
                    LIMIT 50
                """)
                branch_rows = session.execute(branch_sql, params).mappings().fetchall()
                if branch_rows:
                    sp_rows = branch_rows
        except Exception as e:
            logger.warning(f"Branch query failed for {clean_branch}: {e}")

    # If specific topic requested for remedial sprint, try targeted topic query first (if not already filtered by branch)
    if clean_topic and (not sp_rows or not clean_branch):
        try:
            topic_rows = session.execute(
                text("""
                    SELECT 
                        q.id AS question_id,
                        q.question AS question_text,
                        q.options,
                        q.correct_answer,
                        q.explanation,
                        q.marks,
                        q.image_url,
                        COALESCE(q.importance_score, 7.00) AS importance_score,
                        COALESCE(qt.question_type_name, 'MCQ') AS question_type,
                        COALESCE(dl.difficulty_level_name, 'medium') AS difficulty,
                        s.subject_name,
                        ch.chapter_name,
                        t.topic_name,
                        b.board_name,
                        c.class_name
                    FROM question_master q
                    JOIN topic_master t ON q.topic_id = t.id
                    JOIN chapter_master ch ON t.chapter_id = ch.id
                    JOIN subject_master s ON ch.subject_id = s.id
                    JOIN board_master b ON s.board_id = b.id
                    JOIN class_master c ON s.class_id = c.id
                    JOIN question_type_master qt ON q.question_type_id = qt.id
                    LEFT JOIN difficulty_level_master dl ON q.difficulty_level_id = dl.id
                    WHERE q.is_active = 1
                      AND (
                          LOWER(t.topic_name) LIKE LOWER(:topic_pattern)
                          OR LOWER(:clean_topic) LIKE CONCAT('%', LOWER(t.topic_name), '%')
                          OR LOWER(ch.chapter_name) LIKE LOWER(:topic_pattern)
                      )
                    ORDER BY 
                      COALESCE(q.importance_score, 7.00) DESC,
                      CASE 
                        WHEN LOWER(TRIM(c.class_name)) = LOWER(TRIM(:class_grade)) AND LOWER(TRIM(s.subject_name)) = LOWER(TRIM(:subject)) THEN 1
                        WHEN LOWER(TRIM(s.subject_name)) = LOWER(TRIM(:subject)) THEN 2
                        ELSE 3
                      END,
                      RAND()
                    LIMIT 40
                """),
                {
                    "class_grade": clean_class,
                    "subject": clean_subj,
                    "clean_topic": clean_topic,
                    "topic_pattern": f"%{clean_topic}%",
                }
            ).mappings().fetchall()
            if topic_rows:
                sp_rows = topic_rows
        except Exception as e:
            logger.warning(f"Topic query failed, falling back to stored procedure: {e}")

    if not sp_rows or len(sp_rows) < target_count:
        try:
            sp_rows = session.execute(
                text("CALL sp_generate_exam_from_db(:board, :class_grade, :subject, :difficulty)"),
                {
                    "board": clean_board,
                    "class_grade": clean_class,
                    "subject": clean_subj,
                    "difficulty": clean_diff,
                },
            ).mappings().fetchall()
        except Exception as e:
            logger.warning(f"Stored procedure call skipped or failed: {e}")
            sp_rows = []

    # If SP or topic query is still insufficient, query question_master directly by Board + Class + Subject
    if not sp_rows or len(sp_rows) < target_count:
        try:
            direct_rows = session.execute(
                text("""
                    SELECT 
                        q.id AS question_id,
                        q.question AS question_text,
                        q.options,
                        q.correct_answer,
                        q.explanation,
                        q.marks,
                        q.image_url,
                        COALESCE(q.importance_score, 7.00) AS importance_score,
                        COALESCE(qt.question_type_name, 'MCQ') AS question_type,
                        COALESCE(dl.difficulty_level_name, 'medium') AS difficulty,
                        s.subject_name,
                        ch.chapter_name,
                        t.topic_name,
                        b.board_name,
                        c.class_name
                    FROM question_master q
                    JOIN topic_master t ON q.topic_id = t.id
                    JOIN chapter_master ch ON t.chapter_id = ch.id
                    JOIN subject_master s ON ch.subject_id = s.id
                    JOIN board_master b ON s.board_id = b.id
                    JOIN class_master c ON s.class_id = c.id
                    JOIN question_type_master qt ON q.question_type_id = qt.id
                    LEFT JOIN difficulty_level_master dl ON q.difficulty_level_id = dl.id
                    WHERE q.is_active = 1
                      AND (LOWER(b.board_name) LIKE LOWER(:board_pattern) OR :clean_board = '')
                      AND (LOWER(c.class_name) LIKE LOWER(:class_pattern) OR :clean_class = '')
                      AND (LOWER(s.subject_name) LIKE LOWER(:subject_pattern))
                    ORDER BY 
                      COALESCE(q.importance_score, 7.00) DESC,
                      RAND()
                    LIMIT 50
                """),
                {
                    "board_pattern": f"%{clean_board}%",
                    "class_pattern": f"%{clean_class.replace('Class', '').strip()}%",
                    "subject_pattern": f"%{clean_subj}%",
                    "clean_board": clean_board,
                    "clean_class": clean_class,
                }
            ).mappings().fetchall()
            if direct_rows:
                sp_rows = direct_rows
        except Exception as e:
            logger.warning(f"Direct question_master query failed: {e}")

    if not sp_rows:
        return []

    # Filter only questions that match the requested subject
    subject_matched_rows = []
    clean_subj_lower = clean_subj.lower()
    for q in sp_rows:
        q_subj = str(q.get("subject_name") or q.get("subject") or q.get("topic_name") or "").lower()
        if not q_subj or clean_subj_lower in q_subj or q_subj in clean_subj_lower:
            subject_matched_rows.append(q)
        elif "comp" in clean_subj_lower and "comp" in q_subj:
            subject_matched_rows.append(q)
        elif "math" in clean_subj_lower and "math" in q_subj:
            subject_matched_rows.append(q)
        elif "eng" in clean_subj_lower and "eng" in q_subj:
            subject_matched_rows.append(q)
        elif "sci" in clean_subj_lower and "sci" in q_subj:
            subject_matched_rows.append(q)

    # Format questions into standard structure
    formatted_questions = []
    for idx, q in enumerate(subject_matched_rows):
        raw_options = q.get("options")
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

        raw_type = str(q.get("question_type", "mcq")).lower()
        has_real_options = bool(options_list and isinstance(options_list, list) and len(options_list) >= 2)

        if has_real_options:
            final_type = "mcq"
            final_marks = 1
        else:
            options_list = None
            if "num" in raw_type:
                final_type = "numerical"
                final_marks = 1
            elif "obj" in raw_type:
                final_type = "objective"
                final_marks = 1
            else:
                final_type = "saq"
                final_marks = 2

        img_url = q.get("image_url") or q.get("imageUrl") or None
        formatted_questions.append({
            "id": q.get("question_id") or q.get("id"),
            "questionNumber": idx + 1,
            "type": final_type,
            "questionText": q.get("question_text", f"Question {idx + 1}"),
            "options": options_list,
            "correctAnswer": str(q.get("correct_answer", "A")),
            "explanation": q.get("explanation") or "Answer derived from standard curriculum textbook concepts.",
            "topic": q.get("topic_name") or q.get("chapter_name") or clean_subj,
            "difficulty": q.get("difficulty") or clean_diff,
            "marks": final_marks,
            "image_url": img_url,
            "imageUrl": img_url,
            "importance_score": float(q.get("importance_score") or 7.00),
            "origin": "db",
        })

    # Apply Quality Guardrails (Missing images, Broken options, Cross-subject leakage)
    valid_questions = filter_valid_questions(formatted_questions, requested_subject=clean_subj)

    # Separate into Unseen (Priority 1), Weak Concept Reinforcement (Priority 2), and Seen
    unseen_pool = []
    weak_pool = []
    other_pool = []

    for q in valid_questions:
        qid_str = str(q.get("id") or "")
        qtext_str = str(q.get("questionText") or "")
        
        is_seen = (qid_str and qid_str in seen_ids) or (qtext_str and qtext_str in seen_ids)
        is_weak = (qid_str and qid_str in weak_ids) or (qtext_str and qtext_str in weak_ids)

        if not is_seen:
            unseen_pool.append(q)
        elif is_weak:
            weak_pool.append(q)
        else:
            other_pool.append(q)

    # Sort each pool by importance_score DESC
    unseen_pool.sort(key=lambda x: x.get("importance_score", 7.00), reverse=True)
    weak_pool.sort(key=lambda x: x.get("importance_score", 7.00), reverse=True)
    other_pool.sort(key=lambda x: x.get("importance_score", 7.00), reverse=True)

    final_selected = []

    # Priority 1: Fill as many as possible with Unseen questions
    if unseen_pool:
        # Reserve at most 1 slot for high-importance reinforcement if weak pool has high-yield questions
        unseen_take = target_count - (1 if weak_pool and len(unseen_pool) >= target_count else 0)
        final_selected.extend(unseen_pool[:unseen_take])

    # Priority 2: Add 1 smart reinforcement question if student previously struggled with it
    if len(final_selected) < target_count and weak_pool:
        needed = target_count - len(final_selected)
        final_selected.extend(weak_pool[:min(2, needed)])

    # Priority 3: If still short, backfill from other high-importance seen questions
    if len(final_selected) < target_count and other_pool:
        needed = target_count - len(final_selected)
        final_selected.extend(other_pool[:needed])

    return final_selected

    return formatted_questions


import re

def _get_grade_tier(class_grade: str) -> str:
    cg = (class_grade or "").lower().strip()
    if any(k in cg for k in ["neet", "iit", "jee"]):
        return "senior"
    match = re.search(r'(?:class|grade)?\s*(\d+)', cg)
    if match:
        cnum = int(match.group(1))
        if 1 <= cnum <= 4:
            return "kid"
        if 5 <= cnum <= 10:
            return "secondary"
        if cnum >= 11:
            return "senior"
    if any(k in cg for k in ["primary", "kindergarten", "ukg", "lkg"]):
        return "kid"
    if any(k in cg for k in ["senior", "higher secondary", "isc"]):
        return "senior"
    return "secondary"


def generate_exam(
    session: Session,
    *,
    student_id: str,
    student_name: str,
    board: str,
    class_grade: str,
    subject: str,
    difficulty: str,
    question_count: int | None = None,
    time_limit_minutes: int | None = None,
    title: str | None = None,
    is_assigned: bool = False,
    chapter_topic: str | None = None,
    branch: str | None = None,
    chapter_ids: list | None = None,
) -> Exam:
    if not chapter_topic and not branch:
        weak_ch, weak_df = get_student_weak_chapter_or_topic(session, student_id, subject=subject, board=board, class_grade=class_grade)
        if weak_ch:
            chapter_topic = weak_ch

    weak_topics = get_weak_topics(session, student_id)
    matching_runbooks = rag_engine.retrieve_runbooks(session, board, class_grade, subject)
    rag_context = rag_engine.runbooks_to_context(matching_runbooks, difficulty)

    # Dynamic Exam Config from exam_config Table
    cfg = get_exam_config_for_class(session, class_grade)
    cfg_marks = cfg.get("total_marks", 10)
    cfg_duration = cfg.get("duration_minutes", 15)
    cfg_q_count = cfg.get("total_questions", 10)

    # Determine class-based marks blueprint
    tier = _get_grade_tier(class_grade)
    cg_lower = (class_grade or "").lower()
    is_assigned_challenge = bool(is_assigned)

    ref_links = matching_runbooks[0].curated_reference_urls if matching_runbooks else []

    if is_assigned_challenge:
        # Parent Challenge: target_count questions, ALL 100% Genuine MCQs (1 Mark each)
        target_question_count = question_count or 10
        target_mcq_count = target_question_count
        target_saq_count = 0
        target_total_marks = target_question_count * 1
        default_duration_mins = max(10, target_question_count * 1)
    elif tier == "kid":
        # Class 1-4: Exactly 5 MCQs (1 Mark each) = 5 Marks Total
        target_question_count = 5
        target_mcq_count = 5
        target_saq_count = 0
        target_total_marks = 5
        default_duration_mins = 10
    elif tier == "senior":
        # Class 11-12 / NEET / IIT: Exactly 10 Questions (2 Marks each) = 20 Marks Total
        target_question_count = 10
        target_mcq_count = 5
        target_saq_count = 5
        target_total_marks = 20
        default_duration_mins = 25
    else:
        # Class 5 to 10: Exactly 10 Questions = 15 Marks Total (5 MCQs @ 1 Mark + 5 SAQs @ 2 Marks)
        target_question_count = 10
        target_mcq_count = 5
        target_saq_count = 5
        target_total_marks = 15
        default_duration_mins = cfg_duration or 15

    # ------------------------------------------------------------
    # 1. Primary Generation Layer: Relational Database Question Bank
    # ------------------------------------------------------------
    db_questions = _fetch_questions_from_db(
        session,
        board=board,
        class_grade=class_grade,
        subject=subject,
        difficulty=difficulty,
        chapter_topic=chapter_topic,
        branch=branch,
        chapter_ids=chapter_ids,
        student_id=student_id,
        target_count=target_question_count * 2,
    )
    source = "rag-engine-curated"
    llm_used = False

    # Separate DB pool into genuine MCQs (options >= 2) and SAQs (no options)
    db_mcq_pool = [q for q in db_questions if q.get("options") and isinstance(q.get("options"), list) and len(q.get("options")) >= 2]
    db_saq_pool = [q for q in db_questions if not (q.get("options") and isinstance(q.get("options"), list) and len(q.get("options")) >= 2)]

    # 1. Fill MCQ Slots
    final_mcq_list = list(db_mcq_pool[:target_mcq_count])
    if len(final_mcq_list) < target_mcq_count:
        needed_mcqs = target_mcq_count - len(final_mcq_list)
        fb_mcqs = fallback_exam_bank.build_fallback_questions(
            board=board,
            subject=subject,
            difficulty=difficulty,
            ref_links=ref_links,
            class_grade=class_grade,
            limit=needed_mcqs * 2,
            force_mcq=True,
            branch=branch,
        )
        existing_texts = {q.get("questionText", "") for q in final_mcq_list}
        for fb_q in fb_mcqs:
            if fb_q.get("questionText") not in existing_texts and fb_q.get("options") and len(fb_q.get("options", [])) >= 2:
                fb_q["origin"] = "fallback"
                final_mcq_list.append(fb_q)
                if len(final_mcq_list) >= target_mcq_count:
                    break

    # 2. Fill SAQ Slots (if any)
    final_saq_list = list(db_saq_pool[:target_saq_count])
    if len(final_saq_list) < target_saq_count:
        # Convert extra DB MCQs to SAQs if available
        unused_mcqs = [q for q in db_mcq_pool if q not in final_mcq_list]
        for q in unused_mcqs:
            q_copy = dict(q)
            q_copy["options"] = None
            q_copy["type"] = "saq"
            final_saq_list.append(q_copy)
            if len(final_saq_list) >= target_saq_count:
                break

    if len(final_saq_list) < target_saq_count:
        needed_saqs = target_saq_count - len(final_saq_list)
        fb_saqs = fallback_exam_bank.build_fallback_questions(
            board=board,
            subject=subject,
            difficulty=difficulty,
            ref_links=ref_links,
            class_grade=class_grade,
            limit=needed_saqs * 2,
            force_mcq=False,
            branch=branch,
        )
        existing_texts = {q.get("questionText", "") for q in final_saq_list}
        for fb_q in fb_saqs:
            if fb_q.get("questionText") not in existing_texts:
                fb_q_copy = dict(fb_q)
                fb_q_copy["options"] = None
                fb_q_copy["type"] = "saq"
                fb_q_copy["origin"] = "fallback"
                final_saq_list.append(fb_q_copy)
                if len(final_saq_list) >= target_saq_count:
                    break

    # 3. Assemble and apply exact blueprint marks
    questions_data = []

    # Add MCQs
    for q in final_mcq_list[:target_mcq_count]:
        q["type"] = "mcq"
        if tier == "senior":
            q["marks"] = 2
        else:
            q["marks"] = 1
        questions_data.append(q)

    # Add SAQs
    for q in final_saq_list[:target_saq_count]:
        q["type"] = "saq"
        q["options"] = None
        q["marks"] = 2
        questions_data.append(q)

    # Re-index questionNumber and calculate final marks
    for idx, q in enumerate(questions_data):
        q["questionNumber"] = idx + 1

    calculated_marks = sum(int(q.get("marks", 1)) for q in questions_data)

    if is_assigned_challenge:
        exam_title = title or f"{class_grade} {board} {subject} ({difficulty.upper()}) Assigned {calculated_marks}-Mark Challenge"
    else:
        if title:
            exam_title = title
        elif chapter_topic:
            exam_title = f"{class_grade} {board} {subject}: {chapter_topic} Remedial Sprint ({calculated_marks} Marks)"
        elif branch and branch.lower() != "all":
            exam_title = f"{class_grade} {board} {subject} ({branch}) ({difficulty.upper()}) {calculated_marks}-Mark Exam"
        else:
            exam_title = f"{class_grade} {board} {subject} ({difficulty.upper()}) {calculated_marks}-Mark Exam"

    # Compute 100% Dynamic Origins Breakdown
    final_db_count = sum(1 for q in questions_data if q.get("origin") == "db")
    final_fallback_count = sum(1 for q in questions_data if q.get("origin") == "fallback" or str(q.get("id", "")).startswith("fb_"))

    # Dynamic Source Label
    if final_db_count >= len(questions_data):
        source_label = f"DATABASE ({final_db_count}/{len(questions_data)} from question_master)"
    elif final_fallback_count >= len(questions_data):
        source_label = f"FALLBACK_EXAM_BANK ({final_fallback_count}/{len(questions_data)} from fallback_exam_bank.py)"
    else:
        source_label = f"HYBRID ({final_db_count} from Database + {final_fallback_count} from Fallback)"

    # Dynamic Quality Status Label
    if final_db_count >= len(questions_data):
        quality_label = "100% VERIFIED DATABASE CURRICULUM (Instant 0.05s Load)"
    elif final_fallback_count >= len(questions_data):
        quality_label = f"100% STANDARD FALLBACK BANK ({final_fallback_count} Pre-curated Questions)"
    else:
        quality_label = f"HYBRID CURATION ({final_db_count} Database + {final_fallback_count} Fallback Bank)"

    mcq_count = sum(1 for q in questions_data if q.get("type") == "mcq")
    saq_count = sum(1 for q in questions_data if q.get("type") == "saq")
    other_count = len(questions_data) - mcq_count - saq_count

    # Terminal Log Banner (Windows console safe & 100% Dynamic)
    print("\n" + "=" * 78)
    print("[*] [EXAM GENERATION LOG]")
    print(f">> Candidate : {student_name} (ID: {student_id})")
    print(f">> Target    : {board} | {class_grade} | {subject} (Difficulty: {difficulty})")
    print(f">> Mode      : {'PARENT ASSIGNED CHALLENGE' if is_assigned_challenge else 'STUDENT DIAGNOSTIC BLUEPRINT'}")
    print(f">> SOURCE    : >>> {source_label} <<<")
    print(f">> Quality   : >>> {quality_label} <<<")
    print(f">> Breakdown : Database: {final_db_count} Qs | Fallback: {final_fallback_count} Qs | Total: {len(questions_data)} Qs")
    print(f">> Types     : {mcq_count} MCQs @ 1M, {saq_count} SAQs @ 2M{f', {other_count} Other' if other_count > 0 else ''}")
    print(f">> Marks     : {calculated_marks} Marks Total | Time: {time_limit_minutes or default_duration_mins} Mins")
    print("=" * 78 + "\n")

    exam_duration = time_limit_minutes or default_duration_mins

    exam = Exam(
        id=str(uuid.uuid4()),
        student_id=student_id,
        title=exam_title,
        board=board,
        class_grade=class_grade,
        subject=subject,
        difficulty=difficulty,
        total_marks=calculated_marks,
        question_count=len(questions_data),
        time_limit_minutes=exam_duration,
        rag_knowledge_nodes_used=[rb.chapter_name for rb in matching_runbooks],
        source=source,
        status="GENERATED",
        created_at=now_ist(),
    )
    session.add(exam)
    session.flush()

    ref_links_default = matching_runbooks[0].curated_reference_urls if matching_runbooks else []
    for idx, q in enumerate(questions_data):
        q_diff = str(q.get("difficulty") or difficulty).lower()
        if q_diff not in ("simple", "medium", "hard"):
            q_diff = "medium"

        exam.questions.append(
            Question(
                id=str(uuid.uuid4()),
                question_number=idx + 1,
                type=q.get("type", "mcq"),
                question_text=q.get("questionText", f"Question {idx + 1}"),
                options=q.get("options"),
                correct_answer=str(q.get("correctAnswer", "A")),
                explanation=q.get("explanation", "Detailed step explanation."),
                difficulty=q_diff,
                marks=int(q.get("marks", 1)),
                topic=q.get("topic", subject),
                reference_links=ref_links_default,
                hint=q.get("hint"),
                image_url=q.get("image_url") or q.get("imageUrl") or None,
                importance_score=q.get("importance_score", 7.00),
            )
        )
    session.flush()

    return exam


def exam_to_public_dict(exam: Exam) -> dict:
    """Client-facing exam shape — never includes correct_answer or explanation."""
    return {
        "id": exam.id,
        "title": exam.title,
        "board": exam.board,
        "classGrade": exam.class_grade,
        "subject": exam.subject,
        "difficulty": exam.difficulty,
        "totalMarks": exam.total_marks,
        "questionCount": exam.question_count,
        "timeLimitMinutes": exam.time_limit_minutes,
        "ragKnowledgeNodesUsed": exam.rag_knowledge_nodes_used or [],
        "createdAt": exam.created_at.isoformat(),
        "questions": [
            {
                "id": q.id,
                "questionNumber": q.question_number,
                "type": q.type,
                "questionText": q.question_text,
                "options": q.options,
                "difficulty": q.difficulty,
                "marks": q.marks,
                "topic": q.topic,
                "hint": q.hint,
                "image_url": q.image_url,
                "imageUrl": q.image_url,
                # NOTE: correctAnswer / explanation deliberately omitted (§14).
            }
            for q in sorted(exam.questions, key=lambda x: x.question_number)
        ],
    }
