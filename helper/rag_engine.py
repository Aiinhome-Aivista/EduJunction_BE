"""Retrieval for exam grounding. Two layers, matching master prompt §11:

1. Structured retrieval over `runbooks` (metadata filter by board/grade/
   subject) — this is what the frontend's original server.ts already did,
   and it's the primary grounding source since every runbook is small,
   curated, and cheap to send in full.
2. Optional semantic retrieval over ingested document chunks via the vector
   store (database/vector_db.py), for freeform uploaded curriculum material
   that doesn't fit the structured runbook shape. Silently skipped if the
   vector store has nothing indexed yet or is disabled.

Never sends the entire knowledge base to the AI — only the matched subset.
"""
from sqlalchemy.orm import Session

from model.models import Runbook
from database import vector_db
from helper import embedding_engine


def retrieve_runbooks(session: Session, board: str, class_grade: str | None, subject: str | None) -> list[Runbook]:
    query = session.query(Runbook).filter(Runbook.status == "PUBLISHED")
    query = query.filter((Runbook.board == board) | (Runbook.board == "NCERT"))
    if class_grade:
        query = query.filter(Runbook.class_grade == class_grade)
    if subject:
        query = query.filter(Runbook.subject == subject)
    results = query.all()
    return results


def runbooks_to_context(runbooks: list[Runbook], difficulty: str) -> list[dict]:
    context = []
    for rb in runbooks:
        context.append(
            {
                "chapter": rb.chapter_name,
                "concepts": rb.core_concepts,
                "formulas": rb.key_formulas_or_rules,
                "traps": rb.common_traps,
                "references": rb.curated_reference_urls,
                "archetypes": rb.sample_question_archetypes,
                "difficultyGuide": (rb.difficulty_calibration or {}).get(difficulty, ""),
            }
        )
    return context


def retrieve_document_context(board: str, class_grade: str, subject: str, query_text: str, top_k: int = 4) -> list[str]:
    """Semantic search over uploaded/ingested document chunks. Returns plain
    text snippets, or an empty list if the vector store has no matching data
    or is unavailable — callers must treat this as optional enrichment, not
    a required step."""
    if not vector_db.is_enabled():
        return []
    try:
        [query_embedding] = embedding_engine.embed([query_text])
        results = vector_db.query(
            query_embedding=query_embedding,
            top_k=top_k,
            metadata_filter={"board": board, "classGrade": class_grade, "subject": subject},
        )
        return results
    except Exception:
        return []
