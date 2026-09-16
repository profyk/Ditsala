"""
SOS / emergency escalation — docs/DITSALA_MASTER_SPEC.md §26. Lawful
basis: POPIA §11(1)(d) (processing necessary to protect a legitimate
interest of the data subject) — a deliberate, documented exception to
standing consent settings, triggered only by the user's own action.
Framework-agnostic per §3.3.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.domain.notifications.interfaces import PushProvider, SmsProvider
from app.domain.ratelimit.interfaces import RateLimiter
from app.models.location import SosEvent, SosNotification
from app.repositories.admin import SystemConfigRepository
from app.repositories.circle import ContactRepository
from app.repositories.devices import DeviceRepository
from app.repositories.sos import SosEventRepository, SosNotificationRepository
from app.repositories.users import NextOfKinRepository, UserRepository

DEFAULT_CANCEL_WINDOW_SECONDS = 10

# §32: "protect against griefing via repeated false SOS — still always
# allow genuine triggers through, tuned conservatively." Generous on
# purpose: a real emergency can involve several trigger attempts in an
# hour (poor signal, a struggle, a second person also triggering for the
# same user) — this catches scripted/automated abuse, not a distressed
# person retrying. See docs/adr/0010-rate-limiting-key-choice.md.
SOS_TRIGGER_LIMIT = 10
SOS_TRIGGER_WINDOW_SECONDS = 3600


class SosError(Exception):
    """Raised for SOS preconditions a caller should turn into a 4xx, not a 500."""


class SosService:
    def __init__(
        self,
        *,
        sos_events: SosEventRepository,
        sos_notifications: SosNotificationRepository,
        contacts: ContactRepository,
        next_of_kin: NextOfKinRepository,
        devices: DeviceRepository,
        users: UserRepository,
        system_config: SystemConfigRepository,
        push_provider: PushProvider,
        sms_provider: SmsProvider,
        rate_limiter: RateLimiter,
    ) -> None:
        self._sos_events = sos_events
        self._sos_notifications = sos_notifications
        self._contacts = contacts
        self._next_of_kin = next_of_kin
        self._devices = devices
        self._users = users
        self._system_config = system_config
        self._push = push_provider
        self._sms = sms_provider
        self._rate_limiter = rate_limiter

    async def _cancel_window_seconds(self) -> int:
        config = await self._system_config.get_by_key("sos_cancel_window_seconds")
        if config is not None:
            seconds = config.value.get("seconds")
            if isinstance(seconds, int):
                return seconds
        return DEFAULT_CANCEL_WINDOW_SECONDS

    async def trigger(
        self, *, user_id: uuid.UUID, last_known_location_ref: str | None = None
    ) -> SosEvent:
        await self._rate_limiter.hit(
            f"sos:trigger:{user_id}",
            limit=SOS_TRIGGER_LIMIT,
            window_seconds=SOS_TRIGGER_WINDOW_SECONDS,
        )
        return await self._sos_events.add(
            SosEvent(
                user_id=user_id,
                triggered_at=datetime.now(UTC),
                cancel_window_seconds=await self._cancel_window_seconds(),
                last_known_location_ref=last_known_location_ref,
            )
        )

    async def cancel(self, *, user_id: uuid.UUID, event_id: uuid.UUID) -> SosEvent:
        event = await self._sos_events.get(event_id)
        if event is None or event.user_id != user_id:
            raise SosError("No such SOS event.")
        if event.status != "armed":
            raise SosError(f"Cannot cancel an SOS event in status {event.status!r}.")
        if datetime.now(UTC) > event.triggered_at + timedelta(
            seconds=event.cancel_window_seconds
        ):
            raise SosError("The cancellation window has passed.")
        event.status = "cancelled"
        event.cancelled_at = datetime.now(UTC)
        return event

    async def escalate(self, *, event_id: uuid.UUID) -> SosEvent:
        """
        Called once the cancel window elapses without a cancellation —
        Phase 8 wires the actual scheduler (same deferred-scheduling
        pattern as `MessagingService.purge_expired_messages`). Idempotent:
        re-escalating an already-escalated/cancelled/resolved event is a
        no-op rather than double-notifying everyone.
        """
        event = await self._sos_events.get(event_id)
        if event is None:
            raise SosError("No such SOS event.")
        if event.status != "armed":
            return event
        if datetime.now(UTC) < event.triggered_at + timedelta(
            seconds=event.cancel_window_seconds
        ):
            raise SosError("Cannot escalate before the cancellation window elapses.")

        event.status = "escalated"
        for contact in await self._contacts.list_circle_for_user(event.user_id):
            await self._notify_circle_member(event, contact.contact_user_id)
        for kin in await self._next_of_kin.list_for_user(event.user_id):
            if kin.notified_on_sos:
                await self._sms.send_sms(
                    to_phone=kin.phone,
                    body="DITSALA emergency alert: someone who listed you as next of "
                    "kin has triggered an SOS. Please check on them.",
                )
        return event

    async def _notify_circle_member(self, event: SosEvent, notified_user_id: uuid.UUID) -> None:
        for device in await self._devices.list_for_user(notified_user_id):
            if device.revoked_at is None and device.push_token:
                await self._push.send_push(
                    push_token=device.push_token,
                    title="SOS Alert",
                    body="A Circle member has triggered an emergency alert.",
                    data={"sos_event_id": str(event.id)},
                )
                await self._sos_notifications.add(
                    SosNotification(
                        sos_event_id=event.id,
                        notified_user_id=notified_user_id,
                        notified_at=datetime.now(UTC),
                        channel="push",
                    )
                )
        user = await self._users.get(notified_user_id)
        if user is not None:
            await self._sms.send_sms(
                to_phone=user.phone,
                body="DITSALA emergency alert: a Circle member has triggered an SOS. "
                "Open the app for details.",
            )
            await self._sos_notifications.add(
                SosNotification(
                    sos_event_id=event.id,
                    notified_user_id=notified_user_id,
                    notified_at=datetime.now(UTC),
                    channel="sms",
                )
            )

    async def list_for_user(self, user_id: uuid.UUID) -> list[SosEvent]:
        return await self._sos_events.list_for_user(user_id)

    async def list_notifications(
        self, *, user_id: uuid.UUID, event_id: uuid.UUID
    ) -> list[SosNotification]:
        event = await self._sos_events.get(event_id)
        if event is None or event.user_id != user_id:
            raise SosError("No such SOS event.")
        return await self._sos_notifications.list_for_event(event_id)
