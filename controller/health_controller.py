from utils.date_helper import now_ist
from datetime import datetime

from database.dbConnection import db_health_check
from database import graph_db, vector_db
from model import mistral_client
from utils.response import success


def health():
    try:
        db_up = db_health_check()
    except Exception:
        db_up = False

    try:
        vector_enabled = vector_db.is_enabled()
    except Exception:
        vector_enabled = False

    try:
        graph_enabled = graph_db.is_enabled()
    except Exception:
        graph_enabled = False

    try:
        mistral_conf = mistral_client.is_configured()
    except Exception:
        mistral_conf = False

    return success({
        "status": "ok",
        "time": now_ist().isoformat(),
        "database": "up" if db_up else "down",
        "vectorStore": "enabled" if vector_enabled else "disabled",
        "knowledgeGraph": "enabled" if graph_enabled else "disabled",
        "mistralConfigured": mistral_conf,
    })

