"""
Unit tests for admin authentication (§29) — real Postgres. The 4 launch
`admin_roles` rows are seeded by migration `f98829234cbf` and already
committed, so tests fetch them by name rather than creating their own.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pyotp
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import hash_secret
from app.domain.admin.auth_service import AdminAuthError, AdminAuthService
from app.models.admin import AdminRole, AdminUser
from app.repositories.admin import AdminRoleRepository, AdminUserRepository, AuditLogRepository

TEST_JWT_SECRET = "test-admin-jwt-secret-32-bytes-min!!"


@dataclass
class Harness:
    service: AdminAuthService
    admin_users: AdminUserRepository
    admin_roles: AdminRoleRepository
    audit_log: AuditLogRepository


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
    admin_users = AdminUserRepository(session)
    admin_roles = AdminRoleRepository(session)
    audit_log = AuditLogRepository(session)
    service = AdminAuthService(
        admin_users=admin_users,
        admin_roles=admin_roles,
        audit_log=audit_log,
        jwt_secret=TEST_JWT_SECRET,
        access_token_ttl_minutes=480,
    )
    return Harness(
        service=service, admin_users=admin_users, admin_roles=admin_roles, audit_log=audit_log
    )


async def _role(harness: Harness, name: str = "super_admin") -> AdminRole:
    role = await harness.admin_roles.get_by_name(name)
    assert role is not None, f"expected seeded role {name!r} — did migrations run?"
    return role


async def _make_admin(
    harness: Harness,
    *,
    password: str = "CorrectHorseBattery123",
    mfa_enrolled: bool = False,
    mfa_secret: str | None = None,
    role_name: str = "super_admin",
) -> tuple[AdminUser, str]:
    role = await _role(harness, role_name)
    admin = await harness.admin_users.add(
        AdminUser(
            email=f"{uuid.uuid4()}@example.com",
            password_hash=hash_secret(password),
            role_id=role.id,
            mfa_enrolled=mfa_enrolled,
            mfa_secret=mfa_secret,
        )
    )
    return admin, password


async def test_start_login_wrong_password_raises(harness: Harness) -> None:
    admin, _password = await _make_admin(harness)
    with pytest.raises(AdminAuthError, match="Invalid email or password"):
        await harness.service.start_login(email=admin.email, password="wrong")


async def test_start_login_unknown_email_raises(harness: Harness) -> None:
    with pytest.raises(AdminAuthError, match="Invalid email or password"):
        await harness.service.start_login(email="nobody@example.com", password="whatever")


async def test_start_login_unenrolled_requires_mfa_enrollment(harness: Harness) -> None:
    admin, password = await _make_admin(harness, mfa_enrolled=False)
    result = await harness.service.start_login(email=admin.email, password=password)
    assert result.status == "mfa_enroll_required"
    assert result.mfa_enroll_token is not None
    assert result.provisioning_uri is not None
    assert pyotp.parse_uri(result.provisioning_uri).name == admin.email


async def test_enroll_mfa_with_valid_code_succeeds(harness: Harness) -> None:
    admin, password = await _make_admin(harness, mfa_enrolled=False)
    start = await harness.service.start_login(email=admin.email, password=password)
    assert start.mfa_enroll_token is not None
    assert start.provisioning_uri is not None

    # Extract the freshly generated secret the same way a real
    # authenticator app would (via the otpauth:// URI), to prove the
    # round trip end to end rather than reaching into the token directly.
    secret = pyotp.parse_uri(start.provisioning_uri).secret
    code = pyotp.TOTP(secret).now()

    session = await harness.service.enroll_mfa(enroll_token=start.mfa_enroll_token, code=code)
    assert session.access_token
    assert session.role_name == "super_admin"
    assert admin.mfa_enrolled is True
    assert admin.mfa_secret == secret


async def test_enroll_mfa_with_invalid_code_fails(harness: Harness) -> None:
    admin, password = await _make_admin(harness, mfa_enrolled=False)
    start = await harness.service.start_login(email=admin.email, password=password)
    assert start.mfa_enroll_token is not None

    with pytest.raises(AdminAuthError, match="Incorrect code"):
        await harness.service.enroll_mfa(enroll_token=start.mfa_enroll_token, code="000000")
    assert admin.mfa_enrolled is False


async def test_start_login_enrolled_requires_mfa_code(harness: Harness) -> None:
    secret = pyotp.random_base32()
    admin, password = await _make_admin(harness, mfa_enrolled=True, mfa_secret=secret)
    result = await harness.service.start_login(email=admin.email, password=password)
    assert result.status == "mfa_code_required"
    assert result.login_token is not None


async def test_complete_login_with_valid_code_succeeds(harness: Harness) -> None:
    secret = pyotp.random_base32()
    admin, password = await _make_admin(harness, mfa_enrolled=True, mfa_secret=secret)
    start = await harness.service.start_login(email=admin.email, password=password)
    assert start.login_token is not None

    session = await harness.service.complete_login(
        login_token=start.login_token, code=pyotp.TOTP(secret).now()
    )
    assert session.access_token
    assert admin.last_login_at is not None


async def test_complete_login_with_invalid_code_fails(harness: Harness) -> None:
    secret = pyotp.random_base32()
    admin, password = await _make_admin(harness, mfa_enrolled=True, mfa_secret=secret)
    start = await harness.service.start_login(email=admin.email, password=password)
    assert start.login_token is not None

    with pytest.raises(AdminAuthError, match="Incorrect code"):
        await harness.service.complete_login(login_token=start.login_token, code="000000")


async def test_logout_writes_audit_entry(harness: Harness) -> None:
    admin, _password = await _make_admin(
        harness, mfa_enrolled=True, mfa_secret=pyotp.random_base32()
    )
    await harness.service.logout(admin.id)
    entries = await harness.audit_log.list_filtered(actor_id=admin.id, action="admin.logout")
    assert len(entries) == 1


async def test_get_role_name(harness: Harness) -> None:
    admin, _password = await _make_admin(harness, role_name="trust_safety")
    assert await harness.service.get_role_name(admin) == "trust_safety"
