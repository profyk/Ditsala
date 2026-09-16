"""End-to-end API tests for /meetings/* — real Postgres, real access tokens."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.deps import SessionDep, get_meeting_intelligence_service, get_meeting_service
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.security import create_access_token
from app.domain.meet_ai.interfaces import MeetingSummary, TranscriptSegment
from app.domain.meet_ai.service import MeetingIntelligenceService
from app.domain.meetings.service import MeetingService
from app.main import app
from app.models.accounts import User
from app.repositories.meetings import (
    BreakoutRoomParticipantRepository,
    BreakoutRoomRepository,
    MeetingAiNoteRepository,
    MeetingMessageRepository,
    MeetingParticipantRepository,
    MeetingPollRepository,
    MeetingPollVoteRepository,
    MeetingQuestionRepository,
    MeetingRecordingRepository,
    MeetingRepository,
    MeetingTranscriptRepository,
)
from app.services.storage.s3 import S3StorageProvider
from app.tests.test_meeting_intelligence_service import (
    StubIntelligenceProvider,
    StubTranscriptionProvider,
)
from app.tests.test_meeting_service import StubRoomProvider


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
            room_provider=StubRoomProvider(),
            recordings=MeetingRecordingRepository(db_session),
            messages=MeetingMessageRepository(db_session),
            polls=MeetingPollRepository(db_session),
            poll_votes=MeetingPollVoteRepository(db_session),
            questions=MeetingQuestionRepository(db_session),
            breakout_rooms=BreakoutRoomRepository(db_session),
            breakout_room_participants=BreakoutRoomParticipantRepository(db_session),
        )

    async def _override_meeting_intelligence_service(
        db_session: SessionDep,
    ) -> MeetingIntelligenceService:
        return MeetingIntelligenceService(
            meetings=MeetingRepository(db_session),
            participants=MeetingParticipantRepository(db_session),
            recordings=MeetingRecordingRepository(db_session),
            transcripts=MeetingTranscriptRepository(db_session),
            notes=MeetingAiNoteRepository(db_session),
            storage_provider=S3StorageProvider(
                bucket="test-bucket",
                region="us-east-1",
                access_key_id="test",
                secret_access_key="test",
                endpoint_url="",
                url_ttl_minutes=15,
            ),
            transcription_provider=StubTranscriptionProvider(
                [
                    TranscriptSegment(
                        text="Hello team.", started_at_ms=0, ended_at_ms=800, speaker_index=0
                    )
                ]
            ),
            intelligence_provider=StubIntelligenceProvider(
                MeetingSummary(
                    executive_summary="Quick sync.",
                    decisions=["Proceed as planned."],
                    action_items=["Follow up next week."],
                    topics=["Status update"],
                )
            ),
        )

    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_meeting_service] = _override_meeting_service
    app.dependency_overrides[get_meeting_intelligence_service] = (
        _override_meeting_intelligence_service
    )
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


async def test_waiting_room_admit_flow(client: AsyncClient, session: AsyncSession) -> None:
    host = await _make_active_user(session)
    other = await _make_active_user(session)
    r = await client.post(
        "/api/v1/meetings",
        json={"title": "Gated", "waiting_room_enabled": True},
        headers=_bearer_for(host),
    )
    meeting_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/join", json={}, headers=_bearer_for(other)
    )
    assert r.status_code == 200, r.text
    assert r.json()["admission_status"] == "waiting"
    assert r.json()["access"] is None
    participant_id = r.json()["participant_id"]

    r = await client.get(f"/api/v1/meetings/{meeting_id}/waiting-room", headers=_bearer_for(host))
    assert r.status_code == 200, r.text
    assert [p["id"] for p in r.json()] == [participant_id]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/participants/{participant_id}/admit",
        headers=_bearer_for(host),
    )
    assert r.status_code == 200, r.text
    assert r.json()["admission_status"] == "admitted"

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/join", json={}, headers=_bearer_for(other)
    )
    assert r.status_code == 200, r.text
    assert r.json()["admission_status"] == "admitted"
    assert r.json()["access"]["token"]


async def test_host_can_mute_and_remove_a_participant(
    client: AsyncClient, session: AsyncSession
) -> None:
    host = await _make_active_user(session)
    other = await _make_active_user(session)
    r = await client.post(
        "/api/v1/meetings", json={"title": "Standup"}, headers=_bearer_for(host)
    )
    meeting_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/join", json={}, headers=_bearer_for(other)
    )
    participant_id = r.json()["participant_id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/participants/{participant_id}/mute",
        json={"muted": True},
        headers=_bearer_for(host),
    )
    assert r.status_code == 204, r.text

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/participants/{participant_id}/remove",
        headers=_bearer_for(host),
    )
    assert r.status_code == 204, r.text

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/join", json={}, headers=_bearer_for(other)
    )
    assert r.status_code == 400


async def test_chat_poll_and_question_endpoints(
    client: AsyncClient, session: AsyncSession
) -> None:
    host = await _make_active_user(session)
    other = await _make_active_user(session)
    r = await client.post(
        "/api/v1/meetings", json={"title": "Town hall"}, headers=_bearer_for(host)
    )
    meeting_id = r.json()["id"]
    await client.post(f"/api/v1/meetings/{meeting_id}/join", json={}, headers=_bearer_for(other))

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/messages",
        json={"body": "Hello!"},
        headers=_bearer_for(host),
    )
    assert r.status_code == 201, r.text
    r = await client.get(f"/api/v1/meetings/{meeting_id}/messages", headers=_bearer_for(other))
    assert r.status_code == 200, r.text
    assert [m["body"] for m in r.json()] == ["Hello!"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/polls",
        json={"question": "Best time?", "options": ["9am", "2pm"]},
        headers=_bearer_for(host),
    )
    assert r.status_code == 201, r.text
    poll_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/polls/{poll_id}/vote",
        json={"option_index": 1},
        headers=_bearer_for(other),
    )
    assert r.status_code == 204, r.text
    r = await client.get(
        f"/api/v1/meetings/{meeting_id}/polls/{poll_id}/results", headers=_bearer_for(host)
    )
    assert r.status_code == 200, r.text
    assert r.json()["counts"] == {"0": 0, "1": 1}

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/questions",
        json={"body": "What's next?"},
        headers=_bearer_for(other),
    )
    assert r.status_code == 201, r.text
    question_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/questions/{question_id}/answer",
        headers=_bearer_for(host),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "answered"


async def test_recording_start_and_stop(client: AsyncClient, session: AsyncSession) -> None:
    host = await _make_active_user(session)
    r = await client.post(
        "/api/v1/meetings", json={"title": "Recorded"}, headers=_bearer_for(host)
    )
    meeting_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/start", headers=_bearer_for(host)
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "processing"
    recording_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/{recording_id}/stop",
        headers=_bearer_for(host),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"


async def test_breakout_rooms_end_to_end(client: AsyncClient, session: AsyncSession) -> None:
    host = await _make_active_user(session)
    other = await _make_active_user(session)
    r = await client.post(
        "/api/v1/meetings", json={"title": "Workshop"}, headers=_bearer_for(host)
    )
    meeting_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/join", json={}, headers=_bearer_for(other)
    )
    participant_id = r.json()["participant_id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/breakout-rooms",
        json={"names": ["Group A", "Group B"]},
        headers=_bearer_for(host),
    )
    assert r.status_code == 201, r.text
    breakout_room_id = r.json()[0]["id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/breakout-rooms/{breakout_room_id}/assign",
        json={"participant_id": participant_id},
        headers=_bearer_for(host),
    )
    assert r.status_code == 204, r.text

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/breakout-rooms/{breakout_room_id}/join",
        headers=_bearer_for(other),
    )
    assert r.status_code == 200, r.text
    assert r.json()["token"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/breakout-rooms/close", headers=_bearer_for(host)
    )
    assert r.status_code == 200, r.text
    assert all(room["closed_at"] is not None for room in r.json())


async def test_ai_pipeline_transcribe_notes_ask_and_search(
    client: AsyncClient, session: AsyncSession
) -> None:
    host = await _make_active_user(session)
    other = await _make_active_user(session)
    unique = uuid.uuid4().hex[:12]
    r = await client.post(
        "/api/v1/meetings",
        json={"title": f"Weekly Sync {unique}"},
        headers=_bearer_for(host),
    )
    meeting_id = r.json()["id"]
    await client.post(f"/api/v1/meetings/{meeting_id}/join", json={}, headers=_bearer_for(host))
    await client.post(f"/api/v1/meetings/{meeting_id}/join", json={}, headers=_bearer_for(other))

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/start", headers=_bearer_for(host)
    )
    recording_id = r.json()["id"]
    await client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/{recording_id}/stop", headers=_bearer_for(host)
    )

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/recordings/{recording_id}/transcribe",
        headers=_bearer_for(host),
    )
    assert r.status_code == 200, r.text
    assert r.json()[0]["text_segment"] == "Hello team."

    r = await client.get(f"/api/v1/meetings/{meeting_id}/transcript", headers=_bearer_for(other))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/notes/generate", headers=_bearer_for(host)
    )
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["content"] == "Quick sync."
    note_id = r.json()["summary"]["id"]

    r = await client.patch(
        f"/api/v1/meetings/{meeting_id}/notes/{note_id}",
        json={"content": "Edited summary."},
        headers=_bearer_for(other),
    )
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "Edited summary."

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/ask",
        json={"question": "What did I miss?"},
        headers=_bearer_for(other),
    )
    assert r.status_code == 200, r.text
    assert r.json()["answer"]

    r = await client.get(
        "/api/v1/meetings/search", params={"q": unique}, headers=_bearer_for(host)
    )
    assert r.status_code == 200, r.text
    assert [m["id"] for m in r.json()] == [meeting_id]
