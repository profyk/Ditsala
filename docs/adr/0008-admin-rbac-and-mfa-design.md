# ADR 0008: Admin RBAC as a Python mapping; TOTP secrets stored plaintext

Status: Accepted (Phase 7)

## Context

docs/DITSALA_MASTER_SPEC.md §29 defines 4 launch admin roles (`super_admin`, `kyc_reviewer`, `trust_safety`, `support_readonly`) with fixed permission scopes, and requires TOTP MFA enrollment before first use. Phase 1 already modeled `admin_roles`/`admin_permissions`/`admin_role_permissions` as a many-to-many join, anticipating a fully DB-driven RBAC system §29 also mentions ("extensible via admin_roles/admin_permissions").

## Decision 1: role -> permission mapping is a Python constant, not the join table

**Superseded by ADR 0011 (Phase 8)** — the mapping is now DB-driven, per this decision's own "consequence" note below. Left in place as the historical record of why it started this way.

`domain/admin/rbac.py` hardcodes `ROLE_PERMISSIONS: dict[str, frozenset[Permission]]` for the 4 launch roles, checked via `role_has_permission(role_name, permission)`. The `admin_role_permissions`/`admin_permissions` tables are **not populated or read** — only `admin_roles.name` (a real column, the real FK target of `admin_users.role_id`) is used, to know *which* role an admin has.

**Why:** §29's role set is fixed by spec text for launch, not something an admin configures at runtime — there is no "RBAC management" UI in this phase (§29's own text scopes that to `super_admin`, but no such screen was built). Making the mapping DB-driven now would mean building CRUD + a management UI for a table nothing else reads yet, for a set of 4 roles unlikely to change before that UI exists anyway.

**Consequence:** `require_permission()` (api/v1/admin_deps.py) is real enforcement — every admin route requires it via FastAPI's `dependencies=[...]`, verified end-to-end in `test_api_admin.py` across all 4 roles — it just isn't reading from `admin_role_permissions`. Whoever builds real RBAC management (a `super_admin`-only screen to add/remove permissions per role) should populate that table and switch `role_has_permission` to query it instead of the constant; the call site (`require_permission`) doesn't need to change shape, only its implementation.

## Decision 2: TOTP secrets stored plaintext in `admin_users.mfa_secret`

Unlike passwords (Argon2id, one-way) or refresh tokens (SHA-256, compared as hashes), a TOTP secret must be *read back* to compute the current 6-digit code for verification — it can't be a one-way hash. `admin_users.mfa_secret` stores the base32 secret as plain text.

**Why:** No KMS or envelope-encryption infrastructure is provisioned anywhere in this stack yet (Supabase's own encryption-at-rest covers the disk, not application-level field encryption). Adding one for a single column, for a v1 admin panel with a handful of accounts, was judged out of proportion — but this is exactly the kind of thing Working Rule 6 says to log rather than silently ship.

**Tracked for:** `docs/SECURITY_GAPS.md` carries this as an open item — before this handles a real admin population at scale, envelope-encrypt `mfa_secret` (e.g. via a KMS-backed key, decrypted only in `AdminAuthService`) rather than storing it in the clear.

## Decision 3: admin sessions are stateless, no refresh-token pair

Unlike the mobile app's access+refresh pair (§16, ADR 0004), admin access tokens (`core/security.py`'s `create_admin_access_token`) are a single stateless JWT with an 8-hour TTL (`admin_access_token_ttl_minutes`, default 480) and no revocation mechanism beyond expiry.

**Why:** Admin sessions are browser-based, used interactively for a bounded work session — re-authenticating with password + TOTP after 8 hours is a reasonable, simple UX cost that avoids building a second session/refresh-token model alongside the mobile one for comparatively low-volume, internal-tool traffic. `admin.logout` writes an audit entry but cannot revoke an already-issued token before its expiry (same tradeoff class as the mobile access token, see ADR 0004 — bounded by TTL, not instant).

## Consequences

- All 4 roles' access boundaries are verified for real over HTTP in `test_api_admin.py` (login -> MFA enrollment -> role-gated route access), not just unit-tested against the service layer.
- `scripts/create_admin.py` is the only way to provision an admin account (no public signup, per §29's implicit assumption that admin accounts are provisioned out-of-band) — seeds the account, MFA enrollment happens on that account's first real login.
