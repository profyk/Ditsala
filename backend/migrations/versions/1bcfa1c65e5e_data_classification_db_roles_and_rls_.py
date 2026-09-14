"""data classification DB roles and RLS (spec section 5)

Revision ID: 1bcfa1c65e5e
Revises: 631a559a0977
Create Date: 2026-09-15 01:45:00.000000

"""

from alembic import op

revision: str = "1bcfa1c65e5e"
down_revision: str | None = "631a559a0977"
branch_labels: str | None = None
depends_on: str | None = None

# NOLOGIN by design — these roles define structure (grants), not
# credentials. An operator sets a real password out-of-band via
# `ALTER ROLE ... WITH LOGIN PASSWORD '...'` (see docs/DITSALA_MASTER_SPEC.md
# §7.7: secrets only via env vars / secrets manager, never in a migration).
# Running this migration requires the connecting role to have CREATEROLE
# and BYPASSRLS — true of a deploy-time role in any real environment; for
# local dev, run once as a superuser first:
#   ALTER ROLE <your_dev_role> WITH CREATEROLE BYPASSRLS;
ROLES = ("app_backend", "app_admin_readonly", "app_admin_kyc_reviewer", "app_maintenance")

# users/sessions mix classes in one table — P0 columns are named explicitly
# so admin roles get column-level grants excluding them, everything else in
# app.domain.classification.REGISTRY is either a whole excluded table (P1/P2)
# or defaults to P3 (safe for app_admin_readonly at the table level).
USERS_ADMIN_SAFE_COLUMNS = (
    "id, email, email_verified_at, phone, phone_verified_at, display_name, "
    "date_of_birth, account_state, code_set_at, failed_code_attempts, "
    "locked_until, created_at, updated_at"
)
SESSIONS_ADMIN_SAFE_COLUMNS = (
    "id, user_id, device_id, access_token_family_id, expires_at, "
    "revoked_at, revoked_reason, created_at, updated_at"
)

# P0 — cryptographic key material. No admin role, ever. See §7.3.
P0_ONLY_TABLES = ("identity_keys", "signed_prekeys", "one_time_prekeys", "sender_keys")
# P1/P2 — biometric and message/media content. Excluded from the general
# readonly admin role; kyc tables get their own narrower role below.
KYC_TABLES = ("kyc_documents", "kyc_face_verifications")
CONTENT_TABLES = ("messages", "media_objects", "location_pings")

# Every other application table (P3, or mixed handled via column grants
# above) — admin_readonly gets full-row SELECT on these.
ADMIN_READONLY_TABLES = (
    "next_of_kin", "email_verifications", "phone_verifications", "devices",
    "login_attempts", "account_recovery_requests", "conversations",
    "conversation_members", "message_receipts", "contacts", "contact_requests",
    "invitations", "blocks", "reports", "location_shares", "location_access_log",
    "sos_events", "sos_notifications", "calls", "call_participants",
    "admin_users", "admin_roles", "admin_permissions", "admin_role_permissions",
    "audit_log", "system_config", "push_tokens",
)

ALL_APP_TABLES = (
    ("users", "sessions")
    + P0_ONLY_TABLES + KYC_TABLES + CONTENT_TABLES + ADMIN_READONLY_TABLES
)


def upgrade() -> None:
    db_name = op.get_bind().engine.url.database

    for role in ROLES:
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{role}') THEN
                    CREATE ROLE {role} NOLOGIN;
                END IF;
            END
            $$;
        """)
    # Background jobs (retention sweeps, push fan-out — see §30, §34.2, and
    # backend/app/tasks/) run cross-user by nature; RLS below would block
    # them under app_backend, so they connect as app_maintenance instead.
    op.execute("ALTER ROLE app_maintenance BYPASSRLS")

    for role in ROLES:
        op.execute(f"GRANT CONNECT ON DATABASE {db_name} TO {role}")
        op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")

    # --- app_backend: full P1-P3 read/write. P0 columns hold hashes only —
    # the app writes/reads them like any other column, it just never has
    # the plaintext to write. audit_log is insert-only even for the
    # backend itself: true immutability, not just an admin-facing rule. ---
    for table in ALL_APP_TABLES:
        if table == "audit_log":
            continue
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_backend")
    op.execute("GRANT SELECT, INSERT ON audit_log TO app_backend")
    op.execute("GRANT app_backend TO app_maintenance")  # same table grants, plus BYPASSRLS

    # --- app_admin_readonly: P3 (+ P3 columns of mixed tables). Never P0/P1/P2. ---
    op.execute(f"GRANT SELECT ({USERS_ADMIN_SAFE_COLUMNS}) ON users TO app_admin_readonly")
    op.execute(f"GRANT SELECT ({SESSIONS_ADMIN_SAFE_COLUMNS}) ON sessions TO app_admin_readonly")
    for table in ADMIN_READONLY_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO app_admin_readonly")

    # --- app_admin_kyc_reviewer: P1 KYC review only, plus enough of users
    # to identify who's being reviewed (never the code/national-ID hash). ---
    for table in KYC_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO app_admin_kyc_reviewer")
    op.execute(
        "GRANT SELECT (id, display_name, email, phone, account_state) "
        "ON users TO app_admin_kyc_reviewer"
    )

    # --- RLS: defense-in-depth on the tables the spec calls out by name
    # (§5). Enforced via a session-local variable the app sets per request.
    # Plain `SET LOCAL x = $1` does not accept a bind parameter — the
    # Phase 2+ auth middleware must set it via
    # `SELECT set_config('app.current_user_id', %s, true)` (is_local=true)
    # with the user id passed as a bound parameter, never interpolated into
    # SQL text. An unset variable denies all rows
    # (current_setting(..., true) -> NULL -> no match), which is the
    # correct fail-closed default. Table owner (the migration role) and
    # app_maintenance (BYPASSRLS) are unaffected. ---
    for table in ("messages", "conversation_members", "location_shares", "location_pings"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    # conversation_members_read (below) needs to query conversation_members
    # from within conversation_members' own policy — a direct subquery on
    # the same table re-triggers that same policy and Postgres correctly
    # rejects it as infinite recursion. The standard fix: a SECURITY
    # DEFINER function owned by the table owner (not app_backend), which
    # therefore runs with RLS bypassed for this one well-defined check.
    op.execute("""
        CREATE FUNCTION is_conversation_member(p_conversation_id uuid, p_user_id uuid)
        RETURNS boolean
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        AS $$
            SELECT EXISTS (
                SELECT 1 FROM conversation_members
                WHERE conversation_id = p_conversation_id AND user_id = p_user_id
            )
        $$
    """)

    op.execute("""
        CREATE POLICY messages_participant_access ON messages
        FOR ALL TO app_backend
        USING (is_conversation_member(
            conversation_id, NULLIF(current_setting('app.current_user_id', true), '')::uuid
        ))
        WITH CHECK (is_conversation_member(
            conversation_id, NULLIF(current_setting('app.current_user_id', true), '')::uuid
        ))
    """)
    # Membership rows are visible to any member of the same conversation
    # (so a client can render the full member list), but only mutable for
    # your own membership row. Refine further once Phase 4 group-admin
    # actions (adding/removing other members) are built.
    op.execute("""
        CREATE POLICY conversation_members_read ON conversation_members
        FOR SELECT TO app_backend
        USING (is_conversation_member(
            conversation_id, NULLIF(current_setting('app.current_user_id', true), '')::uuid
        ))
    """)
    op.execute("""
        CREATE POLICY conversation_members_write_own ON conversation_members
        FOR INSERT TO app_backend
        WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE POLICY conversation_members_update_own ON conversation_members
        FOR UPDATE TO app_backend
        USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
        WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE POLICY location_shares_participant_access ON location_shares
        FOR ALL TO app_backend
        USING (
            sharer_user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
            OR recipient_user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        )
        WITH CHECK (sharer_user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    """)
    op.execute("""
        CREATE POLICY location_pings_participant_access ON location_pings
        FOR ALL TO app_backend
        USING (location_share_id IN (
            SELECT id FROM location_shares
            WHERE sharer_user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
               OR recipient_user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        ))
    """)


def downgrade() -> None:
    db_name = op.get_bind().engine.url.database

    for table in ("messages", "conversation_members", "location_shares", "location_pings"):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    for policy, table in (
        ("messages_participant_access", "messages"),
        ("conversation_members_read", "conversation_members"),
        ("conversation_members_write_own", "conversation_members"),
        ("conversation_members_update_own", "conversation_members"),
        ("location_shares_participant_access", "location_shares"),
        ("location_pings_participant_access", "location_pings"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    op.execute("DROP FUNCTION IF EXISTS is_conversation_member(uuid, uuid)")

    for role in ("app_admin_kyc_reviewer", "app_admin_readonly", "app_maintenance", "app_backend"):
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}")
        op.execute(f"REVOKE ALL ON SCHEMA public FROM {role}")
        op.execute(f"REVOKE ALL ON DATABASE {db_name} FROM {role}")
    op.execute("REVOKE app_backend FROM app_maintenance")
    for role in ROLES:
        op.execute(f"DROP ROLE IF EXISTS {role}")
