from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency — one session per request."""
    async with _session_factory() as session:
        yield session


async def set_current_user(session: AsyncSession, user_id: UUID) -> None:
    """
    Wires a request's authenticated user into the RLS session variable the
    policies in migrations/versions/1bcfa1c65e5e_* check (§5). Must run
    inside the same transaction as the queries it's meant to scope — call
    it right after opening the session, before any other query. Uses
    set_config with a bound parameter deliberately: plain `SET LOCAL x = $1`
    doesn't accept bind parameters, and string-interpolating a user id into
    SQL text is not a habit worth starting even for a UUID.

    Only takes effect when the session actually connects as app_backend —
    a session connecting as a bypass/superuser role (as local dev's default
    DATABASE_URL currently does — see .env.example) won't be restricted by
    RLS regardless of this call. Wiring this into an app_backend-scoped
    connection is Phase 3's job (auth middleware); this function is the
    piece Phase 1 owes it.
    """
    await session.execute(
        text("SELECT set_config('app.current_user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )
