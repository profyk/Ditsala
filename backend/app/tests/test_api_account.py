"""End-to-end API tests for /account/* — real Postgres, real access tokens."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.security import create_access_token
from app.domain.account.service import AccountLifecycleService
from app.domain.compliance.export import DataExportService
from app.domain.compliance.service import ComplianceService
from app.main import app
from app.models.accounts import User
from app.repositories.admin import AuditLogRepository
from app.repositories.users import DataSubjectRequestRepository, UserRepository
from app.tests.test_compliance_service import StubStorageProvider


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


async def _make_active_user(session: AsyncSession) -> User:
    user = User(
        email=f"{uuid.uuid4()}@example.com",
        phone=f"+27{uuid.uuid4().int % 10**9}",
        display_name="API Account Test User",
        date_of_birth=datetime(1990, 1, 1),
        national_id_hash=uuid.uuid4().hex,
        account_state="active",
        ditsala_code_hash="irrelevant-hash",
    )
    session.add(user)
    await session.flush()
    return user


def _bearer_for(user: User) -> dict[str, str]:
    token = create_access_token(
        user_id=user.id,
        device_id=uuid.uuid4(),
        jwt_secret=get_settings().jwt_secret,
        ttl_minutes=15,
    )
    return {"Authorization": f"Bearer {token}"}


async def test_deactivate_then_cancel(client: AsyncClient, session: AsyncSession) -> None:
    user = await _make_active_user(session)
    headers = _bearer_for(user)

    r = await client.post("/api/v1/account/deactivate", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["account_state"] == "deactivated"
    assert r.json()["hard_delete_after"] is not None

    r = await client.post("/api/v1/account/deactivate/cancel", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["account_state"] == "active"
    assert r.json()["hard_delete_after"] is None

    refreshed = await UserRepository(session).get(user.id)
    assert refreshed is not None
    assert refreshed.account_state == "active"


async def test_deactivate_twice_rejected(client: AsyncClient, session: AsyncSession) -> None:
    user = await _make_active_user(session)
    headers = _bearer_for(user)

    r = await client.post("/api/v1/account/deactivate", headers=headers)
    assert r.status_code == 200, r.text

    r = await client.post("/api/v1/account/deactivate", headers=headers)
    assert r.status_code == 400


async def test_cancel_without_deactivation_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)
    headers = _bearer_for(user)

    r = await client.post("/api/v1/account/deactivate/cancel", headers=headers)
    assert r.status_code == 400


async def test_account_routes_require_auth(client: AsyncClient) -> None:
    r = await client.post("/api/v1/account/deactivate")
    assert r.status_code == 401


async def test_file_and_list_data_subject_requests(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)
    headers = _bearer_for(user)

    r = await client.post(
        "/api/v1/account/data-requests",
        json={"request_type": "access", "details": "Please send me a copy of my data."},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending"
    assert r.json()["request_type"] == "access"

    r = await client.get("/api/v1/account/data-requests", headers=headers)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


async def test_file_data_subject_request_rejects_unknown_type(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)
    r = await client.post(
        "/api/v1/account/data-requests",
        json={"request_type": "bogus"},
        headers=_bearer_for(user),
    )
    assert r.status_code == 422


async def test_download_completed_access_export(client: AsyncClient, session: AsyncSession) -> None:
    user = await _make_active_user(session)
    headers = _bearer_for(user)

    # Completed directly (not via the admin HTTP path — that's covered in
    # test_api_admin.py) with a stub storage provider standing in for the
    # bundle upload itself (no local S3/MinIO in this environment). The
    # download endpoint under test only mints a presigned URL, a local
    # signature computation with no network call, so it needs no stub.
    compliance = ComplianceService(
        requests=DataSubjectRequestRepository(session),
        users=UserRepository(session),
        account_lifecycle=AccountLifecycleService(
            users=UserRepository(session), audit_log=AuditLogRepository(session)
        ),
        export=DataExportService(session=session, storage=StubStorageProvider()),
    )
    request = await compliance.file_request(user, request_type="access", details=None)
    await compliance.complete(
        admin_id=uuid.uuid4(), request_id=request.id, resolution_notes="Bundle generated."
    )

    r = await client.get(f"/api/v1/account/data-requests/{request.id}/download", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["download_url"]


async def test_download_export_rejects_before_completion(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)
    headers = _bearer_for(user)

    r = await client.post(
        "/api/v1/account/data-requests",
        json={"request_type": "access", "details": None},
        headers=headers,
    )
    request_id = r.json()["id"]

    r = await client.get(f"/api/v1/account/data-requests/{request_id}/download", headers=headers)
    assert r.status_code == 400


async def test_avatar_upload_confirm_and_remove(client: AsyncClient, session: AsyncSession) -> None:
    user = await _make_active_user(session)
    headers = _bearer_for(user)

    r = await client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["avatar_url"] is None

    r = await client.post(
        "/api/v1/account/avatar/upload-url", json={"content_type": "image/png"}, headers=headers
    )
    assert r.status_code == 200, r.text
    key = r.json()["key"]
    assert r.json()["upload_url"]

    r = await client.post("/api/v1/account/avatar/confirm", json={"key": key}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["avatar_url"]

    r = await client.get("/api/v1/auth/me", headers=headers)
    assert r.json()["avatar_url"]

    r = await client.delete("/api/v1/account/avatar", headers=headers)
    assert r.status_code == 204, r.text

    r = await client.get("/api/v1/auth/me", headers=headers)
    assert r.json()["avatar_url"] is None


async def test_avatar_upload_rejects_unsupported_content_type(
    client: AsyncClient, session: AsyncSession
) -> None:
    user = await _make_active_user(session)
    r = await client.post(
        "/api/v1/account/avatar/upload-url",
        json={"content_type": "application/pdf"},
        headers=_bearer_for(user),
    )
    assert r.status_code == 422
