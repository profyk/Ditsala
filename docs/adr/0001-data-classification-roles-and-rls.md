# ADR 0001: Data classification enforced via DB roles + RLS, not just app code

Status: Accepted (Phase 1)

## Context

`docs/DITSALA_MASTER_SPEC.md` §5 requires the P0-P3 data classification to be enforced at the database level, not only trusted to application code — "defense in depth against a compromised/misconfigured query." This needed concrete Postgres mechanics.

## Decision

- Four Postgres roles (`app_backend`, `app_admin_readonly`, `app_admin_kyc_reviewer`, `app_maintenance`), created `NOLOGIN` by the migration — credentials are provisioned out-of-band, never in version control.
- Column-level `GRANT`s (not just table-level) for `users` and `sessions`, since they mix P0/P1 columns with P3 ones in the same table.
- RLS on `messages`, `conversation_members`, `location_shares`, `location_pings`, scoped by a session-local variable (`app.current_user_id`) the Phase 2+ auth middleware must set via `set_config(..., true)` with a bound parameter — plain `SET LOCAL x = $1` doesn't accept bind parameters, and string-interpolating a UUID into SQL text isn't a habit worth starting.
- A `SECURITY DEFINER` helper function (`is_conversation_member`) for the one case (`conversation_members` checking its own membership) where a policy would otherwise query the table it's protecting and Postgres correctly rejects that as infinite recursion.
- Every `current_setting(...)` read is wrapped in `NULLIF(..., '')` before casting to `uuid` — `RESET` on a custom (undeclared) GUC can leave it as an empty string rather than truly unset, and casting `''::uuid` throws. This keeps the fail-closed default (no session variable → zero rows) working regardless of that edge case.
- `app_maintenance` gets `BYPASSRLS` for background jobs (retention sweeps, push fan-out) that are cross-user by nature.

## Consequences

- Running the classification migration requires the connecting role to have `CREATEROLE` and `BYPASSRLS` — true of any real deploy-time role, but a hand-rolled local Postgres needs one-time manual bootstrapping (see `CLAUDE.md` "Local dev"). The official Postgres Docker image's `POSTGRES_USER` is a superuser already, so `docker-compose.yml` and CI need no extra steps.
- The RLS policies on `conversation_members` are read-only-by-membership plus write-your-own-row for now; adding/removing *other* members (group-admin actions) needs a policy refinement when Phase 4 builds that feature — noted inline in the migration.
- All of this was verified against a real Postgres via `app/tests/test_rls.py` (proves isolation, not just that grants exist) — this caught the recursion bug and the empty-string GUC edge case before either could reach a later phase.
