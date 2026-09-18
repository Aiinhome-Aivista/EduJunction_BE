"""Authentication middleware: extracts and verifies the JWT bearer token,
attaches the current user's id/role onto flask.g for downstream handlers."""
from functools import wraps

import jwt
from flask import request, g

from utils.errors import UnauthorizedError
from utils.security import decode_token


def _extract_token() -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise UnauthorizedError("Missing or malformed Authorization header")
    return auth_header.split(" ", 1)[1].strip()


def token_required(fn):
    """Attaches g.current_user_id / g.current_user_role. Raises 401 on any
    missing/invalid/expired token."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _extract_token()
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            raise UnauthorizedError("Access token expired", code="TOKEN_EXPIRED")
        except jwt.PyJWTError:
            raise UnauthorizedError("Invalid access token", code="TOKEN_INVALID")

        if payload.get("type") != "access":
            raise UnauthorizedError("Refresh tokens cannot be used to access this endpoint")

        sub = payload["sub"]
        g.current_user_id = int(sub) if str(sub).isdigit() else sub
        g.current_user_role = str(payload.get("role", "")).upper()
        return fn(*args, **kwargs)

    return wrapper
