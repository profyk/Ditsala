"""
Circle: contact requests, trust tiers, invitations, block & report —
docs/DITSALA_MASTER_SPEC.md §22-24. Framework-agnostic, per §3.3.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.security import generate_invite_code
from app.domain.ratelimit.interfaces import RateLimiter
from app.models.accounts import User
from app.models.circle import Block, Contact, ContactRequest, Invitation, Report
from app.repositories.admin import SystemConfigRepository
from app.repositories.circle import (
    BlockRepository,
    ContactRepository,
    ContactRequestRepository,
    InvitationRepository,
    ReportRepository,
)
from app.repositories.users import UserRepository

INVITE_CODE_TTL_DAYS = 7

# §32: per-account limits — no per-IP layer here, since both actions are
# already authenticated (the actor's identity is the account, not the IP
# they happen to be behind). See docs/adr/0010-rate-limiting-key-choice.md.
CONTACT_REQUEST_LIMIT = 30
CONTACT_REQUEST_WINDOW_SECONDS = 24 * 3600
INVITATION_LIMIT = 10
INVITATION_WINDOW_SECONDS = 24 * 3600

# Phone-contact matching (§22 `phone_match`) reveals, for any phone number
# a caller submits, whether it's a registered DITSALA account — the same
# enumeration exposure every phone-based contact-discovery feature has
# (WhatsApp/Telegram included; this isn't a DITSALA-specific weakness).
# A tighter per-call limit than CONTACT_REQUEST_LIMIT since this is
# normally a one-time-per-device-contacts-sync action, not something a
# legitimate user does repeatedly — see docs/SECURITY_GAPS.md.
CONTACT_MATCH_LIMIT = 5
CONTACT_MATCH_WINDOW_SECONDS = 3600
CONTACT_MATCH_MAX_PHONES = 1000


class CircleError(Exception):
    """Raised for Circle preconditions a caller should turn into a 4xx, not a 500."""


@dataclass(frozen=True)
class ContactWithProfile:
    """A Contact row plus the minimal profile the UI needs to render it —
    the repository layer only knows the raw relationship, not identity."""

    contact: Contact
    display_name: str


@dataclass(frozen=True)
class ContactRequestWithProfiles:
    request: ContactRequest
    from_user_display_name: str
    to_user_display_name: str


class CircleService:
    def __init__(
        self,
        *,
        contacts: ContactRepository,
        contact_requests: ContactRequestRepository,
        invitations: InvitationRepository,
        blocks: BlockRepository,
        reports: ReportRepository,
        users: UserRepository,
        system_config: SystemConfigRepository,
        rate_limiter: RateLimiter,
    ) -> None:
        self._contacts = contacts
        self._contact_requests = contact_requests
        self._invitations = invitations
        self._blocks = blocks
        self._reports = reports
        self._users = users
        self._system_config = system_config
        self._rate_limiter = rate_limiter

    # --- §22: contact requests ---

    async def match_contacts(
        self, *, requesting_user_id: uuid.UUID, phones: list[str]
    ) -> list[User]:
        """The `phone_match` channel's lookup half — `send_contact_request`
        already handles the send. Rate-limited per caller (not per phone
        submitted — see CONTACT_MATCH_LIMIT's comment) and capped in size
        so one call can't be used to sweep a large slice of the phone
        number space. The requester's own number is excluded so their own
        entry in their own device contacts never comes back as a match."""
        await self._rate_limiter.hit(
            f"circle:contact_match:{requesting_user_id}",
            limit=CONTACT_MATCH_LIMIT,
            window_seconds=CONTACT_MATCH_WINDOW_SECONDS,
        )
        if len(phones) > CONTACT_MATCH_MAX_PHONES:
            raise CircleError(f"Cannot match more than {CONTACT_MATCH_MAX_PHONES} numbers at once.")
        deduped = {p for p in phones if p}
        matches = await self._users.list_by_phones(list(deduped))
        return [u for u in matches if u.id != requesting_user_id]

    async def send_contact_request(
        self, *, from_user_id: uuid.UUID, to_user_id: uuid.UUID, channel: str
    ) -> ContactRequest:
        await self._rate_limiter.hit(
            f"circle:contact_request:{from_user_id}",
            limit=CONTACT_REQUEST_LIMIT,
            window_seconds=CONTACT_REQUEST_WINDOW_SECONDS,
        )
        if from_user_id == to_user_id:
            raise CircleError("Cannot send a contact request to yourself.")
        if await self._blocks.exists(to_user_id, from_user_id) or await self._blocks.exists(
            from_user_id, to_user_id
        ):
            raise CircleError("Cannot send a contact request to a blocked user.")
        if await self._users.get(to_user_id) is None:
            raise CircleError("No such user.")

        existing_contact = await self._contacts.get_by_pair(from_user_id, to_user_id)
        if existing_contact is not None and existing_contact.tier in ("verified", "trusted"):
            raise CircleError("Already connected to this contact.")
        if await self._contact_requests.get_pending_between(from_user_id, to_user_id) is not None:
            raise CircleError("A contact request is already pending between these users.")

        request = await self._contact_requests.add(
            ContactRequest(from_user_id=from_user_id, to_user_id=to_user_id, channel=channel)
        )
        # §22: unverified tier lets both sides see the pending relationship
        # but not yet message — see MessagingService.start_direct_conversation.
        await self._upsert_tier(from_user_id, to_user_id, "unverified")
        await self._upsert_tier(to_user_id, from_user_id, "unverified")
        return request

    async def accept_contact_request(
        self, *, request_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> ContactRequest:
        request = await self._contact_requests.get(request_id)
        if request is None or request.to_user_id != acting_user_id:
            raise CircleError("No such contact request.")
        if request.status != "pending":
            raise CircleError(f"Cannot accept a request in status {request.status!r}.")

        request.status = "accepted"
        await self._upsert_tier(request.from_user_id, request.to_user_id, "verified")
        await self._upsert_tier(request.to_user_id, request.from_user_id, "verified")
        return request

    async def decline_contact_request(
        self, *, request_id: uuid.UUID, acting_user_id: uuid.UUID
    ) -> ContactRequest:
        request = await self._contact_requests.get(request_id)
        if request is None or request.to_user_id != acting_user_id:
            raise CircleError("No such contact request.")
        if request.status != "pending":
            raise CircleError(f"Cannot decline a request in status {request.status!r}.")

        request.status = "declined"
        # No relationship formed — clear the placeholder 'unverified' rows
        # so a fresh request later isn't blocked by a stale get_by_pair hit.
        for owner, other in (
            (request.from_user_id, request.to_user_id),
            (request.to_user_id, request.from_user_id),
        ):
            contact = await self._contacts.get_by_pair(owner, other)
            if contact is not None and contact.tier == "unverified":
                await self._contacts.delete(contact)
        return request

    async def list_incoming_requests(
        self, user_id: uuid.UUID
    ) -> list[ContactRequestWithProfiles]:
        requests = await self._contact_requests.list_incoming(user_id)
        return await self._with_request_profiles(requests)

    async def list_outgoing_requests(
        self, user_id: uuid.UUID
    ) -> list[ContactRequestWithProfiles]:
        requests = await self._contact_requests.list_outgoing(user_id)
        return await self._with_request_profiles(requests)

    async def _with_request_profiles(
        self, requests: list[ContactRequest]
    ) -> list[ContactRequestWithProfiles]:
        enriched = []
        for req in requests:
            from_user = await self._users.get(req.from_user_id)
            to_user = await self._users.get(req.to_user_id)
            enriched.append(
                ContactRequestWithProfiles(
                    request=req,
                    from_user_display_name=from_user.display_name
                    if from_user is not None
                    else "Unknown user",
                    to_user_display_name=to_user.display_name
                    if to_user is not None
                    else "Unknown user",
                )
            )
        return enriched

    async def _upsert_tier(
        self, owner_user_id: uuid.UUID, contact_user_id: uuid.UUID, tier: str
    ) -> Contact:
        contact = await self._contacts.get_by_pair(owner_user_id, contact_user_id)
        if contact is None:
            return await self._contacts.add(
                Contact(owner_user_id=owner_user_id, contact_user_id=contact_user_id, tier=tier)
            )
        contact.tier = tier
        return contact

    # --- §23: trust tiers & safety-number verification ---

    async def list_contacts(self, user_id: uuid.UUID) -> list[ContactWithProfile]:
        contacts = await self._contacts.list_for_user(user_id)
        return await self._with_profiles(contacts)

    async def list_circle(self, user_id: uuid.UUID) -> list[ContactWithProfile]:
        """Trusted-tier only — what the app surfaces as 'Circle' (§22-23)."""
        contacts = await self._contacts.list_circle_for_user(user_id)
        return await self._with_profiles(contacts)

    async def _with_profiles(self, contacts: list[Contact]) -> list[ContactWithProfile]:
        enriched = []
        for contact in contacts:
            other = await self._users.get(contact.contact_user_id)
            enriched.append(
                ContactWithProfile(
                    contact=contact,
                    display_name=other.display_name if other is not None else "Unknown user",
                )
            )
        return enriched

    async def verify_safety_number(
        self, *, user_id: uuid.UUID, contact_user_id: uuid.UUID
    ) -> ContactWithProfile:
        """
        One side's own confirmation that they matched the safety number
        with `contact_user_id` (in person, QR scan, or secondary channel —
        §23). Each party verifies independently on their own device; the
        other party's Contact row is untouched until they do the same.
        """
        contact = await self._contacts.get_by_pair(user_id, contact_user_id)
        if contact is None or contact.tier not in ("verified", "trusted"):
            raise CircleError("Contact must be at 'verified' tier before safety-number check.")
        contact.tier = "trusted"
        contact.safety_number_verified_at = datetime.now(UTC)
        return (await self._with_profiles([contact]))[0]

    # --- §24: block & report ---

    async def block_user(
        self, *, user_id: uuid.UUID, target_user_id: uuid.UUID, reason: str | None = None
    ) -> Block:
        existing = await self._blocks.get_by_pair(user_id, target_user_id)
        if existing is None:
            existing = await self._blocks.add(
                Block(blocker_user_id=user_id, blocked_user_id=target_user_id, reason=reason)
            )
        # §24: hide the blocker from the blocked user's list, and silently
        # drop any pending request between them — no notification either way.
        blocked_view = await self._contacts.get_by_pair(target_user_id, user_id)
        if blocked_view is not None:
            await self._contacts.delete(blocked_view)
        pending = await self._contact_requests.get_pending_between(user_id, target_user_id)
        if pending is not None:
            pending.status = "declined"
        return existing

    async def unblock_user(self, *, user_id: uuid.UUID, target_user_id: uuid.UUID) -> None:
        existing = await self._blocks.get_by_pair(user_id, target_user_id)
        if existing is not None:
            await self._blocks.delete(existing)

    async def report_user(
        self,
        *,
        reporter_user_id: uuid.UUID,
        reported_user_id: uuid.UUID,
        reason: str,
        context_ref: str | None = None,
    ) -> Report:
        return await self._reports.add(
            Report(
                reporter_user_id=reporter_user_id,
                reported_user_id=reported_user_id,
                reason=reason,
                context_ref=context_ref,
            )
        )

    # --- §22: invitations ---

    async def create_invitation(self, *, inviter_user_id: uuid.UUID, channel: str) -> Invitation:
        await self._rate_limiter.hit(
            f"circle:invitation:{inviter_user_id}",
            limit=INVITATION_LIMIT,
            window_seconds=INVITATION_WINDOW_SECONDS,
        )
        return await self._invitations.add(
            Invitation(
                inviter_user_id=inviter_user_id,
                invite_code=generate_invite_code(),
                channel=channel,
                expires_at=datetime.now(UTC) + timedelta(days=INVITE_CODE_TTL_DAYS),
            )
        )
