import os
from uuid import uuid4

from flask import request, g
from werkzeug.utils import secure_filename

from database.dbConnection import get_session
from helper.rag_ingestion import ingest_document
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import roles_required
from model.models import Document
from utils.errors import ValidationError
from utils.response import success
from utils.config import config


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@token_required
@roles_required("ADMIN", "SUPER_ADMIN", "AUTHOR")
def upload_blog_image():
    if "file" not in request.files:
        raise ValidationError("No image file supplied")
    image = request.files["file"]
    if not image.filename or image.mimetype not in ALLOWED_IMAGE_TYPES:
        raise ValidationError("Only JPG, PNG, WEBP, and GIF images are supported")

    filename = f"{uuid4().hex}_{secure_filename(image.filename)}"
    upload_dir = os.path.join(config.UPLOAD_DIR, "blogs")
    os.makedirs(upload_dir, exist_ok=True)
    image.save(os.path.join(upload_dir, filename))
    return success({"url": f"/uploads/blogs/{filename}", "filename": filename}, 201)


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def upload_file():
    if "file" not in request.files:
        raise ValidationError("No file part in the request")
    file = request.files["file"]
    if not file.filename:
        raise ValidationError("No file selected")

    file_bytes = file.read()

    with get_session() as session:
        document = ingest_document(
            session,
            filename=file.filename,
            file_bytes=file_bytes,
            content_type=file.mimetype or "application/octet-stream",
            board=request.form.get("board"),
            class_grade=request.form.get("classGrade"),
            subject=request.form.get("subject"),
            runbook_id=request.form.get("runbookId"),
            uploaded_by=g.current_user_id,
        )
        return success({
            "id": document.id, "filename": document.filename, "status": document.status,
        }, 201)


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def get_document_status(document_id):
    with get_session() as session:
        document = session.get(Document, document_id)
        if not document:
            raise ValidationError("Document not found")
        return success({
            "id": document.id, "filename": document.filename, "status": document.status,
            "board": document.board, "classGrade": document.class_grade, "subject": document.subject,
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def get_rag_status():
    """Returns overview of ChromaDB vector store and indexed curriculum documents."""
    from sqlalchemy import text
    from database import vector_db

    with get_session() as session:
        total_docs = session.execute(text("SELECT COUNT(*) FROM documents")).scalar() or 0
        total_chunks = session.execute(text("SELECT COUNT(*) FROM document_chunks")).scalar() or 0
        total_runbooks = session.execute(text("SELECT COUNT(*) FROM runbooks WHERE status = 'PUBLISHED'")).scalar() or 0
        total_topics = session.execute(
            text("SELECT COUNT(DISTINCT topic) FROM questions WHERE topic IS NOT NULL AND topic != ''")
        ).scalar() or 0

        # Query all documents with chunk count
        docs_sql = text("""
            SELECT 
                d.id, d.filename, d.content_type, d.board, d.class_grade, d.subject,
                d.status, d.created_at,
                COUNT(dc.id) AS chunk_count
            FROM documents d
            LEFT JOIN document_chunks dc ON dc.document_id = d.id
            GROUP BY d.id, d.filename, d.content_type, d.board, d.class_grade, d.subject, d.status, d.created_at
            ORDER BY d.created_at DESC
        """)
        rows = session.execute(docs_sql).mappings().fetchall()

        docs_list = []
        for r in rows:
            docs_list.append({
                "id": r["id"],
                "filename": r["filename"],
                "content_type": r["content_type"],
                "board": r["board"],
                "classGrade": r["class_grade"],
                "subject": r["subject"],
                "status": r["status"],
                "chunk_count": r["chunk_count"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None
            })

        return success({
            "vector_store_enabled": vector_db.is_enabled(),
            "total_topics": total_topics,
            "total_documents": total_docs,
            "total_chunks": total_chunks,
            "total_runbooks": total_runbooks,
            "documents": docs_list
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def delete_rag_document(document_id):
    """Deletes a document, its chunks from MySQL and vectors from ChromaDB."""
    from sqlalchemy import text
    from model.models import Document, DocumentChunk
    from database import vector_db

    with get_session() as session:
        document = session.get(Document, document_id)
        if not document:
            raise ValidationError("Document not found")

        # Fetch chunk vector ids to clean up ChromaDB
        chunks = session.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).all()
        vector_ids = [c.vector_id for c in chunks if c.vector_id]

        if vector_ids and vector_db.is_enabled():
            try:
                # Remove from ChromaDB if client supports delete
                collection = vector_db.get_collection()
                collection.delete(ids=vector_ids)
            except Exception:
                pass

        session.delete(document)
        session.commit()

        return success({"deleted": True, "id": document_id})


@token_required
@roles_required("ADMIN", "SUPER_ADMIN", "TEACHER")
def generate_questions_from_doc_api():
    """Generates structured questions from a document using LLM for review."""
    from helper.pdf_question_generator import generate_questions_from_doc

    data = request.json or {}
    document_id = data.get("document_id")
    count = int(data.get("count", 5))
    question_type = data.get("type", "MCQ")
    difficulty = data.get("difficulty", "medium")
    custom_instructions = data.get("instructions", "")

    if not document_id:
        raise ValidationError("document_id is required")

    with get_session() as session:
        questions = generate_questions_from_doc(
            session=session,
            document_id=document_id,
            count=count,
            question_type=question_type,
            difficulty=difficulty,
            custom_instructions=custom_instructions,
        )
        return success({
            "document_id": document_id,
            "count": len(questions),
            "questions": questions,
        })


@token_required
@roles_required("ADMIN", "SUPER_ADMIN", "TEACHER")
def save_generated_questions_api():
    """Saves generated questions into question_master."""
    import json
    from sqlalchemy import text

    data = request.json or {}
    questions = data.get("questions", [])
    topic_id = data.get("topic_id")

    if not questions or not isinstance(questions, list):
        raise ValidationError("questions list is required")

    if not topic_id:
        raise ValidationError("topic_id is required to link questions to curriculum")

    saved_count = 0
    with get_session() as session:
        # Check topic validity
        topic_exists = session.execute(
            text("SELECT id FROM topic_master WHERE id = :t"),
            {"t": topic_id}
        ).scalar()
        if not topic_exists:
            raise ValidationError(f"Topic ID {topic_id} does not exist in topic_master")

        # Type mapping cache
        types_map = {
            r[0].upper(): r[1] for r in session.execute(text("SELECT question_type_name, id FROM question_type_master")).fetchall()
        }
        # Difficulty mapping cache
        diffs_map = {
            r[0].lower(): r[1] for r in session.execute(text("SELECT difficulty_level_name, id FROM difficulty_level_master")).fetchall()
        }

        for q in questions:
            q_text = (q.get("question") or "").strip()
            if not q_text:
                continue

            q_type = (q.get("type") or "MCQ").upper()
            type_id = types_map.get(q_type, 1)

            q_diff = (q.get("difficulty") or "medium").lower()
            if q_diff in ["simple", "easy"]:
                diff_id = diffs_map.get("easy", diffs_map.get("simple", 1))
            else:
                diff_id = diffs_map.get(q_diff, 2)

            options = q.get("options")
            options_json = json.dumps(options) if options else None
            correct_answer = (q.get("correct_answer") or "").strip()
            explanation = (q.get("explanation") or "").strip()
            marks = int(q.get("marks", 1))

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
                "question": q_text,
                "options": options_json,
                "correct_answer": correct_answer,
                "explanation": explanation,
                "marks": marks
            })
            saved_count += 1

        session.commit()

    return success({
        "saved": True,
        "saved_count": saved_count,
        "message": f"Successfully added {saved_count} questions to Question Bank!"
    }, 201)


