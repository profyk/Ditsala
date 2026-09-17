"""
Unit tests for the general admin panel backend (§28.1, .3-.8) — real
Postgres. KYC review (§28.2) has its own test file since it's a separate
service.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import hash_secret
from app.domain.admin.auth_service import AdminAuthError, AdminAuthService
from app.domain.admin.service import AdminError, AdminService
from app.models.accounts import User
from app.models.admin import AdminUser
from app.models.circle import Invitation, Report
from app.repositories.admin import (
    AdminRoleRepository,
    AdminUserRepository,
    AuditLogRepository,
    SystemConfigRepository,
)
from app.repositories.circle import InvitationRepository, ReportRepository
from app.repositories.devices import DeviceRepository, LoginAttemptRepository, SessionRepository
from app.repositories.users import UserRepository


@dataclass
class Harness:
    service: AdminService
    users: UserRepository
    reports: ReportRepository
    invitations: InvitationRepository
    audit_log: AuditLogRepository
    admin_users: AdminUserRepository
    admin_roles: AdminRoleRepository


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
def harness(session: AsyncSession) -> Harness:
    users = UserRepository(session)
    reports = ReportRepository(session)
    invitations = InvitationRepository(session)
    audit_log = AuditLogRepository(session)
    admin_users = AdminUserRepository(session)
    admin_roles = AdminRoleRepository(session)
    service = AdminService(
        users=users,
        reports=reports,
        invitations=invitations,
        devices=DeviceRepository(session),
        sessions=SessionRepository(session),
        login_attempts=LoginAttemptRepository(session),
        system_config=SystemConfigRepository(session),
        audit_log=audit_log,
        admin_users=admin_users,
        admin_roles=admin_roles,
    )
    return Harness(
        service=service,
        users=users,
        reports=reports,
        invitations=invitations,
        audit_log=audit_log,
        admin_users=admin_users,
        admin_roles=admin_roles,
    )


@pytest.fixture
async def admin_id(session: AsyncSession) -> uuid.UUID:
    """A real `admin_users` row — `system_config.updated_by_admin_id` has
    a genuine FK constraint to it, so a synthetic UUID won't do."""
    role = await AdminRoleRepository(session).get_by_name("super_admin")
    assert role is not None, "expected seeded role 'super_admin' — did migrations run?"
    admin = await AdminUserRepository(session).add(
        AdminUser(
            email=f"{uuid.uuid4()}@example.com",
            password_hash=hash_secret("irrelevant-for-these-tests"),
            role_id=role.id,
        )
    )
    return admin.id


async def _make_user(harness: Harness, *, account_state: str = "active") -> User:
    return await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Admin Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state=account_state,
        )
    )


async def test_dashboard_summary_counts(harness: Harness) -> None:
    await _make_user(harness, account_state="active")
    await _make_user(harness, account_state="manual_review")
    summary = await harness.service.get_dashboard_summary()
    assert summary.active_accounts >= 1
    assert summary.manual_review_count >= 1
    assert summary.signups_today >= 2


async def test_search_users_by_query_and_state(harness: Harness) -> None:
    user = await _make_user(harness)
    results = await harness.service.search_users(query=user.email, account_state=None)
    assert user.id in [u.id for u in results]

    by_state = await harness.service.search_users(query=None, account_state="active")
    assert user.id in [u.id for u in by_state]


async def test_get_user_not_found_raises(harness: Harness) -> None:
    with pytest.raises(AdminError, match="No such user"):
        await harness.service.get_user(uuid.uuid4())


async def test_force_account_state_writes_audit_entry_and_history(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    user = await _make_user(harness, account_state="active")
    updated = await harness.service.force_account_state(
        admin_id=admin_id, user_id=user.id, new_state="suspended", reason="Abuse report"
    )
    assert updated.account_state == "suspended"

    history = await harness.service.get_user_state_history(user.id)
    assert len(history) == 1
    assert history[0].action == "admin.user.state_changed"
    assert history[0].metadata_json == {
        "from": "active", "to": "suspended", "reason": "Abuse report"
    }


async def test_action_report_suspend_updates_reported_user(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    reporter = await _make_user(harness)
    reported = await _make_user(harness, account_state="active")
    report = await harness.reports.add(
        Report(reporter_user_id=reporter.id, reported_user_id=reported.id, reason="Harassment")
    )

    actioned = await harness.service.action_report(
        admin_id=admin_id, report_id=report.id, action="suspend", reason="Confirmed harassment"
    )
    assert actioned.status == "actioned"
    assert reported.account_state == "suspended"


async def test_action_report_ban_sets_hard_delete_after(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    reporter = await _make_user(harness)
    reported = await _make_user(harness, account_state="active")
    report = await harness.reports.add(
        Report(reporter_user_id=reporter.id, reported_user_id=reported.id, reason="Serious abuse")
    )

    await harness.service.action_report(
        admin_id=admin_id, report_id=report.id, action="ban", reason="Confirmed serious abuse"
    )
    assert reported.account_state == "banned"
    # §34.2: ban starts the deletion clock immediately (no hold by default).
    assert reported.hard_delete_after is not None


async def test_action_report_warn_does_not_change_account_state(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    reporter = await _make_user(harness)
    reported = await _make_user(harness, account_state="active")
    report = await harness.reports.add(
        Report(reporter_user_id=reporter.id, reported_user_id=reported.id, reason="Rude message")
    )

    await harness.service.action_report(
        admin_id=admin_id, report_id=report.id, action="warn", reason="First offense"
    )
    assert reported.account_state == "active"


async def test_action_report_unknown_report_raises(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    with pytest.raises(AdminError, match="No such report"):
        await harness.service.action_report(
            admin_id=admin_id, report_id=uuid.uuid4(), action="warn", reason="x"
        )


async def test_list_reports_by_status(harness: Harness) -> None:
    reporter = await _make_user(harness)
    reported = await _make_user(harness)
    report = await harness.reports.add(
        Report(reporter_user_id=reporter.id, reported_user_id=reported.id, reason="Spam")
    )
    open_reports = await harness.service.list_reports(status="open")
    assert report.id in [r.id for r in open_reports]


async def test_security_summary_reflects_locked_accounts(harness: Harness) -> None:
    user = await _make_user(harness)
    user.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    summary = await harness.service.get_security_summary()
    assert summary.locked_accounts >= 1


async def test_invite_only_mode_toggle(harness: Harness, admin_id: uuid.UUID) -> None:
    assert await harness.service.get_invite_only_mode() is False
    await harness.service.set_invite_only_mode(admin_id=admin_id, enabled=True, reason="Beta")
    assert await harness.service.get_invite_only_mode() is True

    entries = await harness.audit_log.list_filtered(
        actor_id=admin_id, action="admin.system_config.changed"
    )
    assert any(
        e.metadata_json is not None and e.metadata_json["key"] == "invite_only_mode"
        for e in entries
    )


async def test_invitation_stats(harness: Harness) -> None:
    inviter = await _make_user(harness)
    await harness.invitations.add(
        Invitation(
            inviter_user_id=inviter.id,
            invite_code=uuid.uuid4().hex[:10].upper(),
            channel="link",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    stats = await harness.service.get_invitation_stats()
    assert stats.sent >= 1


async def test_system_config_set_and_get_logs_before_after(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    await harness.service.set_system_config(
        admin_id=admin_id,
        key="sos_cancel_window_seconds",
        value={"seconds": 10},
        reason="Launch default",
    )
    updated = await harness.service.set_system_config(
        admin_id=admin_id, key="sos_cancel_window_seconds", value={"seconds": 15}, reason="Tuning"
    )
    assert updated.value == {"seconds": 15}

    entries = await harness.audit_log.list_filtered(
        actor_id=admin_id, action="admin.system_config.changed"
    )
    tuning_entry = next(
        e for e in entries if e.metadata_json and e.metadata_json["reason"] == "Tuning"
    )
    assert tuning_entry.metadata_json is not None
    assert tuning_entry.metadata_json["before"] == {"seconds": 10}
    assert tuning_entry.metadata_json["after"] == {"seconds": 15}


async def test_list_system_config(harness: Harness, admin_id: uuid.UUID) -> None:
    await harness.service.set_system_config(
        admin_id=admin_id, key="feature_flag_x", value={"enabled": True}, reason="Test"
    )
    configs = await harness.service.list_system_config()
    assert any(c.key == "feature_flag_x" for c in configs)


# --- admin user management (super_admin only) ---


async def test_create_admin_creates_with_role(harness: Harness, admin_id: uuid.UUID) -> None:
    email = f"{uuid.uuid4()}@example.com"
    created = await harness.service.create_admin(
        actor_admin_id=admin_id, email=email, password="a-real-password-123", role="kyc_reviewer"
    )
    assert created.email == email
    assert created.role == "kyc_reviewer"
    assert created.is_active is True
    assert created.mfa_enrolled is False

    stored = await harness.admin_users.get_by_email(email)
    assert stored is not None
    assert stored.id == created.id


async def test_create_admin_rejects_short_password(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    with pytest.raises(AdminError, match="too short"):
        await harness.service.create_admin(
            actor_admin_id=admin_id,
            email=f"{uuid.uuid4()}@example.com",
            password="short1",
            role="support_readonly",
        )


async def test_create_admin_rejects_duplicate_email(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    email = f"{uuid.uuid4()}@example.com"
    await harness.service.create_admin(
        actor_admin_id=admin_id, email=email, password="a-real-password-123", role="trust_safety"
    )
    with pytest.raises(AdminError, match="already exists"):
        await harness.service.create_admin(
            actor_admin_id=admin_id,
            email=email,
            password="another-real-password-1",
            role="trust_safety",
        )


async def test_create_admin_rejects_unknown_role(harness: Harness, admin_id: uuid.UUID) -> None:
    with pytest.raises(AdminError, match="Unrecognized role"):
        await harness.service.create_admin(
            actor_admin_id=admin_id,
            email=f"{uuid.uuid4()}@example.com",
            password="a-real-password-123",
            role="cto",
        )


async def test_list_admins_includes_role_name(harness: Harness, admin_id: uuid.UUID) -> None:
    email = f"{uuid.uuid4()}@example.com"
    await harness.service.create_admin(
        actor_admin_id=admin_id,
        email=email,
        password="a-real-password-123",
        role="support_readonly",
    )
    admins = await harness.service.list_admins()
    match = next(a for a in admins if a.email == email)
    assert match.role == "support_readonly"


async def test_set_admin_active_deactivates_and_reactivates(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    created = await harness.service.create_admin(
        actor_admin_id=admin_id,
        email=f"{uuid.uuid4()}@example.com",
        password="a-real-password-123",
        role="support_readonly",
    )
    deactivated = await harness.service.set_admin_active(
        actor_admin_id=admin_id, admin_id=created.id, is_active=False
    )
    assert deactivated.is_active is False

    reactivated = await harness.service.set_admin_active(
        actor_admin_id=admin_id, admin_id=created.id, is_active=True
    )
    assert reactivated.is_active is True


async def test_set_admin_active_rejects_self_deactivation(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    with pytest.raises(AdminError, match="own account"):
        await harness.service.set_admin_active(
            actor_admin_id=admin_id, admin_id=admin_id, is_active=False
        )


async def test_change_admin_role_changes_role(harness: Harness, admin_id: uuid.UUID) -> None:
    created = await harness.service.create_admin(
        actor_admin_id=admin_id,
        email=f"{uuid.uuid4()}@example.com",
        password="a-real-password-123",
        role="support_readonly",
    )
    updated = await harness.service.change_admin_role(
        actor_admin_id=admin_id, admin_id=created.id, role="trust_safety"
    )
    assert updated.role == "trust_safety"


async def test_change_admin_role_rejects_self_change(
    harness: Harness, admin_id: uuid.UUID
) -> None:
    with pytest.raises(AdminError, match="own role"):
        await harness.service.change_admin_role(
            actor_admin_id=admin_id, admin_id=admin_id, role="support_readonly"
        )


async def test_deactivated_admin_cannot_start_login(
    harness: Harness, admin_id: uuid.UUID, session: AsyncSession
) -> None:
    """Deactivation must actually revoke login capability, not just hide
    the row in the panel — this is what wires that guarantee end to end."""
    password = "a-real-password-123"
    created = await harness.service.create_admin(
        actor_admin_id=admin_id,
        email=f"{uuid.uuid4()}@example.com",
        password=password,
        role="support_readonly",
    )
    await harness.service.set_admin_active(
        actor_admin_id=admin_id, admin_id=created.id, is_active=False
    )

    auth_service = AdminAuthService(
        admin_users=harness.admin_users,
        admin_roles=harness.admin_roles,
        audit_log=harness.audit_log,
        jwt_secret="test-secret-at-least-32-bytes-long!!",
        access_token_ttl_minutes=15,
    )
    with pytest.raises(AdminAuthError, match="deactivated"):
        await auth_service.start_login(email=created.email, password=password)
