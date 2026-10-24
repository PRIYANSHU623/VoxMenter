import os

from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

from app.core import question_discovery_config as discovery_config

load_dotenv()

celery_app = Celery(
    "voxmenter",
    broker=os.getenv(
        "CELERY_BROKER_URL",
        "redis://127.0.0.1:6379/1",
    ),
    include=[
        "app.tasks.transcription_tasks",
        "app.tasks.question_discovery_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "daily-question-discovery": {
            "task": "voxmenter.discover_daily_questions",
            "schedule": crontab(
                hour=discovery_config.SCHEDULE_HOUR,
                minute=discovery_config.SCHEDULE_MINUTE,
            ),
            # A message that sat in the queue (worker was down) is dropped
            # instead of running hours late.
            "options": {"expires": discovery_config.RUN_LOCK_TTL_SECONDS},
        },
    },
)
