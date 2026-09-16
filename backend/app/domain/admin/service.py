"""
Admin panel backend — docs/DITSALA_MASTER_SPEC.md §28: dashboard, users,
reports/moderation, security dashboard, invitations, audit log, system
config. KYC review (§28.2) is deliberately its own service
(`kyc_review_service.py`) since it alone carries the P1-access-logging
requirement (§5) — everything else here is P3 metadata only. Every
mutating action is audit-logged (§30); §28's "hard constraint" (no admin
path can ever produce decrypted message content) needs no enforcement
code here because nothing in this file, or anywhere in the backend, ever
holds message plaintext to begin with (§7.3) — there's nothing to leak.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.models.accounts import User
from app.models.admin import AuditLog, SystemConfig
from app.models.circle import Report
from app.repositories.admin import AuditLogRepository, SystemConfigRepository
from app.repositories.circle import InvitationRepository, ReportRepository
from app.repositories.devices import (
    DeviceRepository,
    LoginAttemptRepository,
    SessionRepository,
)
from app.repositories.users import UserRepository

REPORT_ACTIONS = ("warn", "suspend", "ban")
_REPORT_ACTION_TO_STATE = {"suspend": "suspended", "ban": "banned"}


class AdminError(Exception):
    """Raised for admin-action preconditions a caller should turn into a 4xx, not a 500."""


@dataclass(frozen=True)
class DashboardSummary:
    signups_today: int
    signups_this_week: int
    active_accounts: int
    manual_review_count: int
    open_reports_count: int
    pending_invitations: int


@dataclass(frozen=True)
class SecuritySummary:
    locked_accounts: int
    failed_logins_last_24h: int
    active_sessions: int
    new_devices_last_24h: int


@dataclass(frozen=True)
class InvitationStats:
    sent: int
    redeemed: int
    expired: int
    top_inviters: list[tuple[uuid.UUID, int]]


class AdminService:
    def __init__(
        self,
        *,
        users: UserRepository,
        reports: ReportRepository,
        invitations: InvitationRepository,
        devices: DeviceRepository,
        sessions: SessionRepository,
        login_attempts: LoginAttemptRepository,
        system_config: SystemConfigRepository,
        audit_log: AuditLogRepository,
    ) -> None:
        self._users = users
        self._reports = reports
        self._invitations = invitations
        self._devices = devices
        self._sessions = sessions
        self._login_attempts = login_attempts
        self._system_config = system_config
        self._audit_log = audit_log

    # --- §28.1: dashboard ---

    async def get_dashboard_summary(self) -> DashboardSummary:
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        return DashboardSummary(
            signups_today=await self._users.count_created_since(today_start),
            signups_this_week=await self._users.count_created_since(week_start),
            active_accounts=await self._users.count_by_state("active"),
            manual_review_count=await self._users.count_by_state("manual_review"),
            open_reports_count=await self._reports.count_by_status("open"),
            pending_invitations=await self._invitations.count_by_status("sent"),
        )

    # --- §28.3: users ---

    async def search_users(
        self, *, query: str | None, account_state: str | None, limit: int = 50, offset: int = 0
    ) -> list[User]:
        return await self._users.search(
            query=query, account_state=account_state, limit=limit, offset=offset
        )

    async def get_user(self, user_id: uuid.UUID) -> User:
        user = await self._users.get(user_id)
        if user is None:
            raise AdminError("No such user.")
        return user

    async def get_user_state_history(self, user_id: uuid.UUID) -> list[AuditLog]:
        """Derived from `audit_log`, not a separate history table — every
        `force_account_state`/report action already writes one, so this
        is a filtered read, not new bookkeeping (see 'Locked decisions'
        note in CLAUDE.md re: avoiding unnecessary schema growth)."""
        return await self._audit_log.list_for_target("user", user_id)

    async def force_account_state(
        self, *, admin_id: uuid.UUID, user_id: uuid.UUID, new_state: str, reason: str
    ) -> User:
        user = await self.get_user(user_id)
        previous_state = user.account_state
        user.account_state = new_state
        await self._log(
            admin_id,
            "admin.user.state_changed",
            target_type="user",
            target_id=user_id,
            metadata_json={"from": previous_state, "to": new_state, "reason": reason},
        )
        return user

    # --- §28.4: reports & moderation ---

    async def list_reports(self, *, status: str = "open") -> list[Report]:
        return await self._reports.list_by_status(status)

    async def action_report(
        self,
        *,
        admin_id: uuid.UUID,
        report_id: uuid.UUID,
        action: Literal["warn", "suspend", "ban"],
        reason: str,
    ) -> Report:
        if action not in REPORT_ACTIONS:
            raise AdminError(f"Unrecognized report action: {action!r}")
        report = await self._reports.get(report_id)
        if report is None:
            raise AdminError("No such report.")

        report.status = "actioned"
        new_state = _REPORT_ACTION_TO_STATE.get(action)
        if new_state is not None:
            reported_user = await self._users.get(report.reported_user_id)
            if reported_user is not None:
                reported_user.account_state = new_state
                if new_state == "banned":
                    # §34.2: a ban starts the same deletion clock as
                    # self-service deactivation, but with no grace period
                    # by default (no hold) — see docs/adr/0009.
                    reported_user.hard_delete_after = datetime.now(UTC)
        await self._log(
            admin_id,
            f"admin.report.{action}",
            target_type="report",
            target_id=report_id,
            metadata_json={"reported_user_id": str(report.reported_user_id), "reason": reason},
        )
        return report

    # --- §28.5: security dashboard ---

    async def get_security_summary(self) -> SecuritySummary:
        now = datetime.now(UTC)
        last_24h = now - timedelta(hours=24)
        return SecuritySummary(
            locked_accounts=await self._users.count_locked(now=now),
            failed_logins_last_24h=await self._login_attempts.count_since(
                outcome="failure", since=last_24h
            ),
            active_sessions=await self._sessions.count_active(),
            new_devices_last_24h=await self._devices.count_created_since(last_24h),
        )

    # --- §28.6: invitations ---

    async def get_invite_only_mode(self) -> bool:
        config = await self._system_config.get_by_key("invite_only_mode")
        return bool(config is not None and config.value.get("enabled"))

    async def set_invite_only_mode(
        self, *, admin_id: uuid.UUID, enabled: bool, reason: str
    ) -> None:
        await self.set_system_config(
            admin_id=admin_id, key="invite_only_mode", value={"enabled": enabled}, reason=reason
        )

    async def get_invitation_stats(self) -> InvitationStats:
        return InvitationStats(
            sent=await self._invitations.count_by_status("sent"),
            redeemed=await self._invitations.count_by_status("redeemed"),
            expired=await self._invitations.count_by_status("expired"),
            top_inviters=await self._invitations.top_inviters(),
        )

    # --- §28.7: audit log ---

    async def list_audit_log(
        self,
        *,
        actor_id: uuid.UUID | None = None,
        action: str | None = None,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        return await self._audit_log.list_filtered(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            limit=limit,
            offset=offset,
        )

    # --- §28.8: system configuration ---

    async def list_system_config(self) -> list[SystemConfig]:
        return await self._system_config.list_all()

    async def set_system_config(
        self, *, admin_id: uuid.UUID, key: str, value: dict[str, Any], reason: str
    ) -> SystemConfig:
        before = await self._system_config.get_by_key(key)
        before_value = before.value if before is not None else None
        config = await self._system_config.upsert(
            key=key, value=value, updated_by_admin_id=admin_id
        )
        await self._log(
            admin_id,
            "admin.system_config.changed",
            target_type="system_config",
            metadata_json={"key": key, "before": before_value, "after": value, "reason": reason},
        )
        return config

    async def _log(
        self,
        admin_id: uuid.UUID,
        action: str,
        *,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        await self._audit_log.add(
            AuditLog(
                created_at=datetime.now(UTC),
                actor_type="admin",
                actor_id=admin_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                metadata_json=metadata_json,
            )
        )
