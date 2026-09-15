from app.core.config import Settings
from app.services.storage.s3 import S3StorageProvider


class SandboxStorageProvider(S3StorageProvider):
    """
    Sandbox adapter — a local S3-compatible endpoint (e.g. MinIO), same
    client code as production, different host/credentials, per
    docs/DITSALA_MASTER_SPEC.md §3.4. Not live-tested in this environment
    (no local MinIO instance was run here — see docs/SECURITY_GAPS.md).
    """

    @classmethod
    def from_settings(cls, settings: Settings) -> "SandboxStorageProvider":
        return cls(
            bucket=settings.sandbox_s3_bucket,
            region=settings.sandbox_s3_region,
            access_key_id=settings.sandbox_s3_access_key_id,
            secret_access_key=settings.sandbox_s3_secret_access_key,
            endpoint_url=settings.sandbox_s3_endpoint_url,
            url_ttl_minutes=settings.presigned_url_ttl_minutes,
        )
