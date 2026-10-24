"""Tests for the Celery task, its Redis lock and the daily schedule.

Redis is replaced by a tiny in-memory fake and the providers by scripted
fakes, so nothing real is contacted.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from celery.schedules import crontab
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import LockError

from app.celery_app import celery_app
from app.core import question_discovery_config as config
from app.models import CategoryCooldown, Question
from app.services.run_budget import RunBudget
from app.tasks import question_discovery_tasks as tasks
from app.tasks.question_discovery_tasks import (
    LOCK_NAME,
    TASK_NAME,
    discover_daily_questions,
    run_discovery_job,
)
from tests.fakes import FakeGenerator, FakeSearch

PY = [
    "How does Python manage memory?",
    "What are Python decorators used for?",
    "How do Python generators save memory?",
    "Explain how the Python GIL affects threads",
    "What does a context manager do in Python?",
    "How are exceptions handled in Python?",
]
HR = [
    "Tell me about a time you resolved a conflict with a teammate.",
    "How do you handle tight deadlines?",
    "Why do you want to work at this company?",
]


@pytest.fixture(autouse=True)
def pin_config(monkeypatch):
    """Tests must not depend on whatever is set in backend/.env."""
    monkeypatch.setattr(config, "QUESTIONS_PER_CATEGORY_PER_DAY", 3)
    monkeypatch.setattr(config, "CATEGORY_COOLDOWN_DAYS", 3)
    monkeypatch.setattr(config, "ENABLED_CATEGORIES", ("python", "hr"))
    monkeypatch.setattr(config, "MIN_QUESTION_LENGTH", 15)
    monkeypatch.setattr(config, "MAX_QUESTION_LENGTH", 255)
    monkeypatch.setattr(
        config, "ALLOWED_DIFFICULTIES", ("Beginner", "Intermediate", "Advanced")
    )
    monkeypatch.setattr(config, "DEFAULT_DIFFICULTY", "Beginner")
    monkeypatch.setattr(config, "DEDUP_JACCARD_THRESHOLD", 0.8)
    monkeypatch.setattr(config, "DEDUP_SEQUENCE_THRESHOLD", 0.9)


class FakeLock:
    def __init__(self, redis, name):
        self.redis = redis
        self.name = name

    def acquire(self, blocking=True):
        self.redis.acquire_calls.append(blocking)
        if self.redis.acquire_error is not None:
            raise self.redis.acquire_error
        if self.name in self.redis.held:
            return False
        self.redis.held.add(self.name)
        return True

    def release(self):
        if self.redis.release_error is not None:
            raise self.redis.release_error
        self.redis.held.discard(self.name)


class FakeRedis:
    def __init__(self, *, acquire_error=None, release_error=None):
        self.held: set[str] = set()
        self.timeouts: list = []
        self.acquire_calls: list = []
        self.acquire_error = acquire_error
        self.release_error = release_error

    def lock(self, name, timeout=None):
        self.timeouts.append(timeout)
        return FakeLock(self, name)


def make_budget():
    return RunBudget(
        max_search_requests=10,
        max_ai_calls=10,
        max_tokens=10**6,
        max_search_per_category=1,
        max_ai_per_category=1,
    )


def job(session_factory, redis_client, *, search=None, generator=None, **options):
    return run_discovery_job(
        redis_client=redis_client,
        session_factory=session_factory,
        search_factory=lambda: search,
        generator_factory=lambda: generator,
        budget_factory=make_budget,
        triggered_by="test",
        **options,
    )


def must_not_be_called():
    raise AssertionError("This must not be created while another run is active.")


def question_count(session_factory):
    db = session_factory()
    try:
        return db.query(Question).count()
    finally:
        db.close()


# ======================= the job and its lock =======================
def test_a_run_saves_questions_reports_the_result_and_releases_everything(session_factory):
    redis = FakeRedis()
    search = FakeSearch([PY[:3]])

    result = job(session_factory, redis, search=search, categories=["python"])

    assert result["status"] == "finished"
    assert result["triggered_by"] == "test"
    report = result["report"]
    assert report["total_inserted"] == 3
    assert [c["category"] for c in report["categories"]] == ["python"]
    assert report["categories"][0]["status"] == "completed"

    json.dumps(result)  # Celery must be able to store the result as JSON

    assert redis.held == set()  # the lock was released
    assert redis.acquire_calls == [False]  # never waits for another run
    assert redis.timeouts == [config.RUN_LOCK_TTL_SECONDS]  # the lock expires on its own
    assert search.closed
    assert question_count(session_factory) == 3


def test_without_categories_every_enabled_category_runs(session_factory):
    redis = FakeRedis()
    search = FakeSearch([PY[:3], HR[:3]])

    result = job(session_factory, redis, search=search)

    report = result["report"]
    assert {c["category"] for c in report["categories"]} == {"python", "hr"}
    assert report["total_inserted"] == 6


def test_a_second_run_is_skipped_while_one_is_active(session_factory):
    redis = FakeRedis()
    redis.held.add(LOCK_NAME)  # another worker holds the lock

    result = run_discovery_job(
        redis_client=redis,
        session_factory=must_not_be_called,
        search_factory=must_not_be_called,
        generator_factory=must_not_be_called,
        budget_factory=must_not_be_called,
        triggered_by="schedule",
    )

    assert result["status"] == "skipped"
    assert result["triggered_by"] == "schedule"
    assert "already in progress" in result["reason"]
    assert LOCK_NAME in redis.held  # the other run's lock is untouched
    assert question_count(session_factory) == 0


def test_the_lock_can_be_taken_again_after_a_run_finishes(session_factory):
    redis = FakeRedis()

    first = job(session_factory, redis, search=FakeSearch([PY[:3]]), categories=["python"])
    second = job(session_factory, redis, search=FakeSearch(), categories=["python"])

    assert first["status"] == "finished"
    assert second["status"] == "finished"
    assert redis.held == set()


def test_two_jobs_on_the_same_day_never_exceed_the_daily_target(session_factory):
    first = job(session_factory, FakeRedis(), search=FakeSearch([PY[:3]]), categories=["python"])

    search = FakeSearch([PY[3:6]])
    second = job(session_factory, FakeRedis(), search=search, categories=["python"])

    assert first["report"]["categories"][0]["status"] == "completed"
    assert second["report"]["categories"][0]["status"] == "already_processed"
    assert search.calls == []
    assert question_count(session_factory) == 3


def test_redis_being_down_stops_the_job_instead_of_running_unlocked():
    redis = FakeRedis(acquire_error=RedisConnectionError("redis is down"))

    with pytest.raises(RedisConnectionError):
        run_discovery_job(
            redis_client=redis,
            session_factory=must_not_be_called,
            search_factory=must_not_be_called,
            generator_factory=must_not_be_called,
            budget_factory=must_not_be_called,
        )


@pytest.mark.parametrize(
    "error", [LockError("lock expired"), RedisConnectionError("redis went away")]
)
def test_a_lock_that_cannot_be_released_does_not_fail_the_job(session_factory, error):
    redis = FakeRedis(release_error=error)

    result = job(session_factory, redis, search=FakeSearch([PY[:3]]), categories=["python"])

    assert result["status"] == "finished"
    assert result["report"]["total_inserted"] == 3


# ======================= cleanup after crashes =======================
def test_a_database_failure_still_releases_the_lock_and_closes_the_provider():
    redis = FakeRedis()
    search = FakeSearch()

    def broken_session():
        raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        run_discovery_job(
            redis_client=redis,
            session_factory=broken_session,
            search_factory=lambda: search,
            generator_factory=lambda: None,
            budget_factory=make_budget,
        )

    assert redis.held == set()
    assert search.closed


def test_a_provider_setup_failure_releases_the_lock_before_opening_the_database():
    redis = FakeRedis()
    opened = []

    def broken_search():
        raise ValueError("bad search configuration")

    with pytest.raises(ValueError, match="bad search configuration"):
        run_discovery_job(
            redis_client=redis,
            session_factory=lambda: opened.append(1),
            search_factory=broken_search,
            generator_factory=lambda: None,
            budget_factory=make_budget,
        )

    assert redis.held == set()
    assert opened == []


def test_a_failure_in_the_middle_closes_the_session_and_the_provider(session_factory):
    redis = FakeRedis()
    search = FakeSearch()
    sessions = []

    def tracked_session():
        session = session_factory()
        session.close = MagicMock(wraps=session.close)
        sessions.append(session)
        return session

    def broken_budget():
        raise RuntimeError("budget boom")

    with pytest.raises(RuntimeError, match="budget boom"):
        run_discovery_job(
            redis_client=redis,
            session_factory=tracked_session,
            search_factory=lambda: search,
            generator_factory=lambda: None,
            budget_factory=broken_budget,
        )

    assert redis.held == set()
    assert search.closed
    assert sessions[0].close.call_count == 1


def test_a_normal_run_closes_its_database_session(session_factory):
    sessions = []

    def tracked_session():
        session = session_factory()
        session.close = MagicMock(wraps=session.close)
        sessions.append(session)
        return session

    run_discovery_job(
        redis_client=FakeRedis(),
        session_factory=tracked_session,
        search_factory=lambda: FakeSearch([PY[:3]]),
        generator_factory=lambda: None,
        budget_factory=make_budget,
        categories=["python"],
    )

    assert len(sessions) == 1
    assert sessions[0].close.call_count == 1


# ======================= options reach the service =======================
def test_cooldowns_are_respected_unless_an_admin_overrides_them(session_factory):
    db = session_factory()
    db.add(
        CategoryCooldown(
            category="python",
            paused_until=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    db.commit()
    db.close()

    search = FakeSearch([PY[:3]])
    paused = job(session_factory, FakeRedis(), search=search, categories=["python"])
    assert paused["report"]["categories"][0]["status"] == "skipped_cooldown"
    assert search.calls == []

    forced = job(
        session_factory,
        FakeRedis(),
        search=search,
        categories=["python"],
        ignore_cooldown=True,
    )
    assert forced["report"]["categories"][0]["status"] == "completed"
    assert len(search.calls) == 1


def test_the_generator_is_used_when_search_is_unavailable(session_factory):
    generator = FakeGenerator([PY[:3]])

    result = job(session_factory, FakeRedis(), generator=generator, categories=["python"])

    category = result["report"]["categories"][0]
    assert category["status"] == "completed"
    assert category["inserted_ai"] == 3
    assert len(generator.calls) == 1


# ======================= the Celery task =======================
def test_the_celery_task_passes_its_arguments_to_the_job(monkeypatch):
    seen = {}

    def fake_job(**kwargs):
        seen.update(kwargs)
        return {"status": "finished"}

    monkeypatch.setattr(tasks, "run_discovery_job", fake_job)

    outcome = discover_daily_questions.apply(
        kwargs={"categories": ["python"], "ignore_cooldown": True, "triggered_by": "admin:7"}
    )

    assert outcome.successful()
    assert outcome.result == {"status": "finished"}
    assert seen == {
        "categories": ["python"],
        "ignore_cooldown": True,
        "triggered_by": "admin:7",
    }


def test_the_celery_task_defaults_match_the_daily_schedule(monkeypatch):
    seen = {}
    monkeypatch.setattr(tasks, "run_discovery_job", lambda **kwargs: seen.update(kwargs) or {})

    discover_daily_questions.apply()

    assert seen == {"categories": None, "ignore_cooldown": False, "triggered_by": "schedule"}


def test_a_failing_job_fails_the_task_and_is_never_retried(monkeypatch):
    calls = []

    def failing_job(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("boom")

    monkeypatch.setattr(tasks, "run_discovery_job", failing_job)

    outcome = discover_daily_questions.apply()

    assert outcome.failed()
    assert isinstance(outcome.result, RuntimeError)
    assert len(calls) == 1
    assert discover_daily_questions.max_retries == 0


def test_the_task_is_stopped_before_its_lock_can_expire():
    soft = discover_daily_questions.soft_time_limit
    hard = discover_daily_questions.time_limit

    assert soft < hard < config.RUN_LOCK_TTL_SECONDS


# ======================= registration and schedule =======================
def test_the_task_is_registered_with_the_expected_name():
    assert TASK_NAME == "voxmenter.discover_daily_questions"
    assert discover_daily_questions.name == TASK_NAME
    assert TASK_NAME in celery_app.tasks
    assert "app.tasks.question_discovery_tasks" in celery_app.conf.include


def test_it_is_scheduled_exactly_once_a_day_at_the_configured_time():
    entries = [
        entry
        for entry in celery_app.conf.beat_schedule.values()
        if entry["task"] == TASK_NAME
    ]

    assert len(entries) == 1  # one entry means one run per scheduler tick
    entry = entries[0]
    assert entry["schedule"] == crontab(
        hour=config.SCHEDULE_HOUR, minute=config.SCHEDULE_MINUTE
    )
    assert celery_app.conf.timezone == "UTC"
    assert celery_app.conf.enable_utc is True


def test_a_scheduled_message_that_waited_too_long_expires():
    entry = celery_app.conf.beat_schedule["daily-question-discovery"]

    assert entry["options"]["expires"] == config.RUN_LOCK_TTL_SECONDS