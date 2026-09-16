"""
KYC Review Queue — docs/DITSALA_MASTER_SPEC.md §28.2. Split out from
`AdminService` deliberately: this is the one admin surface that touches
P1 data (§5), and §28.2 requires "a documented, logged 'reason for
access' required before any P1 detail is rendered" — `get_detail` writes
that audit entry *before* returning anything, not as a side effect
someone could accidentally skip.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.models.accounts import KycDocument, KycFaceVerification, User
from app.models.admin import AuditLog
from app.repositories.admin import AuditLogRepository
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.users import UserRepository


class KycReviewError(Exception):
    """Raised for KYC-review preconditions a caller should turn into a 4xx, not a 500."""


@dataclass(frozen=True)
class KycReviewDetail:
    user: User
    documents: list[KycDocument]
    face_verifications: list[KycFaceVerification]


class KycReviewService:
    def __init__(
        self,
        *,
        users: UserRepository,
        kyc_documents: KycDocumentRepository,
        kyc_face_verifications: KycFaceVerificationRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._users = users
        self._kyc_documents = kyc_documents
        self._kyc_face_verifications = kyc_face_verifications
        self._audit_log = audit_log

    async def list_queue(self) -> list[User]:
        return await self._users.list_by_state("manual_review")

    async def get_detail(
        self, *, admin_id: uuid.UUID, user_id: uuid.UUID, reason: str
    ) -> KycReviewDetail:
        user = await self._users.get(user_id)
        if user is None:
            raise KycReviewError("No such user.")
        if not reason.strip():
            raise KycReviewError("A reason for access is required before viewing KYC detail.")

        # Logged before returning any P1 data — never as an afterthought.
        await self._log(admin_id, "admin.kyc.viewed", user_id=user_id, reason=reason)

        documents = await self._kyc_documents.list_for_user(user_id)
        faces = await self._kyc_face_verifications.list_for_user(user_id)
        return KycReviewDetail(user=user, documents=documents, face_verifications=faces)

    async def _require_manual_review(self, user_id: uuid.UUID) -> User:
        user = await self._users.get(user_id)
        if user is None:
            raise KycReviewError("No such user.")
        if user.account_state != "manual_review":
            raise KycReviewError(
                f"Cannot review a user in state {user.account_state!r}, expected manual_review."
            )
        return user

    async def approve(self, *, admin_id: uuid.UUID, user_id: uuid.UUID, reason: str) -> User:
        user = await self._require_manual_review(user_id)
        user.account_state = "active"
        await self._log(admin_id, "admin.kyc.approved", user_id=user_id, reason=reason)
        return user

    async def reject(self, *, admin_id: uuid.UUID, user_id: uuid.UUID, reason: str) -> User:
        user = await self._require_manual_review(user_id)
        user.account_state = "banned"
        await self._log(admin_id, "admin.kyc.rejected", user_id=user_id, reason=reason)
        return user

    async def request_recapture(
        self, *, admin_id: uuid.UUID, user_id: uuid.UUID, reason: str
    ) -> User:
        user = await self._require_manual_review(user_id)
        user.account_state = "pending_kyc_document"
        await self._log(admin_id, "admin.kyc.recapture_requested", user_id=user_id, reason=reason)
        return user

    async def _log(
        self, admin_id: uuid.UUID, action: str, *, user_id: uuid.UUID, reason: str
    ) -> None:
        await self._audit_log.add(
            AuditLog(
                created_at=datetime.now(UTC),
                actor_type="admin",
                actor_id=admin_id,
                action=action,
                target_type="user",
                target_id=user_id,
                metadata_json={"reason": reason},
            )
        )
