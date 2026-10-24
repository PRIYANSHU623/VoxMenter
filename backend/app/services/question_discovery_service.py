"""Daily question discovery and generation.

For every enabled category the job:

1. skips the category while it is on cooldown,
2. works out how many questions are still missing for today,
3. looks for real questions on the web (search provider),
4. asks Gemini for original questions if more are needed,
5. checks every candidate against the database and the current batch,
6. saves new questions together with their source details,
7. records the day's result, and starts a cooldown if the category ran dry.

Providers are passed in, so tests can use fakes and never spend real credits.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import question_discovery_config as config
from app.models.question import Question
from app.models.question_discovery import (
    ORIGIN_AI,
    ORIGIN_WEB,
    RUN_COMPLETED,
    RUN_EXHAUSTED,
    RUN_FAILED,
    RUN_LIMIT_REACHED,
    RUN_RUNNING,
    RUN_SKIPPED_COOLDOWN,
    CategoryCooldown,
    QuestionGenerationRun,
    QuestionSource,
)
from app.services.question_dedup import QuestionDeduplicator, build_deduplicator, exact_key
from app.services.question_generation_provider import (
    MAX_QUESTIONS_PER_CALL,
    GenerationProviderError,
    GenerationResult,
)
from app.services.question_search_provider import (
    CandidateQuestion,
    SearchProviderError,
    query_for,
)
from app.services.run_budget import (
    AI_RUN_LIMIT,
    SEARCH_RUN_LIMIT,
    TOKEN_BUDGET,
    BudgetExceeded,
    RunBudget,
)

logger = logging.getLogger(__name__)

# Reported (never stored) when a category was already handled today.
STATUS_ALREADY_DONE = "already_processed"

AI_EXTRA_QUESTIONS = 3  # ask for a few extra to absorb duplicates
AVOID_LIMIT = 40
MAX_ERROR_LENGTH = 1000

# Limits shared by the whole run. Hitting one of these is not the category's
# fault, so it never starts a cooldown. Per-category caps are the normal end
# of a category's effort and are not listed here.
_RUN_LEVEL_REASONS = frozenset({SEARCH_RUN_LIMIT, AI_RUN_LIMIT, TOKEN_BUDGET})


class SearchProvider(Protocol):
    def search_questions(
        self, category: str, query: str, budget: RunBudget
    ) -> list[CandidateQuestion]: ...


class QuestionGenerator(Protocol):
    def generate_questions(
        self,
        category: str,
        count: int,
        budget: RunBudget,
        avoid: Sequence[str] = (),
    ) -> GenerationResult: ...


# ---------- results ----------
@dataclass
class CategoryResult:
    category: str
    status: str
    inserted_web: int = 0
    inserted_ai: int = 0
    duplicates_skipped: int = 0
    invalid_skipped: int = 0
    search_requests: int = 0
    ai_calls: int = 0
    tokens_used: int = 0
    message: str | None = None

    @property
    def inserted_total(self) -> int:
        return self.inserted_web + self.inserted_ai


@dataclass
class DiscoveryReport:
    run_id: str
    started_at: datetime
    finished_at: datetime
    results: list[CategoryResult]

    @property
    def total_inserted(self) -> int:
        return sum(result.inserted_total for result in self.results)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "total_inserted": self.total_inserted,
            "categories": [
                {**asdict(result), "inserted_total": result.inserted_total}
                for result in self.results
            ],
        }


# ---------- small helpers ----------
def _as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes. They are always UTC in this project."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resume_at(today: date, days: int) -> datetime:
    return datetime.combine(today + timedelta(days=days), time.min, tzinfo=timezone.utc)


def _rotate(items: list[str], day: date) -> list[str]:
    offset = day.toordinal() % len(items)
    return items[offset:] + items[:offset]


def _difficulty_from_query(query: str) -> str:
    """Web snippets carry no difficulty, so use hints from the search query."""
    lowered = query.lower()
    if "advanced" in lowered:
        return "Advanced"
    if any(word in lowered for word in ("fresher", "basic", "beginner")):
        return "Beginner"
    return config.DEFAULT_DIFFICULTY


def _is_stale(run: QuestionGenerationRun, now: datetime) -> bool:
    return now - _as_utc(run.started_at) > timedelta(seconds=config.RUN_LOCK_TTL_SECONDS)


class _JobState:
    """Provider availability for the whole job."""

    def __init__(
        self,
        search_provider: SearchProvider | None,
        generator: QuestionGenerator | None,
    ) -> None:
        self.search_provider = search_provider
        self.generator = generator
        # Set when a provider rejects our key, so later categories don't retry.
        self.search_disabled_reason: str | None = None
        self.ai_disabled_reason: str | None = None


# ---------- daily run rows ----------
def _open_run(
    db: Session,
    run_id: str,
    category: str,
    target: int,
    now: datetime,
) -> QuestionGenerationRun | None:
    """Create or re-open today's row for a category.

    Returns None when the category is already finished today or another run
    holds it. The database allows one row per (day, category), and re-opening
    is an atomic compare-and-set, so two workers cannot both claim a category.
    """
    today = now.date()
    run = (
        db.query(QuestionGenerationRun)
        .filter(
            QuestionGenerationRun.run_date == today,
            QuestionGenerationRun.category == category,
        )
        .first()
    )

    if run is None:
        run = QuestionGenerationRun(
            run_id=run_id,
            run_date=today,
            category=category,
            status=RUN_RUNNING,
            target=target,
            started_at=now,
        )
        db.add(run)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # another worker created today's row first
            return None
        return run

    if run.status in (RUN_COMPLETED, RUN_EXHAUSTED):
        return None
    if run.status == RUN_RUNNING and not _is_stale(run, now):
        return None

    claimed = (
        db.query(QuestionGenerationRun)
        .filter(
            QuestionGenerationRun.id == run.id,
            QuestionGenerationRun.status == run.status,
            QuestionGenerationRun.run_id == run.run_id,
        )
        .update(
            {
                "status": RUN_RUNNING,
                "run_id": run_id,
                "target": target,
                "started_at": now,
                "finished_at": None,
                "error_message": None,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if claimed == 0:
        return None
    db.refresh(run)
    return run


def _record_skip(
    db: Session,
    run_id: str,
    category: str,
    target: int,
    now: datetime,
    resume: datetime,
) -> CategoryResult:
    run = _open_run(db, run_id, category, target, now)
    if run is None:
        return CategoryResult(
            category=category,
            status=STATUS_ALREADY_DONE,
            message="Already processed today, or another run is working on it.",
        )

    message = f"Paused until {resume.date().isoformat()} after the last attempt fell short."
    run.status = RUN_SKIPPED_COOLDOWN
    run.error_message = message
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return CategoryResult(category=category, status=RUN_SKIPPED_COOLDOWN, message=message)


class _CategoryRun:
    """Counters for one category. Written to the run row as absolute values,
    so a rolled-back commit never leaves them wrong."""

    def __init__(self, run: QuestionGenerationRun) -> None:
        self.run = run
        self.base_web = run.inserted_web or 0
        self.base_ai = run.inserted_ai or 0
        self.base_duplicates = run.duplicates_skipped or 0
        self.base_invalid = run.invalid_skipped or 0
        self.base_search = run.search_requests or 0
        self.base_ai_calls = run.ai_calls or 0
        self.base_tokens = run.tokens_used or 0
        self.web = 0
        self.ai = 0
        self.duplicates = 0
        self.invalid = 0

    @property
    def inserted_today(self) -> int:
        return self.base_web + self.base_ai + self.web + self.ai

    def sync(self, usage: Any) -> None:
        self.run.inserted_web = self.base_web + self.web
        self.run.inserted_ai = self.base_ai + self.ai
        self.run.duplicates_skipped = self.base_duplicates + self.duplicates
        self.run.invalid_skipped = self.base_invalid + self.invalid
        self.run.search_requests = self.base_search + usage.search_requests
        self.run.ai_calls = self.base_ai_calls + usage.ai_calls
        self.run.tokens_used = self.base_tokens + usage.tokens_used


# ---------- the work for one category ----------
class _CategoryWorker:
    def __init__(
        self,
        db: Session,
        state: _JobState,
        dedup: QuestionDeduplicator,
        budget: RunBudget,
        category: str,
        run: QuestionGenerationRun,
        target: int,
        now: datetime,
    ) -> None:
        self.db = db
        self.state = state
        self.dedup = dedup
        self.budget = budget
        self.category = category
        self.target = target
        self.now = now
        self.cr = _CategoryRun(run)
        self.errors: list[str] = []
        self.limit_hit = False
        self.attempted = False

    @property
    def done(self) -> bool:
        return self.cr.inserted_today >= self.target

    def execute(self) -> None:
        self._search_phase()
        if not self.done:
            self._ai_phase()

    def _search_phase(self) -> None:
        provider = self.state.search_provider
        if provider is None:
            return
        if self.state.search_disabled_reason:
            self.errors.append(self.state.search_disabled_reason)
            return

        for attempt in range(max(1, self.budget.max_search_per_category)):
            if self.done:
                return

            reason = self.budget.search_block_reason(self.category)
            if reason is not None:
                if reason in _RUN_LEVEL_REASONS:
                    self.limit_hit = True
                return

            query = query_for(self.category, attempt, self.now.date())
            try:
                candidates = provider.search_questions(self.category, query, self.budget)
            except BudgetExceeded as error:
                if error.reason in _RUN_LEVEL_REASONS:
                    self.limit_hit = True
                return
            except SearchProviderError as error:
                self.attempted = True
                self.errors.append(f"Search: {error}")
                if error.is_auth_error:
                    self.state.search_disabled_reason = f"Search: {error}"
                return

            self.attempted = True
            difficulty = _difficulty_from_query(query)
            for candidate in candidates:
                if self.done:
                    break
                self._add(
                    candidate.text,
                    difficulty,
                    None,
                    ORIGIN_WEB,
                    provider=candidate.provider,
                    source_url=candidate.source_url,
                    source_title=candidate.source_title,
                    source_domain=candidate.source_domain,
                    attribution=candidate.attribution,
                    search_query=candidate.search_query,
                )

    def _ai_phase(self) -> None:
        generator = self.state.generator
        if generator is None:
            return
        if self.state.ai_disabled_reason:
            self.errors.append(self.state.ai_disabled_reason)
            return

        for _ in range(max(1, self.budget.max_ai_per_category)):
            need = self.target - self.cr.inserted_today
            if need <= 0:
                return

            reason = self.budget.ai_block_reason(self.category)
            if reason is not None:
                if reason in _RUN_LEVEL_REASONS:
                    self.limit_hit = True
                return

            ask = min(MAX_QUESTIONS_PER_CALL, need + AI_EXTRA_QUESTIONS)
            try:
                result = generator.generate_questions(
                    self.category, ask, self.budget, self._recent_titles()
                )
            except BudgetExceeded as error:
                if error.reason in _RUN_LEVEL_REASONS:
                    self.limit_hit = True
                return
            except GenerationProviderError as error:
                self.attempted = True
                self.errors.append(f"AI: {error}")
                if error.is_auth_error:
                    self.state.ai_disabled_reason = f"AI: {error}"
                return

            self.attempted = True
            self.cr.invalid += result.rejected

            added = 0
            for candidate in result.candidates:
                if self.done:
                    break
                saved = self._add(
                    candidate.text,
                    candidate.difficulty,
                    candidate.description,
                    ORIGIN_AI,
                    provider=candidate.provider,
                    model_name=candidate.model_name,
                    attribution=candidate.attribution,
                )
                if saved:
                    added += 1

            if added == 0:
                return  # nothing new came back: stop spending calls

    def _recent_titles(self) -> list[str]:
        rows = (
            self.db.query(Question.title)
            .filter(func.lower(Question.category) == self.category)
            .order_by(Question.id.desc())
            .limit(AVOID_LIMIT)
            .all()
        )
        return [row[0] for row in rows]

    def _add(
        self,
        text: str,
        difficulty: str,
        description: str | None,
        origin: str,
        **source: Any,
    ) -> bool:
        """Validate, de-duplicate and save one question. True if it was saved."""
        if not config.MIN_QUESTION_LENGTH <= len(text) <= config.MAX_QUESTION_LENGTH:
            self.cr.invalid += 1
            return False

        if self.dedup.find_duplicate(text) is not None:
            self.cr.duplicates += 1
            return False

        if difficulty not in config.ALLOWED_DIFFICULTIES:
            difficulty = config.DEFAULT_DIFFICULTY

        counter = "web" if origin == ORIGIN_WEB else "ai"
        incremented = False
        try:
            question = Question(
                title=text,
                description=description,
                category=self.category,
                difficulty=difficulty,
                is_active=True,
            )
            self.db.add(question)
            self.db.flush()
            question_id = question.id
            self.db.add(
                QuestionSource(
                    question_id=question_id,
                    origin=origin,
                    exact_key=exact_key(text),
                    **source,
                )
            )
            setattr(self.cr, counter, getattr(self.cr, counter) + 1)
            incremented = True
            self.cr.sync(self.budget.usage(self.category))
            self.db.commit()
        except IntegrityError:
            # Another run saved the same question first (unique exact_key).
            self.db.rollback()
            if incremented:
                setattr(self.cr, counter, getattr(self.cr, counter) - 1)
            self.cr.duplicates += 1
            self.dedup.add(text)
            return False

        self.dedup.add(text, question_id)
        return True

    def result(self, status: str) -> CategoryResult:
        usage = self.budget.usage(self.category)
        return CategoryResult(
            category=self.category,
            status=status,
            inserted_web=self.cr.web,
            inserted_ai=self.cr.ai,
            duplicates_skipped=self.cr.duplicates,
            invalid_skipped=self.cr.invalid,
            search_requests=usage.search_requests,
            ai_calls=usage.ai_calls,
            tokens_used=usage.tokens_used,
            message="; ".join(self.errors)[:MAX_ERROR_LENGTH] or None,
        )


def _decide_status(worker: _CategoryWorker) -> str:
    if worker.done:
        return RUN_COMPLETED
    if worker.errors:
        return RUN_FAILED
    if worker.limit_hit:
        return RUN_LIMIT_REACHED
    if not worker.attempted:
        worker.errors.append(
            "No question source is available. Add QUESTION_SEARCH_API_KEY or GEMINI_API_KEY."
        )
        return RUN_FAILED
    return RUN_EXHAUSTED


def _update_cooldown(
    db: Session,
    category: str,
    status: str,
    inserted_today: int,
    now: datetime,
    cooldown_days: int,
) -> None:
    row = db.get(CategoryCooldown, category)
    if row is None:
        row = CategoryCooldown(category=category, consecutive_shortfalls=0, last_inserted=0)
        db.add(row)

    row.last_attempt_at = now
    row.last_status = status
    row.last_inserted = inserted_today

    if status == RUN_COMPLETED:
        row.paused_until = None
        row.consecutive_shortfalls = 0
    elif status == RUN_EXHAUSTED:
        row.paused_until = _resume_at(now.date(), cooldown_days)
        row.consecutive_shortfalls = (row.consecutive_shortfalls or 0) + 1


def _finish(
    db: Session,
    worker: _CategoryWorker,
    status: str,
    now: datetime,
    cooldown_days: int,
) -> None:
    worker.cr.sync(worker.budget.usage(worker.category))
    run = worker.cr.run
    run.status = status
    run.error_message = "; ".join(worker.errors)[:MAX_ERROR_LENGTH] or None
    run.finished_at = datetime.now(timezone.utc)
    _update_cooldown(db, worker.category, status, worker.cr.inserted_today, now, cooldown_days)
    db.commit()


def _process_category(
    db: Session,
    state: _JobState,
    dedup: QuestionDeduplicator,
    budget: RunBudget,
    category: str,
    *,
    now: datetime,
    run_id: str,
    target: int,
    cooldown_days: int,
    ignore_cooldown: bool,
) -> CategoryResult:
    cooldown = db.get(CategoryCooldown, category)
    if not ignore_cooldown and cooldown is not None and cooldown.paused_until is not None:
        resume = _as_utc(cooldown.paused_until)
        if now < resume:
            return _record_skip(db, run_id, category, target, now, resume)

    run = _open_run(db, run_id, category, target, now)
    if run is None:
        return CategoryResult(
            category=category,
            status=STATUS_ALREADY_DONE,
            message="Already processed today, or another run is working on it.",
        )

    worker = _CategoryWorker(db, state, dedup, budget, category, run, target, now)
    try:
        worker.execute()
    except Exception:
        logger.exception("Unexpected error while processing category %s", category)
        db.rollback()
        worker.errors.append("Unexpected error. See the server logs.")

    status = _decide_status(worker)
    _finish(db, worker, status, now, cooldown_days)
    return worker.result(status)


# ---------- public entry point ----------
def run_daily_discovery(
    db: Session,
    *,
    search_provider: SearchProvider | None = None,
    generator: QuestionGenerator | None = None,
    budget: RunBudget | None = None,
    categories: Iterable[str] | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
    questions_per_category: int | None = None,
    cooldown_days: int | None = None,
    ignore_cooldown: bool = False,
) -> DiscoveryReport:
    """Run discovery for the enabled categories (or the ones given).

    The caller owns the session and any cross-process locking.
    """
    started = datetime.now(timezone.utc)
    now = now or started
    target = config.QUESTIONS_PER_CATEGORY_PER_DAY if questions_per_category is None else questions_per_category
    days = config.CATEGORY_COOLDOWN_DAYS if cooldown_days is None else cooldown_days
    if target < 1:
        raise ValueError("questions_per_category must be at least 1")
    if days < 1:
        raise ValueError("cooldown_days must be at least 1")

    selected = list(dict.fromkeys(categories if categories is not None else config.ENABLED_CATEGORIES))
    if not selected:
        raise ValueError("At least one category is required")
    unknown = [category for category in selected if category not in config.SUPPORTED_CATEGORIES]
    if unknown:
        raise ValueError(f"Unknown categories: {', '.join(unknown)}")
    selected = _rotate(selected, now.date())

    budget = budget or RunBudget.from_settings()
    run_id = run_id or uuid.uuid4().hex

    # Every existing question, active or not, so a deactivated bad question
    # is never added again.
    dedup = build_deduplicator(
        ((row.id, row.title) for row in db.query(Question.id, Question.title)),
        config.DEDUP_JACCARD_THRESHOLD,
        config.DEDUP_SEQUENCE_THRESHOLD,
    )

    state = _JobState(search_provider, generator)
    results: list[CategoryResult] = []

    for category in selected:
        try:
            result = _process_category(
                db,
                state,
                dedup,
                budget,
                category,
                now=now,
                run_id=run_id,
                target=target,
                cooldown_days=days,
                ignore_cooldown=ignore_cooldown,
            )
        except Exception:
            logger.exception("Discovery failed for category %s", category)
            db.rollback()
            result = CategoryResult(
                category=category,
                status=RUN_FAILED,
                message="Unexpected error. See the server logs.",
            )
        results.append(result)
        logger.info(
            "Question discovery %s: %s (+%d web, +%d ai)",
            category,
            result.status,
            result.inserted_web,
            result.inserted_ai,
        )

    return DiscoveryReport(
        run_id=run_id,
        started_at=started,
        finished_at=datetime.now(timezone.utc),
        results=results,
    )
