"""ArangoDB-backed knowledge graph (master prompt §30). Mirrors mastery,
misconceptions, and topic relationships as a graph for future traversal
queries (e.g. "what prerequisite topics does this student need before X").

Per §30: "If Arango DB is unavailable, the application must still run" — so
every public method is a safe no-op when the connection isn't configured or
fails, and callers should treat this graph as an enrichment layer, not a
source of truth (MySQL remains authoritative for all data used in the API
responses documented in docs/FRONTEND_BACKEND_MAPPING.md).
"""
from utils.config import config
from utils.logger import logger

_db = None
_enabled = False

if config.ARANGO_URL:
    try:
        from arango import ArangoClient

        _client = ArangoClient(hosts=config.ARANGO_URL)
        _db = _client.db(config.ARANGO_DB, username=config.ARANGO_USERNAME, password=config.ARANGO_PASSWORD)
        if not _db.has_collection("students"):
            _db.create_collection("students")
        if not _db.has_collection("topics"):
            _db.create_collection("topics")
        if not _db.has_collection("misconceptions"):
            _db.create_collection("misconceptions")
        for edge_name in ["STUDENT_HAS_MASTERY", "STUDENT_HAS_MISCONCEPTION", "TOPIC_REQUIRES_TOPIC"]:
            if not _db.has_collection(edge_name):
                _db.create_collection(edge_name, edge=True)
        _enabled = True
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.error(f"Knowledge graph disabled (ArangoDB unavailable): {exc}")
        _enabled = False
else:
    logger.info("Knowledge graph disabled: ARANGO_URL not configured")


def is_enabled() -> bool:
    return _enabled


def upsert_student_node(student_id: str, name: str):
    if not _enabled:
        return
    _db.collection("students").insert({"_key": student_id, "name": name}, overwrite=True)


def upsert_mastery_edge(student_id: str, topic: str, mastery_percentage: float):
    if not _enabled:
        return
    topic_key = _safe_key(topic)
    _db.collection("topics").insert({"_key": topic_key, "name": topic}, overwrite=True)
    _db.collection("STUDENT_HAS_MASTERY").insert(
        {
            "_key": f"{student_id}__{topic_key}",
            "_from": f"students/{student_id}",
            "_to": f"topics/{topic_key}",
            "masteryPercentage": mastery_percentage,
        },
        overwrite=True,
    )


def upsert_misconception_edge(student_id: str, topic: str, description: str, severity: str):
    if not _enabled:
        return
    import uuid

    misconception_key = str(uuid.uuid4())
    _db.collection("misconceptions").insert({"_key": misconception_key, "description": description, "severity": severity})
    _db.collection("STUDENT_HAS_MISCONCEPTION").insert(
        {
            "_from": f"students/{student_id}",
            "_to": f"misconceptions/{misconception_key}",
            "topic": topic,
        }
    )


def _safe_key(value: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_-]", "_", value)[:200]
