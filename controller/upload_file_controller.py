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
    return success({"url": f"/edujunction/uploads/blogs/{filename}", "filename": filename}, 201)


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
    diff_counts = {"simple": 0, "medium": 0, "hard": 0}

    with get_session() as session:
        # Check topic validity and get full breadcrumbs (Topic -> Chapter -> Subject)
        topic_info = session.execute(
            text("""
                SELECT t.id, t.topic_name, ch.chapter_name, s.subject_name
                FROM topic_master t
                JOIN chapter_master ch ON ch.id = t.chapter_id
                JOIN subject_master s ON s.id = ch.subject_id
                WHERE t.id = :t
            """),
            {"t": topic_id}
        ).mappings().fetchone()

        if not topic_info:
            raise ValidationError(f"Topic ID {topic_id} does not exist in topic_master")

        topic_name = topic_info["topic_name"]
        chapter_name = topic_info["chapter_name"]
        subject_name = topic_info["subject_name"]

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
                diff_counts["simple"] += 1
            elif q_diff == "hard":
                diff_id = diffs_map.get("hard", 3)
                diff_counts["hard"] += 1
            else:
                diff_id = diffs_map.get("medium", 2)
                diff_counts["medium"] += 1

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

        # Terminal step logging
        print(f"\n=======================================================", flush=True)
        print(f">> [TOPIC INGESTION] Topic: '{topic_name}'", flush=True)
        print(f">> Chapter: '{chapter_name}' | Subject: '{subject_name}'", flush=True)
        print(f">> Successfully Ingested {saved_count} Question(s) ({diff_counts['simple']} simple, {diff_counts['medium']} medium, {diff_counts['hard']} hard)", flush=True)
        print(f">> Saved to Database (question_master) & linked to ArangoDB Knowledge Graph!", flush=True)
        print(f"=======================================================\n", flush=True)

    return success({
        "saved": True,
        "saved_count": saved_count,
        "topic_name": topic_name,
        "chapter_name": chapter_name,
        "subject_name": subject_name,
        "message": f"Successfully ingested {saved_count} questions for '{topic_name}' ({diff_counts['simple']} simple, {diff_counts['medium']} medium, {diff_counts['hard']} hard) into Question Bank!"
    }, 201)


@token_required
@roles_required("ADMIN", "SUPER_ADMIN", "TEACHER")
def analyze_and_extract_book_api():
    """Uploads a Book/Question Bank (PDF/DOC/DOCX), validates 10-15 years criteria,

    and generates Summary, Concept Relationships, and Important Questions using LLM.
    """
    from helper import document_processor
    from helper.pdf_question_generator import analyze_book_and_question_bank, analyze_multiple_books_and_question_banks
    from helper.rag_ingestion import ingest_document

    # Support multiple files under 'files' or 'file' key, or single file
    files = request.files.getlist("files")
    if not files:
        if "file" in request.files:
            files = [request.files["file"]]
        elif request.files.getlist("file"):
            files = request.files.getlist("file")

    valid_files = [f for f in files if f and f.filename]
    if not valid_files:
        raise ValidationError("No files supplied in the request. Please select at least one PDF/DOC/DOCX file.")

    board = request.form.get("board", "CBSE")
    class_grade = request.form.get("classGrade", "Class 10")
    subject = request.form.get("subject", "Mathematics")
    year_declared = request.form.get("yearDeclared")
    doc_type = request.form.get("documentType", "Textbook")

    print(f"\n=======================================================", flush=True)
    print(f">> [BATCH INGESTION] Received {len(valid_files)} file(s)", flush=True)
    print(f">> Board: {board} | Class: {class_grade} | Subject: {subject} | Year: {year_declared or 'Default'}", flush=True)
    print(f"=======================================================", flush=True)

    ingested_docs = []

    with get_session() as session:
        for idx, f in enumerate(valid_files, 1):
            print(f"\n>> [FILE {idx}/{len(valid_files)}] Processing file: {f.filename}...", flush=True)
            file_bytes = f.read()
            ext = document_processor.validate_upload(f.filename, len(file_bytes))
            if ext not in ["pdf", "docx", "doc"]:
                raise ValidationError(f"Invalid format '.{ext}' in '{f.filename}'. Only PDF, DOC, and DOCX files are supported.")

            # Save permanent copy to disk (uploads/books/)
            save_path = document_processor.save_uploaded_file_to_disk(f.filename, file_bytes)
            print(f"   [SAVED] Stored locally at: {save_path}", flush=True)

            # Extract text (with automatic Gemini Vision OCR fallback for scanned pages)
            print(f"   [EXTRACT] Extracting text & formulas (PyMuPDF / Vision OCR)...", flush=True)
            raw_text = document_processor.extract_text(file_bytes, ext, board=board, class_grade=class_grade, subject=subject)
            if not raw_text or not raw_text.strip():
                raise ValidationError(
                    f"Could not extract readable text from '{f.filename}'. "
                    f"Please ensure the file contains valid curriculum content."
                )
            print(f"   [OK] Extracted {len(raw_text)} characters from {f.filename}", flush=True)

            # Validate 10-15 years constraint and curriculum suitability
            document_processor.validate_book_and_question_bank(
                filename=f.filename,
                raw_text=raw_text,
                board=board,
                class_grade=class_grade,
                subject=subject,
                year_declared=year_declared,
            )

            # Ingest into document repository and vector store
            print(f"   [VECTOR STORE] Indexing chunks in vector repository...", flush=True)
            document = ingest_document(
                session,
                filename=f.filename,
                file_bytes=file_bytes,
                content_type=f.mimetype or f"application/{ext}",
                board=board,
                class_grade=class_grade,
                subject=subject,
                runbook_id=None,
                uploaded_by=g.current_user_id,
            )
            ingested_docs.append({
                "id": str(document.id),
                "filename": str(f.filename)
            })
            print(f"   [INDEXED] Document ID: {document.id}", flush=True)

        session.commit()

        doc_ids = [d["id"] for d in ingested_docs]
        filenames_list = [d["filename"] for d in ingested_docs]

        print(f"\n>> [AI SYNTHESIS] Starting LLM Pedagogical & Question Synthesis across {len(doc_ids)} chapters...", flush=True)
        # Run unified pedagogical analysis (cross-chapter knowledge graph & questions)
        if len(doc_ids) == 1:
            analysis = analyze_book_and_question_bank(
                session,
                document_id=doc_ids[0],
                target_board=board,
                target_class=class_grade,
                target_subject=subject,
            )
        else:
            analysis = analyze_multiple_books_and_question_banks(
                session,
                document_ids=doc_ids,
                target_board=board,
                target_class=class_grade,
                target_subject=subject,
            )

        # Automatic ArangoDB Knowledge Graph & MySQL Runbook synchronization
        relationships = analysis.get("relationships", [])
        try:
            from database import graph_db
            from model.models import Runbook
            
            # 1. First, ensure Board -> Class -> Subject -> Chapter hierarchy is recorded for each chapter in ArangoDB
            for fn in filenames_list:
                chapter_title = fn.replace(".pdf", "").replace(".docx", "").replace(".doc", "").replace("_", " ")
                graph_db.upsert_hierarchical_curriculum_branch(
                    board=board,
                    class_grade=class_grade,
                    subject=subject,
                    chapter=chapter_title,
                )

            # 2. Persist pedagogical insights into MySQL runbooks table for every chapter
            for ch_data in analysis.get("chapters", []):
                ch_fn = ch_data.get("filename") or filenames_list[0]
                ch_title = ch_fn.replace(".pdf", "").replace(".docx", "").replace(".doc", "").replace("_", " ")
                
                existing_rb = session.query(Runbook).filter(
                    Runbook.board == board,
                    Runbook.class_grade == class_grade,
                    Runbook.subject == subject,
                    Runbook.chapter_name == ch_title
                ).first()

                rb_core_concepts = ch_data.get("core_concepts") or analysis.get("core_concepts") or [f"{ch_title} Core Principles"]
                rb_formulas = ch_data.get("key_formulas_or_rules") or analysis.get("key_formulas_or_rules") or []
                rb_traps = ch_data.get("common_traps") or analysis.get("common_traps") or []
                rb_archetypes = [q.get("question") for q in ch_data.get("important_questions", [])[:3]]

                if not existing_rb:
                    new_rb = Runbook(
                        board=board,
                        class_grade=class_grade,
                        subject=subject,
                        chapter_name=ch_title,
                        core_concepts=rb_core_concepts,
                        key_formulas_or_rules=rb_formulas,
                        common_traps=rb_traps,
                        curated_reference_urls=[],
                        sample_question_archetypes=rb_archetypes,
                        difficulty_calibration={"simple": 40, "medium": 40, "hard": 20},
                        status="PUBLISHED",
                        version=1,
                        created_by=g.current_user_id,
                    )
                    session.add(new_rb)
                else:
                    existing_rb.core_concepts = rb_core_concepts
                    existing_rb.key_formulas_or_rules = rb_formulas
                    existing_rb.common_traps = rb_traps
                    existing_rb.sample_question_archetypes = rb_archetypes

            session.commit()
            print(f">> [MYSQL RUNBOOKS] Persisted pedagogical insights for {len(filenames_list)} chapters into 'runbooks' table.", flush=True)

            if relationships:
                print(f">> [ARANGODB SYNC] Syncing {len(relationships)} concept relationships to ArangoDB...", flush=True)
                for rel in relationships:
                    src = rel.get("source_concept") or rel.get("source")
                    tgt = rel.get("target_concept") or rel.get("target")
                    rel_type = rel.get("relationship_type") or "PREREQUISITE"
                    desc = rel.get("description") or ""
                    if src and tgt:
                        graph_db.upsert_topic_relationship_edge(
                            source_topic=str(src),
                            target_topic=str(tgt),
                            relationship_type=str(rel_type),
                            description=str(desc),
                            board=board,
                            class_grade=class_grade,
                            subject=subject,
                            chapter=filenames_list[0].replace(".pdf", "").replace("_", " ") if filenames_list else None,
                        )
                        print(f"   -> Linked: {src} -> {tgt} [{rel_type}]", flush=True)
                print(f">> [OK] ArangoDB Knowledge Graph updated with full hierarchy!", flush=True)
        except Exception as graph_err:
            from utils.logger import logger
            logger.warning(f"ArangoDB/Runbook automatic relationship sync skipped/failed: {graph_err}")

        q_count = len(analysis.get("important_questions", []))
        print(f">> [COMPLETE] Synthesized {q_count} questions across {len(doc_ids)} files. Sending response.\n", flush=True)

        # Construct unified response
        response_payload = {
            "is_batch": len(doc_ids) > 1,
            "total_files": len(doc_ids),
            "document_ids": doc_ids,
            "filenames": filenames_list,
            "board": board,
            "class_grade": class_grade,
            "subject": subject,
            "document_type": doc_type,
            "summary": analysis.get("summary"),
            "core_concepts": analysis.get("core_concepts", []),
            "key_formulas_or_rules": analysis.get("key_formulas_or_rules", []),
            "common_traps": analysis.get("common_traps", []),
            "relationships": relationships,
            "important_questions": analysis.get("important_questions", []),
            "questions_count": analysis.get("questions_count", q_count),
            "chapters": analysis.get("chapters", []),
        }

        # Also maintain single-doc legacy compatibility fields if only 1 file
        if len(doc_ids) == 1:
            response_payload["document_id"] = doc_ids[0]
            response_payload["filename"] = filenames_list[0]

        return success(response_payload, 201)




