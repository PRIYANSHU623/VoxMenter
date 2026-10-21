
from datetime import datetime, timezone
from sqlalchemy.orm import relationship
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)

from app.db.session import Base


def utc_now():
    return datetime.now(timezone.utc)


class Recording(Base):
    __tablename__ = "recordings"

    id = Column(Integer, primary_key=True, index=True)

    session_question_id = Column(
        Integer,
        ForeignKey("session_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Private Backblaze B2 object key, never a public URL.
    audio_key = Column(String(1024), nullable=False, unique=True)

    content_type = Column(String(100), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    duration_seconds = Column(Float, nullable=True)

    transcript = Column(Text, nullable=True)

    # uploaded, transcribing, transcribed, evaluating,
    # completed, or failed.
    status = Column(String(50), default="uploaded", nullable=False)

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

    session_question = relationship(
        "SessionQuestion",
        back_populates="recordings",
    )
