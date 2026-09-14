"""
Integration tests for the repository layer against a real Postgres (see
docs/DITSALA_MASTER_SPEC.md: backend tests use a real Postgres, not
SQLite/mocks). Exercises the async SQLAlchemy engine end-to-end, not just
that the models import cleanly.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.accounts import User
from app.models.circle import Contact
from app.models.messaging import Conversation, ConversationMember, Message
from app.repositories.circle import ContactRepository
from app.repositories.conversations import ConversationMemberRepository, ConversationRepository
from app.repositories.messages import MessageRepository
from app.repositories.users import UserRepository


@pytest.fixture
async def session():
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


def _unique_user(display_name: str = "Test User") -> User:
    return User(
        email=f"{uuid.uuid4()}@test.local",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name=display_name,
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
    )


async def test_user_repository_roundtrip(session: AsyncSession) -> None:
    repo = UserRepository(session)
    user = await repo.add(_unique_user("Alice"))

    fetched = await repo.get(user.id)
    assert fetched is not None
    assert fetched.email == user.email
    assert fetched.account_state == "pending_email"  # server_default, not app-set

    by_email = await repo.get_by_email(user.email)
    assert by_email is not None
    assert by_email.id == user.id


async def test_user_repository_get_by_phone(session: AsyncSession) -> None:
    repo = UserRepository(session)
    user = await repo.add(_unique_user("Bob"))

    by_phone = await repo.get_by_phone(user.phone)
    assert by_phone is not None
    assert by_phone.id == user.id


async def test_contact_repository_circle_filtering(session: AsyncSession) -> None:
    users = UserRepository(session)
    contacts = ContactRepository(session)

    owner = await users.add(_unique_user("Owner"))
    circle_member = await users.add(_unique_user("Circle Member"))
    unverified = await users.add(_unique_user("Unverified"))

    await contacts.add(
        Contact(owner_user_id=owner.id, contact_user_id=circle_member.id, tier="trusted")
    )
    await contacts.add(
        Contact(owner_user_id=owner.id, contact_user_id=unverified.id, tier="unverified")
    )

    circle = await contacts.list_circle_for_user(owner.id)
    assert {c.contact_user_id for c in circle} == {circle_member.id}

    found = await contacts.get_by_pair(owner.id, circle_member.id)
    assert found is not None
    assert found.tier == "trusted"


async def test_message_repository_idempotency_and_listing(session: AsyncSession) -> None:
    users = UserRepository(session)
    conversations = ConversationRepository(session)
    members = ConversationMemberRepository(session)
    messages = MessageRepository(session)

    alice = await users.add(_unique_user("Alice"))
    bob = await users.add(_unique_user("Bob"))
    conversation = await conversations.add(Conversation(type="direct"))
    await members.add(
        ConversationMember(
            conversation_id=conversation.id, user_id=alice.id, joined_at=datetime.now(UTC)
        )
    )
    await members.add(
        ConversationMember(
            conversation_id=conversation.id, user_id=bob.id, joined_at=datetime.now(UTC)
        )
    )

    client_message_id = uuid.uuid4().hex
    await messages.add(
        Message(
            conversation_id=conversation.id,
            ciphertext=b"opaque",
            content_type="text",
            client_message_id=client_message_id,
        )
    )

    listed = await messages.list_for_conversation(conversation.id)
    assert len(listed) == 1

    by_client_id = await messages.get_by_client_message_id(client_message_id)
    assert by_client_id is not None
    assert by_client_id.conversation_id == conversation.id

    member_rows = await members.list_for_conversation(conversation.id)
    assert {m.user_id for m in member_rows} == {alice.id, bob.id}
