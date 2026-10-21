
import os
import uuid
from pathlib import Path

import boto3
from botocore.config import Config
from dotenv import load_dotenv

# Load the backend .env file explicitly.
env_file = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(env_file, override=True)

required = [
    "B2_KEY_ID",
    "B2_APPLICATION_KEY",
    "B2_BUCKET_NAME",
    "B2_ENDPOINT_URL",
]

missing = [name for name in required if not os.getenv(name)]
if missing:
    raise SystemExit(f"Missing .env settings: {', '.join(missing)}")

client = boto3.client(
    "s3",
    endpoint_url=os.environ["B2_ENDPOINT_URL"],
    aws_access_key_id=os.environ["B2_KEY_ID"],
    aws_secret_access_key=os.environ["B2_APPLICATION_KEY"],
    region_name="us-east-005",
    config=Config(
        signature_version="s3v4",
        retries={"max_attempts": 1},
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    ),
)

bucket = os.environ["B2_BUCKET_NAME"]
key = f"voxmeter-audio/connection-tests/{uuid.uuid4().hex}.txt"
content = b"VoxMenter Backblaze B2 connection test"

uploaded = False

try:
    print("Uploading test object...")
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=content,
        ContentType="text/plain",
    )
    uploaded = True
    print("Upload successful.")

    print("Downloading test object...")
    response = client.get_object(Bucket=bucket, Key=key)
    try:
        downloaded = response["Body"].read()
    finally:
        response["Body"].close()

    if downloaded != content:
        raise RuntimeError("Downloaded content did not match.")

    print("Download successful.")
    print("Backblaze B2 connection verified.")

except Exception as exc:
    print(f"Test failed: {type(exc).__name__}: {exc}")

finally:
    if uploaded:
        try:
            client.delete_object(Bucket=bucket, Key=key)
            print("Test object cleaned up.")
        except Exception as exc:
            print(
                "Cleanup failed: "
                f"{type(exc).__name__}: {exc}"
            )
            print(f"Test object key: {key}")
