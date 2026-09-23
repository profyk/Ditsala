"""
Provider interface for media storage (docs/DITSALA_MASTER_SPEC.md §3.4,
§18-21). The backend only ever issues signed URLs and stores metadata —
media bytes are encrypted client-side before upload (§6), so this
interface never sees plaintext, and neither does the storage bucket.
"""

from typing import Protocol


class StorageProvider(Protocol):
    async def create_upload_url(self, *, key: str, content_type: str) -> str:
        """A short-lived presigned URL the client PUTs the (already
        client-side-encrypted) object to directly."""
        ...

    async def create_download_url(self, *, key: str) -> str:
        """A short-lived presigned URL to GET the object directly."""
        ...

    async def put_object(self, *, key: str, data: bytes, content_type: str) -> None:
        """A direct server-side write — unlike `create_upload_url`, there is
        no client on the other end (e.g. §34.4's server-generated data-export
        bundle), so the backend uploads the bytes itself rather than issuing
        a presigned URL for someone else to PUT to."""
        ...
