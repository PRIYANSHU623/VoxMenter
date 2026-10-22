import logging
from pathlib import PurePosixPath

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.recording import Recording
from app.services.storage_service import download_audio
from app.services.transcription_service import transcribe_audio

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="voxmenter.transcribe_recording",
    max_retries=2,
)
def transcribe_recording(self, recording_id: int) -> dict:
    db = SessionLocal()

    try:
        recording = db.get(Recording, recording_id)

        if recording is None:
            return {
                "recording_id": recording_id,
                "status": "not_found",
            }

        if recording.status == "transcribed" and recording.transcript:
            return {
                "recording_id": recording.id,
                "status": "transcribed",
            }

        recording.status = "transcribing"
        recording.error_message = None
        db.commit()

        audio_bytes = download_audio(recording.audio_key)
        filename = PurePosixPath(recording.audio_key).name

        transcript = transcribe_audio(
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=recording.content_type,
        )

        recording = db.get(Recording, recording_id)

        if recording is None:
            return {
                "recording_id": recording_id,
                "status": "not_found",
            }

        recording.transcript = transcript
        recording.status = "transcribed"
        recording.error_message = None
        db.commit()

        return {
            "recording_id": recording.id,
            "status": "transcribed",
        }

    except Exception as exc:
        db.rollback()

        logger.exception(
            "Transcription failed for recording %s",
            recording_id,
        )

        recording = db.get(Recording, recording_id)

        if self.request.retries < self.max_retries:
            if recording is not None:
                recording.status = "queued"
                recording.error_message = None
                db.commit()

            raise self.retry(
                exc=exc,
                countdown=10 * (self.request.retries + 1),
            )

        if recording is not None:
            recording.status = "failed"
            recording.error_message = (
                "Transcription failed after multiple attempts. "
                "Please try again."
            )
            db.commit()

        raise

    finally:
        db.close()