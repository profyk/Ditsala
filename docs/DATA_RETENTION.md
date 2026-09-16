# DITSALA Data Retention Policy

*Operationalizes the retention windows fixed in docs/DITSALA_MASTER_SPEC.md §34.2. This document implements those numbers — it does not re-derive them. See that spec section for the POPIA/Botswana DPA storage-limitation reasoning behind each figure.*

## 1. Retention table

| Data | Retention window | Enforcement mechanism |
|---|---|---|
| KYC document image / liveness selfie image | **Zero retention, ever** — never stored by DITSALA in the first place | Architectural: `KycDocument`/`KycFaceVerification` store only `smile_id_job_id` + `result_summary` (scores/decision); no image field exists in the schema |
| `location_pings` | Duration of the active `location_shares` grant, plus 24 hours | `LocationPingRepository.purge_expired(grace_hours=24)`, run hourly by `app/tasks/scheduler.py` |
| `location_pings` attached to an `sos_events` record | 90 days post-event | **Not yet implemented** — see `docs/SECURITY_GAPS.md`; the current schema has no FK linking a ping to the SOS event it was captured during, so this exception cannot be enforced today. Tracked as a follow-up. |
| `audit_log` | 5 years | No automated purge yet (5 years exceeds this project's operational horizon so far) — a future scheduled job should purge rows past this age once the table has meaningful volume |
| `login_attempts` | 12 months | `LoginAttemptRepository.purge_older_than`, run daily by `app/tasks/scheduler.py` |
| `account_recovery_requests` | 12 months | `AccountRecoveryRequestRepository.purge_older_than`, run daily by `app/tasks/scheduler.py` |
| Account data (P0-P2) after self-service deactivation | 30-day reversible grace window, then hard-deleted | `AccountLifecycleService.request_deactivation` sets `hard_delete_after`; `process_scheduled_account_deletions` (hourly sweep) hard-deletes once elapsed. Reversible via `AccountLifecycleService.cancel_deactivation` within the window. |
| Account data (P0-P2) after a ban | Immediate soft-delete, hard-delete after any legal hold expires (default: no hold) | `AdminService.action_report`/`KycReviewService.reject` set `hard_delete_after = now()` on a ban, so it is picked up by the next hourly sweep — same code path as self-service deactivation |
| `audit_log` entry recording that a deletion occurred | Survives the account deletion it records — retained under the `audit_log` schedule above | `audit_log` has **no foreign key** to `users.id` by design (see `docs/adr/0009-account-deletion-cascade.md`), so it is never cascade-deleted alongside the account |

## 2. How deletion actually works

Deleting a `User` row is a single `DELETE` — every one of the 27 foreign keys in this schema that reference `users.id` is declared `ON DELETE CASCADE`, so Postgres itself removes every dependent row (messages, devices, sessions, contacts, location shares, KYC records, everything) in one transaction. See `docs/adr/0009-account-deletion-cascade.md` for the full reasoning, including why `audit_log` is the one deliberate exception.

## 3. Known gaps against this schedule

- **SOS-linked location pings' 90-day exception is not enforced** — see the table above and `docs/SECURITY_GAPS.md`.
- **`audit_log`'s 5-year purge has no scheduled job yet** — not urgent at current data volume, but should be added before the table's age approaches that window in production.
- **Data-subject "access" requests do not yet produce an automatic export** — see `docs/SECURITY_GAPS.md`'s entry on `ComplianceService`.
