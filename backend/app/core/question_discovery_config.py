"""Settings for the daily question discovery and generation job.

Every value can be overridden from backend/.env. Invalid values stop the app
at import time with a clear message instead of failing in the middle of a run.

SCHEDULE_TIME is interpreted as UTC, because celery_app.py runs in UTC.
(03:00 UTC is 08:30 in India.)
"""

import os

from dotenv import load_dotenv

load_dotenv()

# Must match the QuestionType values used by the evaluator.
SUPPORTED_CATEGORIES = (
    "dsa",
    "python",
    "dbms_sql",
    "oop",
    "ai_ml",
    "hr",
    "project",
    "general",
)

_CATEGORY_ALIASES = {
    "projects": "project",
    "dbms": "dbms_sql",
    "sql": "dbms_sql",
    "dbms/sql": "dbms_sql",
    "ai/ml": "ai_ml",
}


def _int_env(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a whole number, got {raw!r}") from None
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}, got {value}")
    return value


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a number, got {raw!r}") from None
    if not 0 < value <= 1:
        raise RuntimeError(f"{name} must be greater than 0 and at most 1, got {value}")
    return value


def _parse_time(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.strip().split(":")
        hour, minute = int(hour_text), int(minute_text)
    except ValueError:
        raise RuntimeError(f'SCHEDULE_TIME must look like "03:00", got {value!r}') from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise RuntimeError(f"SCHEDULE_TIME is not a valid time: {value!r}")
    return hour, minute


def _parse_categories(value: str) -> tuple[str, ...]:
    categories: list[str] = []
    for item in value.split(","):
        key = item.strip().lower()
        if not key:
            continue
        key = _CATEGORY_ALIASES.get(key, key.replace(" ", "_").replace("-", "_"))
        if key not in SUPPORTED_CATEGORIES:
            raise RuntimeError(
                f"ENABLED_CATEGORIES contains unknown category {item.strip()!r}. "
                f"Allowed: {', '.join(SUPPORTED_CATEGORIES)}"
            )
        if key not in categories:
            categories.append(key)
    if not categories:
        raise RuntimeError("ENABLED_CATEGORIES must contain at least one category")
    return tuple(categories)


# ---------- Targets and scheduling ----------
QUESTIONS_PER_CATEGORY_PER_DAY = _int_env("QUESTIONS_PER_CATEGORY_PER_DAY", 7, 1)

# After a category comes up short, it is skipped for this many days.
CATEGORY_COOLDOWN_DAYS = _int_env("CATEGORY_COOLDOWN_DAYS", 3, 1)

SCHEDULE_TIME = os.getenv("SCHEDULE_TIME", "03:00").strip()
SCHEDULE_HOUR, SCHEDULE_MINUTE = _parse_time(SCHEDULE_TIME)

ENABLED_CATEGORIES = _parse_categories(
    os.getenv("ENABLED_CATEGORIES", ",".join(SUPPORTED_CATEGORIES))
)

# ---------- Limits per run (the whole daily job) ----------
# 0 disables that kind of request.
MAX_SEARCH_REQUESTS_PER_RUN = _int_env("MAX_SEARCH_REQUESTS_PER_RUN", 16, 0)
MAX_AI_CALLS_PER_RUN = _int_env("MAX_AI_CALLS_PER_RUN", 16, 0)
# Total tokens (prompt + response) reported by Gemini across the whole run.
MAX_TOKEN_BUDGET_PER_RUN = _int_env("MAX_TOKEN_BUDGET_PER_RUN", 80000, 1)

# Per-category caps, so one category can't use up the whole run budget.
MAX_SEARCH_REQUESTS_PER_CATEGORY = _int_env("MAX_SEARCH_REQUESTS_PER_CATEGORY", 2, 0)
MAX_AI_CALLS_PER_CATEGORY = _int_env("MAX_AI_CALLS_PER_CATEGORY", 2, 0)

# ---------- Provider failures ----------
# Extra attempts after a failed provider call (0 = never retry).
# Each retry counts against the request limits above.
MAX_PROVIDER_RETRIES = _int_env("MAX_PROVIDER_RETRIES", 2, 0)
RETRY_BACKOFF_SECONDS = _int_env("RETRY_BACKOFF_SECONDS", 2, 0)

# ---------- Question validation ----------
MIN_QUESTION_LENGTH = _int_env("MIN_QUESTION_LENGTH", 15, 1)
# questions.title is String(255) in the database.
MAX_QUESTION_LENGTH = _int_env("MAX_QUESTION_LENGTH", 255, 20)
if MAX_QUESTION_LENGTH > 255:
    raise RuntimeError("MAX_QUESTION_LENGTH cannot exceed 255 (questions.title limit)")
if MIN_QUESTION_LENGTH >= MAX_QUESTION_LENGTH:
    raise RuntimeError("MIN_QUESTION_LENGTH must be smaller than MAX_QUESTION_LENGTH")

# The frontend sorts difficulty chips using these exact names.
ALLOWED_DIFFICULTIES = ("Beginner", "Intermediate", "Advanced")
DEFAULT_DIFFICULTY = "Beginner"

# ---------- Duplicate detection ----------
DEDUP_JACCARD_THRESHOLD = _float_env("DEDUP_JACCARD_THRESHOLD", 0.8)
DEDUP_SEQUENCE_THRESHOLD = _float_env("DEDUP_SEQUENCE_THRESHOLD", 0.9)

# ---------- Locking (prevents overlapping runs) ----------
RUN_LOCK_TTL_SECONDS = _int_env("RUN_LOCK_TTL_SECONDS", 3600, 60)
LOCK_REDIS_URL = os.getenv("QUESTION_LOCK_REDIS_URL") or os.getenv(
    "CELERY_BROKER_URL", "redis://127.0.0.1:6379/1"
)

# ---------- Web search (optional) ----------
# Leave empty to run with AI generation only.
SEARCH_PROVIDER = os.getenv("QUESTION_SEARCH_PROVIDER", "").strip().lower()
SEARCH_API_KEY = os.getenv("QUESTION_SEARCH_API_KEY", "").strip()
SEARCH_ENABLED = bool(
    SEARCH_PROVIDER
    and SEARCH_API_KEY
    and MAX_SEARCH_REQUESTS_PER_RUN > 0
    and MAX_SEARCH_REQUESTS_PER_CATEGORY > 0
)

# ---------- Admin access ----------
# Comma-separated emails allowed to trigger jobs and view admin status.
# The users table has no role column, so admins are defined here.
ADMIN_EMAILS = frozenset(
    email.strip().lower()
    for email in os.getenv("ADMIN_EMAILS", "").split(",")
    if email.strip()
)