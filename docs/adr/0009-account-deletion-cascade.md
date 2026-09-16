# ADR 0009: Account hard-delete is one DELETE, not a table-by-table walk

Status: Accepted (Phase 8)

## Context

docs/DITSALA_MASTER_SPEC.md §34.2 requires that on account deletion (30-day grace after self-service deactivation, or immediate-unless-held after a ban), "all P0–P2 data" is hard-deleted. A naive implementation would enumerate every table referencing a user and delete rows from each, in dependency order, before finally deleting the `users` row itself.

## Decision

`AccountLifecycleService.process_scheduled_deletions` does exactly one thing per due account: `await self._users.delete(user)`. Every one of the 27 foreign keys across this schema that reference `users.id` was already declared `ondelete="CASCADE"` back in Phase 1 (`models/*.py`) — devices, sessions, messages, contacts, reports, location shares, KYC records, everything. Deleting the `users` row *is* the cascade; Postgres does the table-by-table work the spec describes, transactionally and atomically, without application code re-deriving the dependency graph.

**The one deliberate exception**: `audit_log.actor_id`/`target_id` are plain UUID columns with no foreign key at all (see `models/admin.py`'s own docstring: "must outlive the account it references"). §34.2 is explicit that a deletion's own audit trail is P3 and "outlives the deletion" — the missing FK is what makes that possible; a `CASCADE` FK there would silently erase the very record required to prove the deletion happened. `AccountLifecycleService` writes the `account.hard_deleted` audit entry immediately before the delete, in the same transaction.

## Consequences

- Adding a new table with a `users.id` foreign key gets deletion-cascade behavior for free *only if* that FK is declared `ondelete="CASCADE"` — this is now a schema-review checklist item, not something `AccountLifecycleService` needs to know about or be updated for.
- A table that must survive a user's deletion (like `audit_log`) needs the same treatment: no FK, or `ondelete="SET NULL"`/`"RESTRICT"` with an explicit reason recorded in that model's docstring, same as `audit_log`'s.
- This does mean deleting a `User` is irreversible and total the moment it runs — the actual safety net is entirely upstream of this method: the 30-day `hard_delete_after` grace window and `AccountLifecycleService.cancel_deactivation`, not anything inside the delete itself.
