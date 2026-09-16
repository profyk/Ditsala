# tasks/

Scheduled maintenance sweeps: message expiry (§7.3), SOS escalation (§26), location-ping retention (§25/§34.2), login-attempt/recovery-request retention (§34.2), and the account hard-delete cascade sweep (§34.2).

**Originally planned as Redis-queue-backed background jobs** — this environment has no Redis binary available (same constraint documented for `ConnectionManager` and `InMemoryRateLimiter`), so `scheduler.py` runs these in-process via APScheduler's `AsyncIOScheduler`, started from `main.py`'s lifespan. This is single-instance only: running more than one backend process would run every sweep once per process, which is wasteful but not unsafe (every job here is idempotent — re-escalating an already-escalated SOS event, re-purging already-purged rows, etc. are all no-ops). Moving to a real distributed scheduler (or a Redis-backed queue with a leader-election lock) is the documented evolution path once this needs to run across more than one instance.

Each job opens its own DB session via `app.core.db.session_scope` and builds the same domain service a request handler would — no separate "task" code path duplicates business logic.
