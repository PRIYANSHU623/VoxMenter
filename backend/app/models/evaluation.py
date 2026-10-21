
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
)
from sqlalchemy.orm import relationship

from app.db.session import Base


def utc_now():
    return datetime.now(timezone.utc)


class Evaluation(Base):
    __tablename__ = "evaluations"

    id = Column(Integer, primary_key=True, index=True)

    session_id = Column(
        Integer,
        ForeignKey("practice_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    technical_score = Column(Float, nullable=True)
    communication_score = Column(Float, nullable=True)

    # Flexible structure for detailed AI-generated feedback.
    feedback = Column(JSON, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    practice_session = relationship(
        "PracticeSession",
        back_populates="evaluations",
    )
