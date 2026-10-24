"""Celery task for the daily question discovery job.

Only one run can be active at a time: a Redis lock with a token and an expiry
guards the job. Because every trigger (the daily schedule, a manual trigger,
a duplicate Beat process, a message that was delayed in the queue) goes
through this task, none of them can start an overlapping run. The database
also enforces one row per category per day, as a second safeguard.
"""

import logging
from collections.abc import Callable
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from redis import Redis
from redis.exceptions import LockError, RedisError

from app.celery_app import celery_app
from app.core import question_discovery_config as config
from app.db.session import SessionLocal
from app.services.question_discovery_service import run_daily_discovery
from app.services.question_generation_provider import GeminiQuestionGenerator
from app.services.question_search_provider import TavilySearchProvider
from app.services.run_budget import RunBudget

logger = logging.getLogger(__name__)

TASK_NAME = "voxmenter.discover_daily_questions"
LOCK_NAME = "voxmenter:question-discovery:lock"

# Stop the task before its lock can expire underneath it.
_SOFT_LIMIT = max(30, int(config.RUN_LOCK_TTL_SECONDS * 0.8))
_HARD_LIMIT = max(_SOFT_LIMIT + 10, int(config.RUN_LOCK_TTL_SECONDS * 0.9))


def run_discovery_job(
    *,
    categories: list[str] | None = None,
    ignore_cooldown: bool = False,
    triggered_by: str = "schedule",
    redis_client: Any = None,
    session_factory: Callable[[], Any] = SessionLocal,
    search_factory: Callable[[], Any] = TavilySearchProvider.from_settings,
    generator_factory: Callable[[], Any] = GeminiQuestionGenerator.from_settings,
    budget_factory: Callable[[], RunBudget] = RunBudget.from_settings,
) -> dict[str, Any]:
    """Run discovery once, unless another run already holds the lock."""
    owns_client = redis_client is None
    client = redis_client if redis_client is not None else Redis.from_url(config.LOCK_REDIS_URL)

    lock = client.lock(LOCK_NAME, timeout=config.RUN_LOCK_TTL_SECONDS)
    if not lock.acquire(blocking=False):
        logger.info("Question discovery skipped: another run is in progress (%s).", triggered_by)
        if owns_client:
            client.connection_pool.disconnect()
        return {
            "status": "skipped",
            "reason": "Another discovery run is already in progress.",
            "triggered_by": triggered_by,
        }

    search_provider = None
    db = None
    try:
        search_provider = search_factory()
        generator = generator_factory()
        db = session_factory()

        logger.info("Question discovery started (%s).", triggered_by)
        report = run_daily_discovery(
            db,
            search_provider=search_provider,
            generator=generator,
            budget=budget_factory(),
            categories=categories,
            ignore_cooldown=ignore_cooldown,
        )
        logger.info("Question discovery finished: %d new questions.", report.total_inserted)

        return {
            "status": "finished",
            "triggered_by": triggered_by,
            "report": report.as_dict(),
        }
    finally:
        if db is not None:
            db.close()
        if search_provider is not None:
            search_provider.close()
        try:
            lock.release()
        except (LockError, RedisError):
            logger.warning("Could not release the discovery lock; it will expire on its own.")
        if owns_client:
            client.connection_pool.disconnect()


@celery_app.task(
    bind=True,
    name=TASK_NAME,
    max_retries=0,  # the daily schedule is the retry
    soft_time_limit=_SOFT_LIMIT,
    time_limit=_HARD_LIMIT,
)
def discover_daily_questions(
    self,
    categories: list[str] | None = None,
    ignore_cooldown: bool = False,
    triggered_by: str = "schedule",
) -> dict[str, Any]:
    try:
        return run_discovery_job(
            categories=categories,
            ignore_cooldown=ignore_cooldown,
            triggered_by=triggered_by,
        )
    except SoftTimeLimitExceeded:
        logger.error("Question discovery stopped: the time limit was reached.")
        raise
    except Exception:
        logger.exception("Question discovery failed.")
        raise
