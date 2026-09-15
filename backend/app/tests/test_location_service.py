"""
Unit tests for location sharing (§25) — real Postgres, no external
providers involved.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.location.service import LocationError, LocationService
from app.models.accounts import User
from app.models.circle import Contact
from app.repositories.circle import ContactRepository
from app.repositories.location import (
    LocationAccessLogRepository,
    LocationPingRepository,
    LocationShareRepository,
)
from app.repositories.users import UserRepository


@dataclass
class Harness:
    service: LocationService
    users: UserRepository
    contacts: ContactRepository


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
    service = LocationService(
        shares=LocationShareRepository(session),
        pings=LocationPingRepository(session),
        access_log=LocationAccessLogRepository(session),
        contacts=contacts,
    )
    return Harness(service=service, users=users, contacts=contacts)


async def _make_user(harness: Harness) -> User:
    return await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Location Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
        )
    )


async def _trust(harness: Harness, owner_id: uuid.UUID, contact_id: uuid.UUID) -> None:
    await harness.contacts.add(
        Contact(owner_user_id=owner_id, contact_user_id=contact_id, tier="trusted")
    )


async def test_create_share_requires_trusted_tier(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)

    with pytest.raises(LocationError, match="trusted"):
        await harness.service.create_share(
            sharer_id=alice.id, recipient_id=bob.id, duration_seconds=3600
        )

    await harness.contacts.add(
        Contact(owner_user_id=alice.id, contact_user_id=bob.id, tier="verified")
    )
    with pytest.raises(LocationError, match="trusted"):
        await harness.service.create_share(
            sharer_id=alice.id, recipient_id=bob.id, duration_seconds=3600
        )


async def test_create_and_revoke_share(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _trust(harness, alice.id, bob.id)

    share = await harness.service.create_share(
        sharer_id=alice.id, recipient_id=bob.id, duration_seconds=3600
    )
    assert share.revoked_at is None
    assert [s.id for s in await harness.service.list_shares_by_me(alice.id)] == [share.id]
    assert [s.id for s in await harness.service.list_shares_to_me(bob.id)] == [share.id]

    revoked = await harness.service.revoke_share(user_id=alice.id, share_id=share.id)
    assert revoked.revoked_at is not None
    assert await harness.service.list_shares_by_me(alice.id) == []


async def test_only_sharer_can_revoke(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _trust(harness, alice.id, bob.id)
    share = await harness.service.create_share(
        sharer_id=alice.id, recipient_id=bob.id, duration_seconds=3600
    )

    with pytest.raises(LocationError, match="No such location share"):
        await harness.service.revoke_share(user_id=bob.id, share_id=share.id)


async def test_record_and_list_pings_logs_recipient_access(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _trust(harness, alice.id, bob.id)
    share = await harness.service.create_share(
        sharer_id=alice.id, recipient_id=bob.id, duration_seconds=3600
    )

    ping = await harness.service.record_ping(
        sharer_id=alice.id, share_id=share.id, lat=1.0, lng=2.0, accuracy_m=5.0
    )
    assert ping.lat == 1.0

    # The sharer viewing their own pings doesn't log an access entry.
    await harness.service.list_pings(viewer_id=alice.id, share_id=share.id)
    assert await harness.service.list_access_log(sharer_id=alice.id, share_id=share.id) == []

    # The recipient viewing does — §25 access transparency.
    pings = await harness.service.list_pings(viewer_id=bob.id, share_id=share.id)
    assert [p.id for p in pings] == [ping.id]
    log = await harness.service.list_access_log(sharer_id=alice.id, share_id=share.id)
    assert len(log) == 1
    assert log[0].accessed_by_user_id == bob.id


async def test_only_share_parties_can_view_pings(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    outsider = await _make_user(harness)
    await _trust(harness, alice.id, bob.id)
    share = await harness.service.create_share(
        sharer_id=alice.id, recipient_id=bob.id, duration_seconds=3600
    )

    with pytest.raises(LocationError, match="No such location share"):
        await harness.service.list_pings(viewer_id=outsider.id, share_id=share.id)


async def test_cannot_record_ping_on_revoked_share(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _trust(harness, alice.id, bob.id)
    share = await harness.service.create_share(
        sharer_id=alice.id, recipient_id=bob.id, duration_seconds=3600
    )
    await harness.service.revoke_share(user_id=alice.id, share_id=share.id)

    with pytest.raises(LocationError, match="no longer active"):
        await harness.service.record_ping(
            sharer_id=alice.id, share_id=share.id, lat=1.0, lng=2.0, accuracy_m=5.0
        )


async def test_only_sharer_can_record_ping(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await _trust(harness, alice.id, bob.id)
    share = await harness.service.create_share(
        sharer_id=alice.id, recipient_id=bob.id, duration_seconds=3600
    )

    with pytest.raises(LocationError, match="No such location share"):
        await harness.service.record_ping(
            sharer_id=bob.id, share_id=share.id, lat=1.0, lng=2.0, accuracy_m=5.0
        )
