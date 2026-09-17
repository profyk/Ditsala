import uuid

from app.models.crypto import IdentityKey, OneTimePrekey, SenderKey, SignedPrekey
from app.repositories.base import Repository


class IdentityKeyRepository(Repository[IdentityKey]):
    model = IdentityKey

    async def get_for_device(self, device_id: uuid.UUID) -> IdentityKey | None:
        result = await self.session.execute(
            self._select().where(IdentityKey.device_id == device_id)
        )
        return result.scalar_one_or_none()

    async def get_most_recent_for_user(self, user_id: uuid.UUID) -> IdentityKey | None:
        """V1 sends to a single device per recipient (docs/adr/0013 —
        multi-device fan-out is a disclosed, not-yet-built gap), so a
        sender needs *a* device to encrypt to: the one whose keys were
        registered most recently."""
        result = await self.session.execute(
            self._select()
            .where(IdentityKey.user_id == user_id)
            .order_by(IdentityKey.created_at.desc())
        )
        return result.scalars().first()


class SignedPrekeyRepository(Repository[SignedPrekey]):
    model = SignedPrekey

    async def get_current_for_device(self, device_id: uuid.UUID) -> SignedPrekey | None:
        """Most recently uploaded, unrotated signed prekey — what a new
        session initiator's X3DH handshake needs (§6)."""
        result = await self.session.execute(
            self._select()
            .where(SignedPrekey.device_id == device_id, SignedPrekey.rotated_at.is_(None))
            .order_by(SignedPrekey.uploaded_at.desc())
        )
        return result.scalars().first()


class OneTimePrekeyRepository(Repository[OneTimePrekey]):
    model = OneTimePrekey

    async def claim_one(self, device_id: uuid.UUID) -> OneTimePrekey | None:
        """One-time prekeys are consumed exactly once during X3DH."""
        result = await self.session.execute(
            self._select().where(
                OneTimePrekey.device_id == device_id,
                OneTimePrekey.consumed_at.is_(None),
            )
        )
        return result.scalars().first()

    async def count_unconsumed(self, device_id: uuid.UUID) -> int:
        result = await self.session.execute(
            self._select().where(
                OneTimePrekey.device_id == device_id, OneTimePrekey.consumed_at.is_(None)
            )
        )
        return len(result.scalars().all())


class SenderKeyRepository(Repository[SenderKey]):
    model = SenderKey

    async def get_for_conversation_device_and_recipient(
        self, conversation_id: uuid.UUID, device_id: uuid.UUID, recipient_device_id: uuid.UUID
    ) -> SenderKey | None:
        result = await self.session.execute(
            self._select().where(
                SenderKey.conversation_id == conversation_id,
                SenderKey.device_id == device_id,
                SenderKey.recipient_device_id == recipient_device_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_conversation_and_recipient(
        self, conversation_id: uuid.UUID, recipient_device_id: uuid.UUID
    ) -> list[SenderKey]:
        """Every other device's Sender Key distribution message addressed
        specifically to this device — never another device's copy, since
        each is individually encrypted per recipient (see the model's
        own docstring)."""
        result = await self.session.execute(
            self._select().where(
                SenderKey.conversation_id == conversation_id,
                SenderKey.recipient_device_id == recipient_device_id,
            )
        )
        return list(result.scalars().all())
