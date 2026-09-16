"""End-to-end API tests for /meetings/* — real Postgres, real access tokens."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.deps import SessionDep, get_meeting_service
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.security import create_access_token
from app.domain.meetings.service import MeetingService
from app.main import app
from app.models.accounts import User
from app.repositories.meetings import MeetingParticipantRepository, MeetingRepository
from app.services.meet.livekit import LiveKitRoomProvider


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_db_session() -> AsyncIterator[AsyncSession]:
        yield session

    async def _override_meeting_service(db_session: SessionDep) -> MeetingService:
        return MeetingService(
            meetings=MeetingRepository(db_session),
            participants=MeetingParticipantRepository(db_session),
            room_provider=LiveKitRoomProvider(
                api_key="test-key-0123456789",
                api_secret="test-secret-0123456789-0123456789",
                livekit_url="wss://test",
            ),
        )

    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_meeting_service] = _override_meeting_service
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_active_user(session: AsyncSession) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="API Meeting Test User",
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
        account_state="active",
    )
    session.add(user)
    await session.flush()
    return user


def _bearer_for(user: User) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        device_id=uuid.uuid4(),
        jwt_secret=get_settings().jwt_secret,
        ttl_minutes=15,
    )
    return {"Authorization": f"Bearer {token}"}


async def test_create_join_and_end_meeting(client: AsyncClient, session: AsyncSession) -> None:
    host = await _make_active_user(session)
    headers = _bearer_for(host)

    r = await client.post("/api/v1/meetings", json={"title": "Kickoff"}, headers=headers)
    assert r.status_code == 201, r.text
    meeting_id = r.json()["id"]
    assert r.json()["status"] == "scheduled"

    r = await client.post(f"/api/v1/meetings/{meeting_id}/join", json={}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "host"
    assert body["access"]["token"]
    assert body["meeting"]["status"] == "live"

    r = await client.post(f"/api/v1/meetings/{meeting_id}/end", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"


async def test_guest_join_requires_no_auth(client: AsyncClient, session: AsyncSession) -> None:
    host = await _make_active_user(session)
    headers = _bearer_for(host)
    r = await client.post("/api/v1/meetings", json={"title": "Open house"}, headers=headers)
    meeting_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/guest-join",
        json={"guest_display_name": "Visitor"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access"]["token"]


async def test_end_meeting_forbidden_for_non_host(
    client: AsyncClient, session: AsyncSession
) -> None:
    host = await _make_active_user(session)
    other = await _make_active_user(session)
    r = await client.post(
        "/api/v1/meetings", json={"title": "Private"}, headers=_bearer_for(host)
    )
    meeting_id = r.json()["id"]

    r = await client.post(f"/api/v1/meetings/{meeting_id}/end", headers=_bearer_for(other))
    assert r.status_code == 400


async def test_meetings_require_authentication(client: AsyncClient) -> None:
    r = await client.post("/api/v1/meetings", json={"title": "x"})
    assert r.status_code == 401
