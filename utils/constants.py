"""Constants mirrored from the frontend's src/types.ts so both sides agree on
valid enum values without the backend needing to import TypeScript."""

BOARDS = [
    "CBSE", "ICSE", "ISC", "WBBSE", "WBCHSE", "UK-Cambridge", "NCERT", "NEET", "IIT", "WB"
]

ACTIVE_BOARDS = ["CBSE", "ICSE", "ISC", "WBBSE", "WBCHSE"]

CLASS_GRADES = [
    "Class 1", "Class 2", "Class 3", "Class 4",
    "Class 5", "Class 6", "Class 7", "Class 8",
    "Class 9", "Class 10", "Class 11", "Class 12",
]

BOARD_CLASS_MAPPING = {
    "CBSE": [f"Class {i}" for i in range(1, 13)],
    "ICSE": [f"Class {i}" for i in range(1, 11)],
    "ISC": ["Class 11", "Class 12"],
    "WBBSE": [f"Class {i}" for i in range(1, 11)],
    "WBCHSE": ["Class 11", "Class 12"],
    "WB": [f"Class {i}" for i in range(1, 11)],
    "UK-Cambridge": [f"Class {i}" for i in range(1, 13)],
    "NCERT": [f"Class {i}" for i in range(1, 13)],
    "NEET": ["Class 11", "Class 12"],
    "IIT": ["Class 11", "Class 12"],
}

SUBJECTS = [
    "Mathematics", "Physics", "Chemistry", "Biology", "Science",
    "Social Studies", "English", "Computer Science", "Logical Reasoning",
    "General Science", "Social Science", "English Core",
]

SUBJECT_ALIASES = {
    "general science": "Science",
    "social science": "Social Studies",
    "english core": "English",
    "maths": "Mathematics",
    "math": "Mathematics",
    "comp science": "Computer Science",
    "cs": "Computer Science",
    "evs": "Science",
}


def normalize_subject(subject: str) -> str:
    if not subject:
        return "Science"
    clean = str(subject).strip()
    return SUBJECT_ALIASES.get(clean.lower(), clean)

DIFFICULTIES = ["simple", "medium", "hard"]

QUESTION_TYPES = ["mcq", "objective", "numerical", "logical"]

PERFORMANCE_BANDS = [
    "Needs Foundation", "Developing", "Proficient", "Advanced Mastery", "Competitive Ready",
]

BADGE_IDS = {
    "PIONEER": "badge-pioneer",
    "PERFECT_10": "badge-perfect-10",
    "SPEED_DEMON": "badge-speed-demon",
    "STREAK_3": "badge-streak-3",
    "STREAK_7": "badge-streak-7",
    "OLYMPIAD_THINKER": "badge-olympiad-thinker",
}

DEFAULT_EXAM_QUESTION_COUNT = 10
DEFAULT_EXAM_TOTAL_MARKS = 10
DEFAULT_EXAM_TIME_LIMIT_MINUTES = 15
