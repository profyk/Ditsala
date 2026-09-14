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


class OneTimePrekeyRepository(Repository[OneTimePrekey]):
    model = OneTimePrekey

    async def claim_one(self, device_id: uuid.UUID) -> OneTimePrekey | None:
        """
        One-time prekeys are consumed exactly once during X3DH. Full
        claim-under-lock semantics land with the Phase 4 messaging domain
        logic; this is the persistence primitive it will build on.
        """
        result = await self.session.execute(
            self._select().where(
                OneTimePrekey.device_id == device_id,
                OneTimePrekey.consumed_at.is_(None),
            )
        )
        return result.scalars().first()


class SenderKeyRepository(Repository[SenderKey]):
    model = SenderKey
