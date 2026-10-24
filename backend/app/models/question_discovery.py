"""Tables for the daily question discovery and generation job.

question_sources          one row per discovered or generated question
question_generation_runs  one row per category per day (daily results)
category_cooldowns        one row per category (pause state)

The existing questions table is not modified. Every source row points at
its question, and deleting a question deletes its source row.

Note: with SQLite, DateTime(timezone=True) values come back without a
timezone. Treat them as UTC when comparing them to the current time.
"""

from datetime import date, datetime, timezone

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.session import Base

# Where a question came from.
ORIGIN_WEB = "web"
ORIGIN_AI = "ai_generated"

# Result of one category's run for one day.
RUN_RUNNING = "running"
RUN_COMPLETED = "completed"  # reached the daily target
RUN_EXHAUSTED = "exhausted"  # ran out of valid questions; cooldown started
RUN_LIMIT_REACHED = "limit_reached"  # stopped by a request/token limit
RUN_FAILED = "failed"  # providers failed, nothing more to try
RUN_SKIPPED_COOLDOWN = "skipped_cooldown"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


class QuestionSource(Base):
    __tablename__ = "question_sources"

    id = Column(Integer, primary_key=True, index=True)

    # One source row per question.
    question_id = Column(
        Integer,
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # "web" or "ai_generated" (see ORIGIN_* above).
    origin = Column(String(20), nullable=False, index=True)

    # Service that produced it, e.g. "tavily" or "gemini".
    provider = Column(String(50), nullable=False)
    model_name = Column(String(100), nullable=True)  # AI-generated only

    # Attribution for questions found online.
    source_url = Column(String(2048), nullable=True)
    source_title = Column(String(500), nullable=True)
    source_domain = Column(String(255), nullable=True)
    attribution = Column(Text, nullable=True)
    search_query = Column(String(500), nullable=True)

    # SHA-256 of the normalised question text (question_dedup.exact_key).
    # Unique, so two concurrent runs cannot insert the same question.
    exact_key = Column(String(64), nullable=False, unique=True)

    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    question = relationship("Question")


class QuestionGenerationRun(Base):
    __tablename__ = "question_generation_runs"

    __table_args__ = (
        UniqueConstraint(
            "run_date",
            "category",
            name="uq_generation_run_day_category",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    # Groups the category rows created by one scheduled or manual job.
    run_id = Column(String(36), nullable=False, index=True)

    run_date = Column(Date, default=utc_today, nullable=False, index=True)
    category = Column(String(100), nullable=False)
    status = Column(String(30), default=RUN_RUNNING, nullable=False)

    target = Column(Integer, default=0, nullable=False)
    inserted_web = Column(Integer, default=0, nullable=False)
    inserted_ai = Column(Integer, default=0, nullable=False)
    duplicates_skipped = Column(Integer, default=0, nullable=False)
    invalid_skipped = Column(Integer, default=0, nullable=False)

    search_requests = Column(Integer, default=0, nullable=False)
    ai_calls = Column(Integer, default=0, nullable=False)
    tokens_used = Column(Integer, default=0, nullable=False)

    error_message = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    @property
    def inserted_total(self) -> int:
        return (self.inserted_web or 0) + (self.inserted_ai or 0)


class CategoryCooldown(Base):
    __tablename__ = "category_cooldowns"

    category = Column(String(100), primary_key=True)

    # While now < paused_until the category is skipped.
    paused_until = Column(DateTime(timezone=True), nullable=True)

    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String(30), nullable=True)
    last_inserted = Column(Integer, default=0, nullable=False)
    consecutive_shortfalls = Column(Integer, default=0, nullable=False)

    updated_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )