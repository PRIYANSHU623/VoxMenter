
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.db.session import Base


def utc_now():
    return datetime.now(timezone.utc)


class PracticeSession(Base):
    __tablename__ = "practice_sessions"

    id = Column(Integer, primary_key=True, index=True)

    # Ownership: each session belongs to one user.
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The question being answered.
    question_id = Column(
        Integer,
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # pending, recording_uploaded, transcribing,
    # evaluating, completed, or failed.
    status = Column(
        String(50),
        default="pending",
        nullable=False,
        index=True,
    )

    # Object key in Cloudflare R2, not the public file URL.
    audio_key = Column(String(1024), nullable=True)

    duration_seconds = Column(Float, nullable=True)
    transcript = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship(
        "User",
        back_populates="practice_sessions",
    )

    question = relationship(
        "Question",
        back_populates="practice_sessions",
    )

    evaluations = relationship(
        "Evaluation",
        back_populates="practice_session",
        cascade="all, delete-orphan",
        order_by="Evaluation.created_at",
    )

        
    session_questions = relationship(
        "SessionQuestion",
        back_populates="practice_session",
        cascade="all, delete-orphan",
        order_by="SessionQuestion.position",
    )