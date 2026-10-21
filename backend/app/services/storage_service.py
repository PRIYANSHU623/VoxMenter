
import os
from functools import lru_cache
from typing import BinaryIO

import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

B2_KEY_ID = os.getenv("B2_KEY_ID")
B2_APPLICATION_KEY = os.getenv("B2_APPLICATION_KEY")
B2_BUCKET_NAME = os.getenv("B2_BUCKET_NAME")
B2_ENDPOINT_URL = os.getenv("B2_ENDPOINT_URL")

# All recording object keys must begin with this prefix because
# the Backblaze application key is restricted to this prefix.
AUDIO_PREFIX = "voxmeter-audio"


def _validate_config() -> None:
    """Fail clearly if required B2 settings are missing."""
    required = {
        "B2_KEY_ID": B2_KEY_ID,
        "B2_APPLICATION_KEY": B2_APPLICATION_KEY,
        "B2_BUCKET_NAME": B2_BUCKET_NAME,
        "B2_ENDPOINT_URL": B2_ENDPOINT_URL,
    }

    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(
            f"Missing Backblaze configuration: {', '.join(missing)}"
        )


@lru_cache(maxsize=1)
def get_s3_client():
    """Create one reusable B2 S3-compatible client."""
    _validate_config()

    return boto3.client(
        "s3",
        endpoint_url=B2_ENDPOINT_URL,
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APPLICATION_KEY,
        region_name="us-east-005",
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _validate_object_key(object_key: str) -> None:
    """Prevent keys outside our application's audio prefix."""
    if (
        not object_key.startswith(f"{AUDIO_PREFIX}/")
        or ".." in object_key.split("/")
        or object_key.startswith("/")
    ):
        raise ValueError("Invalid audio object key")


def upload_audio(
    file_obj: BinaryIO,
    object_key: str,
    content_type: str,
) -> str:
    """Upload an audio file to the private B2 bucket."""
    _validate_object_key(object_key)

    get_s3_client().upload_fileobj(
        file_obj,
        B2_BUCKET_NAME,
        object_key,
        ExtraArgs={"ContentType": content_type},
    )

    return object_key


def create_playback_url(
    object_key: str,
    expires_in: int = 300,
) -> str:
    """Create a temporary URL for playing a stored recording."""
    _validate_object_key(object_key)

    if not 1 <= expires_in <= 3600:
        raise ValueError("URL expiry must be between 1 and 3600 seconds")

    return get_s3_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": B2_BUCKET_NAME,
            "Key": object_key,
        },
        ExpiresIn=expires_in,
    )


def delete_audio(object_key: str) -> None:
    """Delete a stored recording from B2."""
    _validate_object_key(object_key)

    get_s3_client().delete_object(
        Bucket=B2_BUCKET_NAME,
        Key=object_key,
    )
