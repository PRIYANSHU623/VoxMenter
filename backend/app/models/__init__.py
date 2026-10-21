# This file imports all models so SQLAlchemy can discover their tables when we initialize the database.


from app.models.user import User
from app.models.evaluation import Evaluation
from app.models.question import Question
from app.models.practice_session import PracticeSession
from app.models.session_question import SessionQuestion
from app.models.recording import Recording


__all__ = ["User", "Evaluation", "Question", "PracticeSession", "SessionQuestion", "Recording"]