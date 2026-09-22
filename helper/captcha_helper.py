"""Custom stateless Math Captcha generator and verifier using HMAC signatures."""
import base64
import hashlib
import hmac
import random
import time
from utils.config import config


def _get_secret() -> bytes:
    key = config.JWT_SECRET_KEY or "edujunction-default-secure-captcha-secret-key-2026"
    return key.encode("utf-8")


def generate_math_captcha(ttl_seconds: int = 600) -> dict:
    """
    Generates a simple random math problem and returns the question text
    along with a secure HMAC-signed token (captchaId).
    """
    op = random.choice(["+", "-", "+", "*"])
    if op == "+":
        a = random.randint(3, 29)
        b = random.randint(2, 20)
        answer = a + b
        question = f"{a} + {b} = ?"
    elif op == "-":
        a = random.randint(10, 35)
        b = random.randint(1, a - 1)
        answer = a - b
        question = f"{a} - {b} = ?"
    else:  # multiplication with small single digits
        a = random.randint(2, 9)
        b = random.randint(2, 9)
        answer = a * b
        question = f"{a} * {b} = ?"

    expiry = int(time.time()) + ttl_seconds
    salt = base64.urlsafe_b64encode(random.randbytes(8)).decode("utf-8").rstrip("=")
    
    # Payload for signature includes answer, expiry, and salt
    sign_payload = f"{answer}:{expiry}:{salt}".encode("utf-8")
    signature = hmac.new(_get_secret(), sign_payload, hashlib.sha256).hexdigest()

    # Raw token data containing expiry, salt, and HMAC signature
    raw_token = f"{expiry}:{salt}:{signature}"
    captcha_id = base64.urlsafe_b64encode(raw_token.encode("utf-8")).decode("utf-8")

    return {
        "captchaId": captcha_id,
        "question": question,
    }


def verify_math_captcha(captcha_id: str | None, user_answer: str | int | None) -> tuple[bool, str]:
    """
    Verifies the user's captcha answer against the HMAC-signed captcha_id.
    Returns (is_valid, error_message).
    """
    if not captcha_id or str(captcha_id).strip() == "":
        return False, "Captcha token is missing. Please refresh and try again."

    if user_answer is None or str(user_answer).strip() == "":
        return False, "Please enter the answer to the security captcha."

    try:
        user_ans_int = int(str(user_answer).strip())
    except (ValueError, TypeError):
        return False, "Captcha answer must be a valid number."

    try:
        decoded = base64.urlsafe_b64decode(captcha_id.encode("utf-8")).decode("utf-8")
        parts = decoded.split(":")
        if len(parts) != 3:
            return False, "Invalid captcha token format."

        expiry_str, salt, signature = parts
        expiry = int(expiry_str)

        current_time = int(time.time())
        if current_time > expiry:
            return False, "Captcha has expired. Please refresh for a new question."

        # Verify signature with user's provided answer
        sign_payload = f"{user_ans_int}:{expiry}:{salt}".encode("utf-8")
        expected_sig = hmac.new(_get_secret(), sign_payload, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected_sig, signature):
            return False, "Incorrect captcha answer. Please try again."

        return True, ""
    except Exception:
        return False, "Captcha verification failed. Please refresh and try again."
