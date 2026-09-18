import re

from utils.constants import BOARDS, ACTIVE_BOARDS, CLASS_GRADES, BOARD_CLASS_MAPPING, SUBJECTS, DIFFICULTIES
from utils.errors import ValidationError

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def require_fields(payload: dict, fields: list[str]):
    missing = [f for f in fields if payload.get(f) in (None, "")]
    if missing:
        raise ValidationError(f"Missing required field(s): {', '.join(missing)}")


def validate_email(email: str):
    if not email or not EMAIL_RE.match(email):
        raise ValidationError("Invalid email address")


def validate_password_strength(password: str):
    if not password or len(password) < 8:
        raise ValidationError("Password must be at least 8 characters long")


def validate_enum(value: str, allowed: list[str], field_name: str):
    if value not in allowed:
        raise ValidationError(f"Invalid {field_name}: '{value}'. Must be one of {allowed}")


def validate_board(value: str):
    validate_enum(value, BOARDS, "board")


def validate_class_grade(value: str):
    validate_enum(value, CLASS_GRADES, "classGrade")


def validate_board_class(board: str, class_grade: str):
    validate_board(board)
    validate_class_grade(class_grade)
    allowed_classes = BOARD_CLASS_MAPPING.get(board)
    if allowed_classes and class_grade not in allowed_classes:
        raise ValidationError(
            f"'{class_grade}' is not applicable for {board}. "
            f"Allowed classes for {board}: {', '.join(allowed_classes)}."
        )


def validate_subject(value: str):
    validate_enum(value, SUBJECTS, "subject")


def validate_difficulty(value: str):
    validate_enum(value, DIFFICULTIES, "difficulty")


def validate_pin(pin: str):
    if not pin or not re.match(r"^\d{4,6}$", pin):
        raise ValidationError("PIN must be 4-6 digits")


USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,28}[a-zA-Z0-9]$")


def validate_username(username: str):
    if not username or not isinstance(username, str):
        raise ValidationError("Username is required")
    u = username.strip()
    if len(u) < 3 or len(u) > 30:
        raise ValidationError("Username must be between 3 and 30 characters")
    if "." in u:
        raise ValidationError("Username cannot contain dots ('.')")
    if " " in u:
        raise ValidationError("Username cannot contain spaces")
    if not USERNAME_RE.match(u):
        raise ValidationError(
            "Username can only contain letters, numbers, underscores, and hyphens (3-30 characters), and cannot start or end with a symbol."
        )

