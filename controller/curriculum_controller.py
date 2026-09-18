import csv
import io
import json
from flask import request, jsonify, g
from sqlalchemy import text
import pandas as pd

from database.dbConnection import get_session
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import roles_required
from utils.logger import logger
from utils.errors import AppError, NotFoundError
from utils.response import success


@token_required
@roles_required("ADMIN", "SUPER_ADMIN", "TEACHER")
def get_curriculum_tree():
    """
    Returns full hierarchical taxonomy:
    Board -> Class -> Subject -> Chapter -> Topic (with question counts)
    """
    try:
        with get_session() as session:
            sql = text("""
                SELECT 
                    b.id AS board_id, b.board_name,
                    c.id AS class_id, c.class_name,
                    s.id AS subject_id, s.subject_name,
                    ch.id AS chapter_id, ch.chapter_name,
                    t.id AS topic_id, t.topic_name,
                    COUNT(q.id) AS question_count
                FROM board_master b
                JOIN class_master c ON c.is_active = 1
                LEFT JOIN subject_master s ON (s.board_id = b.id OR (s.board_id = 1 AND NOT EXISTS (SELECT 1 FROM subject_master sm WHERE sm.board_id = b.id AND sm.class_id = c.id))) AND s.class_id = c.id AND s.is_active = 1
                LEFT JOIN chapter_master ch ON ch.subject_id = s.id AND ch.is_active = 1
                LEFT JOIN topic_master t ON t.chapter_id = ch.id AND t.is_active = 1
                LEFT JOIN question_master q ON q.topic_id = t.id AND q.is_active = 1
                WHERE b.is_active = 1
                GROUP BY b.id, b.board_name, c.id, c.class_name, s.id, s.subject_name,
                         ch.id, ch.chapter_name, t.id, t.topic_name
                ORDER BY b.id, c.id, s.subject_name, ch.id, t.id
            """)
            rows = session.execute(sql).mappings().fetchall()

            # Structure into nested hierarchy
            boards_map = {}
            for r in rows:
                b_id = r["board_id"]
                if b_id not in boards_map:
                    boards_map[b_id] = {
                        "id": b_id,
                        "board_name": r["board_name"],
                        "classes": {}
                    }

                c_id = r["class_id"]
                if c_id not in boards_map[b_id]["classes"]:
                    boards_map[b_id]["classes"][c_id] = {
                        "id": c_id,
                        "class_name": r["class_name"],
                        "subjects": {}
                    }

                s_id = r["subject_id"]
                if s_id:
                    if s_id not in boards_map[b_id]["classes"][c_id]["subjects"]:
                        boards_map[b_id]["classes"][c_id]["subjects"][s_id] = {
                            "id": s_id,
                            "subject_name": r["subject_name"],
                            "chapters": {}
                        }

                    ch_id = r["chapter_id"]
                    if ch_id:
                        if ch_id not in boards_map[b_id]["classes"][c_id]["subjects"][s_id]["chapters"]:
                            boards_map[b_id]["classes"][c_id]["subjects"][s_id]["chapters"][ch_id] = {
                                "id": ch_id,
                                "chapter_name": r["chapter_name"],
                                "topics": []
                            }

                        t_id = r["topic_id"]
                        if t_id:
                            boards_map[b_id]["classes"][c_id]["subjects"][s_id]["chapters"][ch_id]["topics"].append({
                                "id": t_id,
                                "topic_name": r["topic_name"],
                                "question_count": r["question_count"]
                            })

            # Format dictionaries to lists
            tree = []
            for b in boards_map.values():
                b_node = {
                    "id": b["id"],
                    "board_name": b["board_name"],
                    "classes": []
                }
                for c in b["classes"].values():
                    c_node = {
                        "id": c["id"],
                        "class_name": c["class_name"],
                        "subjects": []
                    }
                    for s in c["subjects"].values():
                        s_node = {
                            "id": s["id"],
                            "subject_name": s["subject_name"],
                            "chapters": []
                        }
                        for ch in s["chapters"].values():
                            s_node["chapters"].append(ch)
                        c_node["subjects"].append(s_node)
                    b_node["classes"].append(c_node)
                tree.append(b_node)

            return success(tree)
    except Exception as e:
        logger.error(f"Error fetching curriculum tree: {e}", exc_info=True)
        raise AppError("CURRICULUM_FETCH_FAILED", f"Failed to fetch curriculum tree: {str(e)}", 500)


@token_required
@roles_required("ADMIN", "SUPER_ADMIN", "TEACHER")
def list_questions():
    """
    List and filter questions from question_master.
    Supports query params: board_id, class_id, subject_id, chapter_id, topic_id, difficulty, type, search, page, limit
    """
    try:
        page = int(request.args.get("page", 1))
        limit = int(request.args.get("limit", 20))
        offset = (page - 1) * limit

        board_id = request.args.get("board_id")
        class_id = request.args.get("class_id")
        subject_id = request.args.get("subject_id")
        chapter_id = request.args.get("chapter_id")
        topic_id = request.args.get("topic_id")
        difficulty = request.args.get("difficulty")
        q_type = request.args.get("type")
        search = request.args.get("search", "").strip()

        conditions = ["q.is_active = 1"]
        params = {"limit": limit, "offset": offset}

        if board_id:
            conditions.append("s.board_id = :board_id")
            params["board_id"] = int(board_id)
        if class_id:
            conditions.append("s.class_id = :class_id")
            params["class_id"] = int(class_id)
        if subject_id:
            conditions.append("s.id = :subject_id")
            params["subject_id"] = int(subject_id)
        if chapter_id:
            conditions.append("ch.id = :chapter_id")
            params["chapter_id"] = int(chapter_id)
        if topic_id:
            conditions.append("t.id = :topic_id")
            params["topic_id"] = int(topic_id)
        if difficulty:
            diff_clean = difficulty.strip().lower()
            if diff_clean in ["simple", "easy"]:
                conditions.append("LOWER(dl.difficulty_level_name) IN ('easy', 'simple')")
            else:
                conditions.append("LOWER(dl.difficulty_level_name) = :difficulty")
                params["difficulty"] = diff_clean
        if q_type:
            conditions.append("LOWER(qt.question_type_name) = LOWER(:q_type)")
            params["q_type"] = q_type
        if search:
            search_conds = [
                "q.question LIKE :search",
                "q.explanation LIKE :search",
                "q.correct_answer LIKE :search",
                "t.topic_name LIKE :search",
                "ch.chapter_name LIKE :search",
                "s.subject_name LIKE :search",
                "b.board_name LIKE :search",
                "c.class_name LIKE :search",
                "qt.question_type_name LIKE :search",
                "dl.difficulty_level_name LIKE :search"
            ]
            if search.lower() in ["simple", "easy"]:
                search_conds.append("LOWER(dl.difficulty_level_name) IN ('easy', 'simple')")

            conditions.append(f"({' OR '.join(search_conds)})")
            params["search"] = f"%{search}%"

        where_clause = " AND ".join(conditions)

        with get_session() as session:
            count_sql = text(f"""
                SELECT COUNT(q.id)
                FROM question_master q
                JOIN topic_master t ON q.topic_id = t.id
                JOIN chapter_master ch ON t.chapter_id = ch.id
                JOIN subject_master s ON ch.subject_id = s.id
                JOIN board_master b ON s.board_id = b.id
                JOIN class_master c ON s.class_id = c.id
                JOIN question_type_master qt ON q.question_type_id = qt.id
                LEFT JOIN difficulty_level_master dl ON q.difficulty_level_id = dl.id
                WHERE {where_clause}
            """)
            total_count = session.execute(count_sql, params).scalar()

            data_sql = text(f"""
                SELECT 
                    q.id,
                    q.question,
                    q.options,
                    q.correct_answer,
                    q.explanation,
                    q.marks,
                    q.created_at,
                    qt.question_type_name AS type,
                    COALESCE(dl.difficulty_level_name, 'medium') AS difficulty,
                    t.id AS topic_id,
                    t.topic_name,
                    ch.id AS chapter_id,
                    ch.chapter_name,
                    s.id AS subject_id,
                    s.subject_name,
                    b.id AS board_id,
                    b.board_name,
                    c.id AS class_id,
                    c.class_name
                FROM question_master q
                JOIN topic_master t ON q.topic_id = t.id
                JOIN chapter_master ch ON t.chapter_id = ch.id
                JOIN subject_master s ON ch.subject_id = s.id
                JOIN board_master b ON s.board_id = b.id
                JOIN class_master c ON s.class_id = c.id
                JOIN question_type_master qt ON q.question_type_id = qt.id
                LEFT JOIN difficulty_level_master dl ON q.difficulty_level_id = dl.id
                WHERE {where_clause}
                ORDER BY q.id DESC
                LIMIT :limit OFFSET :offset
            """)
            rows = session.execute(data_sql, params).mappings().fetchall()

            questions = []
            for r in rows:
                opts = r["options"]
                if isinstance(opts, str):
                    try:
                        opts = json.loads(opts)
                    except Exception:
                        pass

                questions.append({
                    "id": r["id"],
                    "question": r["question"],
                    "options": opts,
                    "correct_answer": r["correct_answer"],
                    "explanation": r["explanation"],
                    "marks": r["marks"],
                    "type": r["type"],
                    "difficulty": r["difficulty"],
                    "topic_id": r["topic_id"],
                    "topic_name": r["topic_name"],
                    "chapter_id": r["chapter_id"],
                    "chapter_name": r["chapter_name"],
                    "subject_id": r["subject_id"],
                    "subject_name": r["subject_name"],
                    "board_id": r["board_id"],
                    "board_name": r["board_name"],
                    "class_id": r["class_id"],
                    "class_name": r["class_name"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None
                })

            return success({
                "items": questions,
                "total": total_count,
                "page": page,
                "limit": limit,
                "pages": (total_count + limit - 1) // limit if total_count > 0 else 1
            })
    except Exception as e:
        logger.error(f"Error listing questions: {e}", exc_info=True)
        raise AppError("QUESTIONS_FETCH_FAILED", f"Failed to list questions: {str(e)}", 500)


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def create_question():
    """Create a single question in question_master."""
    try:
        data = request.json or {}
        topic_id = data.get("topic_id")
        question_text = data.get("question", "").strip()
        correct_answer = data.get("correct_answer", "").strip()
        options = data.get("options")
        explanation = data.get("explanation", "")
        marks = int(data.get("marks", 1))
        type_name = data.get("type", "MCQ").upper()
        difficulty_name = data.get("difficulty", "medium").lower()

        if not topic_id or not question_text or not correct_answer:
            raise AppError("VALIDATION_ERROR", "topic_id, question, and correct_answer are required", 400)

        with get_session() as session:
            # Resolve type_id and auto-fetch default_marks from question_type_master
            type_row = session.execute(
                text("SELECT id, default_marks FROM question_type_master WHERE UPPER(question_type_name) = :t LIMIT 1"),
                {"t": type_name}
            ).mappings().first()

            type_id = type_row["id"] if type_row else 1
            default_marks = int(type_row["default_marks"]) if (type_row and type_row["default_marks"] is not None) else 1
            # Auto-assign from question_type_master
            effective_marks = default_marks if (marks is None or "marks" not in data) else marks

            # Resolve difficulty_id
            diff_search = "easy" if difficulty_name in ["simple", "easy"] else difficulty_name
            diff_id = session.execute(
                text("SELECT id FROM difficulty_level_master WHERE LOWER(difficulty_level_name) = :d LIMIT 1"),
                {"d": diff_search}
            ).scalar() or 1

            options_json = json.dumps(options) if options else None

            ins_sql = text("""
                INSERT INTO question_master 
                (topic_id, question_type_id, difficulty_level_id, question, options, correct_answer, explanation, marks, is_active, created_at, updated_at)
                VALUES 
                (:topic_id, :type_id, :diff_id, :question, :options, :correct_answer, :explanation, :marks, 1, NOW(), NOW())
            """)
            session.execute(ins_sql, {
                "topic_id": topic_id,
                "type_id": type_id,
                "diff_id": diff_id,
                "question": question_text,
                "options": options_json,
                "correct_answer": correct_answer,
                "explanation": explanation,
                "marks": effective_marks
            })
            session.commit()

            return success({"created": True, "message": "Question added successfully!"})
    except AppError:
        raise
    except Exception as e:
        logger.error(f"Error creating question: {e}", exc_info=True)
        raise AppError("CREATE_QUESTION_FAILED", f"Failed to create question: {str(e)}", 500)


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def update_question(question_id):
    """Update an existing question in question_master."""
    try:
        data = request.json or {}
        question_text = data.get("question")
        correct_answer = data.get("correct_answer")
        options = data.get("options")
        explanation = data.get("explanation")
        marks = data.get("marks")
        type_name = data.get("type")
        difficulty_name = data.get("difficulty")
        topic_id = data.get("topic_id")

        with get_session() as session:
            existing = session.execute(
                text("SELECT id FROM question_master WHERE id = :id"),
                {"id": question_id}
            ).first()
            if not existing:
                raise NotFoundError("Question not found")

            updates = ["updated_at = NOW()"]
            params = {"id": question_id}

            if question_text is not None:
                updates.append("question = :question")
                params["question"] = question_text
            if correct_answer is not None:
                updates.append("correct_answer = :correct_answer")
                params["correct_answer"] = correct_answer
            if explanation is not None:
                updates.append("explanation = :explanation")
                params["explanation"] = explanation
            if marks is not None:
                updates.append("marks = :marks")
                params["marks"] = int(marks)
            if topic_id is not None:
                updates.append("topic_id = :topic_id")
                params["topic_id"] = int(topic_id)
            if options is not None:
                updates.append("options = :options")
                params["options"] = json.dumps(options) if isinstance(options, (list, dict)) else options

            if type_name:
                type_id = session.execute(
                    text("SELECT id FROM question_type_master WHERE UPPER(question_type_name) = :t LIMIT 1"),
                    {"t": type_name.upper()}
                ).scalar()
                if type_id:
                    updates.append("question_type_id = :type_id")
                    params["type_id"] = type_id

            if difficulty_name:
                diff_search = "easy" if difficulty_name.lower().strip() in ["simple", "easy"] else difficulty_name.lower().strip()
                diff_id = session.execute(
                    text("SELECT id FROM difficulty_level_master WHERE LOWER(difficulty_level_name) = :d LIMIT 1"),
                    {"d": diff_search}
                ).scalar()
                if diff_id:
                    updates.append("difficulty_level_id = :diff_id")
                    params["diff_id"] = diff_id

            session.execute(
                text(f"UPDATE question_master SET {', '.join(updates)} WHERE id = :id"),
                params
            )
            session.commit()

            return success({"updated": True, "id": question_id})
    except AppError:
        raise
    except Exception as e:
        logger.error(f"Error updating question {question_id}: {e}", exc_info=True)
        raise AppError("UPDATE_QUESTION_FAILED", f"Failed to update question: {str(e)}", 500)


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def delete_question(question_id):
    """Soft delete question from question_master."""
    try:
        with get_session() as session:
            result = session.execute(
                text("UPDATE question_master SET is_active = 0, updated_at = NOW() WHERE id = :id"),
                {"id": question_id}
            )
            if result.rowcount == 0:
                raise NotFoundError("Question not found")
            session.commit()
            return success({"deleted": True, "id": question_id})
    except AppError:
        raise
    except Exception as e:
        logger.error(f"Error deleting question {question_id}: {e}", exc_info=True)
        raise AppError("DELETE_QUESTION_FAILED", f"Failed to delete question: {str(e)}", 500)


def _ensure_upload_batches_table(session):
    """Auto-creates question_upload_batches table if not present."""
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS question_upload_batches (
            id INT AUTO_INCREMENT PRIMARY KEY,
            file_name VARCHAR(255) NOT NULL,
            file_size_bytes INT DEFAULT 0,
            total_rows INT DEFAULT 0,
            inserted_count INT DEFAULT 0,
            updated_count INT DEFAULT 0,
            duplicate_skipped_count INT DEFAULT 0,
            status VARCHAR(50) DEFAULT 'SUCCESS',
            uploaded_by INT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_upload_batches_created (created_at DESC)
        )
    """))


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def get_upload_history():
    """Returns the history of recent bulk question uploads."""
    try:
        limit = min(int(request.args.get("limit", 20)), 50)
        with get_session() as session:
            _ensure_upload_batches_table(session)
            sql = text("""
                SELECT 
                    b.id,
                    b.file_name,
                    b.file_size_bytes,
                    b.total_rows,
                    b.inserted_count,
                    b.updated_count,
                    b.duplicate_skipped_count,
                    b.status,
                    b.created_at,
                    u.name AS uploader_name
                FROM question_upload_batches b
                LEFT JOIN users u ON b.uploaded_by = u.id
                ORDER BY b.id DESC
                LIMIT :limit
            """)
            rows = session.execute(sql, {"limit": limit}).mappings().fetchall()

            history = []
            for r in rows:
                history.append({
                    "id": r["id"],
                    "file_name": r["file_name"],
                    "file_size_bytes": r["file_size_bytes"],
                    "total_rows": r["total_rows"],
                    "inserted_count": r["inserted_count"],
                    "updated_count": r["updated_count"],
                    "duplicate_skipped_count": r["duplicate_skipped_count"],
                    "status": r["status"],
                    "uploader_name": r["uploader_name"] or "Admin",
                    "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M:%S") if r["created_at"] else ""
                })

            return success(history)
    except Exception as e:
        logger.error(f"Error fetching upload history: {e}", exc_info=True)
        raise AppError("UPLOAD_HISTORY_FAILED", f"Failed to fetch upload history: {str(e)}", 500)


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def bulk_upload_questions():
    """
    Bulk upload questions from CSV or Excel file with deduplication & incremental upsert.
    """
    try:
        if "file" not in request.files:
            raise AppError("VALIDATION_ERROR", "No file uploaded. Please provide a CSV or Excel file.", 400)

        file = request.files["file"]
        if not file.filename:
            raise AppError("VALIDATION_ERROR", "Uploaded file is empty.", 400)

        file_bytes = file.read()
        file_size = len(file_bytes)
        file.seek(0)

        filename = file.filename.lower()
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes))
        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(file_bytes))
        else:
            raise AppError("INVALID_FORMAT", "Only CSV, XLSX, or XLS files are supported.", 400)

        # Normalize column names
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        # Check required columns
        req_cols = ["question_text", "correct_answer"]
        if "question" in df.columns and "question_text" not in df.columns:
            df["question_text"] = df["question"]

        for col in req_cols:
            if col not in df.columns:
                raise AppError("MISSING_COLUMN", f"Required column '{col}' missing in uploaded file.", 400)

        total_rows = len(df)
        inserted_count = 0
        updated_count = 0
        duplicate_skipped_count = 0
        skipped_count = 0
        errors = []

        with get_session() as session:
            _ensure_upload_batches_table(session)

            # Preload master lookup dicts for high performance
            types_dict = {
                r[0].upper(): r[1]
                for r in session.execute(text("SELECT question_type_name, id FROM question_type_master")).fetchall()
            }
            diff_dict = {
                r[0].lower(): r[1]
                for r in session.execute(text("SELECT difficulty_level_name, id FROM difficulty_level_master")).fetchall()
            }
            topics_dict = {
                r[0].lower(): r[1]
                for r in session.execute(text("SELECT topic_name, id FROM topic_master")).fetchall()
            }

            for idx, row in df.iterrows():
                try:
                    q_text = str(row.get("question_text", "")).strip()
                    c_ans = str(row.get("correct_answer", "")).strip()

                    if not q_text or not c_ans or q_text == "nan" or c_ans == "nan":
                        skipped_count += 1
                        continue

                    # Smart Hierarchical Topic Resolution:
                    t_id = None
                    if "topic_id" in row and pd.notna(row["topic_id"]):
                        try:
                            t_id = int(row["topic_id"])
                        except Exception:
                            pass

                    if not t_id:
                        b_col = str(row.get("board", row.get("board_name", ""))).strip().lower()
                        c_col = str(row.get("class_grade", row.get("class_name", row.get("class", "")))).strip().lower()
                        s_col = str(row.get("subject", row.get("subject_name", ""))).strip().lower()
                        ch_col = str(row.get("chapter", row.get("chapter_name", ""))).strip().lower()
                        top_col = str(row.get("topic", row.get("topic_name", ""))).strip().lower()

                        if top_col:
                            if b_col and c_col and s_col and ch_col:
                                match_sql = text("""
                                    SELECT t.id 
                                    FROM topic_master t
                                    JOIN chapter_master ch ON t.chapter_id = ch.id
                                    JOIN subject_master s ON ch.subject_id = s.id
                                    JOIN board_master b ON s.board_id = b.id
                                    JOIN class_master c ON s.class_id = c.id
                                    WHERE LOWER(TRIM(b.board_name)) = :b
                                      AND (LOWER(TRIM(c.class_name)) = :c OR LOWER(TRIM(REPLACE(c.class_name, 'Class ', ''))) = :c)
                                      AND LOWER(TRIM(s.subject_name)) = :s
                                      AND LOWER(TRIM(ch.chapter_name)) LIKE :ch
                                      AND LOWER(TRIM(t.topic_name)) LIKE :top
                                    LIMIT 1
                                """)
                                t_id = session.execute(match_sql, {
                                    "b": b_col, "c": c_col, "s": s_col,
                                    "ch": f"%{ch_col}%", "top": f"%{top_col}%"
                                }).scalar()

                            if not t_id and ch_col:
                                match_sql2 = text("""
                                    SELECT t.id FROM topic_master t
                                    JOIN chapter_master ch ON t.chapter_id = ch.id
                                    WHERE LOWER(TRIM(ch.chapter_name)) LIKE :ch
                                      AND LOWER(TRIM(t.topic_name)) LIKE :top
                                    LIMIT 1
                                """)
                                t_id = session.execute(match_sql2, {
                                    "ch": f"%{ch_col}%", "top": f"%{top_col}%"
                                }).scalar()

                            if not t_id:
                                t_id = topics_dict.get(top_col)
                                if not t_id:
                                    t_id = session.execute(
                                        text("SELECT id FROM topic_master WHERE LOWER(TRIM(topic_name)) LIKE :top LIMIT 1"),
                                        {"top": f"%{top_col}%"}
                                    ).scalar()

                    if not t_id:
                        t_id = next(iter(topics_dict.values()), 1)

                    # Question Type
                    q_type = str(row.get("type", "MCQ")).strip().upper()
                    q_type_id = types_dict.get(q_type, types_dict.get("MCQ", 1))

                    # Difficulty
                    diff = str(row.get("difficulty", "medium")).strip().lower()
                    if diff in ["simple", "easy"]:
                        diff_id = diff_dict.get("easy", diff_dict.get("simple", 1))
                    else:
                        diff_id = diff_dict.get(diff, diff_dict.get("medium", 2))

                    # Marks
                    marks = 1
                    if "marks" in row and pd.notna(row["marks"]):
                        try:
                            marks = int(row["marks"])
                        except Exception:
                            marks = 1

                    # Explanation
                    expl = str(row.get("explanation", "")) if pd.notna(row.get("explanation")) else ""

                    # Options for MCQ
                    options_list = []
                    for opt_key in ["option_a", "option_b", "option_c", "option_d", "opt_a", "opt_b", "opt_c", "opt_d"]:
                        if opt_key in row and pd.notna(row[opt_key]):
                            prefix = opt_key.split("_")[-1].upper()
                            val = str(row[opt_key]).strip()
                            if not val.startswith(f"{prefix})"):
                                options_list.append(f"{prefix}) {val}")
                            else:
                                options_list.append(val)

                    options_json = json.dumps(options_list) if options_list else None

                    # --- Deduplication & Incremental Upsert Check ---
                    existing_q = session.execute(
                        text("""
                            SELECT id, options, correct_answer, marks, difficulty_level_id, question_type_id 
                            FROM question_master 
                            WHERE topic_id = :topic_id AND LOWER(TRIM(question)) = LOWER(TRIM(:question))
                            LIMIT 1
                        """),
                        {"topic_id": t_id, "question": q_text}
                    ).mappings().first()

                    if existing_q:
                        opt_match = (existing_q["options"] == options_json) or (not existing_q["options"] and not options_json)
                        ans_match = (str(existing_q["correct_answer"]).strip().lower() == c_ans.lower())
                        marks_match = (int(existing_q["marks"] or 1) == marks)

                        if opt_match and ans_match and marks_match:
                            # Exact Duplicate: Skip to prevent database bloat
                            duplicate_skipped_count += 1
                            skipped_count += 1
                        else:
                            # Update existing row with newer fields
                            session.execute(
                                text("""
                                    UPDATE question_master
                                    SET options = :options, correct_answer = :correct_answer, explanation = :explanation,
                                        marks = :marks, difficulty_level_id = :diff_id, question_type_id = :type_id,
                                        updated_at = NOW()
                                    WHERE id = :id
                                """),
                                {
                                    "id": existing_q["id"],
                                    "options": options_json,
                                    "correct_answer": c_ans,
                                    "explanation": expl,
                                    "marks": marks,
                                    "diff_id": diff_id,
                                    "type_id": q_type_id
                                }
                            )
                            updated_count += 1
                    else:
                        # New Question: Insert
                        ins_sql = text("""
                            INSERT INTO question_master
                            (topic_id, question_type_id, difficulty_level_id, question, options, correct_answer, explanation, marks, is_active, created_at, updated_at)
                            VALUES
                            (:topic_id, :type_id, :diff_id, :question, :options, :correct_answer, :explanation, :marks, 1, NOW(), NOW())
                        """)
                        session.execute(ins_sql, {
                            "topic_id": t_id,
                            "type_id": q_type_id,
                            "diff_id": diff_id,
                            "question": q_text,
                            "options": options_json,
                            "correct_answer": c_ans,
                            "explanation": expl,
                            "marks": marks
                        })
                        inserted_count += 1
                except Exception as row_err:
                    errors.append(f"Row {idx + 2}: {str(row_err)}")
                    skipped_count += 1

            # Record batch log in question_upload_batches
            uploader_id = getattr(g, "current_user_id", None)
            session.execute(
                text("""
                    INSERT INTO question_upload_batches
                    (file_name, file_size_bytes, total_rows, inserted_count, updated_count, duplicate_skipped_count, status, uploaded_by, created_at)
                    VALUES
                    (:file_name, :size, :total, :inserted, :updated, :duplicates, 'SUCCESS', :user_id, NOW())
                """),
                {
                    "file_name": file.filename,
                    "size": file_size,
                    "total": total_rows,
                    "inserted": inserted_count,
                    "updated": updated_count,
                    "duplicates": duplicate_skipped_count,
                    "user_id": uploader_id
                }
            )

            session.commit()

        msg = f"Ingested {inserted_count} new questions."
        if updated_count > 0:
            msg += f" Updated {updated_count} existing questions."
        if duplicate_skipped_count > 0:
            msg += f" Skipped {duplicate_skipped_count} duplicates."

        return success({
            "inserted": inserted_count,
            "updated": updated_count,
            "duplicate_skipped": duplicate_skipped_count,
            "skipped": skipped_count,
            "total_rows": total_rows,
            "errors": errors[:10],
            "message": msg
        })
    except AppError:
        raise
    except Exception as e:
        logger.error(f"Error during bulk question upload: {e}", exc_info=True)
        raise AppError("BULK_UPLOAD_FAILED", f"Bulk question upload failed: {str(e)}", 500)


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def bulk_upload_questions_stream():
    """
    Streaming NDJSON endpoint emitting row-by-row real-time percentage progress.
    """
    if "file" not in request.files:
        raise AppError("VALIDATION_ERROR", "No file uploaded.", 400)

    file = request.files["file"]
    if not file.filename:
        raise AppError("VALIDATION_ERROR", "Uploaded file is empty.", 400)

    file_bytes = file.read()
    file_size = len(file_bytes)
    filename = file.filename.lower()

    if filename.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes))
    elif filename.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(file_bytes))
    else:
        raise AppError("INVALID_FORMAT", "Only CSV, XLSX, or XLS files are supported.", 400)

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    if "question" in df.columns and "question_text" not in df.columns:
        df["question_text"] = df["question"]

    uploader_id = getattr(g, "current_user_id", None)
    total_rows = len(df)

    def generate_progress():
        inserted_count = 0
        updated_count = 0
        duplicate_skipped_count = 0
        skipped_count = 0
        errors = []

        yield json.dumps({
            "type": "progress",
            "percent": 5,
            "current": 0,
            "total": total_rows,
            "step": "Validating spreadsheet schema & loading master lookup tables..."
        }) + "\n"

        with get_session() as session:
            _ensure_upload_batches_table(session)

            types_dict = {
                r[0].upper(): r[1]
                for r in session.execute(text("SELECT question_type_name, id FROM question_type_master")).fetchall()
            }
            diff_dict = {
                r[0].lower(): r[1]
                for r in session.execute(text("SELECT difficulty_level_name, id FROM difficulty_level_master")).fetchall()
            }
            topics_dict = {
                r[0].lower(): r[1]
                for r in session.execute(text("SELECT topic_name, id FROM topic_master")).fetchall()
            }

            for idx, row in df.iterrows():
                try:
                    q_text = str(row.get("question_text", "")).strip()
                    c_ans = str(row.get("correct_answer", "")).strip()

                    if not q_text or not c_ans or q_text == "nan" or c_ans == "nan":
                        skipped_count += 1
                        continue

                    # Hierarchy Resolution
                    t_id = None
                    if "topic_id" in row and pd.notna(row["topic_id"]):
                        try:
                            t_id = int(row["topic_id"])
                        except Exception:
                            pass

                    if not t_id:
                        b_col = str(row.get("board", row.get("board_name", ""))).strip().lower()
                        c_col = str(row.get("class_grade", row.get("class_name", row.get("class", "")))).strip().lower()
                        s_col = str(row.get("subject", row.get("subject_name", ""))).strip().lower()
                        ch_col = str(row.get("chapter", row.get("chapter_name", ""))).strip().lower()
                        top_col = str(row.get("topic", row.get("topic_name", ""))).strip().lower()

                        if top_col:
                            if b_col and c_col and s_col and ch_col:
                                match_sql = text("""
                                    SELECT t.id FROM topic_master t
                                    JOIN chapter_master ch ON t.chapter_id = ch.id
                                    JOIN subject_master s ON ch.subject_id = s.id
                                    JOIN board_master b ON s.board_id = b.id
                                    JOIN class_master c ON s.class_id = c.id
                                    WHERE LOWER(TRIM(b.board_name)) = :b
                                      AND (LOWER(TRIM(c.class_name)) = :c OR LOWER(TRIM(REPLACE(c.class_name, 'Class ', ''))) = :c)
                                      AND LOWER(TRIM(s.subject_name)) = :s
                                      AND LOWER(TRIM(ch.chapter_name)) LIKE :ch
                                      AND LOWER(TRIM(t.topic_name)) LIKE :top
                                    LIMIT 1
                                """)
                                t_id = session.execute(match_sql, {
                                    "b": b_col, "c": c_col, "s": s_col,
                                    "ch": f"%{ch_col}%", "top": f"%{top_col}%"
                                }).scalar()

                            if not t_id and ch_col:
                                match_sql2 = text("""
                                    SELECT t.id FROM topic_master t
                                    JOIN chapter_master ch ON t.chapter_id = ch.id
                                    WHERE LOWER(TRIM(ch.chapter_name)) LIKE :ch
                                      AND LOWER(TRIM(t.topic_name)) LIKE :top
                                    LIMIT 1
                                """)
                                t_id = session.execute(match_sql2, {
                                    "ch": f"%{ch_col}%", "top": f"%{top_col}%"
                                }).scalar()

                            if not t_id:
                                t_id = topics_dict.get(top_col)
                                if not t_id:
                                    t_id = session.execute(
                                        text("SELECT id FROM topic_master WHERE LOWER(TRIM(topic_name)) LIKE :top LIMIT 1"),
                                        {"top": f"%{top_col}%"}
                                    ).scalar()

                    if not t_id:
                        t_id = next(iter(topics_dict.values()), 1)

                    q_type = str(row.get("type", "MCQ")).strip().upper()
                    q_type_id = types_dict.get(q_type, types_dict.get("MCQ", 1))

                    diff = str(row.get("difficulty", "medium")).strip().lower()
                    diff_id = diff_dict.get(diff, diff_dict.get("medium", 2))

                    marks = 1
                    if "marks" in row and pd.notna(row["marks"]):
                        try:
                            marks = int(row["marks"])
                        except Exception:
                            marks = 1

                    expl = str(row.get("explanation", "")) if pd.notna(row.get("explanation")) else ""

                    options_list = []
                    for opt_key in ["option_a", "option_b", "option_c", "option_d", "opt_a", "opt_b", "opt_c", "opt_d"]:
                        if opt_key in row and pd.notna(row[opt_key]):
                            prefix = opt_key.split("_")[-1].upper()
                            val = str(row[opt_key]).strip()
                            if not val.startswith(f"{prefix})"):
                                options_list.append(f"{prefix}) {val}")
                            else:
                                options_list.append(val)

                    options_json = json.dumps(options_list) if options_list else None

                    # Deduplication check
                    existing_q = session.execute(
                        text("""
                            SELECT id, options, correct_answer, marks 
                            FROM question_master 
                            WHERE topic_id = :topic_id AND LOWER(TRIM(question)) = LOWER(TRIM(:question))
                            LIMIT 1
                        """),
                        {"topic_id": t_id, "question": q_text}
                    ).mappings().first()

                    if existing_q:
                        opt_match = (existing_q["options"] == options_json) or (not existing_q["options"] and not options_json)
                        ans_match = (str(existing_q["correct_answer"]).strip().lower() == c_ans.lower())
                        marks_match = (int(existing_q["marks"] or 1) == marks)

                        if opt_match and ans_match and marks_match:
                            duplicate_skipped_count += 1
                            skipped_count += 1
                        else:
                            session.execute(
                                text("""
                                    UPDATE question_master
                                    SET options = :options, correct_answer = :correct_answer, explanation = :explanation,
                                        marks = :marks, difficulty_level_id = :diff_id, question_type_id = :type_id,
                                        updated_at = NOW()
                                    WHERE id = :id
                                """),
                                {
                                    "id": existing_q["id"], "options": options_json, "correct_answer": c_ans,
                                    "explanation": expl, "marks": marks, "diff_id": diff_id, "type_id": q_type_id
                                }
                            )
                            updated_count += 1
                    else:
                        session.execute(
                            text("""
                                INSERT INTO question_master
                                (topic_id, question_type_id, difficulty_level_id, question, options, correct_answer, explanation, marks, is_active, created_at, updated_at)
                                VALUES
                                (:topic_id, :type_id, :diff_id, :question, :options, :correct_answer, :explanation, :marks, 1, NOW(), NOW())
                            """),
                            {
                                "topic_id": t_id, "type_id": q_type_id, "diff_id": diff_id,
                                "question": q_text, "options": options_json, "correct_answer": c_ans,
                                "explanation": expl, "marks": marks
                            }
                        )
                        inserted_count += 1
                except Exception as row_err:
                    errors.append(f"Row {idx + 2}: {str(row_err)}")
                    skipped_count += 1

                # Calculate live row progress percentage (from 10% to 95%)
                live_percent = min(95, int(10 + (((idx + 1) / total_rows) * 85)))
                topic_snippet = str(row.get("topic", row.get("topic_name", "Curriculum"))).strip()
                yield json.dumps({
                    "type": "progress",
                    "percent": live_percent,
                    "current": idx + 1,
                    "total": total_rows,
                    "step": f"Processing question {idx + 1}/{total_rows}: {topic_snippet[:25]}..."
                }) + "\n"

            # Batch history record
            session.execute(
                text("""
                    INSERT INTO question_upload_batches
                    (file_name, file_size_bytes, total_rows, inserted_count, updated_count, duplicate_skipped_count, status, uploaded_by, created_at)
                    VALUES
                    (:file_name, :size, :total, :inserted, :updated, :duplicates, 'SUCCESS', :user_id, NOW())
                """),
                {
                    "file_name": file.filename,
                    "size": file_size,
                    "total": total_rows,
                    "inserted": inserted_count,
                    "updated": updated_count,
                    "duplicates": duplicate_skipped_count,
                    "user_id": uploader_id
                }
            )
            session.commit()

        msg = f"Ingested {inserted_count} new questions."
        if updated_count > 0:
            msg += f" Updated {updated_count} existing."
        if duplicate_skipped_count > 0:
            msg += f" Skipped {duplicate_skipped_count} duplicates."

        yield json.dumps({
            "type": "complete",
            "percent": 100,
            "inserted": inserted_count,
            "updated": updated_count,
            "duplicate_skipped": duplicate_skipped_count,
            "skipped": skipped_count,
            "total_rows": total_rows,
            "errors": errors[:10],
            "message": msg
        }) + "\n"

    from flask import Response
    return Response(generate_progress(), mimetype="application/x-ndjson")

