import uuid

from sqlalchemy import func, select, update

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

    async def list_for_user(
        self, owner_user_id: uuid.UUID, *, min_tier: tuple[str, ...] | None = None
    ) -> list[Contact]:
        stmt = self._select().where(Contact.owner_user_id == owner_user_id)
        if min_tier is not None:
            stmt = stmt.where(Contact.tier.in_(min_tier))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_circle_for_user(self, owner_user_id: uuid.UUID) -> list[Contact]:
        """Contacts at the 'trusted' tier — the UI's 'Circle'. See §22-23."""
        return await self.list_for_user(owner_user_id, min_tier=("trusted",))

    async def demote_trusted_contacts_of(self, reidentified_user_id: uuid.UUID) -> None:
        """
        §23: when `reidentified_user_id`'s Signal identity key changes, every
        contact who had trusted them (verified the old safety number) must
        be walked back to 'verified' and re-prompted — never silently
        re-trusted. Bulk UPDATE, not a load-mutate-flush loop, since this
        can fan out to every one of the re-keyed user's trusters.
        """
        await self.session.execute(
            update(Contact)
            .where(
                Contact.contact_user_id == reidentified_user_id,
                Contact.tier == "trusted",
            )
            .values(tier="verified", safety_number_verified_at=None)
        )


class ContactRequestRepository(Repository[ContactRequest]):
    model = ContactRequest

    async def get_pending_between(
        self, from_user_id: uuid.UUID, to_user_id: uuid.UUID
    ) -> ContactRequest | None:
        """Either direction — used to reject a duplicate/crossed request."""
        result = await self.session.execute(
            self._select().where(
                ContactRequest.status == "pending",
                (
                    (ContactRequest.from_user_id == from_user_id)
                    & (ContactRequest.to_user_id == to_user_id)
                )
                | (
                    (ContactRequest.from_user_id == to_user_id)
                    & (ContactRequest.to_user_id == from_user_id)
                ),
            )
        )
        return result.scalar_one_or_none()

    async def list_incoming(self, user_id: uuid.UUID) -> list[ContactRequest]:
        result = await self.session.execute(
            self._select().where(
                ContactRequest.to_user_id == user_id, ContactRequest.status == "pending"
            )
        )
        return list(result.scalars().all())

    async def list_outgoing(self, user_id: uuid.UUID) -> list[ContactRequest]:
        result = await self.session.execute(
            self._select().where(
                ContactRequest.from_user_id == user_id, ContactRequest.status == "pending"
            )
        )
        return list(result.scalars().all())


class InvitationRepository(Repository[Invitation]):
    model = Invitation

    async def get_by_code(self, invite_code: str) -> Invitation | None:
        result = await self.session.execute(
            self._select().where(Invitation.invite_code == invite_code)
        )
        return result.scalar_one_or_none()

    async def count_by_status(self, status: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Invitation).where(Invitation.status == status)
        )
        return result.scalar_one()

    async def top_inviters(self, *, limit: int = 10) -> list[tuple[uuid.UUID, int]]:
        """§32 abuse signal: inviters ranked by invitations sent — the
        admin Invitations screen flags outliers, it doesn't auto-block
        them (rate limiting itself is enforced at request time, §32)."""
        result = await self.session.execute(
            select(Invitation.inviter_user_id, func.count().label("sent_count"))
            .group_by(Invitation.inviter_user_id)
            .order_by(func.count().desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]


class BlockRepository(Repository[Block]):
    model = Block

    async def exists(self, blocker_user_id: uuid.UUID, blocked_user_id: uuid.UUID) -> bool:
        return await self.get_by_pair(blocker_user_id, blocked_user_id) is not None

    async def get_by_pair(
        self, blocker_user_id: uuid.UUID, blocked_user_id: uuid.UUID
    ) -> Block | None:
        result = await self.session.execute(
            self._select().where(
                Block.blocker_user_id == blocker_user_id,
                Block.blocked_user_id == blocked_user_id,
            )
        )
        return result.scalar_one_or_none()


class ReportRepository(Repository[Report]):
    model = Report

    async def list_by_status(self, status: str) -> list[Report]:
        result = await self.session.execute(
            self._select().where(Report.status == status).order_by(Report.created_at.desc())
        )
        return list(result.scalars().all())

    async def count_by_status(self, status: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Report).where(Report.status == status)
        )
        return result.scalar_one()
