"""
Unit tests for §34.4 data subject rights — real Postgres, no external
providers involved.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.account.service import AccountLifecycleService
from app.domain.compliance.export import DataExportService
from app.domain.compliance.service import ComplianceError, ComplianceService
from app.domain.messaging.interfaces import StorageProvider
from app.models.accounts import User
from app.repositories.admin import AuditLogRepository
from app.repositories.users import DataSubjectRequestRepository, UserRepository


class StubStorageProvider(StorageProvider):
    async def create_upload_url(self, *, key: str, content_type: str) -> str:
        return f"https://stub-upload.test/{key}"

    async def create_download_url(self, *, key: str) -> str:
        return f"https://stub-download.test/{key}"

    async def put_object(self, *, key: str, data: bytes, content_type: str) -> None:
        pass

    async def delete_object(self, *, key: str) -> None:
        pass


@dataclass
class Harness:
    service: ComplianceService
    users: UserRepository
    requests: DataSubjectRequestRepository


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
    requests = DataSubjectRequestRepository(session)
    account_lifecycle = AccountLifecycleService(users=users, audit_log=AuditLogRepository(session))
    service = ComplianceService(requests=requests, users=users, account_lifecycle=account_lifecycle)
    return Harness(service=service, users=users, requests=requests)


@pytest.fixture
def harness_with_export(session: AsyncSession) -> Harness:
    users = UserRepository(session)
    requests = DataSubjectRequestRepository(session)
    account_lifecycle = AccountLifecycleService(users=users, audit_log=AuditLogRepository(session))
    export = DataExportService(session=session, storage=StubStorageProvider())
    service = ComplianceService(
        requests=requests, users=users, account_lifecycle=account_lifecycle, export=export
    )
    return Harness(service=service, users=users, requests=requests)


async def _make_user(harness: Harness) -> User:
    return await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Compliance Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
            ditsala_code_hash="irrelevant-hash",
        )
    )


ADMIN_ID = uuid.uuid4()


async def test_file_request_sets_30_day_sla(harness: Harness) -> None:
    user = await _make_user(harness)
    before = datetime.now(UTC)

    request = await harness.service.file_request(
        user, request_type="access", details="Please send me a copy of my data."
    )

    assert request.status == "pending"
    assert request.due_at > before + timedelta(days=29)
    assert request.due_at < before + timedelta(days=31)


async def test_file_request_rejects_unknown_type(harness: Harness) -> None:
    user = await _make_user(harness)
    with pytest.raises(ComplianceError, match="Unrecognized request type"):
        await harness.service.file_request(user, request_type="bogus", details=None)


async def test_list_for_user_only_returns_that_users_requests(harness: Harness) -> None:
    user_a = await _make_user(harness)
    user_b = await _make_user(harness)
    await harness.service.file_request(user_a, request_type="access", details=None)
    await harness.service.file_request(user_b, request_type="correction", details="fix my name")

    a_requests = await harness.service.list_for_user(user_a.id)
    assert len(a_requests) == 1
    assert a_requests[0].user_id == user_a.id


async def test_mark_in_progress_then_complete(harness: Harness) -> None:
    user = await _make_user(harness)
    request = await harness.service.file_request(user, request_type="correction", details="x")

    in_progress = await harness.service.mark_in_progress(admin_id=ADMIN_ID, request_id=request.id)
    assert in_progress.status == "in_progress"
    assert in_progress.actioned_by_admin_id == ADMIN_ID

    completed = await harness.service.complete(
        admin_id=ADMIN_ID, request_id=request.id, resolution_notes="Corrected display name."
    )
    assert completed.status == "completed"
    assert completed.resolved_at is not None
    assert completed.resolution_notes == "Corrected display name."


async def test_complete_deletion_request_starts_account_deactivation(harness: Harness) -> None:
    user = await _make_user(harness)
    request = await harness.service.file_request(user, request_type="deletion", details=None)

    await harness.service.complete(
        admin_id=ADMIN_ID, request_id=request.id, resolution_notes="Deletion request honored."
    )

    assert user.account_state == "deactivated"
    assert user.hard_delete_after is not None


async def test_reject_records_notes(harness: Harness) -> None:
    user = await _make_user(harness)
    request = await harness.service.file_request(user, request_type="access", details=None)

    rejected = await harness.service.reject(
        admin_id=ADMIN_ID, request_id=request.id, resolution_notes="Could not verify identity."
    )
    assert rejected.status == "rejected"
    assert rejected.resolution_notes == "Could not verify identity."


async def test_cannot_action_already_resolved_request(harness: Harness) -> None:
    user = await _make_user(harness)
    request = await harness.service.file_request(user, request_type="access", details=None)
    await harness.service.reject(admin_id=ADMIN_ID, request_id=request.id, resolution_notes="no")

    with pytest.raises(ComplianceError, match="already 'rejected'"):
        await harness.service.mark_in_progress(admin_id=ADMIN_ID, request_id=request.id)


async def test_actioning_unknown_request_raises(harness: Harness) -> None:
    with pytest.raises(ComplianceError, match="No such data subject request"):
        await harness.service.mark_in_progress(admin_id=ADMIN_ID, request_id=uuid.uuid4())


async def test_complete_access_request_without_export_service_leaves_key_unset(
    harness: Harness,
) -> None:
    """Additive-by-default: a ComplianceService built without an `export`
    (every pre-existing call site, unchanged) still completes normally."""
    user = await _make_user(harness)
    request = await harness.service.file_request(user, request_type="access", details=None)

    completed = await harness.service.complete(
        admin_id=ADMIN_ID, request_id=request.id, resolution_notes="Handled manually."
    )

    assert completed.status == "completed"
    assert completed.export_storage_key is None


async def test_complete_access_request_generates_a_real_export_bundle(
    harness_with_export: Harness,
) -> None:
    user = await _make_user(harness_with_export)
    request = await harness_with_export.service.file_request(
        user, request_type="access", details=None
    )

    completed = await harness_with_export.service.complete(
        admin_id=ADMIN_ID, request_id=request.id, resolution_notes="Bundle generated."
    )

    assert completed.export_storage_key is not None
    assert completed.export_storage_key.startswith(f"data-exports/{user.id}/")


async def test_get_export_download_url_after_completion(harness_with_export: Harness) -> None:
    user = await _make_user(harness_with_export)
    request = await harness_with_export.service.file_request(
        user, request_type="access", details=None
    )
    await harness_with_export.service.complete(
        admin_id=ADMIN_ID, request_id=request.id, resolution_notes="Bundle generated."
    )

    url = await harness_with_export.service.get_export_download_url(
        user=user, request_id=request.id
    )
    assert url.startswith("https://stub-download.test/data-exports/")


async def test_get_export_download_url_rejects_a_different_user(
    harness_with_export: Harness,
) -> None:
    user = await _make_user(harness_with_export)
    other_user = await _make_user(harness_with_export)
    request = await harness_with_export.service.file_request(
        user, request_type="access", details=None
    )
    await harness_with_export.service.complete(
        admin_id=ADMIN_ID, request_id=request.id, resolution_notes="Bundle generated."
    )

    with pytest.raises(ComplianceError, match="No such data subject request"):
        await harness_with_export.service.get_export_download_url(
            user=other_user, request_id=request.id
        )


async def test_get_export_download_url_rejects_before_completion(
    harness_with_export: Harness,
) -> None:
    user = await _make_user(harness_with_export)
    request = await harness_with_export.service.file_request(
        user, request_type="access", details=None
    )

    with pytest.raises(ComplianceError, match="No export is available"):
        await harness_with_export.service.get_export_download_url(user=user, request_id=request.id)
