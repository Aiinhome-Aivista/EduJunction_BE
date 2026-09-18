from utils.date_helper import now_ist
import uuid
from datetime import datetime

from flask import request, g

from database.dbConnection import get_session
from middleware.authMiddleware import token_required
from middleware.roleMiddleware import roles_required
from model.models import Runbook
from utils.errors import NotFoundError
from utils.response import success
from utils.serializers import runbook_to_dict
from utils.validators import require_fields, validate_board, validate_class_grade, validate_subject



def list_runbooks():
    """Public read — matches the frontend's original unauthenticated
    GET /api/runbooks used by SuperAdminPanel's list view."""
    board = request.args.get("board")
    class_grade = request.args.get("classGrade")
    subject = request.args.get("subject")

    with get_session() as session:
        query = session.query(Runbook).filter(Runbook.status == "PUBLISHED")
        if board:
            query = query.filter(Runbook.board.ilike(board))
        if class_grade:
            query = query.filter(Runbook.class_grade.ilike(class_grade))
        if subject:
            query = query.filter(Runbook.subject.ilike(subject))
        results = query.order_by(Runbook.updated_at.desc()).all()
        return success([runbook_to_dict(rb) for rb in results], count=len(results))


def get_runbook(runbook_id):
    with get_session() as session:
        rb = session.get(Runbook, runbook_id)
        if not rb:
            raise NotFoundError("Runbook node not found")
        return success(runbook_to_dict(rb))


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def create_runbook():
    payload = request.get_json(force=True, silent=True) or {}
    require_fields(payload, ["board", "classGrade", "subject", "chapterName"])
    validate_board(payload["board"])
    validate_class_grade(payload["classGrade"])
    validate_subject(payload["subject"])

    default_calibration = {
        "simple": "Standard definitions and formula applications",
        "medium": "Two-step analytical calculations and conceptual reasoning",
        "hard": "Multi-concept synthesis and Olympiad / competitive problem solving",
    }

    with get_session() as session:
        rb = Runbook(
            id=str(uuid.uuid4()), board=payload["board"], class_grade=payload["classGrade"],
            subject=payload["subject"], chapter_name=payload["chapterName"],
            core_concepts=payload.get("coreConcepts", []),
            key_formulas_or_rules=payload.get("keyFormulasOrRules", []),
            common_traps=payload.get("commonTraps", []),
            curated_reference_urls=payload.get("curatedReferenceUrls", []),
            sample_question_archetypes=payload.get("sampleQuestionArchetypes", []),
            difficulty_calibration=payload.get("difficultyCalibration", default_calibration),
            status="PUBLISHED", created_by=g.current_user_id,
        )
        session.add(rb)
        session.flush()
        return success(runbook_to_dict(rb), 201, message="Runbook added successfully to K-Graph")


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def update_runbook(runbook_id):
    payload = request.get_json(force=True, silent=True) or {}
    field_map = {
        "board": "board", "classGrade": "class_grade", "subject": "subject",
        "chapterName": "chapter_name", "coreConcepts": "core_concepts",
        "keyFormulasOrRules": "key_formulas_or_rules", "commonTraps": "common_traps",
        "curatedReferenceUrls": "curated_reference_urls",
        "sampleQuestionArchetypes": "sample_question_archetypes",
        "difficultyCalibration": "difficulty_calibration", "status": "status",
    }
    with get_session() as session:
        rb = session.get(Runbook, runbook_id)
        if not rb:
            raise NotFoundError("Runbook node not found")
        for json_key, attr in field_map.items():
            if json_key in payload:
                setattr(rb, attr, payload[json_key])
        rb.version = (rb.version or 1) + 1
        rb.updated_at = now_ist()
        return success(runbook_to_dict(rb), message="Runbook updated")


@token_required
@roles_required("ADMIN", "SUPER_ADMIN")
def delete_runbook(runbook_id):
    with get_session() as session:
        rb = session.get(Runbook, runbook_id)
        if not rb:
            raise NotFoundError("Runbook node not found")
        session.delete(rb)
        return success({"deleted": True}, message="Runbook deleted")
