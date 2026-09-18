from utils.date_helper import now_ist
import json
import random
import uuid
from datetime import datetime

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from helper import fallback_exam_bank, rag_engine
from model import mistral_client
from model.models import Exam, Question, Mastery
from prompts import exam_generation_prompt
from utils.ai_schemas import GeneratedExamSchema
from utils.constants import (
    DEFAULT_EXAM_QUESTION_COUNT, DEFAULT_EXAM_TOTAL_MARKS, DEFAULT_EXAM_TIME_LIMIT_MINUTES,
)
from utils.logger import logger


def get_weak_topics(session: Session, student_id: str, threshold: float = 75.0) -> list[str]:
    rows = session.query(Mastery).filter(
        Mastery.student_id == student_id, Mastery.mastery_score < threshold
    ).all()
    return [row.topic for row in rows]


def _fetch_questions_from_db(
    session: Session,
    *,
    board: str,
    class_grade: str,
    subject: str,
    difficulty: str,
    chapter_topic: str | None = None,
) -> list[dict]:
    """Fetches real-time curriculum questions directly via Stored Procedure
    or topic-specific filtering for adaptive remedial sprints.
    """
    clean_board = (board or "").strip()
    clean_class = (class_grade or "").strip()
    clean_subj = (subject or "").strip()
    clean_diff = (difficulty or "medium").strip()
    clean_topic = (chapter_topic or "").strip()

    sp_rows = []

    # If specific topic requested for remedial sprint, try targeted topic query first
    if clean_topic:
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
                      CASE 
                        WHEN LOWER(TRIM(c.class_name)) = LOWER(TRIM(:class_grade)) AND LOWER(TRIM(s.subject_name)) = LOWER(TRIM(:subject)) THEN 1
                        WHEN LOWER(TRIM(s.subject_name)) = LOWER(TRIM(:subject)) THEN 2
                        ELSE 3
                      END,
                      RAND()
                    LIMIT 10
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

    if not sp_rows:
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
        raw_marks = int(q.get("marks", 1))

        if "saq" in raw_type or "short" in raw_type or raw_marks == 2:
            final_type = "saq"
            final_marks = 2
        elif "num" in raw_type:
            final_type = "numerical"
            final_marks = 1
        elif "logic" in raw_type:
            final_type = "logical"
            final_marks = 1
        elif "obj" in raw_type and not options_list:
            final_type = "objective"
            final_marks = 1
        else:
            final_type = "mcq"
            final_marks = 1

        formatted_questions.append({
            "questionNumber": idx + 1,
            "type": final_type,
            "questionText": q.get("question_text", f"Question {idx + 1}"),
            "options": options_list,
            "correctAnswer": str(q.get("correct_answer", "A")),
            "explanation": q.get("explanation") or "Answer derived from standard curriculum textbook concepts.",
            "topic": q.get("topic_name") or q.get("chapter_name") or clean_subj,
            "difficulty": q.get("difficulty") or clean_diff,
            "marks": final_marks,
        })

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
) -> Exam:
    weak_topics = get_weak_topics(session, student_id)
    matching_runbooks = rag_engine.retrieve_runbooks(session, board, class_grade, subject)
    rag_context = rag_engine.runbooks_to_context(matching_runbooks, difficulty)

    # Determine class-based marks blueprint
    tier = _get_grade_tier(class_grade)
    cg_lower = (class_grade or "").lower()

    if tier == "kid":
        default_q_count = 5
        default_grade_marks = 5
        default_duration_mins = 10
    elif tier == "senior":
        default_q_count = 10
        default_grade_marks = 20
        default_duration_mins = 25
    elif any(c in cg_lower for c in ["class 9", "class 10"]):
        default_q_count = 10
        default_grade_marks = 15
        default_duration_mins = 20
    else:
        default_q_count = 10
        default_grade_marks = 15
        default_duration_mins = 15

    is_assigned_challenge = bool(is_assigned)
    target_question_count = question_count or default_q_count

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
    )
    db_count = len(db_questions)
    questions_data = list(db_questions)
    source = "rag-engine-curated"
    llm_used = False

    # If DB questions found, slice or supplement
    if questions_data and len(questions_data) > target_question_count:
        questions_data = questions_data[:target_question_count]

    # ------------------------------------------------------------
    # 2. Secondary Layer: LLM + RAG (kept inactive during initial launch)
    # ------------------------------------------------------------
    USE_LLM_LAYER = False
    if (not questions_data or len(questions_data) < target_question_count) and USE_LLM_LAYER and mistral_client.is_configured():
        try:
            user_prompt = exam_generation_prompt.build_user_prompt(
                board=board, class_grade=class_grade, subject=subject, difficulty=difficulty,
                student_name=student_name, weak_topics=weak_topics, rag_context=rag_context,
            )
            raw = mistral_client.generate_json(exam_generation_prompt.SYSTEM_PROMPT, user_prompt)
            validated = GeneratedExamSchema.model_validate(raw)
            questions_data = [q.model_dump() for q in validated.questions][:target_question_count]
            source = "mistral-rag"
            llm_used = True
        except (mistral_client.MistralUnavailableError, PydanticValidationError) as exc:
            logger.error(f"Exam generation via Mistral failed, using fallback: {exc}")

    # ------------------------------------------------------------
    # 3. Deterministic Fallback Bank (Safety backup / full question complement)
    # ------------------------------------------------------------
    fallback_used = False
    if not questions_data or len(questions_data) < target_question_count:
        ref_links = matching_runbooks[0].curated_reference_urls if matching_runbooks else []
        fallback_qs = fallback_exam_bank.build_fallback_questions(
            board=board,
            subject=subject,
            difficulty=difficulty,
            ref_links=ref_links,
            class_grade=class_grade,
            limit=target_question_count,
            force_mcq=is_assigned_challenge,
        )
        fallback_used = True
        if not questions_data:
            questions_data = fallback_qs
        else:
            # Supplement remaining needed
            needed = target_question_count - len(questions_data)
            questions_data.extend(fallback_qs[:needed])

    # Re-index questionNumber
    for idx, q in enumerate(questions_data):
        q["questionNumber"] = idx + 1

    # Determine visual source label for terminal tracking
    if db_count >= len(questions_data):
        source_label = "DATABASE (question_master / sp_generate_exam_from_db)"
    elif llm_used:
        source_label = "LLM (Mistral AI Engine)"
    elif db_count == 0:
        source_label = "FALLBACK_EXAM_BANK (fallback_exam_bank.py)"
    else:
        source_label = f"HYBRID ({db_count} from Database + {len(questions_data) - db_count} from Fallback)"

    # If parent assigned challenge, enforce 100% MCQ format (1 mark each)
    if is_assigned_challenge:
        for q in questions_data:
            q["type"] = "mcq"
            q["marks"] = 1
            if not q.get("options") or len(q.get("options", [])) < 2:
                corr = q.get("correctAnswer", "A")
                q["options"] = [
                    f"A) {corr}",
                    "B) Alternative Option B",
                    "C) Alternative Option C",
                    "D) Alternative Option D",
                ]
                q["correctAnswer"] = "A"
        calculated_marks = len(questions_data)
        exam_title = title or f"{class_grade} {board} {subject} ({difficulty.upper()}) Assigned {calculated_marks}-Mark Challenge"
    else:
        # Standard Diagnostic Blueprint:
        # Class 1-4: 5 MCQs (1 Mark each) = 5 Marks Total
        # Class 5-10: 5 MCQs (1 Mark each) + 5 SAQs (2 Marks each) = 15 Marks Total
        # Class 11-12/NEET/IIT: 10 Questions (2 Marks each) = 20 Marks Total
        if tier == "kid":
            for q in questions_data:
                q["marks"] = 1
                q["type"] = "mcq"
            calculated_marks = sum(int(q.get("marks", 1)) for q in questions_data)
        elif tier == "senior":
            for q in questions_data:
                q["marks"] = 2
            calculated_marks = sum(int(q.get("marks", 2)) for q in questions_data)
        else:
            # Class 5 to 10
            for idx, q in enumerate(questions_data):
                if idx < 5:
                    q["marks"] = 1
                    q["type"] = "mcq"
                else:
                    q["marks"] = 2
                    q["type"] = "saq"
                    q["options"] = None
            calculated_marks = sum(int(q.get("marks", 1)) for q in questions_data)

        if title:
            exam_title = title
        elif chapter_topic:
            exam_title = f"{class_grade} {board} {subject}: {chapter_topic} Remedial Sprint ({calculated_marks} Marks)"
        else:
            exam_title = f"{class_grade} {board} {subject} ({difficulty.upper()}) Diagnostic {calculated_marks}-Mark Exam"

    mcq_count = sum(1 for q in questions_data if q.get("type") == "mcq")
    saq_count = sum(1 for q in questions_data if q.get("type") == "saq")
    other_count = len(questions_data) - mcq_count - saq_count

    # Terminal Log Banner (Windows console safe)
    print("\n" + "=" * 78)
    print("[*] [EXAM GENERATION LOG]")
    print(f">> Candidate : {student_name} (ID: {student_id})")
    print(f">> Target    : {board} | {class_grade} | {subject} (Difficulty: {difficulty})")
    print(f">> Mode      : {'PARENT ASSIGNED CHALLENGE' if is_assigned_challenge else 'STUDENT DIAGNOSTIC BLUEPRINT'}")
    print(f">> SOURCE    : >>> {source_label} <<<")
    print(f">> Questions : {len(questions_data)} Total ({mcq_count} MCQs @ 1M, {saq_count} SAQs @ 2M{f', {other_count} Other' if other_count > 0 else ''})")
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
                # NOTE: correctAnswer / explanation deliberately omitted (§14).
            }
            for q in sorted(exam.questions, key=lambda x: x.question_number)
        ],
    }
