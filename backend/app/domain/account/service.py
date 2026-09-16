"""
Self-service account lifecycle — docs/DITSALA_MASTER_SPEC.md §34.2's
deletion cascade, the self-service half. `process_scheduled_deletions`
is the sweep a scheduler calls (see `app/tasks/`); the admin-initiated
half (banning a user, which also starts the same clock with no grace) is
in `domain/admin/service.py`/`domain/admin/kyc_review_service.py`.

Hard-deleting a `User` row is deliberately just that — one DELETE. Every
`users.id` foreign key in this schema is `ondelete="CASCADE"` (see
docs/adr/0009-account-deletion-cascade.md), so the cascade the spec
requires is enforced by Postgres itself, not walked table-by-table here.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.models.accounts import User
from app.models.admin import AuditLog
from app.repositories.admin import AuditLogRepository
from app.repositories.users import UserRepository

DEACTIVATION_GRACE_DAYS = 30


class AccountLifecycleError(Exception):
    """Raised for account-lifecycle preconditions a caller should turn into a 4xx, not a 500."""


class AccountLifecycleService:
    def __init__(self, *, users: UserRepository, audit_log: AuditLogRepository) -> None:
        self._users = users
        self._audit_log = audit_log

    # --- self-service (§14, §34.2) ---

    async def request_deactivation(self, user: User) -> User:
        if user.account_state not in ("active", "manual_review"):
            raise AccountLifecycleError(
                f"Cannot deactivate an account in state {user.account_state!r}."
            )
        now = datetime.now(UTC)
        user.account_state = "deactivated"
        user.deactivated_at = now
        user.hard_delete_after = now + timedelta(days=DEACTIVATION_GRACE_DAYS)
        await self._log(user.id, "account.deactivation_requested")
        return user

    async def cancel_deactivation(self, user: User) -> User:
        """Reversible within the grace window — §34.2's whole point of a
        30-day window before the delete is irreversible."""
        if user.account_state != "deactivated":
            raise AccountLifecycleError("Account is not deactivated.")
        if user.hard_delete_after is not None and user.hard_delete_after <= datetime.now(UTC):
            raise AccountLifecycleError("The grace window has already elapsed.")
        user.account_state = "active"
        user.deactivated_at = None
        user.hard_delete_after = None
        await self._log(user.id, "account.deactivation_cancelled")
        return user

    # --- §34.2 scheduled sweep ---

    async def process_scheduled_deletions(self) -> int:
        """
        Hard-deletes every account whose grace window has elapsed —
        called on an interval by the scheduler (`app/tasks/`), not
        per-request. The audit entry is written *before* the delete so
        it survives the cascade (§34.2: "audit_log entries recording
        that a deletion occurred are themselves P3 and outlive the
        deletion").
        """
        due = await self._users.list_pending_hard_delete(now=datetime.now(UTC))
        for user in due:
            # `audit_log` has no FK to `users` (§30 — it must outlive the
            # account it references), so logging before deleting is a
            # matter of intent-ordering, not a cascade-survival necessity.
            await self._log(
                user.id, "account.hard_deleted", metadata={"account_state": user.account_state}
            )
            await self._users.delete(user)
        return len(due)

    async def _log(
        self, user_id: uuid.UUID, action: str, *, metadata: dict[str, str] | None = None
    ) -> None:
        await self._audit_log.add(
            AuditLog(
                created_at=datetime.now(UTC),
                actor_type="user",
                actor_id=user_id,
                action=action,
                target_type="user",
                target_id=user_id,
                metadata_json=metadata,
            )
        )
