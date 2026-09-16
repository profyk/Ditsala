"""
End-to-end API tests for /admin/* — real Postgres, real HTTP layer. This
is the one place RBAC enforcement (§29) itself is exercised — the domain
tests (test_admin_service.py etc.) call services directly and never touch
`require_permission`'s dependency wiring.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.security import hash_secret
from app.main import app
from app.models.accounts import User
from app.models.admin import AdminUser
from app.repositories.admin import AdminRoleRepository


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def _override_db_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = _override_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _make_admin(
    session: AsyncSession, *, role_name: str = "super_admin", password: str = "SuperSecret123!"
) -> AdminUser:
    role = await AdminRoleRepository(session).get_by_name(role_name)
    assert role is not None
    admin = AdminUser(
        email=f"{uuid.uuid4()}@example.com", password_hash=hash_secret(password), role_id=role.id
    )
    session.add(admin)
    await session.flush()
    return admin


async def _login(client: AsyncClient, admin: AdminUser, password: str) -> str:
    """Full login flow through the real HTTP endpoints, including first-
    time TOTP enrollment — returns a bearer access token."""
    r = await client.post(
        "/api/v1/admin/auth/login/start", json={"email": admin.email, "password": password}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "mfa_enroll_required"
    secret = pyotp.parse_uri(body["provisioning_uri"]).secret

    r = await client.post(
        "/api/v1/admin/auth/mfa/enroll",
        json={"enroll_token": body["mfa_enroll_token"], "code": pyotp.TOTP(secret).now()},
    )
    assert r.status_code == 200, r.text
    return str(r.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_login_requires_mfa_then_issues_access_token(
    client: AsyncClient, session: AsyncSession
) -> None:
    admin = await _make_admin(session)
    token = await _login(client, admin, "SuperSecret123!")

    r = await client.get("/api/v1/admin/auth/me", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json() == {"email": admin.email, "role": "super_admin"}


async def test_second_login_uses_mfa_code_not_enrollment(
    client: AsyncClient, session: AsyncSession
) -> None:
    admin = await _make_admin(session)
    await _login(client, admin, "SuperSecret123!")  # enrolls MFA

    r = await client.post(
        "/api/v1/admin/auth/login/start",
        json={"email": admin.email, "password": "SuperSecret123!"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "mfa_code_required"


async def test_wrong_password_returns_401(client: AsyncClient, session: AsyncSession) -> None:
    admin = await _make_admin(session)
    r = await client.post(
        "/api/v1/admin/auth/login/start", json={"email": admin.email, "password": "wrong"}
    )
    assert r.status_code == 401


async def test_dashboard_requires_authentication(client: AsyncClient) -> None:
    r = await client.get("/api/v1/admin/dashboard")
    assert r.status_code == 401


async def test_super_admin_can_view_dashboard_and_system_config(
    client: AsyncClient, session: AsyncSession
) -> None:
    admin = await _make_admin(session, role_name="super_admin")
    token = await _login(client, admin, "SuperSecret123!")

    r = await client.get("/api/v1/admin/dashboard", headers=_auth(token))
    assert r.status_code == 200, r.text

    r = await client.get("/api/v1/admin/system-config", headers=_auth(token))
    assert r.status_code == 200, r.text


async def test_support_readonly_cannot_action_reports_or_touch_system_config(
    client: AsyncClient, session: AsyncSession
) -> None:
    admin = await _make_admin(session, role_name="support_readonly")
    token = await _login(client, admin, "SuperSecret123!")

    # Allowed: users:view, dashboard:view.
    r = await client.get("/api/v1/admin/dashboard", headers=_auth(token))
    assert r.status_code == 200, r.text
    r = await client.get("/api/v1/admin/users", headers=_auth(token))
    assert r.status_code == 200, r.text

    # Forbidden: no reports:action, no system_config:view.
    r = await client.post(
        f"/api/v1/admin/reports/{uuid.uuid4()}/action",
        json={"action": "warn", "reason": "x"},
        headers=_auth(token),
    )
    assert r.status_code == 403
    r = await client.get("/api/v1/admin/system-config", headers=_auth(token))
    assert r.status_code == 403


async def test_kyc_reviewer_cannot_access_reports_or_users_action(
    client: AsyncClient, session: AsyncSession
) -> None:
    admin = await _make_admin(session, role_name="kyc_reviewer")
    token = await _login(client, admin, "SuperSecret123!")

    r = await client.get("/api/v1/admin/kyc/queue", headers=_auth(token))
    assert r.status_code == 200, r.text

    r = await client.get("/api/v1/admin/reports", headers=_auth(token))
    assert r.status_code == 403


async def test_kyc_review_requires_reason_and_logs_it(
    client: AsyncClient, session: AsyncSession
) -> None:
    admin = await _make_admin(session, role_name="kyc_reviewer")
    token = await _login(client, admin, "SuperSecret123!")

    user = User(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="KYC API Test User",
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
        account_state="manual_review",
    )
    session.add(user)
    await session.flush()

    r = await client.get(f"/api/v1/admin/kyc/{user.id}", headers=_auth(token))
    assert r.status_code == 422  # missing required `reason` query param

    r = await client.get(
        f"/api/v1/admin/kyc/{user.id}",
        params={"reason": "Flagged for manual review"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["user"]["id"] == str(user.id)

    r = await client.post(
        f"/api/v1/admin/kyc/{user.id}/approve",
        json={"reason": "Looks legitimate"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["account_state"] == "active"


async def test_trust_safety_can_action_report_and_force_state(
    client: AsyncClient, session: AsyncSession
) -> None:
    admin = await _make_admin(session, role_name="trust_safety")
    token = await _login(client, admin, "SuperSecret123!")

    reported = User(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="Reported User",
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
        account_state="active",
    )
    session.add(reported)
    await session.flush()

    r = await client.post(
        f"/api/v1/admin/users/{reported.id}/state",
        json={"new_state": "suspended", "reason": "Manual review outcome"},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["account_state"] == "suspended"

    r = await client.get(f"/api/v1/admin/users/{reported.id}/history", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
