
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.api.auth import get_current_user
from app.models.recording import Recording
from app.models.session_question import SessionQuestion
from app.models.question import Question

from app.models.practice_session import PracticeSession
from app.models.evaluation import Evaluation
from app.services.ai_evaluation_provider import evaluate_with_gemini
from app.services.evaluation_service import calculate_evaluation_scores
from app.schemas.evaluation import QuestionType

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





@router.post("/{session_id}/evaluate")
# def evaluate_practice_session(
#     session_id: int,
#     db: Session = Depends(get_db),
#     current_user: User = Depends(get_current_user),
# ):
@router.post("/{session_id}/evaluate")
def evaluate_practice_session(
    session_id: int,
    recording_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Verify that the practice session belongs to the logged-in user.
    session = get_session(db, current_user, session_id)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practice session not found",
        )

    # 2. Find the latest successfully transcribed recording
    # # associated with this practice session.
    # recording = (
    #     db.query(Recording)
    #     .join(
    #         SessionQuestion,
    #         Recording.session_question_id == SessionQuestion.id,
    #     )
    #     .filter(
    #         SessionQuestion.session_id == session.id,
    #         Recording.status == "transcribed",
    #         Recording.transcript.isnot(None),
    #         Recording.transcript != "",
    #     )
    #     .order_by(Recording.created_at.desc())
    #     .first()
    # )
    
    recording_query = (
        db.query(Recording)
        .join(
            SessionQuestion,
            Recording.session_question_id == SessionQuestion.id,
        )
        .filter(
            SessionQuestion.session_id == session.id,
            Recording.status == "transcribed",
            Recording.transcript.isnot(None),
            Recording.transcript != "",
        )
    )

    # Optional: evaluate one specific attempt. The join above already
    # guarantees it belongs to this user's session.
    if recording_id is not None:
        recording_query = recording_query.filter(Recording.id == recording_id)

    recording = recording_query.order_by(Recording.created_at.desc()).first()

    if recording is None or not recording.transcript.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No successfully transcribed recording was found "
                "for this practice session."
            ),
        )

    transcript = recording.transcript

    # 3. Get the session question associated with this recording.
    session_question = (
        db.query(SessionQuestion)
        .filter(
            SessionQuestion.id == recording.session_question_id,
            SessionQuestion.session_id == session.id,
        )
        .first()
    )

    if session_question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session question not found",
        )

    # 4. Get the actual question answered in this recording.
    question = (
        db.query(Question)
        .filter(Question.id == session_question.question_id)
        .first()
    )

    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Question not found",
        )

    question_text = question.title

    if question.description:
        question_text += "\n" + question.description

    # 5. Map the question category to a supported evaluation type.
    allowed_types = {
        "dsa",
        "python",
        "dbms_sql",
        "oop",
        "ai_ml",
        "hr",
        "project",
        "general",
    }

    raw_type = (question.category or "general").lower().strip()

    question_type: QuestionType = (
        raw_type if raw_type in allowed_types else "general"
    )

    # 6. Generate the evaluation and calculate scores.
    try:
        result = evaluate_with_gemini(
            question=question_text,
            transcript=transcript,
            question_type=question_type,
        )

        scores = calculate_evaluation_scores(result)

        # Store the full evaluation report as JSON-compatible data.
        report = result.model_dump(mode="json")
        report["calculated_scores"] = scores
        report["recording_id"] = recording.id

        # 7. Save the evaluation to SQLite.
        evaluation = Evaluation(
            session_id=session.id,
            technical_score=scores["technical_score"],
            communication_score=scores["communication_score"],
            feedback=report,
        )

        db.add(evaluation)

        # Update the session's status after successful evaluation.
        session.status = "completed"

        db.commit()
        db.refresh(evaluation)

        return {
            "evaluation_id": evaluation.id,
            "session_id": session.id,
            "technical_score": evaluation.technical_score,
            "communication_score": evaluation.communication_score,
            "created_at": evaluation.created_at,
            "report": evaluation.feedback,
        }

    except Exception as exc:
        db.rollback()

        # Do not expose API keys or internal provider error details.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Evaluation failed. Please try again.",
        ) from exc


@router.get("/{session_id}/evaluation")
def get_session_evaluation(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # 1. Verify ownership before accessing evaluation data.
    session = get_session(db, current_user, session_id)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practice session not found",
        )

    # 2. Retrieve the latest saved evaluation.
    evaluation = (
        db.query(Evaluation)
        .filter(Evaluation.session_id == session.id)
        .order_by(Evaluation.created_at.desc(), Evaluation.id.desc())
        .first()
    )

    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No evaluation exists for this session yet.",
        )

    return {
        "evaluation_id": evaluation.id,
        "session_id": session.id,
        "technical_score": evaluation.technical_score,
        "communication_score": evaluation.communication_score,
        "created_at": evaluation.created_at,
        "report": evaluation.feedback,
    }


@router.get("/{session_id}/evaluations")
def list_session_evaluations(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Ownership check first, same as every other session route.
    session = get_session(db, current_user, session_id)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Practice session not found",
        )

    evaluations = (
        db.query(Evaluation)
        .filter(Evaluation.session_id == session.id)
        .order_by(Evaluation.created_at, Evaluation.id)
        .all()
    )

    return [
        {
            "evaluation_id": item.id,
            "session_id": session.id,
            "technical_score": item.technical_score,
            "communication_score": item.communication_score,
            "created_at": item.created_at,
            "report": item.feedback,
        }
        for item in evaluations
    ]