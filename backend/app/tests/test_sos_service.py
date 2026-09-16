"""
Unit tests for SOS / emergency escalation (§26) — real Postgres, stub
push/SMS providers (real network calls aren't appropriate for a safety
feature's test suite; the providers themselves are exercised at the
adapter level, same boundary as Twilio Verify/Smile ID elsewhere).
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.notifications.interfaces import PushProvider, SmsProvider
from app.domain.sos.service import SosError, SosService
from app.models.accounts import NextOfKin, User
from app.models.circle import Contact
from app.models.devices import Device
from app.repositories.admin import SystemConfigRepository
from app.repositories.circle import ContactRepository
from app.repositories.devices import DeviceRepository
from app.repositories.sos import SosEventRepository, SosNotificationRepository
from app.repositories.users import NextOfKinRepository, UserRepository
from app.services.ratelimit.memory import InMemoryRateLimiter


class StubPushProvider(PushProvider):
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_push(
        self, *, push_token: str, title: str, body: str, data: dict[str, Any] | None = None
    ) -> None:
        self.sent.append({"push_token": push_token, "title": title, "body": body})


class StubSmsProvider(SmsProvider):
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send_sms(self, *, to_phone: str, body: str) -> None:
        self.sent.append({"to_phone": to_phone, "body": body})


@dataclass
class Harness:
    service: SosService
    users: UserRepository
    contacts: ContactRepository
    devices: DeviceRepository
    next_of_kin: NextOfKinRepository
    push: StubPushProvider
    sms: StubSmsProvider


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
    contacts = ContactRepository(session)
    devices = DeviceRepository(session)
    next_of_kin = NextOfKinRepository(session)
    push = StubPushProvider()
    sms = StubSmsProvider()
    service = SosService(
        sos_events=SosEventRepository(session),
        sos_notifications=SosNotificationRepository(session),
        contacts=contacts,
        next_of_kin=next_of_kin,
        devices=devices,
        users=users,
        system_config=SystemConfigRepository(session),
        push_provider=push,
        sms_provider=sms,
        rate_limiter=InMemoryRateLimiter(),
    )
    return Harness(
        service=service, users=users, contacts=contacts, devices=devices,
        next_of_kin=next_of_kin, push=push, sms=sms,
    )


async def _make_user(harness: Harness) -> User:
    return await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="SOS Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
        )
    )


async def _make_device(harness: Harness, user_id: uuid.UUID, push_token: str | None) -> Device:
    now = datetime.now(UTC)
    return await harness.devices.add(
        Device(
            user_id=user_id, device_name="Test Device", platform="ios",
            first_seen_at=now, last_seen_at=now, is_trusted=True, push_token=push_token,
        )
    )


async def test_trigger_creates_armed_event_with_default_window(harness: Harness) -> None:
    alice = await _make_user(harness)
    event = await harness.service.trigger(user_id=alice.id, last_known_location_ref="1.0,2.0")
    assert event.status == "armed"
    assert event.cancel_window_seconds == 10
    assert event.last_known_location_ref == "1.0,2.0"


async def test_cancel_within_window_succeeds(harness: Harness) -> None:
    alice = await _make_user(harness)
    event = await harness.service.trigger(user_id=alice.id)
    cancelled = await harness.service.cancel(user_id=alice.id, event_id=event.id)
    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at is not None


async def test_cancel_after_window_fails(harness: Harness) -> None:
    alice = await _make_user(harness)
    event = await harness.service.trigger(user_id=alice.id)
    event.triggered_at = datetime.now(UTC) - timedelta(seconds=30)

    with pytest.raises(SosError, match="cancellation window has passed"):
        await harness.service.cancel(user_id=alice.id, event_id=event.id)


async def test_only_triggering_user_can_cancel(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    event = await harness.service.trigger(user_id=alice.id)

    with pytest.raises(SosError, match="No such SOS event"):
        await harness.service.cancel(user_id=bob.id, event_id=event.id)


async def test_escalate_before_window_elapses_fails(harness: Harness) -> None:
    alice = await _make_user(harness)
    event = await harness.service.trigger(user_id=alice.id)

    with pytest.raises(SosError, match="Cannot escalate"):
        await harness.service.escalate(event_id=event.id)


async def test_escalate_notifies_trusted_circle_and_next_of_kin(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)  # trusted circle member
    await harness.contacts.add(
        Contact(owner_user_id=alice.id, contact_user_id=bob.id, tier="trusted")
    )
    await _make_device(harness, bob.id, push_token="ExponentPushToken[bob]")
    await harness.next_of_kin.add(
        NextOfKin(
            user_id=alice.id, full_name="Aunt Jane", relationship="Aunt",
            phone="+27831234567", notified_on_sos=True,
        )
    )
    await harness.next_of_kin.add(
        NextOfKin(
            user_id=alice.id, full_name="Uncle Sam", relationship="Uncle",
            phone="+27831234568", notified_on_sos=False,
        )
    )

    event = await harness.service.trigger(user_id=alice.id)
    event.triggered_at = datetime.now(UTC) - timedelta(seconds=30)

    escalated = await harness.service.escalate(event_id=event.id)
    assert escalated.status == "escalated"

    # Bob got both push (his device token) and SMS (his phone).
    assert any(p["push_token"] == "ExponentPushToken[bob]" for p in harness.push.sent)
    assert any(s["to_phone"] == bob.phone for s in harness.sms.sent)
    # Only the next-of-kin row with notified_on_sos=True was messaged.
    assert any(s["to_phone"] == "+27831234567" for s in harness.sms.sent)
    assert not any(s["to_phone"] == "+27831234568" for s in harness.sms.sent)

    notifications = await harness.service.list_notifications(user_id=alice.id, event_id=event.id)
    assert {n.channel for n in notifications} == {"push", "sms"}


async def test_escalate_is_idempotent(harness: Harness) -> None:
    alice = await _make_user(harness)
    event = await harness.service.trigger(user_id=alice.id)
    event.triggered_at = datetime.now(UTC) - timedelta(seconds=30)

    await harness.service.escalate(event_id=event.id)
    # A second escalate call on an already-escalated event is a no-op —
    # doesn't re-notify everyone.
    result = await harness.service.escalate(event_id=event.id)
    assert result.status == "escalated"


async def test_list_for_user_returns_own_history(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    event = await harness.service.trigger(user_id=alice.id)
    await harness.service.trigger(user_id=bob.id)

    events = await harness.service.list_for_user(alice.id)
    assert [e.id for e in events] == [event.id]
