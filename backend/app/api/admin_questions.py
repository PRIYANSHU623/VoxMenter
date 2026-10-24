"""Administrator routes for the daily question discovery job.

Every route requires an account listed in ADMIN_EMAILS (backend/.env). The
dependency is attached to the router itself, so a route added later cannot be
left open by accident.
"""

import logging
import os
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.core import question_discovery_config as config
from app.db.session import get_db
from app.models.question import Question
from app.models.question_discovery import (
    CategoryCooldown,
    QuestionGenerationRun,
    QuestionSource,
)
from app.models.user import User
from app.tasks.question_discovery_tasks import LOCK_NAME, discover_daily_questions

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/question-discovery",
    tags=["Admin: Question Discovery"],
    dependencies=[Depends(require_admin)],
)


# ---------- schemas ----------
class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    categories: list[str] | None = None
    ignore_cooldown: bool = False


class RunQueued(BaseModel):
    status: Literal["queued"]
    task_id: str
    categories: list[str] | None
    ignore_cooldown: bool


class StatusResponse(BaseModel):
    schedule_utc: str
    questions_per_category_per_day: int
    cooldown_days: int
    enabled_categories: list[str]
    search_enabled: bool
    ai_enabled: bool
    max_search_requests_per_run: int
    max_ai_calls_per_run: int
    max_token_budget_per_run: int
    run_in_progress: bool | None  # None when Redis could not be checked
    last_run_finished_at: datetime | None


class RunRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: str
    run_date: date
    category: str
    status: str
    target: int
    inserted_web: int
    inserted_ai: int
    duplicates_skipped: int
    invalid_skipped: int
    search_requests: int
    ai_calls: int
    tokens_used: int
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None


class CooldownState(BaseModel):
    category: str
    enabled: bool
    active: bool
    paused_until: datetime | None
    last_attempt_at: datetime | None
    last_status: str | None
    last_inserted: int
    consecutive_shortfalls: int


class DiscoveredQuestion(BaseModel):
    id: int
    title: str
    description: str | None
    category: str
    difficulty: str
    is_active: bool
    origin: str
    provider: str
    model_name: str | None
    source_url: str | None
    source_title: str | None
    source_domain: str | None
    attribution: str | None
    created_at: datetime


class QuestionActiveUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool


# ---------- helpers ----------
def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes. They are always UTC in this project."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _lock_held() -> bool | None:
    """True if a run holds the lock, False if not, None if Redis is unreachable."""
    client = None
    try:
        client = Redis.from_url(
            config.LOCK_REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        return bool(client.exists(LOCK_NAME))
    except (RedisError, OSError):
        logger.warning("Could not check the question discovery lock.")
        return None
    finally:
        if client is not None:
            client.connection_pool.disconnect()


def _ai_enabled() -> bool:
    return (
        bool(os.getenv("GEMINI_API_KEY", "").strip())
        and config.MAX_AI_CALLS_PER_RUN > 0
        and config.MAX_AI_CALLS_PER_CATEGORY > 0
    )


def _normalize_categories(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    cleaned = list(dict.fromkeys(v.strip().lower() for v in values if v.strip()))
    if not cleaned:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one category, or omit the field to run every enabled category.",
        )
    unknown = [v for v in cleaned if v not in config.SUPPORTED_CATEGORIES]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown categories: {', '.join(unknown)}. "
                f"Allowed: {', '.join(config.SUPPORTED_CATEGORIES)}"
            ),
        )
    return cleaned


def _cooldown_state(
    category: str,
    row: CategoryCooldown | None,
    now: datetime,
) -> CooldownState:
    paused_until = row.paused_until if row is not None else None
    return CooldownState(
        category=category,
        enabled=category in config.ENABLED_CATEGORIES,
        active=paused_until is not None and _aware(paused_until) > now,
        paused_until=paused_until,
        last_attempt_at=row.last_attempt_at if row is not None else None,
        last_status=row.last_status if row is not None else None,
        last_inserted=(row.last_inserted if row is not None else 0) or 0,
        consecutive_shortfalls=(row.consecutive_shortfalls if row is not None else 0) or 0,
    )


def _to_item(question: Question, source: QuestionSource) -> DiscoveredQuestion:
    return DiscoveredQuestion(
        id=question.id,
        title=question.title,
        description=question.description,
        category=question.category,
        difficulty=question.difficulty,
        is_active=question.is_active,
        origin=source.origin,
        provider=source.provider,
        model_name=source.model_name,
        source_url=source.source_url,
        source_title=source.source_title,
        source_domain=source.source_domain,
        attribution=source.attribution,
        created_at=source.created_at,
    )


# ---------- routes ----------
@router.get("/status", response_model=StatusResponse)
def get_status(db: Session = Depends(get_db)):
    last_finished = db.query(func.max(QuestionGenerationRun.finished_at)).scalar()
    return StatusResponse(
        schedule_utc=config.SCHEDULE_TIME,
        questions_per_category_per_day=config.QUESTIONS_PER_CATEGORY_PER_DAY,
        cooldown_days=config.CATEGORY_COOLDOWN_DAYS,
        enabled_categories=list(config.ENABLED_CATEGORIES),
        search_enabled=config.SEARCH_ENABLED,
        ai_enabled=_ai_enabled(),
        max_search_requests_per_run=config.MAX_SEARCH_REQUESTS_PER_RUN,
        max_ai_calls_per_run=config.MAX_AI_CALLS_PER_RUN,
        max_token_budget_per_run=config.MAX_TOKEN_BUDGET_PER_RUN,
        run_in_progress=_lock_held(),
        last_run_finished_at=last_finished,
    )


@router.post("/run", response_model=RunQueued, status_code=202)
def trigger_run(
    payload: RunRequest | None = None,
    admin: User = Depends(require_admin),
):
    payload = payload or RunRequest()
    categories = _normalize_categories(payload.categories)

    if _lock_held():
        raise HTTPException(
            status_code=409,
            detail="A discovery run is already in progress.",
        )

    try:
        task = discover_daily_questions.apply_async(
            kwargs={
                "categories": categories,
                "ignore_cooldown": payload.ignore_cooldown,
                "triggered_by": f"admin:{admin.id}",
            },
            expires=config.RUN_LOCK_TTL_SECONDS,
            retry=True,
            retry_policy={
                "max_retries": 1,
                "interval_start": 0,
                "interval_step": 0.2,
                "interval_max": 0.5,
            },
        )
    except Exception:
        logger.exception("Could not queue the question discovery task.")
        raise HTTPException(
            status_code=503,
            detail="The task queue is unavailable. Please try again.",
        )

    logger.info("Admin %s queued question discovery (task %s).", admin.id, task.id)
    return RunQueued(
        status="queued",
        task_id=str(task.id),
        categories=categories,
        ignore_cooldown=payload.ignore_cooldown,
    )


@router.get("/runs", response_model=list[RunRow])
def list_runs(
    category: str | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(QuestionGenerationRun)
    if category:
        query = query.filter(QuestionGenerationRun.category == category.strip().lower())
    return (
        query.order_by(
            QuestionGenerationRun.run_date.desc(),
            QuestionGenerationRun.id.desc(),
        )
        .limit(limit)
        .all()
    )


@router.get("/cooldowns", response_model=list[CooldownState])
def list_cooldowns(db: Session = Depends(get_db)):
    rows = {row.category: row for row in db.query(CategoryCooldown).all()}
    now = datetime.now(timezone.utc)
    return [
        _cooldown_state(category, rows.get(category), now)
        for category in config.SUPPORTED_CATEGORIES
    ]


@router.delete("/cooldowns/{category}", response_model=CooldownState)
def clear_cooldown(
    category: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    key = category.strip().lower()
    if key not in config.SUPPORTED_CATEGORIES:
        raise HTTPException(status_code=404, detail="Unknown category")

    row = db.get(CategoryCooldown, key)
    if row is not None and row.paused_until is not None:
        row.paused_until = None
        db.commit()
        db.refresh(row)
        logger.info("Admin %s cleared the cooldown for %s.", admin.id, key)

    return _cooldown_state(key, row, datetime.now(timezone.utc))


@router.get("/questions", response_model=list[DiscoveredQuestion])
def list_discovered_questions(
    category: str | None = Query(default=None),
    origin: Literal["web", "ai_generated"] | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Question, QuestionSource).join(
        QuestionSource, QuestionSource.question_id == Question.id
    )
    if category:
        query = query.filter(Question.category == category.strip().lower())
    if origin:
        query = query.filter(QuestionSource.origin == origin)
    if is_active is not None:
        query = query.filter(Question.is_active.is_(is_active))

    rows = query.order_by(Question.id.desc()).offset(skip).limit(limit).all()
    return [_to_item(question, source) for question, source in rows]


@router.patch("/questions/{question_id}", response_model=DiscoveredQuestion)
def set_question_active(
    question_id: int,
    payload: QuestionActiveUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    row = (
        db.query(Question, QuestionSource)
        .join(QuestionSource, QuestionSource.question_id == Question.id)
        .filter(Question.id == question_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Auto-added question not found")

    question, source = row
    question.is_active = payload.is_active
    db.commit()
    db.refresh(question)
    logger.info(
        "Admin %s set question %s active=%s.", admin.id, question_id, payload.is_active
    )
    return _to_item(question, source)
