"""
Unit tests for §34.2 self-service account lifecycle — real Postgres,
no external providers involved (nothing here talks to a vendor).
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.domain.account.service import AccountLifecycleError, AccountLifecycleService
from app.models.accounts import User
from app.repositories.admin import AuditLogRepository
from app.repositories.users import UserRepository


@dataclass
class Harness:
    service: AccountLifecycleService
    users: UserRepository
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
    audit_log = AuditLogRepository(session)
    return Harness(
        service=AccountLifecycleService(users=users, audit_log=audit_log),
        users=users,
        audit_log=audit_log,
    )


async def _make_active_user(harness: Harness) -> User:
    return await harness.users.add(
        User(
            email=f"{uuid.uuid4()}@example.com",
            phone=f"+27{uuid.uuid4().int % 10**9}",
            display_name="Lifecycle Test User",
            date_of_birth=datetime(1990, 1, 1),
            national_id_hash=uuid.uuid4().hex,
            account_state="active",
            ditsala_code_hash="irrelevant-hash",
        )
    )


async def test_request_deactivation_sets_grace_window(harness: Harness) -> None:
    user = await _make_active_user(harness)
    before = datetime.now(UTC)

    await harness.service.request_deactivation(user)

    assert user.account_state == "deactivated"
    assert user.deactivated_at is not None
    assert user.hard_delete_after is not None
    assert user.hard_delete_after > before + timedelta(days=29)
    assert user.hard_delete_after < before + timedelta(days=31)

    entries = await harness.audit_log.list_filtered(target_id=user.id)
    assert any(e.action == "account.deactivation_requested" for e in entries)


async def test_request_deactivation_rejects_already_deactivated(harness: Harness) -> None:
    user = await _make_active_user(harness)
    await harness.service.request_deactivation(user)

    with pytest.raises(AccountLifecycleError, match="Cannot deactivate"):
        await harness.service.request_deactivation(user)


async def test_cancel_deactivation_reverses_state(harness: Harness) -> None:
    user = await _make_active_user(harness)
    await harness.service.request_deactivation(user)

    await harness.service.cancel_deactivation(user)

    assert user.account_state == "active"
    assert user.deactivated_at is None
    assert user.hard_delete_after is None

    entries = await harness.audit_log.list_filtered(target_id=user.id)
    assert any(e.action == "account.deactivation_cancelled" for e in entries)


async def test_cancel_deactivation_rejects_non_deactivated_account(harness: Harness) -> None:
    user = await _make_active_user(harness)

    with pytest.raises(AccountLifecycleError, match="not deactivated"):
        await harness.service.cancel_deactivation(user)


async def test_cancel_deactivation_rejects_elapsed_grace_window(harness: Harness) -> None:
    user = await _make_active_user(harness)
    await harness.service.request_deactivation(user)
    user.hard_delete_after = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(AccountLifecycleError, match="already elapsed"):
        await harness.service.cancel_deactivation(user)


async def test_process_scheduled_deletions_removes_due_accounts(
    harness: Harness, session: AsyncSession
) -> None:
    due_user = await _make_active_user(harness)
    await harness.service.request_deactivation(due_user)
    due_user.hard_delete_after = datetime.now(UTC) - timedelta(seconds=1)

    not_due_user = await _make_active_user(harness)
    await harness.service.request_deactivation(not_due_user)
    # freshly requested — hard_delete_after is ~30 days out, not due

    due_user_id = due_user.id
    not_due_user_id = not_due_user.id
    await session.flush()

    count = await harness.service.process_scheduled_deletions()

    assert count == 1
    assert await harness.users.get(due_user_id) is None
    assert await harness.users.get(not_due_user_id) is not None

    entries = await harness.audit_log.list_filtered(target_id=due_user_id)
    assert any(e.action == "account.hard_deleted" for e in entries)


async def test_process_scheduled_deletions_ignores_accounts_with_no_grace_window(
    harness: Harness,
) -> None:
    user = await _make_active_user(harness)
    assert user.hard_delete_after is None

    count = await harness.service.process_scheduled_deletions()

    assert count == 0
    assert await harness.users.get(user.id) is not None
