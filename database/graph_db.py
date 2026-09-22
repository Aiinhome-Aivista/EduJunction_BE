import re
import uuid
from sqlalchemy import text
from utils.config import config
from utils.logger import logger

_db = None
_enabled = False

VERTEX_COLLECTIONS = ["boards", "classes", "subjects", "chapters", "topics", "misconceptions", "students"]
EDGE_COLLECTIONS = [
    "BOARD_HAS_CLASS",
    "CLASS_HAS_SUBJECT",
    "SUBJECT_HAS_CHAPTER",
    "CHAPTER_HAS_TOPIC",
    "TOPIC_REQUIRES_TOPIC",
    "TOPIC_HAS_MISCONCEPTION",
    "STUDENT_HAS_MASTERY",
    "STUDENT_HAS_MISCONCEPTION",
]

if config.ARANGO_URL:
    try:
        from arango import ArangoClient

        _client = ArangoClient(hosts=config.ARANGO_URL)

        # 1. Connect to _system database to ensure target database exists
        try:
            _sys_db = _client.db("_system", username=config.ARANGO_USERNAME, password=config.ARANGO_PASSWORD)
            if not _sys_db.has_database(config.ARANGO_DB):
                _sys_db.create_database(config.ARANGO_DB)
                logger.info(f"ArangoDB: Created new database '{config.ARANGO_DB}' successfully.")
        except Exception as sys_err:
            logger.debug(f"ArangoDB _system database check note: {sys_err}")

        # 2. Connect to target application database
        _db = _client.db(config.ARANGO_DB, username=config.ARANGO_USERNAME, password=config.ARANGO_PASSWORD)

        # Ensure all vertex collections exist
        for v_name in VERTEX_COLLECTIONS:
            if not _db.has_collection(v_name):
                _db.create_collection(v_name)

        # Ensure all edge collections exist
        for edge_name in EDGE_COLLECTIONS:
            if not _db.has_collection(edge_name):
                _db.create_collection(edge_name, edge=True)

        # Setup or update comprehensive Named Graph for rich visual representation in ArangoDB UI
        graph_name = "curriculum_knowledge_graph"
        edge_defs = [
            {
                "edge_collection": "BOARD_HAS_CLASS",
                "from_vertex_collections": ["boards"],
                "to_vertex_collections": ["classes"],
            },
            {
                "edge_collection": "CLASS_HAS_SUBJECT",
                "from_vertex_collections": ["classes"],
                "to_vertex_collections": ["subjects"],
            },
            {
                "edge_collection": "SUBJECT_HAS_CHAPTER",
                "from_vertex_collections": ["subjects"],
                "to_vertex_collections": ["chapters"],
            },
            {
                "edge_collection": "CHAPTER_HAS_TOPIC",
                "from_vertex_collections": ["chapters"],
                "to_vertex_collections": ["topics"],
            },
            {
                "edge_collection": "TOPIC_REQUIRES_TOPIC",
                "from_vertex_collections": ["topics"],
                "to_vertex_collections": ["topics"],
            },
            {
                "edge_collection": "TOPIC_HAS_MISCONCEPTION",
                "from_vertex_collections": ["topics"],
                "to_vertex_collections": ["misconceptions"],
            },
            {
                "edge_collection": "STUDENT_HAS_MASTERY",
                "from_vertex_collections": ["students"],
                "to_vertex_collections": ["topics"],
            },
        ]

        if not _db.has_graph(graph_name):
            try:
                _db.create_graph(graph_name, edge_definitions=edge_defs)
            except Exception as graph_err:
                logger.info(f"ArangoDB named graph create note: {graph_err}")

        _enabled = True
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.error(f"Knowledge graph disabled (ArangoDB unavailable): {exc}")
        _enabled = False
else:
    logger.info("Knowledge graph disabled: ARANGO_URL not configured")


def is_enabled() -> bool:
    return _enabled


def _safe_key(value: str) -> str:
    if not value:
        return "unknown"
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(value).strip())[:200]


def upsert_hierarchical_curriculum_branch(
    board: str,
    class_grade: str,
    subject: str,
    chapter: str,
    topics_list: list = None,
):
    """Creates the full structured hierarchy: Board -> Class -> Subject -> Chapter -> Topics."""
    if not _enabled or not _db:
        return

    try:
        b_key = _safe_key(board or "General")
        c_key = f"{b_key}__{_safe_key(class_grade or 'Class_10')}"
        s_key = f"{c_key}__{_safe_key(subject or 'General')}"
        ch_key = f"{s_key}__{_safe_key(chapter or 'Chapter_1')}"

        # 1. Board Node
        _db.collection("boards").insert({"_key": b_key, "name": board, "type": "Board"}, overwrite=True)

        # 2. Class Node
        _db.collection("classes").insert({"_key": c_key, "name": class_grade, "board": board, "type": "Class"}, overwrite=True)
        _db.collection("BOARD_HAS_CLASS").insert({
            "_key": f"{b_key}__{c_key}",
            "_from": f"boards/{b_key}",
            "_to": f"classes/{c_key}",
            "relation": "CONTAINS"
        }, overwrite=True)

        # 3. Subject Node
        _db.collection("subjects").insert({"_key": s_key, "name": subject, "class": class_grade, "board": board, "type": "Subject"}, overwrite=True)
        _db.collection("CLASS_HAS_SUBJECT").insert({
            "_key": f"{c_key}__{s_key}",
            "_from": f"classes/{c_key}",
            "_to": f"subjects/{s_key}",
            "relation": "OFFERS"
        }, overwrite=True)

        # 4. Chapter Node
        _db.collection("chapters").insert({"_key": ch_key, "name": chapter, "subject": subject, "class": class_grade, "board": board, "type": "Chapter"}, overwrite=True)
        _db.collection("SUBJECT_HAS_CHAPTER").insert({
            "_key": f"{s_key}__{ch_key}",
            "_from": f"subjects/{s_key}",
            "_to": f"chapters/{ch_key}",
            "relation": "INCLUDES"
        }, overwrite=True)

        # 5. Topics Nodes & Chapter-Topic Edges
        if topics_list:
            for t_item in topics_list:
                t_name = t_item if isinstance(t_item, str) else t_item.get("name") or t_item.get("topic")
                if not t_name:
                    continue
                t_key = _safe_key(t_name)
                _db.collection("topics").insert({
                    "_key": t_key,
                    "name": t_name,
                    "chapter": chapter,
                    "subject": subject,
                    "class": class_grade,
                    "board": board,
                    "type": "Topic"
                }, overwrite=True)

                _db.collection("CHAPTER_HAS_TOPIC").insert({
                    "_key": f"{ch_key}__{t_key}",
                    "_from": f"chapters/{ch_key}",
                    "_to": f"topics/{t_key}",
                    "relation": "COVERS_TOPIC"
                }, overwrite=True)

    except Exception as e:
        logger.warning(f"ArangoDB hierarchical branch sync failed: {e}")


def upsert_topic_relationship_edge(
    source_topic: str,
    target_topic: str,
    relationship_type: str = "PREREQUISITE",
    description: str = "",
    board: str = None,
    class_grade: str = None,
    subject: str = None,
    chapter: str = None,
):
    """Inserts or updates topic nodes and relationship edge in ArangoDB knowledge graph."""
    if not _enabled or not _db:
        return
    try:
        source_key = _safe_key(source_topic)
        target_key = _safe_key(target_topic)

        # Ensure topic nodes exist
        _db.collection("topics").insert({
            "_key": source_key,
            "name": source_topic,
            "board": board,
            "class": class_grade,
            "subject": subject,
            "type": "Topic"
        }, overwrite=True)

        _db.collection("topics").insert({
            "_key": target_key,
            "name": target_topic,
            "board": board,
            "class": class_grade,
            "subject": subject,
            "type": "Topic"
        }, overwrite=True)

        edge_key = f"{source_key}__{target_key}"
        _db.collection("TOPIC_REQUIRES_TOPIC").insert(
            {
                "_key": edge_key,
                "_from": f"topics/{source_key}",
                "_to": f"topics/{target_key}",
                "relationshipType": relationship_type,
                "description": description,
            },
            overwrite=True
        )

        # If chapter context is provided, attach to chapter hierarchy
        if chapter:
            upsert_hierarchical_curriculum_branch(
                board=board,
                class_grade=class_grade,
                subject=subject,
                chapter=chapter,
                topics_list=[source_topic, target_topic]
            )

    except Exception as e:
        logger.warning(f"ArangoDB relationship edge insert failed: {e}")


def sync_full_mysql_curriculum_to_arango(session):
    """Syncs the full active MySQL curriculum tree (Board -> Class -> Subject -> Chapter -> Topic)
    into ArangoDB with all hierarchical edges using fast batch upsert.
    """
    if not _enabled or not _db:
        return {"synced": False, "reason": "ArangoDB not enabled"}

    sql = text("""
        SELECT 
            b.id AS board_id, b.board_name,
            c.id AS class_id, c.class_name,
            s.id AS subject_id, s.subject_name,
            ch.id AS chapter_id, ch.chapter_name,
            t.id AS topic_id, t.topic_name
        FROM board_master b
        JOIN class_master c ON c.is_active = 1
        LEFT JOIN subject_master s ON (s.board_id = b.id OR s.board_id = 1) AND s.class_id = c.id AND s.is_active = 1
        LEFT JOIN chapter_master ch ON ch.subject_id = s.id AND ch.is_active = 1
        LEFT JOIN topic_master t ON t.chapter_id = ch.id AND t.is_active = 1
        WHERE b.is_active = 1
        ORDER BY b.id, c.id, s.id, ch.id, t.id
    """)

    rows = session.execute(sql).mappings().fetchall()

    boards_dict = {}
    classes_dict = {}
    subjects_dict = {}
    chapters_dict = {}
    topics_dict = {}

    board_class_edges = {}
    class_subject_edges = {}
    subject_chapter_edges = {}
    chapter_topic_edges = {}

    for r in rows:
        b_name = r["board_name"]
        c_name = r["class_name"]
        s_name = r["subject_name"]
        ch_name = r["chapter_name"]
        t_name = r["topic_name"]

        if not b_name or not c_name:
            continue

        b_key = _safe_key(b_name)
        c_key = f"{b_key}__{_safe_key(c_name)}"

        boards_dict[b_key] = {"_key": b_key, "name": b_name, "type": "Board"}
        classes_dict[c_key] = {"_key": c_key, "name": c_name, "board": b_name, "type": "Class"}
        board_class_edges[f"{b_key}__{c_key}"] = {
            "_key": f"{b_key}__{c_key}",
            "_from": f"boards/{b_key}",
            "_to": f"classes/{c_key}",
            "relation": "CONTAINS"
        }

        if s_name:
            s_key = f"{c_key}__{_safe_key(s_name)}"
            subjects_dict[s_key] = {"_key": s_key, "name": s_name, "class": c_name, "board": b_name, "type": "Subject"}
            class_subject_edges[f"{c_key}__{s_key}"] = {
                "_key": f"{c_key}__{s_key}",
                "_from": f"classes/{c_key}",
                "_to": f"subjects/{s_key}",
                "relation": "OFFERS"
            }

            if ch_name:
                ch_key = f"{s_key}__{_safe_key(ch_name)}"
                chapters_dict[ch_key] = {"_key": ch_key, "name": ch_name, "subject": s_name, "class": c_name, "board": b_name, "type": "Chapter"}
                subject_chapter_edges[f"{s_key}__{ch_key}"] = {
                    "_key": f"{s_key}__{ch_key}",
                    "_from": f"subjects/{s_key}",
                    "_to": f"chapters/{ch_key}",
                    "relation": "INCLUDES"
                }

                if t_name:
                    t_key = _safe_key(t_name)
                    topics_dict[t_key] = {
                        "_key": t_key,
                        "name": t_name,
                        "chapter": ch_name,
                        "subject": s_name,
                        "class": c_name,
                        "board": b_name,
                        "type": "Topic"
                    }
                    chapter_topic_edges[f"{ch_key}__{t_key}"] = {
                        "_key": f"{ch_key}__{t_key}",
                        "_from": f"chapters/{ch_key}",
                        "_to": f"topics/{t_key}",
                        "relation": "COVERS_TOPIC"
                    }

    # Batch insert with overwrite
    if boards_dict:
        _db.collection("boards").import_bulk(list(boards_dict.values()), on_duplicate="update")
    if classes_dict:
        _db.collection("classes").import_bulk(list(classes_dict.values()), on_duplicate="update")
    if subjects_dict:
        _db.collection("subjects").import_bulk(list(subjects_dict.values()), on_duplicate="update")
    if chapters_dict:
        _db.collection("chapters").import_bulk(list(chapters_dict.values()), on_duplicate="update")
    if topics_dict:
        _db.collection("topics").import_bulk(list(topics_dict.values()), on_duplicate="update")

    if board_class_edges:
        _db.collection("BOARD_HAS_CLASS").import_bulk(list(board_class_edges.values()), on_duplicate="update")
    if class_subject_edges:
        _db.collection("CLASS_HAS_SUBJECT").import_bulk(list(class_subject_edges.values()), on_duplicate="update")
    if subject_chapter_edges:
        _db.collection("SUBJECT_HAS_CHAPTER").import_bulk(list(subject_chapter_edges.values()), on_duplicate="update")
    if chapter_topic_edges:
        _db.collection("CHAPTER_HAS_TOPIC").import_bulk(list(chapter_topic_edges.values()), on_duplicate="update")

    return {
        "synced": True,
        "counts": {
            "boards": len(boards_dict),
            "classes": len(classes_dict),
            "subjects": len(subjects_dict),
            "chapters": len(chapters_dict),
            "topics": len(topics_dict),
            "edges": len(board_class_edges) + len(class_subject_edges) + len(subject_chapter_edges) + len(chapter_topic_edges),
        }
    }


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
    misconception_key = str(uuid.uuid4())
    t_key = _safe_key(topic)
    _db.collection("misconceptions").insert({"_key": misconception_key, "description": description, "severity": severity})
    _db.collection("topics").insert({"_key": t_key, "name": topic}, overwrite=True)

    _db.collection("TOPIC_HAS_MISCONCEPTION").insert(
        {
            "_key": f"{t_key}__{misconception_key}",
            "_from": f"topics/{t_key}",
            "_to": f"misconceptions/{misconception_key}",
            "severity": severity,
        },
        overwrite=True
    )
    _db.collection("STUDENT_HAS_MISCONCEPTION").insert(
        {
            "_from": f"students/{student_id}",
            "_to": f"misconceptions/{misconception_key}",
            "topic": topic,
        }
    )


