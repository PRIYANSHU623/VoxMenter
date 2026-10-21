
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.api.auth import get_current_user
from app.models.session_question import SessionQuestion
from app.models.question import Question
from app.schemas.practice import (
    SessionQuestionCreate,
    SessionQuestionResponse,
)

from app.schemas.practice import (
    PracticeSessionCreate,
    PracticeSessionUpdate,
    PracticeSessionResponse,
)

from app.services.practice_service import (
    create_session,
    list_sessions,
    get_session,
    update_session_status,
)

router = APIRouter(
    prefix="/api/practice/sessions",
    tags=["Practice Sessions"],
)


@router.post(
    "",
    response_model=PracticeSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_practice_session(
    data: PracticeSessionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return create_session(db, current_user, data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("", response_model=list[PracticeSessionResponse])
def get_practice_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_sessions(db, current_user)


@router.get("/{session_id}", response_model=PracticeSessionResponse)
def get_practice_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = get_session(db, current_user, session_id)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practice session not found",
        )

    return session


@router.patch("/{session_id}", response_model=PracticeSessionResponse)
def patch_practice_session(
    session_id: int,
    data: PracticeSessionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = get_session(db, current_user, session_id)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practice session not found",
        )

    return update_session_status(db, session, data)




@router.post(
    "/{session_id}/questions",
    response_model=SessionQuestionResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_session_question(
    session_id: int,
    data: SessionQuestionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify that this session belongs to the authenticated user.
    session = get_session(db, current_user, session_id)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practice session not found",
        )

    # Only active questions can be added.
    question = (
        db.query(Question)
        .filter(
            Question.id == data.question_id,
            Question.is_active.is_(True),
        )
        .first()
    )

    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active question not found",
        )

    # Place the new question after the existing questions.
    last_position = (
        db.query(SessionQuestion.position)
        .filter(SessionQuestion.session_id == session_id)
        .order_by(SessionQuestion.position.desc())
        .first()
    )

    next_position = (last_position[0] if last_position else 0) + 1

    session_question = SessionQuestion(
        session_id=session_id,
        question_id=question.id,
        position=next_position,
        status="pending",
    )

    db.add(session_question)
    db.commit()
    db.refresh(session_question)

    return session_question


@router.get(
    "/{session_id}/questions",
    response_model=list[SessionQuestionResponse],
)
def list_session_questions(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify ownership before returning any questions.
    session = get_session(db, current_user, session_id)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practice session not found",
        )

    return (
        db.query(SessionQuestion)
        .filter(SessionQuestion.session_id == session_id)
        .order_by(SessionQuestion.position)
        .all()
    )
