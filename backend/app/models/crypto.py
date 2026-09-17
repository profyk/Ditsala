"""
E2EE key material — metadata only. The backend relays these opaque values
per the Signal Protocol but never has the private-key half of anything
here; see docs/DITSALA_MASTER_SPEC.md §6, §4.3.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IdentityKey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "identity_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), unique=True
    )
    # P0 — public key material, but classified P0 because a changed value
    # here is exactly the signal that gates the §23 safety-number warning.
    public_identity_key: Mapped[bytes] = mapped_column(LargeBinary)
    registration_id: Mapped[int] = mapped_column(Integer)


class SignedPrekey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "signed_prekeys"

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    key_id: Mapped[int] = mapped_column(Integer)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    signature: Mapped[bytes] = mapped_column(LargeBinary)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OneTimePrekey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "one_time_prekeys"

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    key_id: Mapped[int] = mapped_column(Integer)
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SenderKey(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Group messaging (Sender Keys) — docs/DITSALA_MASTER_SPEC.md §6. A
    real E2EE Sender Key distribution message is individually encrypted
    per recipient device (it's sealed via that recipient's own prekey,
    same as a 1:1 message) — so `distribution_message_ref` differs per
    (conversation, sending device, recipient device), never one shared
    blob for a whole conversation (see docs/adr/0013)."""

    __tablename__ = "sender_keys"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "device_id",
            "recipient_device_id",
            name="uq_sender_keys_conversation_device_recipient",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    recipient_device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    distribution_message_ref: Mapped[bytes] = mapped_column(LargeBinary)
