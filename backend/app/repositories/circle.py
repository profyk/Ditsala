import uuid

from app.models.circle import Block, Contact, ContactRequest, Invitation, Report
from app.repositories.base import Repository


class ContactRepository(Repository[Contact]):
    model = Contact

    async def get_by_pair(
        self, owner_user_id: uuid.UUID, contact_user_id: uuid.UUID
    ) -> Contact | None:
        result = await self.session.execute(
            self._select().where(
                Contact.owner_user_id == owner_user_id,
                Contact.contact_user_id == contact_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_circle_for_user(self, owner_user_id: uuid.UUID) -> list[Contact]:
        """Contacts at the 'trusted' tier — the UI's 'Circle'. See §22-23."""
        result = await self.session.execute(
            self._select().where(
                Contact.owner_user_id == owner_user_id, Contact.tier == "trusted"
            )
        )
        return list(result.scalars().all())


class ContactRequestRepository(Repository[ContactRequest]):
    model = ContactRequest


class InvitationRepository(Repository[Invitation]):
    model = Invitation

    async def get_by_code(self, invite_code: str) -> Invitation | None:
        result = await self.session.execute(
            self._select().where(Invitation.invite_code == invite_code)
        )
        return result.scalar_one_or_none()


class BlockRepository(Repository[Block]):
    model = Block

    async def exists(self, blocker_user_id: uuid.UUID, blocked_user_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            self._select().where(
                Block.blocker_user_id == blocker_user_id,
                Block.blocked_user_id == blocked_user_id,
            )
        )
        return result.scalar_one_or_none() is not None


class ReportRepository(Repository[Report]):
    model = Report
