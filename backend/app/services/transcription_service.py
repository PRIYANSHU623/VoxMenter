# import os
# from io import BytesIO

# from dotenv import load_dotenv
# from openai import OpenAI


# from app.db.session import SessionLocal
# from app.models.recording import Recording
# from app.services.storage_service import download_audio


# load_dotenv()

# MODEL_NAME = "gpt-transcribe"


# def transcribe_audio(
#     audio_bytes: bytes,
#     filename: str,
#     content_type: str,
# ) -> str:
#     """Transcribe an audio recording into English text."""
#     api_key = os.getenv("OPENAI_API_KEY")
#     if not api_key:
#         raise RuntimeError("OPENAI_API_KEY is not configured")

#     client = OpenAI(api_key=api_key)
    

#     result = client.audio.transcriptions.create(
#         model=MODEL_NAME,
#         file=(filename, BytesIO(audio_bytes), content_type),
#         language="en",
#     )

#     transcript = result.text.strip()
#     if not transcript:
#         raise ValueError("The transcription service returned empty text")

#     return transcript


#  using openrouter api key



# import base64
# import os

# import requests
# from dotenv import load_dotenv

# load_dotenv()

# OPENROUTER_TRANSCRIPTION_URL = (
#     "https://openrouter.ai/api/v1/audio/transcriptions"
# )
# MODEL_NAME = "openai/whisper-large-v3"


# def transcribe_audio(
#     audio_bytes: bytes,
#     filename: str,
#     content_type: str,
# ) -> str:
#     """Transcribe an audio recording using OpenRouter Whisper."""

#     api_key = os.getenv("OPENAI_API_KEY")
#     if not api_key:
#         raise RuntimeError("OPENROUTER_API_KEY is not configured")

#     if not audio_bytes:
#         raise ValueError("Audio file is empty")

#     # Determine the format from the filename.
#     extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
#     supported_formats = {
#         "wav", "mp3", "flac", "m4a", "ogg", "webm", "aac"
#     }

#     if extension not in supported_formats:
#         raise ValueError(
#             f"Unsupported audio format: {extension or 'unknown'}"
#         )

#     base64_audio = base64.b64encode(audio_bytes).decode("utf-8")

#     headers = {
#         "Authorization": f"Bearer {api_key}",
#         "Content-Type": "application/json",
#     }

#     payload = {
#         "model": MODEL_NAME,
#         "input_audio": {
#             "data": base64_audio,
#             "format": extension,
#         },
#         "language": "en",
#     }

#     try:
#         response = requests.post(
#             OPENROUTER_TRANSCRIPTION_URL,
#             headers=headers,
#             json=payload,
#             timeout=55,
#         )
#         response.raise_for_status()
#     except requests.RequestException as exc:
#         # Avoid returning API keys or request headers in error messages.
#         status_code = (
#             exc.response.status_code
#             if exc.response is not None
#             else None
#         )
#         if status_code:
#             raise RuntimeError(
#                 f"OpenRouter transcription request failed "
#                 f"(HTTP {status_code}). Check the worker logs "
#                 "and OpenRouter account."
#             ) from None
#         raise RuntimeError(
#             "Could not connect to OpenRouter transcription service."
#         ) from None

#     try:
#         result = response.json()
#     except ValueError:
#         raise RuntimeError(
#             "OpenRouter returned an invalid JSON response."
#         ) from None

#     transcript = result.get("text")
#     if not isinstance(transcript, str) or not transcript.strip():
#         raise RuntimeError(
#             "OpenRouter returned no transcript. Check the model response."
#         )

#     return transcript.strip()



#################################LOCAL WISPHER MODEL ##################################

from io import BytesIO

from faster_whisper import WhisperModel

_model = None


def get_model() -> WhisperModel:
    """Load the model once per worker process."""
    global _model

    if _model is None:
        _model = WhisperModel(
            "tiny.en",
            device="cpu",
            compute_type="int8",
            cpu_threads=1,
            num_workers=1,
        )

    return _model


def transcribe_audio(
    audio_bytes: bytes,
    filename: str,
    content_type: str,
) -> str:
    """Transcribe English audio locally without an API key."""

    if not audio_bytes:
        raise ValueError("Audio file is empty")

    audio_file = BytesIO(audio_bytes)
    audio_file.name = filename

    model = get_model()

    segments, _info = model.transcribe(
        audio_file,
        language="en",
        beam_size=5,
        vad_filter=True,
    )

    transcript = " ".join(
        segment.text.strip() for segment in segments
    ).strip()

    if not transcript:
        raise ValueError("No speech was detected in the recording")

    return transcript
