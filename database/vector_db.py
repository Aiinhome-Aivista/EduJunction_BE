"""ChromaDB wrapper for document-chunk embeddings (master prompt §11/§30).
Used only for freeform uploaded documents — structured runbook retrieval in
helper/rag_engine.py does not depend on this. If chromadb isn't installed or
the persistent store can't be opened, the module runs in disabled mode and
every public function becomes a safe no-op, per master prompt §30's
"if unavailable, the application must still run" requirement.
"""
from utils.config import config
from utils.logger import logger

_client = None
_collection = None
_enabled = False

try:
    # NumPy 2.0 backward compatibility shim
    import numpy as np
    if not hasattr(np, "float_"):
        np.float_ = np.float64
    if not hasattr(np, "int_"):
        np.int_ = np.int64

    import chromadb
    from chromadb.config import Settings

    _client = chromadb.PersistentClient(
        path=config.VECTOR_DB_PATH,
        settings=Settings(anonymized_telemetry=False)
    )
    _collection = _client.get_or_create_collection(name="acugrade_documents")
    _enabled = True
except Exception as exc:  # pragma: no cover - environment dependent
    logger.error(f"Vector store disabled (chromadb unavailable): {exc}")
    _enabled = False


def is_enabled() -> bool:
    return _enabled


def upsert_chunks(chunk_ids: list[str], texts: list[str], embeddings: list[list[float]], metadatas: list[dict]):
    if not _enabled:
        return
    _collection.upsert(ids=chunk_ids, embeddings=embeddings, documents=texts, metadatas=metadatas)


def query(query_embedding: list[float], top_k: int, metadata_filter: dict | None = None) -> list[str]:
    """Embedding-based query. The caller (helper/rag_engine.py) computes the
    query embedding via helper/embedding_engine.py (Mistral) — we deliberately
    don't use Chroma's own default embedding function here, to keep a single
    embedding provider for both ingestion and retrieval."""
    if not _enabled:
        return []
    where = {k: v for k, v in (metadata_filter or {}).items() if v} or None
    results = _collection.query(query_embeddings=[query_embedding], n_results=top_k, where=where)
    documents = results.get("documents", [[]])
    return documents[0] if documents else []


def delete_by_document(document_id: str):
    if not _enabled:
        return
    _collection.delete(where={"document_id": document_id})
