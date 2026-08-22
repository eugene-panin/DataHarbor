"""S3 / SeaweedFS helpers for DataHarbor Core."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


def get_s3_client():
    """Return an S3 client from env (SeaweedFS-compatible)."""
    endpoint_url = os.getenv("S3_ENDPOINT_URL", "http://localhost:8334")

    if os.path.exists("/.dockerenv") and ("localhost" in endpoint_url or "127.0.0.1" in endpoint_url):
        endpoint_url = "http://seaweedfs:8333"

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=os.getenv("S3_ACCESS_KEY") or "minioadmin",
        aws_secret_access_key=os.getenv("S3_SECRET_KEY") or "minioadmin",
        region_name=os.getenv("S3_REGION", "us-east-1"),
        config=Config(signature_version="s3v4"),
    )


def upload_payload_to_s3(key: str, data: dict[str, Any]) -> str:
    """Upload a JSON payload to the configured bucket."""
    bucket_name = os.getenv("S3_BUCKET_NAME", "dataharbor-raw")
    client = get_s3_client()
    payload_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

    try:
        try:
            client.head_bucket(Bucket=bucket_name)
        except Exception:
            try:
                client.create_bucket(Bucket=bucket_name)
            except Exception:
                pass

        client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=payload_bytes,
            ContentType="application/json",
        )
        logger.info("Uploaded %s to s3://%s", key, bucket_name)
        return f"s3://{bucket_name}/{key}"
    except (BotoCoreError, ClientError) as e:
        logger.error("Failed to upload %s to S3: %s", key, e)
        raise


def download_media_stream_to_s3(
    media_url: str,
    s3_key: str,
    content_type: str = "video/mp4",
) -> dict[str, Any]:
    """Stream a remote media URL into S3."""
    from urllib.request import urlopen

    bucket_name = os.getenv("S3_BUCKET_NAME", "dataharbor-raw")
    client = get_s3_client()
    logger.info("Streaming media from %s to s3://%s/%s", media_url, bucket_name, s3_key)

    try:
        with urlopen(media_url, timeout=30) as response:
            body = response.read()
            client.put_object(
                Bucket=bucket_name,
                Key=s3_key,
                Body=body,
                ContentType=content_type,
            )
        s3_path = f"s3://{bucket_name}/{s3_key}"
        logger.info("Streamed media to %s", s3_path)
        return {"status": "success", "s3_path": s3_path, "s3_key": s3_key}
    except Exception as e:
        logger.error("Error streaming media %s to S3: %s", media_url, e)
        return {"status": "error", "message": str(e)}
