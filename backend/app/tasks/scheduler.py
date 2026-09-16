"""
Scheduled maintenance sweeps — wired into `main.py`'s lifespan via
APScheduler's `AsyncIOScheduler`. This is the in-process, single-instance
evolution path documented in `README.md` (this directory's original plan
was a Redis-backed queue, per CLAUDE.md's Redis lock-in) — no Redis binary
is available in this environment, and a single backend process is all
this phase's scale needs, the same reasoning already applied to
`ConnectionManager` and `InMemoryRateLimiter`.

Each job opens its own short-lived DB session (`session_scope`) rather
than sharing one across runs — jobs fire independently and shouldn't be
able to interfere with each other's transactions.
"""

from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import get_settings
from app.core.db import session_scope
from app.domain.account.service import AccountLifecycleService
from app.domain.messaging.service import MessagingService
from app.domain.sos.service import SosService
from app.repositories.admin import AuditLogRepository, SystemConfigRepository
from app.repositories.circle import BlockRepository, ContactRepository
from app.repositories.conversations import ConversationMemberRepository, ConversationRepository
from app.repositories.crypto import (
    IdentityKeyRepository,
    OneTimePrekeyRepository,
    SenderKeyRepository,
    SignedPrekeyRepository,
)
from app.repositories.devices import (
    AccountRecoveryRequestRepository,
    DeviceRepository,
    LoginAttemptRepository,
)
from app.repositories.location import LocationPingRepository
from app.repositories.messages import (
    MediaObjectRepository,
    MessageReceiptRepository,
    MessageRepository,
)
from app.repositories.sos import SosEventRepository, SosNotificationRepository
from app.repositories.users import NextOfKinRepository, UserRepository
from app.services.factory import get_push_provider, get_sms_provider, get_storage_provider
from app.services.ratelimit.memory import rate_limiter
from app.services.realtime.websocket_manager import connection_manager

# §34.2: login_attempts and account_recovery_requests are both retained 12
# months, then hard-deleted.
RETENTION_DAYS = 365


async def purge_expired_messages() -> int:
    """§7.3 disappearing messages — tombstones ciphertext past its TTL."""
    async with session_scope() as session:
        service = MessagingService(
            identity_keys=IdentityKeyRepository(session),
            signed_prekeys=SignedPrekeyRepository(session),
            one_time_prekeys=OneTimePrekeyRepository(session),
            sender_keys=SenderKeyRepository(session),
            conversations=ConversationRepository(session),
            conversation_members=ConversationMemberRepository(session),
            messages=MessageRepository(session),
            message_receipts=MessageReceiptRepository(session),
            media_objects=MediaObjectRepository(session),
            devices=DeviceRepository(session),
            blocks=BlockRepository(session),
            contacts=ContactRepository(session),
            storage_provider=get_storage_provider(get_settings()),
            connection_manager=connection_manager,
        )
        return await service.purge_expired_messages()


async def escalate_armed_sos_events() -> int:
    """§26 — an armed SOS event whose cancel window has elapsed without a
    cancellation gets escalated (notify Circle + next-of-kin)."""
    async with session_scope() as session:
        service = SosService(
            sos_events=SosEventRepository(session),
            sos_notifications=SosNotificationRepository(session),
            contacts=ContactRepository(session),
            next_of_kin=NextOfKinRepository(session),
            devices=DeviceRepository(session),
            users=UserRepository(session),
            system_config=SystemConfigRepository(session),
            push_provider=get_push_provider(get_settings()),
            sms_provider=get_sms_provider(get_settings()),
            rate_limiter=rate_limiter,
        )
        now = datetime.now(UTC)
        escalated = 0
        for event in await SosEventRepository(session).list_armed():
            if now >= event.triggered_at + timedelta(seconds=event.cancel_window_seconds):
                await service.escalate(event_id=event.id)
                escalated += 1
        return escalated


async def purge_expired_location_pings() -> int:
    """§25/§34.2 — location pings past their share's expiry, plus a
    24-hour grace period (see `LocationPingRepository.purge_expired`)."""
    async with session_scope() as session:
        return await LocationPingRepository(session).purge_expired()


async def purge_old_login_attempts_and_recovery_requests() -> tuple[int, int]:
    """§34.2 — both retained 12 months, then hard-deleted."""
    async with session_scope() as session:
        cutoff = datetime.now(UTC) - timedelta(days=RETENTION_DAYS)
        login_attempts_purged = await LoginAttemptRepository(session).purge_older_than(cutoff)
        recovery_requests_purged = await AccountRecoveryRequestRepository(
            session
        ).purge_older_than(cutoff)
        return login_attempts_purged, recovery_requests_purged


async def process_scheduled_account_deletions() -> int:
    """§34.2 — hard-deletes accounts whose deactivation/ban grace window
    has elapsed."""
    async with session_scope() as session:
        service = AccountLifecycleService(
            users=UserRepository(session), audit_log=AuditLogRepository(session)
        )
        return await service.process_scheduled_deletions()


def start_scheduler() -> AsyncIOScheduler:
    """
    Called once from `main.py`'s lifespan. Intervals are deliberately
    conservative (minutes, not seconds) — none of these sweeps are
    latency-sensitive; SOS escalation's own timeliness comes from the
    cancel window itself (§26 default 10s), not from how often this job
    polls for events already past it.
    """
    scheduler = AsyncIOScheduler()
    scheduler.add_job(purge_expired_messages, "interval", minutes=15, id="purge_expired_messages")
    scheduler.add_job(
        escalate_armed_sos_events, "interval", seconds=30, id="escalate_armed_sos_events"
    )
    scheduler.add_job(
        purge_expired_location_pings, "interval", hours=1, id="purge_expired_location_pings"
    )
    scheduler.add_job(
        purge_old_login_attempts_and_recovery_requests,
        "interval",
        hours=24,
        id="purge_old_login_attempts_and_recovery_requests",
    )
    scheduler.add_job(
        process_scheduled_account_deletions,
        "interval",
        hours=1,
        id="process_scheduled_account_deletions",
    )
    scheduler.start()
    return scheduler
