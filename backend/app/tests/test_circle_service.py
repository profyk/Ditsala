"""
Unit tests for Circle — contact requests, trust tiers, block, report,
invitations (§22-24). Real Postgres, no external providers involved.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.circle.service import CircleError, CircleService
from app.models.accounts import User
from app.repositories.admin import SystemConfigRepository
from app.repositories.circle import (
    BlockRepository,
    ContactRepository,
    ContactRequestRepository,
    InvitationRepository,
    ReportRepository,
)
from app.repositories.users import UserRepository
from app.services.ratelimit.memory import InMemoryRateLimiter


@dataclass
class Harness:
    service: CircleService
    users: UserRepository
    contacts: ContactRepository
    contact_requests: ContactRequestRepository


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
    contact_requests = ContactRequestRepository(session)
    service = CircleService(
        contacts=contacts,
        contact_requests=contact_requests,
        invitations=InvitationRepository(session),
        blocks=BlockRepository(session),
        reports=ReportRepository(session),
        users=users,
        system_config=SystemConfigRepository(session),
        rate_limiter=InMemoryRateLimiter(),
    )
    return Harness(
        service=service, users=users, contacts=contacts, contact_requests=contact_requests
    )


async def _make_user(harness: Harness) -> User:
    return await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Circle Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
        )
    )


# --- §22: contact requests ---


async def test_send_request_creates_unverified_contacts_both_ways(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)

    request = await harness.service.send_contact_request(
        from_user_id=alice.id, to_user_id=bob.id, channel="qr"
    )
    assert request.status == "pending"

    alice_view = await harness.contacts.get_by_pair(alice.id, bob.id)
    bob_view = await harness.contacts.get_by_pair(bob.id, alice.id)
    assert alice_view is not None and alice_view.tier == "unverified"
    assert bob_view is not None and bob_view.tier == "unverified"


async def test_cannot_send_request_to_self(harness: Harness) -> None:
    alice = await _make_user(harness)
    with pytest.raises(CircleError, match="yourself"):
        await harness.service.send_contact_request(
            from_user_id=alice.id, to_user_id=alice.id, channel="qr"
        )


async def test_duplicate_pending_request_rejected(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await harness.service.send_contact_request(
        from_user_id=alice.id, to_user_id=bob.id, channel="qr"
    )
    with pytest.raises(CircleError, match="already pending"):
        await harness.service.send_contact_request(
            from_user_id=bob.id, to_user_id=alice.id, channel="qr"
        )


async def test_accept_promotes_both_sides_to_verified(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    request = await harness.service.send_contact_request(
        from_user_id=alice.id, to_user_id=bob.id, channel="invite_link"
    )

    accepted = await harness.service.accept_contact_request(
        request_id=request.id, acting_user_id=bob.id
    )
    assert accepted.status == "accepted"

    alice_view = await harness.contacts.get_by_pair(alice.id, bob.id)
    bob_view = await harness.contacts.get_by_pair(bob.id, alice.id)
    assert alice_view is not None and alice_view.tier == "verified"
    assert bob_view is not None and bob_view.tier == "verified"


async def test_only_recipient_can_accept(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    request = await harness.service.send_contact_request(
        from_user_id=alice.id, to_user_id=bob.id, channel="qr"
    )
    with pytest.raises(CircleError, match="No such contact request"):
        await harness.service.accept_contact_request(
            request_id=request.id, acting_user_id=alice.id
        )


async def test_decline_clears_unverified_placeholder_and_allows_resend(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    request = await harness.service.send_contact_request(
        from_user_id=alice.id, to_user_id=bob.id, channel="qr"
    )
    declined = await harness.service.decline_contact_request(
        request_id=request.id, acting_user_id=bob.id
    )
    assert declined.status == "declined"
    assert await harness.contacts.get_by_pair(alice.id, bob.id) is None
    assert await harness.contacts.get_by_pair(bob.id, alice.id) is None

    # A fresh request can now be sent — the stale pending-request check
    # only matches status == 'pending'.
    second = await harness.service.send_contact_request(
        from_user_id=alice.id, to_user_id=bob.id, channel="qr"
    )
    assert second.status == "pending"


async def test_list_incoming_and_outgoing_requests(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    request = await harness.service.send_contact_request(
        from_user_id=alice.id, to_user_id=bob.id, channel="qr"
    )

    outgoing = await harness.service.list_outgoing_requests(alice.id)
    assert [r.request.id for r in outgoing] == [request.id]
    assert outgoing[0].to_user_display_name == bob.display_name

    incoming = await harness.service.list_incoming_requests(bob.id)
    assert [r.request.id for r in incoming] == [request.id]
    assert incoming[0].from_user_display_name == alice.display_name

    assert await harness.service.list_incoming_requests(alice.id) == []


# --- §23: trust tiers & safety-number verification ---


async def test_verify_safety_number_promotes_to_trusted_one_sided(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    request = await harness.service.send_contact_request(
        from_user_id=alice.id, to_user_id=bob.id, channel="qr"
    )
    await harness.service.accept_contact_request(request_id=request.id, acting_user_id=bob.id)

    result = await harness.service.verify_safety_number(user_id=alice.id, contact_user_id=bob.id)
    assert result.contact.tier == "trusted"
    assert result.contact.safety_number_verified_at is not None
    assert result.display_name == bob.display_name

    # Bob hasn't verified his own side yet — his Contact row is untouched.
    bob_view = await harness.contacts.get_by_pair(bob.id, alice.id)
    assert bob_view is not None and bob_view.tier == "verified"

    circle = await harness.service.list_circle(alice.id)
    assert [c.contact.contact_user_id for c in circle] == [bob.id]


async def test_cannot_verify_safety_number_before_verified_tier(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await harness.service.send_contact_request(
        from_user_id=alice.id, to_user_id=bob.id, channel="qr"
    )

    with pytest.raises(CircleError, match="'verified' tier"):
        await harness.service.verify_safety_number(user_id=alice.id, contact_user_id=bob.id)


# --- §24: block & report ---


async def test_block_hides_blocker_and_drops_pending_request(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    request = await harness.service.send_contact_request(
        from_user_id=bob.id, to_user_id=alice.id, channel="phone_match"
    )

    await harness.service.block_user(user_id=alice.id, target_user_id=bob.id, reason="spam")

    # Bob's view of alice disappears — he's blocked without notification.
    assert await harness.contacts.get_by_pair(bob.id, alice.id) is None
    refreshed = await harness.contact_requests.get(request.id)
    assert refreshed is not None and refreshed.status == "declined"

    await harness.service.unblock_user(user_id=alice.id, target_user_id=bob.id)
    # A fresh request can now be sent since the old one is no longer pending.
    new_request = await harness.service.send_contact_request(
        from_user_id=bob.id, to_user_id=alice.id, channel="phone_match"
    )
    assert new_request.status == "pending"


async def test_cannot_send_request_to_a_blocked_user(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    await harness.service.block_user(user_id=alice.id, target_user_id=bob.id)

    with pytest.raises(CircleError, match="blocked"):
        await harness.service.send_contact_request(
            from_user_id=bob.id, to_user_id=alice.id, channel="qr"
        )


async def test_report_user(harness: Harness) -> None:
    alice = await _make_user(harness)
    bob = await _make_user(harness)
    report = await harness.service.report_user(
        reporter_user_id=alice.id, reported_user_id=bob.id, reason="Harassment"
    )
    assert report.status == "open"
    assert report.reported_user_id == bob.id


# --- §22: invitations ---


async def test_create_invitation(harness: Harness) -> None:
    alice = await _make_user(harness)
    invitation = await harness.service.create_invitation(inviter_user_id=alice.id, channel="sms")
    assert invitation.status == "sent"
    assert len(invitation.invite_code) == 10
    assert invitation.expires_at is not None
