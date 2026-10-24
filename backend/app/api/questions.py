from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.db.session import get_db
from app.models.question import Question
from app.models.user import User
from app.schemas.question import QuestionCreate, QuestionResponse

router = APIRouter(prefix="/api/questions", tags=["Questions"])

@router.get("/", response_model=list[QuestionResponse])
def list_questions(
    category: str | None = Query(default=None),
    difficulty: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Question).filter(Question.is_active.is_(True))

    if category:
        query = query.filter(Question.category.ilike(category))

    if difficulty:
        query = query.filter(Question.difficulty.ilike(difficulty))

    return query.order_by(Question.id).offset(skip).limit(limit).all()



@router.get("/{question_id}", response_model = QuestionResponse)
def get_question(question_id: int, db: Session = Depends(get_db)):
    # Inactive questions can still be read by id, so old practice sessions,
    # reports and history keep working after an admin deactivates a question.
    # The list endpoint above only shows active questions.
    question = db.query(Question).filter(Question.id == question_id).first()
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    return question


@router.post("/", response_model=QuestionResponse, status_code=status.HTTP_201_CREATED)
def create_question(
    data: QuestionCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    question = Question(**data.model_dump())
    
    db.add(question)
    db.commit()
    db.refresh(question)
    return question
