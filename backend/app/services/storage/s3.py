import asyncio

import boto3
from botocore.client import Config as BotoConfig

from app.core.config import Settings
from app.domain.messaging.interfaces import StorageProvider


class S3StorageProvider(StorageProvider):
    """
    Real adapter — any S3-compatible bucket (AWS S3 or Supabase Storage,
    per docs/DITSALA_MASTER_SPEC.md §3). Presigned-URL generation is a
    local Signature V4 computation (no network call), but it's run via
    `asyncio.to_thread` regardless to keep this interface consistently
    async and never block the event loop on boto3's client setup.
    """

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        endpoint_url: str,
        url_ttl_minutes: int,
    ) -> None:
        self._bucket = bucket
        self._ttl_seconds = url_ttl_minutes * 60
        self._client = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            endpoint_url=endpoint_url or None,
            config=BotoConfig(signature_version="s3v4"),
        )

    async def create_upload_url(self, *, key: str, content_type: str) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=self._ttl_seconds,
        )

    async def create_download_url(self, *, key: str) -> str:
        return await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=self._ttl_seconds,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "S3StorageProvider":
        return cls(
            bucket=settings.s3_bucket,
            region=settings.s3_region,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            endpoint_url=settings.s3_endpoint_url,
            url_ttl_minutes=settings.presigned_url_ttl_minutes,
        )
