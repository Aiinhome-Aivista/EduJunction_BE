from utils.date_helper import now_ist
from datetime import datetime

from database.dbConnection import db_health_check
from database import graph_db, vector_db
from model import mistral_client
from utils.response import success


def health():
    return success({
        "status": "ok",
        "time": now_ist().isoformat(),
        "database": "up" if db_health_check() else "down",
        "vectorStore": "enabled" if vector_db.is_enabled() else "disabled",
        "knowledgeGraph": "enabled" if graph_db.is_enabled() else "disabled",
        "mistralConfigured": mistral_client.is_configured(),
    })

