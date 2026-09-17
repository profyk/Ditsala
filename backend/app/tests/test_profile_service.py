"""
Unit tests for the profile-picture flow — real Postgres, and a real
`S3StorageProvider` (presigned-URL generation is a local Signature V4
computation, no network call — same reasoning test_meeting_service.py
uses for real LiveKit token minting).
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.account.profile_service import ProfileError, ProfileService
from app.models.accounts import User
from app.repositories.users import UserRepository
from app.services.storage.s3 import S3StorageProvider


@dataclass
class Harness:
    service: ProfileService
    users: UserRepository


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
def harness(session: AsyncSession) -> Harness:
    users = UserRepository(session)
    service = ProfileService(
        users=users,
        storage_provider=S3StorageProvider(
            bucket="test-bucket",
            region="us-east-1",
            access_key_id="test",
            secret_access_key="test",
            endpoint_url="",
            url_ttl_minutes=15,
        ),
    )
    return Harness(service=service, users=users)


async def _make_user(harness: Harness) -> User:
    return await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Profile Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
        )
    )


async def test_avatar_starts_unset(harness: Harness) -> None:
    user = await _make_user(harness)
    assert await harness.service.get_avatar_url(user) is None


async def test_request_upload_rejects_an_unsupported_content_type(harness: Harness) -> None:
    user = await _make_user(harness)
    with pytest.raises(ProfileError, match="Unsupported image type"):
        await harness.service.request_avatar_upload(user, content_type="application/pdf")


async def test_full_avatar_lifecycle(harness: Harness) -> None:
    user = await _make_user(harness)

    key, upload_url = await harness.service.request_avatar_upload(user, content_type="image/png")
    assert key.startswith(f"avatars/{user.id}/")
    assert upload_url  # a real presigned URL string

    avatar_url = await harness.service.confirm_avatar(user, key=key)
    assert avatar_url is not None
    assert await harness.service.get_avatar_url(user) == avatar_url

    await harness.service.remove_avatar(user)
    assert await harness.service.get_avatar_url(user) is None


async def test_confirm_avatar_rejects_a_key_belonging_to_another_user(harness: Harness) -> None:
    user = await _make_user(harness)
    other_users_key = f"avatars/{uuid.uuid4()}/{uuid.uuid4()}"

    with pytest.raises(ProfileError, match="does not belong to you"):
        await harness.service.confirm_avatar(user, key=other_users_key)
