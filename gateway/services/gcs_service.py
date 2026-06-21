import os
from datetime import timedelta
from google.cloud import storage
from config import GCS_BUCKET_NAME
from log_utils.logger import get_logger

logger = get_logger("gcs-service")

_gcs_client = None

def get_gcs_client():
    global _gcs_client
    if _gcs_client is None:
        try:
            project_id = os.environ.get("GCP_PROJECT", "augmen-496803")
            _gcs_client = storage.Client(project=project_id)
        except Exception as e:
            logger.error(f"Failed to initialize GCS client: {e}")
            raise e
    return _gcs_client

def get_bucket():
    client = get_gcs_client()
    return client.bucket(GCS_BUCKET_NAME)

def upload_image_to_gcs(image_bytes: bytes, content_type: str, session_id: str, document_type: str, filename: str) -> str:
    """Upload an image to GCS and return the blob key (path without gs://bucket/)."""
    bucket = get_bucket()
    blob_path = f"govt_id/{session_id}/{document_type}/{filename}"
    blob = bucket.blob(blob_path)
    blob.upload_from_string(image_bytes, content_type=content_type)
    return blob_path

def generate_signed_url(blob_path: str, expiration_minutes: int = 15) -> str:
    """Generate a short-lived signed URL for a GCS blob."""
    bucket = get_bucket()
    blob = bucket.blob(blob_path)
    
    # Check if we are running in an environment where we can generate signed URLs
    # Service accounts can generate signed urls.
    try:
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=expiration_minutes),
            method="GET",
        )
        return url
    except Exception as e:
        logger.error(f"Failed to generate signed URL for {blob_path}: {e}")
        # Fallback to direct URL if permissions fail (will only work if public, which it shouldn't be)
        return f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{blob_path}"

def download_blob_bytes(blob_path: str) -> tuple[bytes, str]:
    """Download a blob's bytes and get its content type."""
    bucket = get_bucket()
    blob = bucket.blob(blob_path)
    if not blob.exists():
        raise FileNotFoundError(f"Blob {blob_path} not found")
    blob.reload()  # load metadata to get content_type
    content_type = blob.content_type or "application/octet-stream"
    return blob.download_as_bytes(), content_type

