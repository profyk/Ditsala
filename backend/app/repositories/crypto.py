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

    async def list_for_conversation(self, conversation_id: uuid.UUID) -> list[SenderKey]:
        result = await self.session.execute(
            self._select().where(SenderKey.conversation_id == conversation_id)
        )
        return list(result.scalars().all())
