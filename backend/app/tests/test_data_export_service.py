"""
Unit tests for §34.4's data-export bundle (`domain/compliance/export.py`)
— real Postgres, a stub `StorageProvider` (no local S3/MinIO in this
environment, see docs/SECURITY_GAPS.md).
"""

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.compliance.export import DataExportService
from app.domain.messaging.interfaces import StorageProvider
from app.models.accounts import User
from app.models.circle import Contact
from app.models.devices import Device
from app.models.location import LocationPing, LocationShare
from app.models.messaging import Conversation, MediaObject, Message
from app.repositories.circle import ContactRepository
from app.repositories.conversations import ConversationRepository
from app.repositories.devices import DeviceRepository
from app.repositories.location import LocationPingRepository, LocationShareRepository
from app.repositories.messages import MediaObjectRepository, MessageRepository
from app.repositories.users import UserRepository


class StubStorageProvider(StorageProvider):
    def __init__(self) -> None:
        self.puts: dict[str, tuple[bytes, str]] = {}

    async def create_upload_url(self, *, key: str, content_type: str) -> str:
        return f"https://stub-upload.test/{key}"

    async def create_download_url(self, *, key: str) -> str:
        return f"https://stub-download.test/{key}"

    async def put_object(self, *, key: str, data: bytes, content_type: str) -> None:
        self.puts[key] = (data, content_type)

    async def delete_object(self, *, key: str) -> None:
        self.puts.pop(key, None)


@dataclass
class Harness:
    export: DataExportService
    storage: StubStorageProvider
    users: UserRepository
    devices: DeviceRepository
    contacts: ContactRepository
    conversations: ConversationRepository
    messages: MessageRepository
    media_objects: MediaObjectRepository
    location_shares: LocationShareRepository
    location_pings: LocationPingRepository


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
    storage = StubStorageProvider()
    return Harness(
        export=DataExportService(session=session, storage=storage),
        storage=storage,
        users=UserRepository(session),
        devices=DeviceRepository(session),
        contacts=ContactRepository(session),
        conversations=ConversationRepository(session),
        messages=MessageRepository(session),
        media_objects=MediaObjectRepository(session),
        location_shares=LocationShareRepository(session),
        location_pings=LocationPingRepository(session),
    )


async def _make_user(harness: Harness, **overrides: object) -> User:
    defaults: dict[str, object] = dict(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="Export Test User",
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
        account_state="active",
        ditsala_code_hash="super-secret-code-hash",
    )
    defaults.update(overrides)
    return await harness.users.add(User(**defaults))


async def _bundle(harness: Harness, user: User) -> dict[str, Any]:
    key = await harness.export.generate_export(user)
    data, content_type = harness.storage.puts[key]
    assert content_type == "application/json"
    bundle: dict[str, Any] = json.loads(data)
    return bundle


async def test_export_includes_own_user_row_but_excludes_p0_secret(harness: Harness) -> None:
    user = await _make_user(harness)

    bundle = await _bundle(harness, user)

    [user_row] = bundle["tables"]["users"]
    assert user_row["display_name"] == "Export Test User"
    assert "ditsala_code_hash" not in user_row
    # P1 (KYC-adjacent, already a hash not raw biometric data) passes through.
    assert user_row["national_id_hash"] == user.national_id_hash
    assert bundle["user_id"] == str(user.id)


async def test_export_picks_up_a_table_via_generic_one_hop_scan(harness: Harness) -> None:
    user = await _make_user(harness)
    now = datetime.now(UTC)
    await harness.devices.add(
        Device(
            user_id=user.id,
            device_name="Export Test Phone",
            platform="ios",
            first_seen_at=now,
            last_seen_at=now,
        )
    )

    bundle = await _bundle(harness, user)

    [device_row] = bundle["tables"]["devices"]
    assert device_row["device_name"] == "Export Test Phone"


async def test_export_matches_either_fk_column_without_duplicating_rows(harness: Harness) -> None:
    owner = await _make_user(harness)
    other = await _make_user(harness)
    await harness.contacts.add(
        Contact(owner_user_id=owner.id, contact_user_id=other.id, tier="verified")
    )

    owner_bundle = await _bundle(harness, owner)
    other_bundle = await _bundle(harness, other)

    assert len(owner_bundle["tables"]["contacts"]) == 1
    assert len(other_bundle["tables"]["contacts"]) == 1


async def test_export_includes_own_messages_via_device_join_and_redacts_ciphertext(
    harness: Harness,
) -> None:
    user = await _make_user(harness)
    now = datetime.now(UTC)
    device = await harness.devices.add(
        Device(
            user_id=user.id,
            device_name="Sender Device",
            platform="android",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    conversation = await harness.conversations.add(Conversation(type="direct", created_by=user.id))
    await harness.messages.add(
        Message(
            conversation_id=conversation.id,
            sender_device_id=device.id,
            ciphertext=b"top-secret-plaintext-would-never-be-here",
            content_type="text",
            client_message_id=str(uuid.uuid4()),
        )
    )

    bundle = await _bundle(harness, user)

    [message_row] = bundle["tables"]["messages"]
    assert message_row["content_type"] == "text"
    assert "top-secret" not in message_row["ciphertext"]
    assert "not included in export" in message_row["ciphertext"]


async def test_export_includes_media_via_message_join_and_redacts_s3_key(
    harness: Harness,
) -> None:
    user = await _make_user(harness)
    now = datetime.now(UTC)
    device = await harness.devices.add(
        Device(
            user_id=user.id,
            device_name="Sender Device",
            platform="android",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    conversation = await harness.conversations.add(Conversation(type="direct", created_by=user.id))
    message = await harness.messages.add(
        Message(
            conversation_id=conversation.id,
            sender_device_id=device.id,
            ciphertext=b"ciphertext-not-checked-here",
            content_type="media",
            client_message_id=str(uuid.uuid4()),
        )
    )
    await harness.media_objects.add(
        MediaObject(
            message_id=message.id,
            s3_key="private/bucket/path/should-never-leak.enc",
            encrypted_size_bytes=1024,
            content_hash="sha256:deadbeef",
        )
    )

    bundle = await _bundle(harness, user)

    [media_row] = bundle["tables"]["media_objects"]
    assert media_row["encrypted_size_bytes"] == 1024
    assert "should-never-leak" not in media_row["s3_key"]
    assert "not included in export" in media_row["s3_key"]


async def test_export_includes_own_shared_location_pings_but_not_a_recipients_view(
    harness: Harness,
) -> None:
    sharer = await _make_user(harness)
    recipient = await _make_user(harness)
    now = datetime.now(UTC)
    share = await harness.location_shares.add(
        LocationShare(
            sharer_user_id=sharer.id,
            recipient_user_id=recipient.id,
            starts_at=now,
            expires_at=now,
        )
    )
    await harness.location_pings.add(
        LocationPing(
            location_share_id=share.id, lat=1.23, lng=4.56, accuracy_m=5.0, recorded_at=now
        )
    )

    sharer_bundle = await _bundle(harness, sharer)
    recipient_bundle = await _bundle(harness, recipient)

    [ping_row] = sharer_bundle["tables"]["location_pings"]
    assert "not included in export" in ping_row["lat"]
    assert "location_pings" not in recipient_bundle["tables"]


async def test_export_omits_a_table_with_no_matching_rows(harness: Harness) -> None:
    user = await _make_user(harness)

    bundle = await _bundle(harness, user)

    assert "devices" not in bundle["tables"]
    assert "contacts" not in bundle["tables"]


async def test_create_download_url_delegates_to_storage(harness: Harness) -> None:
    url = await harness.export.create_download_url("data-exports/some-user/some-export.json")
    assert url == "https://stub-download.test/data-exports/some-user/some-export.json"
