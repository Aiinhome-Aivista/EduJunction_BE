"""Simple in-process rate limiter (per IP, sliding window). Good enough for a
single-instance deployment; swap for a Redis-backed limiter before scaling
horizontally — that's a documented limitation, not a hidden gap."""
import time
import threading
from collections import defaultdict, deque

from flask import request

from utils.errors import AppError

_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)

WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 120


def rate_limit():
    """Call at the top of app.before_request. Raises 429 when exceeded."""
    identity = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
    now = time.time()
    with _lock:
        window = _hits[identity]
        while window and now - window[0] > WINDOW_SECONDS:
            window.popleft()
        if len(window) >= MAX_REQUESTS_PER_WINDOW:
            raise AppError("RATE_LIMITED", "Too many requests, please slow down", 429)
        window.append(now)
