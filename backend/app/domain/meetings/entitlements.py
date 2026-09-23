"""
Conference Room plan enforcement — kept separate from `service.py`
(already large) so the actual business rules ("how many guests, how
long, which tools") are one small, dependency-light, easily-unit-tested
place rather than interleaved with LiveKit/repository calls. See
`app/domain/billing/conference_plans.py` for the plan/entitlement
vocabulary this resolves against.

Every function below is either pure (no I/O — trivially unit-testable
with no database, unlike almost everything else in this codebase) or a
thin resolution step that degrades to the permissive `DEFAULT_ENTITLEMENTS`
whenever a `PlanService` isn't wired — see `resolve_conference_entitlements`.
That degrade-to-permissive behavior is what keeps every existing
`MeetingService` test (none of which construct a `PlanService`) passing
unchanged: enforcement only turns on where `app/api/v1/deps.py` actually
wires a real `PlanService` in, i.e. production.
"""

from app.domain.billing.conference_plans import (
    DEFAULT_ENTITLEMENTS,
    MAX_DURATION_MINUTES_KEY,
    MAX_GUESTS_KEY,
    MAX_MEETINGS_PER_MONTH_KEY,
    TOOLS_KEY,
    ConferenceEntitlements,
)
from app.domain.billing.plans import PlanService
from app.models.accounts import User
from app.models.meetings import MeetingParticipant


async def resolve_conference_entitlements(
    plan_service: PlanService | None, host: User | None
) -> ConferenceEntitlements:
    """What the meeting's host's Conference plan actually grants.
    Permissive (`DEFAULT_ENTITLEMENTS` — unlimited, every tool on) when
    `plan_service` is `None` (not wired — every existing test) or `host`
    is `None` (a lookup for a host whose account was hard-deleted, e.g.
    an orphaned meeting row — deny-by-locking-them-out would be a worse
    failure mode than just not capping it)."""
    if plan_service is None or host is None:
        return DEFAULT_ENTITLEMENTS
    plan_code = plan_service.resolve_conference_plan_code_for_user(host)
    max_guests = await plan_service.get_entitlement_by_plan_code(plan_code, MAX_GUESTS_KEY)
    max_duration_minutes = await plan_service.get_entitlement_by_plan_code(
        plan_code, MAX_DURATION_MINUTES_KEY
    )
    max_meetings_per_month = await plan_service.get_entitlement_by_plan_code(
        plan_code, MAX_MEETINGS_PER_MONTH_KEY
    )
    tools = await plan_service.get_entitlement_by_plan_code(plan_code, TOOLS_KEY, default=[])
    return ConferenceEntitlements(
        max_guests=max_guests,
        max_duration_minutes=max_duration_minutes,
        max_meetings_per_month=max_meetings_per_month,
        tools=frozenset(tools or []),
    )


def clamp_duration_minutes(
    requested_minutes: int | None, entitlements: ConferenceEntitlements
) -> int | None:
    """Scheduling longer than the plan allows doesn't reject the
    request — it silently clamps, same UX as most SaaS "your plan caps
    meetings at Xh" behavior (reject-outright would just mean a confusing
    422 on an otherwise-normal schedule action). `None` (no requested
    duration, or no plan cap) passes through unchanged."""
    if requested_minutes is None or entitlements.max_duration_minutes is None:
        return requested_minutes
    return min(requested_minutes, entitlements.max_duration_minutes)


def total_minutes_exceeds_cap(
    total_minutes: int, entitlements: ConferenceEntitlements
) -> bool:
    """Used by `extend_duration`, where clamping silently would be
    actively misleading (the host explicitly asked to add N minutes —
    silently giving them fewer with no error is worse than telling them
    their plan is the reason it stopped)."""
    if entitlements.max_duration_minutes is None:
        return False
    return total_minutes > entitlements.max_duration_minutes


def count_active_participants(participants: list[MeetingParticipant]) -> int:
    """"Currently occupying a seat right now" — a waiting-room guest
    (about to occupy one once admitted) plus anyone actively connected
    (joined and not yet left). Deliberately NOT a historical/cumulative
    count of every participant row that's ever existed: `guest_join`
    mints a brand-new row on every single call (it has no way to
    recognize a returning guest as "the same person" — no account, no
    session), so a handful of real people simply reconnecting, or
    retrying a failed join, would otherwise permanently ratchet up the
    count and exhaust a low-tier plan's guest cap with nobody actually
    in the room. That was this function's original design ("counts a
    participant who joined and later left too") — a real bug, caught by
    exactly that happening during normal use, not a hypothetical.

    `left_at` being set always excludes a participant, regardless of
    `admission_status` — including a still-`waiting` one: a guest who
    gives up and disconnects before ever being admitted (`page.tsx`
    calls `leaveAsParticipant` from `onDisconnected`, which only fires
    once actually connected — a `waiting` guest closing the tab before
    admission has no such signal today, a real, separate, smaller gap
    left open here) shouldn't hold their spot in line forever either,
    on the rare path where `left_at` does get set for one."""
    return sum(
        1
        for p in participants
        if p.left_at is None
        and (
            p.admission_status == "waiting"
            or (p.admission_status != "removed" and p.joined_at is not None)
        )
    )


def guest_capacity_exceeded(current_count: int, max_guests: int | None) -> bool:
    """Takes a plain `max_guests` cap rather than a full
    `ConferenceEntitlements` so the same check works both against a
    freshly-resolved entitlement and against `Meeting.max_participants`
    (the cap snapshotted at creation time — see that field's docstring),
    without needing to fabricate an `entitlements` object for the latter."""
    if max_guests is None:
        return False
    return current_count >= max_guests


def has_tool(entitlements: ConferenceEntitlements, tool_id: str) -> bool:
    return entitlements.has_tool(tool_id)
