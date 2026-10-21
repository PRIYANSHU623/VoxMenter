
from app.db.session import Base, engine, SessionLocal
from app.models import User, Question, PracticeSession, Evaluation


def test_models():
    # Create any missing tables.
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()

    try:
        # Create a test user.
        user = User(
            email="test@example.com",
            hashed_password="test_hash",
        )
        db.add(user)
        db.flush()

        # Create an interview question.
        question = Question(
            title="Explain Python decorators",
            description="Explain decorators and give an example.",
            category="Python",
            difficulty="Intermediate",
        )
        db.add(question)
        db.flush()

        # Create a practice session.
        session = PracticeSession(
            user_id=user.id,
            question_id=question.id,
            status="pending",
        )
        db.add(session)
        db.flush()

        # Create an evaluation.
        evaluation = Evaluation(
            session_id=session.id,
            technical_score=8.0,
            communication_score=7.5,
            feedback={
                "strengths": ["Clear explanation"],
                "improvements": ["Give more examples"],
            },
        )
        db.add(evaluation)
        db.commit()

        # Verify relationships.
        db.refresh(user)
        db.refresh(session)

        assert user.practice_sessions[0].id == session.id
        assert session.question.title == "Explain Python decorators"
        assert session.evaluations[0].technical_score == 8.0

        print("All four models and relationships work!")

    finally:
        db.close()


if __name__ == "__main__":
    test_models()
