"""Password hashing and JWT encode/decode. No plaintext secret ever touches a
response.

Uses the `bcrypt` library directly rather than passlib's bcrypt wrapper:
passlib 1.7.x's backend-detection code is incompatible with bcrypt>=4.1
(the `__about__` attribute it probes for was removed), so we talk to
bcrypt's own API instead of depending on passlib being patched.
"""
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from utils.config import config

BCRYPT_ROUNDS = 12
MAX_BCRYPT_BYTES = 72  # bcrypt silently ignores bytes beyond this — reject earlier inputs explicitly instead


def _prepare(raw: str) -> bytes:
    encoded = raw.encode("utf-8")
    if len(encoded) > MAX_BCRYPT_BYTES:
        raise ValueError("Password/PIN exceeds bcrypt's 72-byte limit")
    return encoded


def hash_password(raw_password: str) -> str:
    hashed = bcrypt.hashpw(_prepare(raw_password), bcrypt.gensalt(rounds=BCRYPT_ROUNDS))
    return hashed.decode("utf-8")


def verify_password(raw_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(raw_password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_pin(raw_pin: str) -> str:
    """PINs use the same hashing scheme as passwords — never stored/compared in plaintext."""
    return hash_password(raw_pin)


def verify_pin(raw_pin: str, pin_hash: str) -> bool:
    return verify_password(raw_pin, pin_hash)


def _create_token(subject: str, role: str, expires_delta: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm="HS256")


def create_access_token(user_id: str, role: str) -> str:
    return _create_token(
        user_id, role, timedelta(minutes=config.JWT_ACCESS_TOKEN_EXPIRE_MINUTES), "access"
    )


def create_refresh_token(user_id: str, role: str) -> str:
    return _create_token(
        user_id, role, timedelta(days=config.JWT_REFRESH_TOKEN_EXPIRE_DAYS), "refresh"
    )


def decode_token(token: str) -> dict:
    """Raises jwt.PyJWTError subclasses on invalid/expired tokens — callers must catch."""
    return jwt.decode(token, config.JWT_SECRET_KEY, algorithms=["HS256"])
