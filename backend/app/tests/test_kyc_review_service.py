"""
Unit tests for the KYC Review Queue (§28.2, §5) — real Postgres. The
required-reason-before-P1-access rule is the one thing this file most
needs to prove, not just the state transitions.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.admin.kyc_review_service import KycReviewError, KycReviewService
from app.models.accounts import KycDocument, User
from app.repositories.admin import AuditLogRepository
from app.repositories.kyc import KycDocumentRepository, KycFaceVerificationRepository
from app.repositories.users import UserRepository

ADMIN_ID = uuid.uuid4()


@dataclass
class Harness:
    service: KycReviewService
    users: UserRepository
    kyc_documents: KycDocumentRepository
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
    users = UserRepository(session)
    kyc_documents = KycDocumentRepository(session)
    audit_log = AuditLogRepository(session)
    service = KycReviewService(
        users=users,
        kyc_documents=kyc_documents,
        kyc_face_verifications=KycFaceVerificationRepository(session),
        audit_log=audit_log,
    )
    return Harness(service=service, users=users, kyc_documents=kyc_documents, audit_log=audit_log)


async def _make_user(harness: Harness, *, account_state: str = "manual_review") -> User:
    return await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="KYC Review Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state=account_state,
        )
    )


async def test_list_queue_returns_only_manual_review(harness: Harness) -> None:
    in_queue = await _make_user(harness, account_state="manual_review")
    await _make_user(harness, account_state="active")

    queue = await harness.service.list_queue()
    assert in_queue.id in [u.id for u in queue]
    assert len(queue) == 1


async def test_get_detail_requires_nonempty_reason(harness: Harness) -> None:
    user = await _make_user(harness)
    with pytest.raises(KycReviewError, match="reason for access"):
        await harness.service.get_detail(admin_id=ADMIN_ID, user_id=user.id, reason="   ")


async def test_get_detail_logs_p1_access_before_returning(harness: Harness) -> None:
    user = await _make_user(harness)
    await harness.kyc_documents.add(
        KycDocument(
            user_id=user.id,
            document_type="sa_id",
            smile_id_job_id=uuid.uuid4().hex,
            status="passed",
            result_summary={"result_code": "1012"},
        )
    )

    detail = await harness.service.get_detail(
        admin_id=ADMIN_ID, user_id=user.id, reason="Reviewing flagged document mismatch"
    )
    assert detail.user.id == user.id
    assert len(detail.documents) == 1
    assert detail.documents[0].result_summary == {"result_code": "1012"}

    entries = await harness.audit_log.list_filtered(actor_id=ADMIN_ID, action="admin.kyc.viewed")
    assert len(entries) == 1
    assert entries[0].target_id == user.id
    assert entries[0].metadata_json is not None
    assert entries[0].metadata_json["reason"] == "Reviewing flagged document mismatch"


async def test_get_detail_unknown_user_raises(harness: Harness) -> None:
    with pytest.raises(KycReviewError, match="No such user"):
        await harness.service.get_detail(admin_id=ADMIN_ID, user_id=uuid.uuid4(), reason="x")


async def test_approve_transitions_to_active(harness: Harness) -> None:
    user = await _make_user(harness)
    updated = await harness.service.approve(admin_id=ADMIN_ID, user_id=user.id, reason="Clean")
    assert updated.account_state == "active"


async def test_reject_transitions_to_banned(harness: Harness) -> None:
    user = await _make_user(harness)
    updated = await harness.service.reject(
        admin_id=ADMIN_ID, user_id=user.id, reason="Document forgery suspected"
    )
    assert updated.account_state == "banned"
    # §34.2: ban starts the deletion clock immediately (no hold by default).
    assert updated.hard_delete_after is not None


async def test_request_recapture_transitions_to_pending_kyc_document(harness: Harness) -> None:
    user = await _make_user(harness)
    updated = await harness.service.request_recapture(
        admin_id=ADMIN_ID, user_id=user.id, reason="Blurry photo"
    )
    assert updated.account_state == "pending_kyc_document"


async def test_cannot_approve_a_user_not_in_manual_review(harness: Harness) -> None:
    user = await _make_user(harness, account_state="active")
    with pytest.raises(KycReviewError, match="expected manual_review"):
        await harness.service.approve(admin_id=ADMIN_ID, user_id=user.id, reason="x")
