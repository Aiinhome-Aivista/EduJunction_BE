"""Telemetry & Session Tracking Service:
Handles non-blocking asynchronous event logging, data sanitization,
anti-spam deduplication, and admin metrics/timeline queries.
"""
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import case, func, or_, text
from database.dbConnection import get_session
from model.models import User, UserEventLog, UserSession, get_ist_now

# Dedicated non-blocking thread pool for background telemetry writes
_telemetry_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="TelemetryWorker")

# Keys to sanitize recursively in payloads
SENSITIVE_KEY_PATTERN = re.compile(
    r"^(password|pass|secret|token|auth|authorization|api[_-]?key|card[_-]?number|cvv|cvc|pin|otp)$",
    re.IGNORECASE,
)

# In-memory LRU-like de-duplication cache: (session_id, event_name, hash_payload) -> timestamp
_recent_events_cache: dict[str, datetime] = {}
DEDUP_WINDOW_SECONDS = 2


def sanitize_payload(obj, depth: int = 0):
    """Recursively mask sensitive values in dicts, lists, and JSON structures."""
    if depth > 6:
        return "[MAX_DEPTH_REACHED]"

    if isinstance(obj, dict):
        sanitized = {}
        for k, v in obj.items():
            if SENSITIVE_KEY_PATTERN.match(str(k)):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_payload(v, depth + 1)
        return sanitized
    elif isinstance(obj, list):
        return [sanitize_payload(item, depth + 1) for item in obj]
    elif isinstance(obj, str):
        # Truncate overly long payload strings
        return obj[:1500] if len(obj) > 1500 else obj
    return obj


def extract_client_ip(req) -> str:
    """Resolves the real public IP from proxy and cloud headers."""
    if not req:
        return "127.0.0.1"

    cf_ip = req.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()

    xff = req.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()

    x_real_ip = req.headers.get("X-Real-IP")
    if x_real_ip:
        return x_real_ip.strip()

    client_header = req.headers.get("x-client-ip")
    if client_header:
        return client_header.strip()

    return req.remote_addr or "127.0.0.1"


def detect_device_type(user_agent: str | None) -> str:
    """Parses raw User-Agent to categorize client device."""
    if not user_agent:
        return "desktop"

    ua = user_agent.lower()
    if any(t in ua for t in ["ipad", "tablet", "playbook", "silk"]):
        return "tablet"
    if any(m in ua for m in ["mobile", "iphone", "android", "blackberry", "webos", "windows phone"]):
        return "mobile"
    return "desktop"


def _is_duplicate_event(session_id: str, event_name: str, payload_str: str) -> bool:
    """Returns True if identical event was logged within DEDUP_WINDOW_SECONDS."""
    now = get_ist_now()
    cache_key = f"{session_id}:{event_name}:{hash(payload_str)}"

    last_time = _recent_events_cache.get(cache_key)
    if last_time and (now - last_time).total_seconds() < DEDUP_WINDOW_SECONDS:
        return True

    _recent_events_cache[cache_key] = now
    # Periodically keep cache size bounded
    if len(_recent_events_cache) > 2000:
        cutoff = now - timedelta(seconds=60)
        keys_to_remove = [k for k, v in _recent_events_cache.items() if v < cutoff]
        for k in keys_to_remove:
            _recent_events_cache.pop(k, None)

    return False


def _write_event_worker(
    session_id: str,
    user_id: int | None,
    event_name: str,
    event_category: str,
    input_payload: dict | list | None,
    result_summary: dict | list | None,
    status: str,
    execution_time_ms: int,
    error_message: str | None,
    ip_address: str | None,
    user_agent: str | None,
):
    """Worker function executed inside ThreadPoolExecutor to record session & event."""
    try:
        now = get_ist_now()
        device_type = detect_device_type(user_agent)

        with get_session() as session:
            # 1. Ensure user_session exists or update last_activity_at
            user_session = session.get(UserSession, session_id)
            if not user_session:
                user_session = UserSession(
                    id=session_id,
                    user_id=user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    device_type=device_type,
                    started_at=now,
                    last_activity_at=now,
                    is_active=True,
                )
                session.add(user_session)
            else:
                user_session.last_activity_at = now
                user_session.is_active = True
                if user_id and not user_session.user_id:
                    user_session.user_id = user_id
                if ip_address:
                    user_session.ip_address = ip_address

            # 2. Add event log
            event = UserEventLog(
                id=str(uuid.uuid4()),
                session_id=session_id,
                user_id=user_id,
                event_name=event_name[:100],
                event_category=event_category[:50],
                input_payload=input_payload,
                result_summary=result_summary,
                status=status if status in ["SUCCESS", "FAILURE", "PENDING", "CANCELLED"] else "SUCCESS",
                execution_time_ms=execution_time_ms or 0,
                error_message=str(error_message)[:1000] if error_message else None,
                ip_address=ip_address,
                created_at=now,
            )
            session.add(event)
    except Exception as exc:
        # Logging failed asynchronously; pass silently so main app is never affected
        pass


def record_event_async(
    session_id: str | None,
    user_id: int | None = None,
    user_role: str | None = None,
    event_name: str = "PAGE_VIEW",
    event_category: str = "NAVIGATION",
    input_payload: dict | list | None = None,
    result_summary: dict | list | None = None,
    status: str = "SUCCESS",
    execution_time_ms: int = 0,
    error_message: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
):
    """
    Public non-blocking entry point to queue telemetry writes.
    Includes Admin exclusion, payload sanitization, and deduplication.
    """
    if not session_id or not session_id.strip():
        return

    # Exclude admin activity from customer telemetry
    if user_role and str(user_role).strip().upper() in ["ADMIN", "SUPER_ADMIN"]:
        return

    # Sanitize payloads
    clean_input = sanitize_payload(input_payload) if input_payload else None
    clean_result = sanitize_payload(result_summary) if result_summary else None

    # Anti-spam deduplication check
    payload_fingerprint = json.dumps(clean_input, sort_keys=True, default=str) if clean_input else ""
    if _is_duplicate_event(session_id, event_name, payload_fingerprint):
        return

    # Dispatch to background thread pool
    _telemetry_executor.submit(
        _write_event_worker,
        session_id=session_id.strip(),
        user_id=user_id,
        event_name=event_name.strip(),
        event_category=event_category.strip(),
        input_payload=clean_input,
        result_summary=clean_result,
        status=status,
        execution_time_ms=execution_time_ms,
        error_message=error_message,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ----------------------------------------------------------------------
# Admin Telemetry Query Services
# ----------------------------------------------------------------------

def get_telemetry_stats(timeout_minutes: int = 10) -> dict:
    """Returns top KPI metrics for the Admin Dashboard."""
    now = get_ist_now()
    active_threshold = now - timedelta(minutes=timeout_minutes)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with get_session() as session:
        # Active sessions count
        active_sessions_count = (
            session.query(func.count(UserSession.id))
            .filter(UserSession.last_activity_at >= active_threshold)
            .scalar() or 0
        )

        # Total events today
        events_today_query = (
            session.query(
                func.count(UserEventLog.id).label("total"),
                func.sum(case((UserEventLog.status == "FAILURE", 1), else_=0)).label("failures"),
                func.avg(UserEventLog.execution_time_ms).label("avg_latency"),
            )
            .filter(UserEventLog.created_at >= today_start)
            .first()
        )

        total_events = events_today_query.total if events_today_query else 0
        failed_events = int(events_today_query.failures or 0) if events_today_query else 0
        avg_latency = round(float(events_today_query.avg_latency or 0), 1) if events_today_query else 0

        success_count = total_events - failed_events
        success_rate = round((success_count / total_events * 100), 1) if total_events > 0 else 100.0

        return {
            "activeSessions": active_sessions_count,
            "totalEventsToday": total_events,
            "failedEventsToday": failed_events,
            "successRatePercent": success_rate,
            "avgLatencyMs": avg_latency,
            "inactivityTimeoutMinutes": timeout_minutes,
        }


def get_telemetry_sessions(
    page: int = 1,
    page_size: int = 20,
    search: str = "",
    status_filter: str = "all",
    timeout_minutes: int = 10,
) -> dict:
    """Returns paginated session records with user identity, device, counts, and last activity."""
    now = get_ist_now()
    active_threshold = now - timedelta(minutes=timeout_minutes)

    page = max(1, int(page))
    page_size = min(max(5, int(page_size)), 100)
    offset = (page - 1) * page_size

    with get_session() as session:
        # Base query joined with User
        query = session.query(UserSession).outerjoin(User, UserSession.user_id == User.id)

        # Search filter
        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            query = query.filter(
                or_(
                    func.lower(UserSession.id).like(term),
                    func.lower(UserSession.ip_address).like(term),
                    func.lower(User.name).like(term),
                    func.lower(User.email).like(term),
                )
            )

        # Status filter
        if status_filter == "active":
            query = query.filter(UserSession.last_activity_at >= active_threshold)
        elif status_filter == "inactive":
            query = query.filter(UserSession.last_activity_at < active_threshold)

        total_sessions = query.count()

        # Fetch page records
        sessions = (
            query.order_by(UserSession.last_activity_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )

        session_list = []
        for s in sessions:
            # Calculate live active status
            is_active_live = s.last_activity_at >= active_threshold

            # Count total events and failure events for this session
            stats = (
                session.query(
                    func.count(UserEventLog.id).label("event_count"),
                    func.sum(case((UserEventLog.status == "FAILURE", 1), else_=0)).label("error_count"),
                )
                .filter(UserEventLog.session_id == s.id)
                .first()
            )

            # Get latest meaningful action / page view
            last_page_event = (
                session.query(UserEventLog)
                .filter(UserEventLog.session_id == s.id, UserEventLog.event_category == "NAVIGATION")
                .order_by(UserEventLog.created_at.desc())
                .first()
            )
            last_any_event = (
                session.query(UserEventLog)
                .filter(UserEventLog.session_id == s.id)
                .order_by(UserEventLog.created_at.desc())
                .first()
            )
            last_event = last_page_event or last_any_event

            session_list.append({
                "id": s.id,
                "userId": s.user_id,
                "userName": s.user.name if s.user else "Guest Visitor",
                "userEmail": s.user.email if s.user else None,
                "userRole": s.user.role.role_name if (s.user and s.user.role) else "GUEST",
                "ipAddress": s.ip_address or "Unknown",
                "deviceType": s.device_type or "desktop",
                "startedAt": s.started_at.isoformat() if s.started_at else None,
                "lastActivityAt": s.last_activity_at.isoformat() if s.last_activity_at else None,
                "isActive": is_active_live,
                "eventCount": stats.event_count if stats else 0,
                "errorCount": int(stats.error_count or 0) if stats else 0,
                "lastAction": last_event.event_name if last_event else "PAGE_VIEW",
                "lastStatus": last_event.status if last_event else "SUCCESS",
            })

        return {
            "sessions": session_list,
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total_sessions,
                "totalPages": (total_sessions + page_size - 1) // page_size,
            },
        }


def get_session_timeline(session_id: str, timeout_minutes: int = 10) -> dict:
    """Returns full step-by-step audit journey for a specific session."""
    with get_session() as session:
        user_session = session.get(UserSession, session_id)
        if not user_session:
            return {"session": None, "events": []}

        # Calculate live active status using the same threshold logic
        now = get_ist_now()
        active_threshold = now - timedelta(minutes=timeout_minutes)
        is_active_live = (
            user_session.last_activity_at >= active_threshold
            if user_session.last_activity_at
            else False
        )

        events = (
            session.query(UserEventLog)
            .filter(UserEventLog.session_id == session_id)
            .order_by(UserEventLog.created_at.asc())
            .all()
        )

        event_items = []
        for e in events:
            event_items.append({
                "id": e.id,
                "eventName": e.event_name,
                "category": e.event_category,
                "inputPayload": e.input_payload,
                "resultSummary": e.result_summary,
                "status": e.status,
                "executionTimeMs": e.execution_time_ms,
                "errorMessage": e.error_message,
                "ipAddress": e.ip_address,
                "createdAt": e.created_at.isoformat() if e.created_at else None,
            })

        return {
            "session": {
                "id": user_session.id,
                "userId": user_session.user_id,
                "userName": user_session.user.name if user_session.user else "Guest Visitor",
                "userEmail": user_session.user.email if user_session.user else None,
                "userRole": user_session.user.role.role_name if (user_session.user and user_session.user.role) else "GUEST",
                "deviceType": user_session.device_type,
                "ipAddress": user_session.ip_address,
                "startedAt": user_session.started_at.isoformat() if user_session.started_at else None,
                "lastActivityAt": user_session.last_activity_at.isoformat() if user_session.last_activity_at else None,
                "isActive": is_active_live,
            },
            "events": event_items,
        }

