import logging
from typing import Optional
from sqlalchemy.orm import Session
from model.models import AuditLog, gen_uuid, get_ist_now

logger = logging.getLogger("sahajpath")


def get_client_ip(req=None) -> Optional[str]:
    """Extract client IP safely from Flask request or headers."""
    try:
        if req is None:
            from flask import request as flask_req
            req = flask_req
        if req:
            forwarded_for = req.headers.get("X-Forwarded-For")
            if forwarded_for:
                return forwarded_for.split(",")[0].strip()
            real_ip = req.headers.get("X-Real-IP")
            if real_ip:
                return real_ip.strip()
            if hasattr(req, "remote_addr") and req.remote_addr:
                return req.remote_addr
            if hasattr(req, "client") and req.client:
                return req.client.host
    except Exception as e:
        logger.warning(f"Error extracting client IP for audit log: {e}")
    return None


def log_audit(
    db: Session,
    action: str,
    user_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    request=None,
) -> Optional[AuditLog]:
    """
    Safely record an audit log event into the audit_logs table.
    Ensures that logging errors never disrupt primary business logic.
    """
    try:
        resolved_ip = ip_address or get_client_ip(request)
        audit_entry = AuditLog(
            id=gen_uuid(),
            user_id=user_id,
            action=str(action)[:120],
            entity_type=str(entity_type)[:60] if entity_type else None,
            entity_id=str(entity_id)[:60] if entity_id else None,
            ip_address=str(resolved_ip)[:64] if resolved_ip else None,
            created_at=get_ist_now(),
        )
        db.add(audit_entry)
        db.flush()
        return audit_entry
    except Exception as e:
        logger.error(f"Failed to record audit log [{action}]: {e}")
        return None
