
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.session import Base


def utc_now():
    return datetime.now(timezone.utc)


class SessionQuestion(Base):
    __tablename__ = "session_questions"

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "position",
            name="uq_session_question_position",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    session_id = Column(
        Integer,
        ForeignKey("practice_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    question_id = Column(
        Integer,
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # The question's position within this practice session.
    position = Column(Integer, nullable=False)

    status = Column(String(50), default="pending", nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    practice_session = relationship(
        "PracticeSession",
        back_populates="session_questions",
    )

    question = relationship("Question")

    recordings = relationship(
        "Recording",
        back_populates="session_question",
        cascade="all, delete-orphan",
        order_by="Recording.created_at",
    )
