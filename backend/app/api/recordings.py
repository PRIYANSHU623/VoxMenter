
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.practice_session import PracticeSession
from app.models.session_question import SessionQuestion
from app.models.recording import Recording
from app.services.practice_service import get_session
from app.services.storage_service import (
    upload_audio,
    create_playback_url,
    delete_audio,
)

router = APIRouter(tags=["Recordings"])

MAX_AUDIO_SIZE = 25 * 1024 * 1024

ALLOWED_AUDIO_TYPES = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/ogg": "ogg",
}


def get_audio_size(upload: UploadFile) -> int:
    upload.file.seek(0, 2)
    size = upload.file.tell()
    upload.file.seek(0)
    return size


def validate_audio(file: UploadFile) -> tuple[str, str, int]:
    content_type = (file.content_type or "").lower()
    extension = ALLOWED_AUDIO_TYPES.get(content_type)

    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported audio type",
        )

    file_size = get_audio_size(file)

    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded audio file is empty",
        )

    if file_size > MAX_AUDIO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio file exceeds the 25 MB limit",
        )

    return content_type, extension, file_size


def get_owned_session_question(
    db: Session,
    current_user: User,
    session_question_id: int,
) -> SessionQuestion | None:
    return (
        db.query(SessionQuestion)
        .join(
            PracticeSession,
            SessionQuestion.session_id == PracticeSession.id,
        )
        .filter(
            SessionQuestion.id == session_question_id,
            PracticeSession.user_id == current_user.id,
        )
        .first()
    )


def get_owned_recording(
    db: Session,
    current_user: User,
    recording_id: int,
) -> Recording | None:
    return (
        db.query(Recording)
        .join(
            SessionQuestion,
            Recording.session_question_id == SessionQuestion.id,
        )
        .join(
            PracticeSession,
            SessionQuestion.session_id == PracticeSession.id,
        )
        .filter(
            Recording.id == recording_id,
            PracticeSession.user_id == current_user.id,
        )
        .first()
    )


@router.post(
    "/api/session-questions/{session_question_id}/recordings",
    status_code=status.HTTP_201_CREATED,
)
def upload_question_recording(
    session_question_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session_question = get_owned_session_question(
        db, current_user, session_question_id
    )

    if session_question is None:
        raise HTTPException(
            status_code=404,
            detail="Session question not found",
        )

    content_type, extension, file_size = validate_audio(file)

    object_key = (
        f"voxmeter-audio/users/{current_user.id}/"
        f"sessions/{session_question.session_id}/"
        f"questions/{session_question.id}/"
        f"{uuid4().hex}.{extension}"
    )

    uploaded = False

    try:
        upload_audio(file.file, object_key, content_type)
        uploaded = True

        recording = Recording(
            session_question_id=session_question.id,
            audio_key=object_key,
            content_type=content_type,
            size_bytes=file_size,
            status="uploaded",
        )

        db.add(recording)
        session_question.status = "recording_uploaded"

        # Keep the old session status consistent while legacy routes exist.
        practice_session = (
            db.query(PracticeSession)
            .filter(PracticeSession.id == session_question.session_id)
            .first()
        )
        if practice_session is not None:
            practice_session.status = "recording_uploaded"

        db.commit()
        db.refresh(recording)

        return {
            "message": "Recording uploaded successfully",
            "recording_id": recording.id,
            "session_question_id": session_question.id,
            "session_id": session_question.session_id,
            "status": recording.status,
            "content_type": recording.content_type,
            "size_bytes": recording.size_bytes,
            "created_at": recording.created_at,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()

        if uploaded:
            try:
                delete_audio(object_key)
            except Exception:
                pass

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not save the recording. Please try again.",
        ) from exc
    finally:
        file.file.close()


@router.get(
    "/api/session-questions/{session_question_id}/recordings"
)
def list_question_recordings(
    session_question_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session_question = get_owned_session_question(
        db, current_user, session_question_id
    )

    if session_question is None:
        raise HTTPException(
            status_code=404,
            detail="Session question not found",
        )

    recordings = (
        db.query(Recording)
        .filter(Recording.session_question_id == session_question.id)
        .order_by(Recording.created_at)
        .all()
    )

    return [
        {
            "recording_id": item.id,
            "session_question_id": item.session_question_id,
            "status": item.status,
            "content_type": item.content_type,
            "size_bytes": item.size_bytes,
            "duration_seconds": item.duration_seconds,
            "transcript": item.transcript,
            "created_at": item.created_at,
        }
        for item in recordings
    ]


@router.get("/api/recordings/{recording_id}/playback")
def get_recording_playback_url(
    recording_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    recording = get_owned_recording(db, current_user, recording_id)

    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")

    try:
        playback_url = create_playback_url(
            recording.audio_key, expires_in=300
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not generate a playback URL",
        ) from exc

    return {
        "recording_id": recording.id,
        "playback_url": playback_url,
        "expires_in": 300,
    }


@router.delete("/api/recordings/{recording_id}")
def delete_recording(
    recording_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    recording = get_owned_recording(db, current_user, recording_id)

    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")

    object_key = recording.audio_key
    session_question_id = recording.session_question_id

    # Delete from B2 first; keep the database record if this fails.
    try:
        delete_audio(object_key)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not delete the recording from storage",
        ) from exc

    try:
        db.delete(recording)
        db.flush()

        remaining = (
            db.query(Recording)
            .filter(
                Recording.session_question_id == session_question_id
            )
            .count()
        )

        session_question = (
            db.query(SessionQuestion)
            .filter(SessionQuestion.id == session_question_id)
            .first()
        )

        if session_question is not None and remaining == 0:
            session_question.status = "pending"

        db.commit()

    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Audio was deleted from storage, but the database "
                "update failed. Please check the recording."
            ),
        ) from exc

    return {
        "message": "Recording deleted successfully",
        "recording_id": recording_id,
    }


# -------------------------------------------------------------------
# Legacy routes: keep temporarily for compatibility with older clients.
# New uploads should use the session-question endpoints above.
# -------------------------------------------------------------------

legacy_router = APIRouter(
    prefix="/api/recordings",
    tags=["Legacy Recordings"],
)


@legacy_router.post("/{session_id}")
def legacy_upload_recording(
    session_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    practice_session = get_session(db, current_user, session_id)

    if practice_session is None:
        raise HTTPException(status_code=404, detail="Practice session not found")

    content_type, extension, file_size = validate_audio(file)
    object_key = (
        f"voxmeter-audio/users/{current_user.id}/"
        f"sessions/{session_id}/{uuid4().hex}.{extension}"
    )

    uploaded = False

    try:
        upload_audio(file.file, object_key, content_type)
        uploaded = True

        practice_session.audio_key = object_key
        practice_session.status = "recording_uploaded"
        db.commit()
        db.refresh(practice_session)

        return {
            "message": "Legacy recording uploaded successfully",
            "session_id": session_id,
            "status": practice_session.status,
            "size_bytes": file_size,
        }
    except Exception as exc:
        db.rollback()
        if uploaded:
            try:
                delete_audio(object_key)
            except Exception:
                pass
        raise HTTPException(
            status_code=502,
            detail="Could not save the recording. Please try again.",
        ) from exc
    finally:
        file.file.close()


@legacy_router.get("/{session_id}/playback")
def legacy_recording_playback(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    practice_session = get_session(db, current_user, session_id)

    if practice_session is None:
        raise HTTPException(status_code=404, detail="Practice session not found")

    if not practice_session.audio_key:
        raise HTTPException(status_code=404, detail="No legacy recording exists")

    try:
        playback_url = create_playback_url(
            practice_session.audio_key, expires_in=300
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not generate a playback URL",
        ) from exc

    return {
        "session_id": session_id,
        "playback_url": playback_url,
        "expires_in": 300,
    }


@legacy_router.delete("/{session_id}")
def legacy_delete_recording(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    practice_session = get_session(db, current_user, session_id)

    if practice_session is None:
        raise HTTPException(status_code=404, detail="Practice session not found")

    if not practice_session.audio_key:
        raise HTTPException(status_code=404, detail="No legacy recording exists")

    object_key = practice_session.audio_key

    try:
        delete_audio(object_key)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not delete the recording from storage",
        ) from exc

    try:
        practice_session.audio_key = None
        practice_session.status = "pending"
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Audio was deleted, but the database update failed.",
        ) from exc

    return {"message": "Legacy recording deleted", "session_id": session_id}
