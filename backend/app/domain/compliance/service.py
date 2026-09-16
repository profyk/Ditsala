"""
Data subject rights — docs/DITSALA_MASTER_SPEC.md §34.4. Users file
access/correction/deletion requests themselves; admins action them
(§28) within the 30-day response SLA this module computes at filing
time. Deliberately its own service rather than folded into
`AccountLifecycleService` or `domain/admin/service.py`: filing is a
self-service action neither of those otherwise exposes, and a
correction request especially can span several other domain services (a
user asking to correct their `national_id_hash` touches onboarding/KYC,
not just the `users` row) — this service tracks the request against its
SLA and records how it was resolved, it doesn't perform the underlying
fix itself.

**Deletion requests**: marking one `completed` delegates to
`AccountLifecycleService.request_deactivation` — the same 30-day
reversible grace window as self-service deactivation (docs/adr/0009), so
there is exactly one deletion-cascade code path in the system, not two.

**Access requests**: a full data-export bundle (gathering every P0-P3
field for a user across every table into a downloadable file) is not
built here — that is a materially larger, separate feature than request
tracking, and doing it well needs its own design pass (a large dump of a
user's own P0/P1 data has its own handling requirements). This service
tracks the request and lets an admin record how it was actually
fulfilled (`resolution_notes`) — see docs/SECURITY_GAPS.md.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.domain.account.service import AccountLifecycleService
from app.models.accounts import DataSubjectRequest, User
from app.repositories.users import DataSubjectRequestRepository, UserRepository

RESPONSE_SLA_DAYS = 30


class ComplianceError(Exception):
    """Raised for data-subject-request preconditions a caller should turn into a 4xx, not a 500."""


class ComplianceService:
    def __init__(
        self,
        *,
        requests: DataSubjectRequestRepository,
        users: UserRepository,
        account_lifecycle: AccountLifecycleService,
    ) -> None:
        self._requests = requests
        self._users = users
        self._account_lifecycle = account_lifecycle

    # --- filed by the user themselves ---

    async def file_request(
        self, user: User, *, request_type: str, details: str | None
    ) -> DataSubjectRequest:
        if request_type not in ("access", "correction", "deletion"):
            raise ComplianceError(f"Unrecognized request type: {request_type!r}")
        now = datetime.now(UTC)
        return await self._requests.add(
            DataSubjectRequest(
                user_id=user.id,
                request_type=request_type,
                details=details,
                due_at=now + timedelta(days=RESPONSE_SLA_DAYS),
            )
        )

    async def list_for_user(self, user_id: uuid.UUID) -> list[DataSubjectRequest]:
        return await self._requests.list_for_user(user_id)

    # --- §28: admin-actionable ---

    async def list_by_status(self, status: str = "pending") -> list[DataSubjectRequest]:
        return await self._requests.list_by_status(status)

    async def mark_in_progress(
        self, *, admin_id: uuid.UUID, request_id: uuid.UUID
    ) -> DataSubjectRequest:
        request = await self._get_actionable(request_id)
        request.status = "in_progress"
        request.actioned_by_admin_id = admin_id
        return request

    async def complete(
        self, *, admin_id: uuid.UUID, request_id: uuid.UUID, resolution_notes: str
    ) -> DataSubjectRequest:
        request = await self._get_actionable(request_id)
        if request.request_type == "deletion":
            user = await self._users.get(request.user_id)
            if user is None:
                raise ComplianceError("The user this request belongs to no longer exists.")
            await self._account_lifecycle.request_deactivation(user)
        request.status = "completed"
        request.resolved_at = datetime.now(UTC)
        request.resolution_notes = resolution_notes
        request.actioned_by_admin_id = admin_id
        return request

    async def reject(
        self, *, admin_id: uuid.UUID, request_id: uuid.UUID, resolution_notes: str
    ) -> DataSubjectRequest:
        request = await self._get_actionable(request_id)
        request.status = "rejected"
        request.resolved_at = datetime.now(UTC)
        request.resolution_notes = resolution_notes
        request.actioned_by_admin_id = admin_id
        return request

    async def _get_actionable(self, request_id: uuid.UUID) -> DataSubjectRequest:
        request = await self._requests.get(request_id)
        if request is None:
            raise ComplianceError("No such data subject request.")
        if request.status in ("completed", "rejected"):
            raise ComplianceError(f"Request is already {request.status!r}.")
        return request
