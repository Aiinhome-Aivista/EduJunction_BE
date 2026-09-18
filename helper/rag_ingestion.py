"""Orchestrates the ingestion pipeline described in master prompt §11/§29:
Upload -> Validate -> Save -> Extract -> Chunk -> Embed -> Vector Store.
"""
import uuid

from sqlalchemy.orm import Session

from database import vector_db
from helper import document_processor, embedding_engine
from model.mistral_client import MistralUnavailableError
from model.models import Document, DocumentChunk
from utils.logger import logger


def ingest_document(
    session: Session,
    *,
    filename: str,
    file_bytes: bytes,
    content_type: str,
    board: str | None,
    class_grade: str | None,
    subject: str | None,
    runbook_id: str | None,
    uploaded_by: str,
) -> Document:
    ext = document_processor.validate_upload(filename, len(file_bytes))
    raw_text = document_processor.extract_text(file_bytes, ext)

    # Validate that PDF content matches target Board, Class, and Subject
    document_processor.validate_curriculum_metadata(
        filename=filename,
        raw_text=raw_text,
        target_board=board,
        target_class=class_grade,
        target_subject=subject,
    )

    document = Document(
        id=str(uuid.uuid4()),
        runbook_id=runbook_id,
        filename=filename,
        content_type=content_type,
        board=board,
        class_grade=class_grade,
        subject=subject,
        uploaded_by=uploaded_by,
        status="PENDING",
    )
    session.add(document)
    session.flush()

    try:
        cleaned = document_processor.clean_text(raw_text)
        chunks = document_processor.chunk_text(cleaned)

        if not chunks:
            document.status = "FAILED"
            return document

        if vector_db.is_enabled():
            embeddings = embedding_engine.embed(chunks)
        else:
            embeddings = None

        chunk_records = []
        for idx, chunk_text_value in enumerate(chunks):
            chunk_id = str(uuid.uuid4())
            chunk_records.append(
                DocumentChunk(
                    id=chunk_id,
                    document_id=document.id,
                    chunk_index=idx,
                    content=chunk_text_value,
                    vector_id=chunk_id if embeddings else None,
                )
            )
        session.add_all(chunk_records)

        if embeddings:
            vector_db.upsert_chunks(
                chunk_ids=[c.id for c in chunk_records],
                texts=chunks,
                embeddings=embeddings,
                metadatas=[
                    {"document_id": document.id, "board": board or "", "classGrade": class_grade or "", "subject": subject or ""}
                    for _ in chunks
                ],
            )

        document.status = "PROCESSED"
    except MistralUnavailableError:
        logger.error(f"Ingestion for document {document.id} completed extraction but embedding failed")
        document.status = "FAILED"
    except Exception as exc:
        logger.error(f"Ingestion failed for document {document.id}: {exc}")
        document.status = "FAILED"

    return document
