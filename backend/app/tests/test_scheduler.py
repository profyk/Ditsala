"""
Integration tests for app/tasks/scheduler.py — real Postgres. Each sweep's
actual business logic is already covered at the service/repository layer
(test_messaging_service.py, test_sos_service.py, test_account_service.py,
etc.); these tests instead prove the scheduler's own wiring — building the
real service through `session_scope` and committing — actually works end
to end through the top-level entry points main.py calls.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.core.db as db_module
from app.core.config import get_settings
from app.models.accounts import User
from app.models.devices import LoginAttempt
from app.models.location import SosEvent
from app.repositories.devices import LoginAttemptRepository
from app.repositories.sos import SosEventRepository
from app.repositories.users import UserRepository
from app.tasks.scheduler import (
    escalate_armed_sos_events,
    process_scheduled_account_deletions,
    purge_expired_location_pings,
    purge_expired_messages,
    purge_old_login_attempts_and_recovery_requests,
)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _dispose_scheduler_engine_after_test() -> AsyncIterator[None]:
    """
    `app.core.db._engine` is a module-level singleton, created once for
    the whole process — correct in production, but pytest-asyncio hands
    each test function a fresh event loop, and asyncpg connections are
    bound to the loop they were opened under. Disposing the pool after
    every test drops those loop-bound connections so the next test's
    `session_scope()` call opens fresh ones under its own loop, instead
    of tripping over connections orphaned by the previous one.
    """
    yield
    await db_module._engine.dispose()


async def _make_user(session: AsyncSession, **overrides: object) -> User:
    fields: dict[str, object] = {
        "email": f"{uuid.uuid4()}@example.com",
        "phone": f"+27{uuid.uuid4().int % 10**9}",
        "display_name": "Scheduler Test User",
        "date_of_birth": datetime(1990, 1, 1),
        "national_id_hash": uuid.uuid4().hex,
        "account_state": "active",
        "ditsala_code_hash": "irrelevant-hash",
        **overrides,
    }
    user = User(**fields)
    session.add(user)
    await session.flush()
    await session.commit()
    return user


async def test_purge_expired_messages_runs_clean() -> None:
    assert await purge_expired_messages() == 0


async def test_purge_expired_location_pings_runs_clean() -> None:
    # Just proves the wiring (real session, real repository call, commit)
    # works end to end — not asserting a count, since this shared local
    # dev database can carry expired pings left by other test runs.
    assert await purge_expired_location_pings() >= 0


async def test_escalate_armed_sos_events_escalates_due_events(session: AsyncSession) -> None:
    user = await _make_user(session)
    event = await SosEventRepository(session).add(
        SosEvent(
            user_id=user.id,
            triggered_at=datetime.now(UTC) - timedelta(minutes=5),
            cancel_window_seconds=10,
        )
    )
    await session.commit()

    escalated_count = await escalate_armed_sos_events()

    assert escalated_count >= 1
    # A plain expire_all() + get() round-trip on a *still-existing* row hits
    # a greenlet edge case in this SQLAlchemy version's identity-map-hit
    # path — refresh() re-fetches this specific object directly instead.
    await session.refresh(event)
    assert event.status == "escalated"


async def test_purge_old_login_attempts_removes_only_stale_rows(session: AsyncSession) -> None:
    stale = LoginAttempt(
        user_id=None, ip_hash="stale-ip", stage="code", outcome="failure",
        created_at=(datetime.now(UTC) - timedelta(days=400)).replace(tzinfo=None),
    )
    fresh = LoginAttempt(user_id=None, ip_hash="fresh-ip", stage="code", outcome="failure")
    session.add_all([stale, fresh])
    await session.commit()
    stale_id, fresh_id = stale.id, fresh.id

    login_purged, _recovery_purged = await purge_old_login_attempts_and_recovery_requests()

    assert login_purged >= 1
    session.expire_all()  # see test_process_scheduled_account_deletions_removes_due_users
    attempts = LoginAttemptRepository(session)
    assert await attempts.get(stale_id) is None
    assert await attempts.get(fresh_id) is not None


async def test_process_scheduled_account_deletions_removes_due_users(
    session: AsyncSession,
) -> None:
    due_user = await _make_user(
        session,
        account_state="deactivated",
        hard_delete_after=datetime.now(UTC) - timedelta(seconds=1),
    )
    due_user_id = due_user.id

    deleted_count = await process_scheduled_account_deletions()

    assert deleted_count >= 1
    # The scheduler deletes via its own separate session — this test's
    # session still has the pre-delete row cached in its identity map
    # (expire_on_commit=False), so a plain `.get()` would return the stale
    # in-memory copy instead of re-querying.
    session.expire_all()
    assert await UserRepository(session).get(due_user_id) is None
