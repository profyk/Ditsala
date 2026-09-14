"""
Proves the RLS policies from migrations/versions/1bcfa1c65e5e_* actually
isolate rows, not just that the grants exist syntactically. Runs against a
real Postgres (see docs/DITSALA_MASTER_SPEC.md: tests are part of every
phase, backend tests use a real Postgres).

Requires the local/CI Postgres user running tests to be a member of
app_backend (`GRANT app_backend TO <role>;`) so `SET ROLE app_backend` can
drop RLS-bypass privileges for the duration of each test — see
CLAUDE.md "Local dev" for the one-time local setup command.
"""

import uuid

import psycopg
import pytest

from app.core.config import get_settings


def _sync_dsn() -> str:
    return get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")


def _returned_id(cur: psycopg.Cursor) -> uuid.UUID:
    row = cur.fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


@pytest.fixture
def conn():
    with psycopg.connect(_sync_dsn(), autocommit=True) as connection:
        yield connection


@pytest.fixture
def two_users_with_a_conversation(conn: psycopg.Connection) -> dict[str, uuid.UUID]:
    """
    Fixture data inserted as the bypass role (table owner), then read back
    under app_backend + RLS in the tests themselves.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (email, phone, display_name, date_of_birth, "
            "national_id_hash, account_state) VALUES "
            "(%s, %s, 'Alice', '1990-01-01', %s, 'active') RETURNING id",
            (
                f"alice-{uuid.uuid4()}@test.local",
                f"+27{uuid.uuid4().int % 10**9}",
                uuid.uuid4().hex,
            ),
        )
        alice_id = _returned_id(cur)
        cur.execute(
            "INSERT INTO users (email, phone, display_name, date_of_birth, "
            "national_id_hash, account_state) VALUES "
            "(%s, %s, 'Bob', '1990-01-01', %s, 'active') RETURNING id",
            (
                f"bob-{uuid.uuid4()}@test.local",
                f"+27{uuid.uuid4().int % 10**9}",
                uuid.uuid4().hex,
            ),
        )
        bob_id = _returned_id(cur)
        cur.execute(
            "INSERT INTO users (email, phone, display_name, date_of_birth, "
            "national_id_hash, account_state) VALUES "
            "(%s, %s, 'Carol (outsider)', '1990-01-01', %s, 'active') RETURNING id",
            (
                f"carol-{uuid.uuid4()}@test.local",
                f"+27{uuid.uuid4().int % 10**9}",
                uuid.uuid4().hex,
            ),
        )
        carol_id = _returned_id(cur)

        cur.execute(
            "INSERT INTO conversations (type) VALUES ('direct') RETURNING id"
        )
        conversation_id = _returned_id(cur)
        for uid in (alice_id, bob_id):
            cur.execute(
                "INSERT INTO conversation_members (conversation_id, user_id, joined_at) "
                "VALUES (%s, %s, now())",
                (conversation_id, uid),
            )
        cur.execute(
            "INSERT INTO messages (conversation_id, ciphertext, content_type, client_message_id) "
            "VALUES (%s, %s, 'text', %s) RETURNING id",
            (conversation_id, b"opaque-ciphertext", uuid.uuid4().hex),
        )
        message_id = _returned_id(cur)

        cur.execute(
            "INSERT INTO location_shares "
            "(sharer_user_id, recipient_user_id, starts_at, expires_at) "
            "VALUES (%s, %s, now(), now() + interval '1 hour') RETURNING id",
            (alice_id, bob_id),
        )
        share_id = _returned_id(cur)
        cur.execute(
            "INSERT INTO location_pings (location_share_id, lat, lng, accuracy_m, recorded_at) "
            "VALUES (%s, -25.7, 28.2, 5.0, now())",
            (share_id,),
        )

    return {
        "alice_id": alice_id,
        "bob_id": bob_id,
        "carol_id": carol_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "share_id": share_id,
    }


def _as_app_backend(cur: psycopg.Cursor, current_user_id: uuid.UUID | None) -> None:
    cur.execute("SET ROLE app_backend")
    if current_user_id is None:
        cur.execute("RESET app.current_user_id")
    else:
        # SET doesn't accept bind parameters; set_config() does.
        cur.execute("SELECT set_config('app.current_user_id', %s, false)", (str(current_user_id),))


def test_participant_sees_their_message(conn, two_users_with_a_conversation):
    ids = two_users_with_a_conversation
    with conn.cursor() as cur:
        _as_app_backend(cur, ids["alice_id"])
        cur.execute("SELECT id FROM messages WHERE id = %s", (ids["message_id"],))
        assert cur.fetchone() is not None


def test_outsider_cannot_see_the_message(conn, two_users_with_a_conversation):
    ids = two_users_with_a_conversation
    with conn.cursor() as cur:
        _as_app_backend(cur, ids["carol_id"])
        cur.execute("SELECT id FROM messages WHERE id = %s", (ids["message_id"],))
        assert cur.fetchone() is None


def test_unset_current_user_sees_nothing(conn, two_users_with_a_conversation):
    """Fail-closed default: no session variable set -> zero rows, not everything."""
    ids = two_users_with_a_conversation
    with conn.cursor() as cur:
        _as_app_backend(cur, None)
        cur.execute("SELECT id FROM messages WHERE id = %s", (ids["message_id"],))
        assert cur.fetchone() is None


def test_conversation_member_sees_fellow_member(conn, two_users_with_a_conversation):
    ids = two_users_with_a_conversation
    with conn.cursor() as cur:
        _as_app_backend(cur, ids["alice_id"])
        cur.execute(
            "SELECT user_id FROM conversation_members WHERE conversation_id = %s",
            (ids["conversation_id"],),
        )
        member_ids = {row[0] for row in cur.fetchall()}
        assert member_ids == {ids["alice_id"], ids["bob_id"]}


def test_outsider_cannot_see_conversation_members(conn, two_users_with_a_conversation):
    ids = two_users_with_a_conversation
    with conn.cursor() as cur:
        _as_app_backend(cur, ids["carol_id"])
        cur.execute(
            "SELECT user_id FROM conversation_members WHERE conversation_id = %s",
            (ids["conversation_id"],),
        )
        assert cur.fetchall() == []


def test_sharer_and_recipient_see_the_location_share(conn, two_users_with_a_conversation):
    ids = two_users_with_a_conversation
    with conn.cursor() as cur:
        for uid in (ids["alice_id"], ids["bob_id"]):
            _as_app_backend(cur, uid)
            cur.execute("SELECT id FROM location_shares WHERE id = %s", (ids["share_id"],))
            assert cur.fetchone() is not None, f"{uid} should see the share"


def test_outsider_cannot_see_the_location_share_or_pings(conn, two_users_with_a_conversation):
    ids = two_users_with_a_conversation
    with conn.cursor() as cur:
        _as_app_backend(cur, ids["carol_id"])
        cur.execute("SELECT id FROM location_shares WHERE id = %s", (ids["share_id"],))
        assert cur.fetchone() is None
        cur.execute(
            "SELECT id FROM location_pings WHERE location_share_id = %s", (ids["share_id"],)
        )
        assert cur.fetchall() == []


def test_participant_sees_location_pings(conn, two_users_with_a_conversation):
    ids = two_users_with_a_conversation
    with conn.cursor() as cur:
        _as_app_backend(cur, ids["bob_id"])
        cur.execute(
            "SELECT id FROM location_pings WHERE location_share_id = %s", (ids["share_id"],)
        )
        assert len(cur.fetchall()) == 1
