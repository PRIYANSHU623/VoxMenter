
from sqlalchemy.orm import Session

from app.models.question import Question
from app.models.practice_session import PracticeSession
from app.models.user import User
from app.schemas.practice import (
    PracticeSessionCreate,
    PracticeSessionUpdate,
)


def create_session(
    db: Session,
    user: User,
    data: PracticeSessionCreate,
) -> PracticeSession:
    question = (
        db.query(Question)
        .filter(
            Question.id == data.question_id,
            Question.is_active.is_(True),
        )
        .first()
    )

    if question is None:
        raise ValueError("Active question not found")

    session = PracticeSession(
        user_id=user.id,
        question_id=question.id,
        status="pending",
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    return session


def list_sessions(
    db: Session,
    user: User,
) -> list[PracticeSession]:
    return (
        db.query(PracticeSession)
        .filter(PracticeSession.user_id == user.id)
        .order_by(PracticeSession.created_at.desc())
        .all()
    )


def get_session(
    db: Session,
    user: User,
    session_id: int,
) -> PracticeSession | None:
    return (
        db.query(PracticeSession)
        .filter(
            PracticeSession.id == session_id,
            PracticeSession.user_id == user.id,
        )
        .first()
    )


def update_session_status(
    db: Session,
    session: PracticeSession,
    data: PracticeSessionUpdate,
) -> PracticeSession:
    session.status = data.status

    db.commit()
    db.refresh(session)

    return session
