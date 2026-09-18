"""Structured logging. Never pass password/token/API-key values to these calls."""
import logging
import sys

logger = logging.getLogger("sahajpath")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter('{"time":"%(asctime)s","level":"%(levelname)s","msg":%(message)r}')
    )
    logger.addHandler(handler)


def log_request(method: str, path: str, status: int, duration_ms: float, user_id: str | None = None):
    logger.info(f"{method} {path} status={status} duration_ms={duration_ms:.1f} user={user_id or '-'}")


def log_ai_call(operation: str, duration_ms: float, success: bool, fallback_used: bool = False):
    logger.info(
        f"ai_call op={operation} duration_ms={duration_ms:.1f} success={success} fallback={fallback_used}"
    )
