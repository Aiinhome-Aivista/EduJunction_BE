"""Telemetry & User Session Tracking Controller:
Endpoints for admin dashboard stats, sessions stream, session timeline,
and frontend non-blocking event tracking.
"""
from flask import g, request

from helper.telemetry_service import (
    extract_client_ip,
    get_session_timeline,
    get_telemetry_sessions,
    get_telemetry_stats,
    record_event_async,
)
from utils.response import success


def get_stats():
    """GET /api/v1/admin/telemetry/stats?timeout_minutes=10"""
    timeout_minutes = int(request.args.get("timeout_minutes", 10))
    data = get_telemetry_stats(timeout_minutes=timeout_minutes)
    return success(data, message="Telemetry stats retrieved successfully")


def get_sessions():
    """GET /api/v1/admin/telemetry/sessions?page=1&page_size=20&search=&status_filter=all&timeout_minutes=10"""
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", request.args.get("limit", 20)))
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status_filter", request.args.get("status", "all")).strip().lower()
    timeout_minutes = int(request.args.get("timeout_minutes", 10))

    data = get_telemetry_sessions(
        page=page,
        page_size=page_size,
        search=search,
        status_filter=status_filter,
        timeout_minutes=timeout_minutes,
    )
    return success(data, message="Telemetry sessions retrieved successfully")


def get_timeline(session_id: str):
    """GET /api/v1/admin/telemetry/sessions/<session_id>/timeline"""
    timeout_minutes = int(request.args.get("timeout_minutes", 10))
    data = get_session_timeline(session_id, timeout_minutes=timeout_minutes)
    return success(data, message="Session timeline retrieved successfully")


def track_event():
    """POST /api/v1/track/event
    Public non-blocking ingestion endpoint for frontend user actions.
    """
    payload = request.get_json(silent=True) or {}

    session_id = payload.get("sessionId") or request.headers.get("x-session-id")
    event_name = payload.get("eventName", "PAGE_VIEW")
    category = payload.get("category", "NAVIGATION")
    input_payload = payload.get("inputPayload")
    result_summary = payload.get("resultSummary")
    status = payload.get("status", "SUCCESS")
    execution_time_ms = int(payload.get("executionTimeMs", 0))
    error_message = payload.get("errorMessage")

    ip_address = extract_client_ip(request)
    user_agent = request.headers.get("User-Agent")

    user_id = getattr(g, "current_user_id", None)
    user_role = getattr(g, "current_user_role", None)

    # Queue asynchronous write
    record_event_async(
        session_id=session_id,
        user_id=user_id,
        user_role=user_role,
        event_name=event_name,
        event_category=category,
        input_payload=input_payload,
        result_summary=result_summary,
        status=status,
        execution_time_ms=execution_time_ms,
        error_message=error_message,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return success({"queued": True}, message="Event queued for telemetry")

