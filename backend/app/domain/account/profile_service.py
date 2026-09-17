"""
Profile picture — reuses the exact same `StorageProvider` presigned-URL
pattern `MessagingService` already uses for media (docs/DITSALA_MASTER_SPEC.md
§3). Unlike message media, an avatar is not E2EE — a profile picture is
meant to be visible to your Circle (and, per RBAC, admins), so there's no
client-side encryption key to manage here, just an object key.
"""

import uuid

from app.domain.messaging.interfaces import StorageProvider
from app.models.accounts import User
from app.repositories.users import UserRepository

ALLOWED_AVATAR_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


class ProfileError(Exception):
    """Raised for profile preconditions a caller should turn into a 4xx, not a 500."""


class ProfileService:
    def __init__(self, *, users: UserRepository, storage_provider: StorageProvider) -> None:
        self._users = users
        self._storage = storage_provider

    async def request_avatar_upload(self, user: User, *, content_type: str) -> tuple[str, str]:
        if content_type not in ALLOWED_AVATAR_CONTENT_TYPES:
            raise ProfileError(f"Unsupported image type: {content_type!r}.")
        key = f"avatars/{user.id}/{uuid.uuid4()}"
        upload_url = await self._storage.create_upload_url(key=key, content_type=content_type)
        return key, upload_url

    async def confirm_avatar(self, user: User, *, key: str) -> str | None:
        if not key.startswith(f"avatars/{user.id}/"):
            raise ProfileError("This upload key does not belong to you.")
        user.avatar_key = key
        return await self.get_avatar_url(user)

    async def remove_avatar(self, user: User) -> None:
        user.avatar_key = None

    async def get_avatar_url(self, user: User) -> str | None:
        if user.avatar_key is None:
            return None
        return await self._storage.create_download_url(key=user.avatar_key)
