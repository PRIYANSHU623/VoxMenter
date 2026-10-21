
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.practice_session import PracticeSession
from app.models.session_question import SessionQuestion
from app.models.recording import Recording


def infer_content_type(audio_key: str) -> str:
    """Infer a content type from an existing audio object's extension."""
    extension = PurePosixPath(audio_key).suffix.lower()

    content_types = {
        ".webm": "audio/webm",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".mp4": "audio/mp4",
        ".m4a": "audio/x-m4a",
        ".ogg": "audio/ogg",
    }

    return content_types.get(extension, "application/octet-stream")


def migrate():
    with Session(engine) as db:
        created_questions = 0
        created_recordings = 0

        try:
            sessions = (
                db.query(PracticeSession)
                .order_by(PracticeSession.id)
                .all()
            )

            for practice_session in sessions:
                # Create one initial question entry for each old session.
                session_question = (
                    db.query(SessionQuestion)
                    .filter_by(session_id=practice_session.id)
                    .order_by(SessionQuestion.position)
                    .first()
                )

                if session_question is None:
                    session_question = SessionQuestion(
                        session_id=practice_session.id,
                        question_id=practice_session.question_id,
                        position=1,
                        status=(
                            "recording_uploaded"
                            if practice_session.audio_key
                            else practice_session.status
                        ),
                    )
                    db.add(session_question)
                    db.flush()
                    created_questions += 1

                # Preserve existing audio by referencing its current B2 key.
                audio_key = practice_session.audio_key

                if not audio_key:
                    continue

                existing_recording = (
                    db.query(Recording)
                    .filter_by(audio_key=audio_key)
                    .first()
                )

                if existing_recording is not None:
                    continue

                recording = Recording(
                    session_question_id=session_question.id,
                    audio_key=audio_key,
                    content_type=infer_content_type(audio_key),
                    # The old database did not store the file size.
                    size_bytes=0,
                    duration_seconds=practice_session.duration_seconds,
                    transcript=practice_session.transcript,
                    status="uploaded",
                    error_message=practice_session.error_message,
                )

                db.add(recording)
                created_recordings += 1

            db.commit()

            print("Migration completed successfully.")
            print(f"Sessions checked: {len(sessions)}")
            print(f"Session questions created: {created_questions}")
            print(f"Recording records created: {created_recordings}")
            print("Existing evaluation records were not modified.")
            print("Existing B2 audio objects were not moved or deleted.")

        except Exception:
            db.rollback()
            raise


if __name__ == "__main__":
    migrate()
