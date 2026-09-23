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
    """"Currently occupying a seat": admitted (or never needed
    admission) and not yet marked `removed`. Deliberately counts a
    participant who joined and later left too — `left_at` just means
    "not connected right now," not "gave up their seat" (they can
    rejoin), which is the more conservative reading for a capacity gate."""
    return sum(1 for p in participants if p.admission_status != "removed")


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
