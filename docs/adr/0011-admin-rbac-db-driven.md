# ADR 0011: Admin RBAC is DB-driven, not a hardcoded Python mapping

Status: Accepted (Phase 8, closes the simplification noted in ADR 0008)

## Context

ADR 0008 hardcoded the 4 launch admin roles' permissions as a Python constant (`domain/admin/rbac.py`'s `ROLE_PERMISSIONS`) rather than reading the `admin_role_permissions`/`admin_permissions` join tables Phase 1 already modeled, reasoning that no RBAC-management UI existed yet to populate them. That gap was tracked in `docs/SECURITY_GAPS.md`.

## Decision

`require_permission()` (`api/v1/admin_deps.py`) now checks `admin_role_permissions` directly via `AdminRoleRepository.role_has_permission(role_id, permission_name)` — a join against `admin_permissions` by name. Migration `7a3f2e9c1b4d` seeds both tables with a frozen snapshot of the same mapping ADR 0008's Python constant held, so this change is behavior-preserving: every existing test and every existing role's access stays identical, only the source of truth moves from code to data.

`domain/admin/rbac.py` keeps only the `Permission` enum — the canonical set of permission names every route references — since that's genuinely a compile-time-checked constant or grepped constant), not per-deployment configuration. The role -> permission *mapping* is what moved to the database.

## Consequences

- A `super_admin`-only RBAC management screen (still not built) can now change what a role can do by writing rows to `admin_role_permissions`, with no deploy required — this was the entire point of Phase 1 modeling those tables in the first place.
- Adding a brand new permission still requires a code change (a new `Permission` enum member, referenced by a new `require_permission(...)` call at a new route) — that part was never going to be data-driven, since a permission with no code checking it does nothing.
- Every RBAC-gated route's behavior is unchanged from before this ADR; `app/tests/test_api_admin.py`'s existing RBAC tests pass unmodified, since the seeded data reproduces the prior hardcoded mapping exactly.
