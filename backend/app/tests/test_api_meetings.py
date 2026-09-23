"""End-to-end API tests for /meetings/* — real Postgres, real access tokens."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import jwt
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
from app.domain.translation.service import TranslationService
from app.main import app
from app.models.accounts import User
from app.repositories.admin import SystemConfigRepository
from app.repositories.meetings import (
    BreakoutRoomParticipantRepository,
    BreakoutRoomRepository,
    MeetingAiNoteRepository,
    MeetingDocumentRepository,
    MeetingMessageRepository,
    MeetingParticipantRepository,
    MeetingPollRepository,
    MeetingPollVoteRepository,
    MeetingQuestionRepository,
    MeetingRecordingRepository,
    MeetingRegistrationRepository,
    MeetingRepository,
    MeetingTranscriptRepository,
)
from app.repositories.translation import (
    ConferenceLanguagePreferenceRepository,
    InterpreterSessionRepository,
    TranslationRequestRepository,
    TranslationUsageRepository,
    UserLanguagePreferenceRepository,
)
from app.repositories.users import UserRepository
from app.services.storage.s3 import S3StorageProvider
from app.services.translation.mock import MockTranslationProvider
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
            registrations=MeetingRegistrationRepository(db_session),
            documents=MeetingDocumentRepository(db_session),
            storage_provider=S3StorageProvider(
                bucket="test-bucket",
                region="us-east-1",
                access_key_id="test",
                secret_access_key="test",
                endpoint_url="",
                url_ttl_minutes=15,
            ),
            conference_language_preferences=ConferenceLanguagePreferenceRepository(db_session),
            translation_service=TranslationService(
                translation_requests=TranslationRequestRepository(db_session),
                translation_usage=TranslationUsageRepository(db_session),
                user_language_preferences=UserLanguagePreferenceRepository(db_session),
                interpreter_sessions=InterpreterSessionRepository(db_session),
                system_config=SystemConfigRepository(db_session),
                provider=MockTranslationProvider(),
            ),
            users=UserRepository(db_session),
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
    """Chat/polls/questions are public-given-a-participant_id (not
    CurrentUserDep) — apps/meet's web client only ever has a guest or
    host-link session, never a real DITSALA access token, so every one
    of these needs to work from just a participant_id. See
    test_guest_can_set_conference_language_and_translate_chat for the
    same reasoning applied to multilingual chat."""
    host = await _make_active_user(session)
    other = await _make_active_user(session)
    r = await client.post(
        "/api/v1/meetings", json={"title": "Town hall"}, headers=_bearer_for(host)
    )
    meeting_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/join", json={}, headers=_bearer_for(host)
    )
    host_participant_id = r.json()["participant_id"]
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/join", json={}, headers=_bearer_for(other)
    )
    other_participant_id = r.json()["participant_id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/messages",
        json={"participant_id": host_participant_id, "body": "Hello!"},
    )
    assert r.status_code == 201, r.text
    r = await client.get(
        f"/api/v1/meetings/{meeting_id}/messages",
        params={"participant_id": other_participant_id},
    )
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
        json={"participant_id": other_participant_id, "option_index": 1},
    )
    assert r.status_code == 204, r.text
    r = await client.get(
        f"/api/v1/meetings/{meeting_id}/polls/{poll_id}/results",
        params={"participant_id": host_participant_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["counts"] == {"0": 0, "1": 1}

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/questions",
        json={"participant_id": other_participant_id, "body": "What's next?"},
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
        params={"participant_id": participant_id},
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


async def test_join_info_is_public_and_reports_scheduling_state(
    client: AsyncClient, session: AsyncSession
) -> None:
    host = await _make_active_user(session)
    r = await client.post(
        "/api/v1/meetings",
        json={
            "title": "Board meeting",
            "password": "s3cret!",
            "scheduled_start_at": "2099-01-01T12:00:00Z",
        },
        headers=_bearer_for(host),
    )
    meeting_id = r.json()["id"]

    r = await client.get(f"/api/v1/meetings/{meeting_id}/join-info")
    assert r.status_code == 200, r.text
    assert r.json()["requires_password"] is True
    assert r.json()["joinable_now"] is False


async def test_webinar_stage_control_and_registration_endpoints(
    client: AsyncClient, session: AsyncSession
) -> None:
    host = await _make_active_user(session)
    other = await _make_active_user(session)
    r = await client.post(
        "/api/v1/meetings",
        json={"title": "Product launch", "meeting_type": "webinar"},
        headers=_bearer_for(host),
    )
    meeting_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/register",
        json={"email": "fan@example.com", "display_name": "A Fan"},
    )
    assert r.status_code == 201, r.text

    r = await client.get(
        f"/api/v1/meetings/{meeting_id}/registrations", headers=_bearer_for(host)
    )
    assert r.status_code == 200, r.text
    assert [reg["email"] for reg in r.json()] == ["fan@example.com"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/join", json={}, headers=_bearer_for(other)
    )
    participant_id = r.json()["participant_id"]
    assert r.json()["access"]["token"]
    assert (
        jwt.decode(r.json()["access"]["token"], options={"verify_signature": False})["video"][
            "canPublish"
        ]
        is False
    )

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/participants/{participant_id}/invite-to-stage",
        headers=_bearer_for(host),
    )
    assert r.status_code == 200, r.text
    assert r.json()["stage_status"] == "on_stage"

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/participants/{participant_id}/move-to-audience",
        headers=_bearer_for(host),
    )
    assert r.status_code == 200, r.text
    assert r.json()["stage_status"] == "audience"


# ---- host-link / host-join handoff (apps/meet has no session of its own) ----


async def test_host_link_and_host_join_bypasses_password(
    client: AsyncClient, session: AsyncSession
) -> None:
    host = await _make_active_user(session)
    headers = _bearer_for(host)
    r = await client.post(
        "/api/v1/meetings",
        json={"title": "Password protected", "password": "secret123"},
        headers=headers,
    )
    meeting_id = r.json()["id"]

    r = await client.post(f"/api/v1/meetings/{meeting_id}/host-link", headers=headers)
    assert r.status_code == 200, r.text
    token = r.json()["token"]

    # No Authorization header, no password — the token alone is the
    # credential, and the host bypasses their own meeting's password
    # (the _check_joinable fix this feature needed).
    r = await client.post(f"/api/v1/meetings/{meeting_id}/host-join", json={"token": token})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "host"
    assert r.json()["access"]["token"]


async def test_waiting_room_admit_and_extend_work_via_the_host_token(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The whole point of switching these three endpoints to
    MeetingActorDep: apps/meet's host-link handoff (no real access token
    of its own) must be able to see who's waiting, admit them, and
    extend the meeting — not just a CurrentUserDep-authenticated caller."""
    host = await _make_active_user(session)
    headers = _bearer_for(host)
    r = await client.post(
        "/api/v1/meetings",
        json={
            "title": "Global Standup",
            "scheduled_duration_minutes": 30,
            "waiting_room_enabled": True,
        },
        headers=headers,
    )
    meeting_id = r.json()["id"]
    r = await client.post(f"/api/v1/meetings/{meeting_id}/host-link", headers=headers)
    host_token = r.json()["token"]
    host_token_headers = {"Authorization": f"Bearer {host_token}"}

    r = await client.post(f"/api/v1/meetings/{meeting_id}/host-join", json={"token": host_token})
    assert r.status_code == 200, r.text

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/guest-join",
        json={"guest_display_name": "Visitor"},
    )
    guest_participant_id = r.json()["participant_id"]
    assert r.json()["admission_status"] == "waiting"

    r = await client.get(
        f"/api/v1/meetings/{meeting_id}/waiting-room", headers=host_token_headers
    )
    assert r.status_code == 200, r.text
    assert [p["id"] for p in r.json()] == [guest_participant_id]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/participants/{guest_participant_id}/admit",
        headers=host_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["admission_status"] == "admitted"

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/extend",
        json={"additional_minutes": 15},
        headers=host_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["duration_extended_minutes"] == 15


async def test_full_host_toolset_works_via_the_host_token(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The exact regression apps/meet's host was hitting: lock, mute,
    promote, remove, polls, breakout rooms, and meeting analytics all
    used to require CurrentUserDep (a real DITSALA access token) — which
    apps/meet, a separate origin with no session of its own, never has.
    Every one of these now goes through MeetingActorDep instead, so the
    host-link token alone (exactly what apps/meet actually holds) must
    be able to drive all of them, with no Authorization header carrying
    a real access token anywhere in this test."""
    host = await _make_active_user(session)
    other = await _make_active_user(session)
    r = await client.post(
        "/api/v1/meetings", json={"title": "Full toolset"}, headers=_bearer_for(host)
    )
    meeting_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/host-link", headers=_bearer_for(host)
    )
    host_token_headers = {"Authorization": f"Bearer {r.json()['token']}"}

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/join", json={}, headers=_bearer_for(other)
    )
    participant_id = r.json()["participant_id"]

    # Full participant list (unlike /waiting-room, includes admitted ones)
    r = await client.get(
        f"/api/v1/meetings/{meeting_id}/participants", headers=host_token_headers
    )
    assert r.status_code == 200, r.text
    assert {p["id"] for p in r.json()} >= {participant_id}

    # Lock / unlock
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/lock", json={"locked": True}, headers=host_token_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["locked_at"] is not None
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/lock", json={"locked": False}, headers=host_token_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["locked_at"] is None

    # Mute / promote / remove
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/participants/{participant_id}/mute",
        json={"muted": True},
        headers=host_token_headers,
    )
    assert r.status_code == 204, r.text
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/participants/{participant_id}/promote",
        headers=host_token_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "co_host"

    # Polls: create + close via the host token
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/polls",
        json={"question": "Ship it?", "options": ["Yes", "No"]},
        headers=host_token_headers,
    )
    assert r.status_code == 201, r.text
    poll_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/polls/{poll_id}/close", headers=host_token_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["closed_at"] is not None

    # Breakout rooms: create + assign + close via the host token
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/breakout-rooms",
        json={"names": ["Room 1"]},
        headers=host_token_headers,
    )
    assert r.status_code == 201, r.text
    breakout_room_id = r.json()[0]["id"]
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/breakout-rooms/{breakout_room_id}/assign",
        json={"participant_id": participant_id},
        headers=host_token_headers,
    )
    assert r.status_code == 204, r.text
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/breakout-rooms/close", headers=host_token_headers
    )
    assert r.status_code == 200, r.text
    assert all(room["closed_at"] is not None for room in r.json())

    # Attendance analytics — the plan-gated tool this session's own new
    # feature added; DEFAULT_ENTITLEMENTS (this test's MeetingService has
    # no PlanService wired) is permissive, so it should just work.
    r = await client.get(
        f"/api/v1/meetings/{meeting_id}/analytics", headers=host_token_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["unique_attendees"] >= 1

    # End the meeting itself — also host-only, also via the host token.
    r = await client.post(f"/api/v1/meetings/{meeting_id}/end", headers=host_token_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"


async def test_guest_can_use_reactions_chat_polls_questions_and_breakout_rooms(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The other half of the same fix: a guest (no DITSALA account, no
    JWT, nothing but the participant_id guest-join handed back) must be
    able to actually use every one of these tools — previously every one
    of them required CurrentUserDep and would have 401'd a guest outright."""
    host = await _make_active_user(session)
    r = await client.post(
        "/api/v1/meetings", json={"title": "Open to guests"}, headers=_bearer_for(host)
    )
    meeting_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/guest-join",
        json={"guest_display_name": "Visitor"},
    )
    guest_id = r.json()["participant_id"]

    # Reactions and raise-hand — no Authorization header at all.
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/reactions",
        json={"participant_id": guest_id, "reaction": "👍"},
    )
    assert r.status_code == 204, r.text
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/raise-hand",
        json={"participant_id": guest_id, "raised": True},
    )
    assert r.status_code == 204, r.text

    # Chat
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/messages",
        json={"participant_id": guest_id, "body": "Hi from a guest!"},
    )
    assert r.status_code == 201, r.text
    r = await client.get(
        f"/api/v1/meetings/{meeting_id}/messages", params={"participant_id": guest_id}
    )
    assert r.status_code == 200, r.text
    assert [m["body"] for m in r.json()] == ["Hi from a guest!"]

    # Polls: host creates (via a real token), guest votes and reads results.
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/polls",
        json={"question": "Coffee or tea?", "options": ["Coffee", "Tea"]},
        headers=_bearer_for(host),
    )
    poll_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/polls/{poll_id}/vote",
        json={"participant_id": guest_id, "option_index": 0},
    )
    assert r.status_code == 204, r.text
    r = await client.get(
        f"/api/v1/meetings/{meeting_id}/polls", params={"participant_id": guest_id}
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1

    # Q&A
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/questions",
        json={"participant_id": guest_id, "body": "Will there be a recording?"},
    )
    assert r.status_code == 201, r.text
    r = await client.get(
        f"/api/v1/meetings/{meeting_id}/questions", params={"participant_id": guest_id}
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/questions/{r.json()[0]['id']}/upvote",
        params={"participant_id": guest_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["upvote_count"] == 1

    # Breakout rooms: host creates + assigns (real token), guest joins with
    # nothing but their own participant_id.
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/breakout-rooms",
        json={"names": ["Guests"]},
        headers=_bearer_for(host),
    )
    breakout_room_id = r.json()[0]["id"]
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/breakout-rooms/{breakout_room_id}/assign",
        json={"participant_id": guest_id},
        headers=_bearer_for(host),
    )
    assert r.status_code == 204, r.text
    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/breakout-rooms/{breakout_room_id}/join",
        params={"participant_id": guest_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["token"]


async def test_host_join_rejects_token_for_a_different_meeting(
    client: AsyncClient, session: AsyncSession
) -> None:
    host = await _make_active_user(session)
    headers = _bearer_for(host)
    r = await client.post("/api/v1/meetings", json={"title": "Meeting A"}, headers=headers)
    meeting_a_id = r.json()["id"]
    r = await client.post("/api/v1/meetings", json={"title": "Meeting B"}, headers=headers)
    meeting_b_id = r.json()["id"]

    r = await client.post(f"/api/v1/meetings/{meeting_a_id}/host-link", headers=headers)
    token_for_a = r.json()["token"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_b_id}/host-join", json={"token": token_for_a}
    )
    assert r.status_code == 403, r.text


async def test_host_link_forbidden_for_non_host(
    client: AsyncClient, session: AsyncSession
) -> None:
    host = await _make_active_user(session)
    other = await _make_active_user(session)
    r = await client.post(
        "/api/v1/meetings", json={"title": "Private"}, headers=_bearer_for(host)
    )
    meeting_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/host-link", headers=_bearer_for(other)
    )
    assert r.status_code == 400


# ---- meeting documents — guest-viewable files --------------------------------


async def test_meeting_documents_upload_list_download_for_guest(
    client: AsyncClient, session: AsyncSession
) -> None:
    host = await _make_active_user(session)
    headers = _bearer_for(host)
    r = await client.post("/api/v1/meetings", json={"title": "Docs meeting"}, headers=headers)
    meeting_id = r.json()["id"]
    await client.post(f"/api/v1/meetings/{meeting_id}/join", json={}, headers=headers)

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/documents/upload",
        json={"filename": "agenda.pdf", "content_type": "application/pdf", "size_bytes": 1024},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    document_id = r.json()["document_id"]
    assert r.json()["upload_url"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/guest-join",
        json={"guest_display_name": "Visitor"},
    )
    guest_participant_id = r.json()["participant_id"]

    r = await client.get(
        f"/api/v1/meetings/{meeting_id}/documents",
        params={"participant_id": guest_participant_id},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.json()[0]["id"] == document_id
    assert r.json()[0]["filename"] == "agenda.pdf"

    r = await client.get(
        f"/api/v1/meetings/{meeting_id}/documents/{document_id}/download",
        params={"participant_id": guest_participant_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["download_url"]


async def test_guest_can_set_conference_language_and_translate_chat(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The whole point of gating these public-given-a-participant-id
    (not CurrentUserDep) — apps/meet's web client only ever has a guest
    or a host-link session, never a real DITSALA access token, so a
    guest must be able to use multilingual chat without one."""
    host = await _make_active_user(session)
    headers = _bearer_for(host)
    r = await client.post("/api/v1/meetings", json={"title": "Global Standup"}, headers=headers)
    meeting_id = r.json()["id"]
    r = await client.post(f"/api/v1/meetings/{meeting_id}/join", json={}, headers=headers)
    host_participant_id = r.json()["participant_id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/guest-join",
        json={"guest_display_name": "Visitor"},
    )
    guest_participant_id = r.json()["participant_id"]

    r = await client.put(
        f"/api/v1/meetings/{meeting_id}/participants/{guest_participant_id}/language",
        json={"language": "zh"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["language"] == "zh"

    r = await client.get(
        f"/api/v1/meetings/{meeting_id}/participants/{guest_participant_id}/language",
    )
    assert r.status_code == 200, r.text
    assert r.json()["language"] == "zh"

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/messages",
        json={"participant_id": host_participant_id, "body": "Hello, nice to meet you."},
    )
    assert r.status_code == 201, r.text
    message_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/messages/{message_id}/translate",
        params={"participant_id": guest_participant_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["translated_text"] == "你好，很高兴认识你。"
    assert r.json()["target_language"] == "zh"
    assert r.json()["status"] == "completed"


async def test_document_upload_forbidden_for_non_host(
    client: AsyncClient, session: AsyncSession
) -> None:
    host = await _make_active_user(session)
    other = await _make_active_user(session)
    r = await client.post(
        "/api/v1/meetings", json={"title": "Docs"}, headers=_bearer_for(host)
    )
    meeting_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_id}/documents/upload",
        json={"filename": "x.txt", "content_type": "text/plain", "size_bytes": 10},
        headers=_bearer_for(other),
    )
    assert r.status_code == 400


async def test_documents_list_rejects_a_participant_from_another_meeting(
    client: AsyncClient, session: AsyncSession
) -> None:
    host = await _make_active_user(session)
    headers = _bearer_for(host)
    r = await client.post("/api/v1/meetings", json={"title": "Meeting A"}, headers=headers)
    meeting_a_id = r.json()["id"]
    r = await client.post("/api/v1/meetings", json={"title": "Meeting B"}, headers=headers)
    meeting_b_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/meetings/{meeting_a_id}/guest-join", json={"guest_display_name": "Visitor"}
    )
    participant_in_a = r.json()["participant_id"]

    r = await client.get(
        f"/api/v1/meetings/{meeting_b_id}/documents",
        params={"participant_id": participant_in_a},
    )
    assert r.status_code == 400
