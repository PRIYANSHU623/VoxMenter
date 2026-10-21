
from io import BytesIO
from uuid import uuid4

from app.services.storage_service import (
    upload_audio,
    create_playback_url,
    delete_audio,
)

object_key = (
    f"voxmeter-audio/connection-tests/{uuid4().hex}.webm"
)

try:
    print("Uploading test object...")
    upload_audio(
        BytesIO(b"VoxMenter storage test"),
        object_key,
        "audio/webm",
    )
    print("Upload successful.")

    print("Generating playback URL...")
    url = create_playback_url(object_key)
    assert url.startswith("https://")
    print("Playback URL generated successfully.")

finally:
    print("Cleaning up test object...")
    delete_audio(object_key)
    print("Cleanup successful.")
