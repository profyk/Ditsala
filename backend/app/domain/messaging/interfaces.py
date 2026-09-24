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

    async def delete_object(self, *, key: str) -> None:
        """Removes the underlying object. Closes the disclosed gap where
        deleting a meeting document/recording only ever removed the DB
        row — a real "Delete" button needs the file actually gone, not
        just hidden from the list. A missing key is not an error (S3's
        own `delete_object` is already idempotent this way)."""
        ...
