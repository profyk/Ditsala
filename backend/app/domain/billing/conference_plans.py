"""
Conference Room plan catalogue — the four tiers (Free/Pro/Premium/
Enterprise) an admin configures via `/admin/billing/plans/*`
(`PlanService`) and a host resolves against via
`PlanService.resolve_conference_plan_code_for_user`.

This module is deliberately just constants, no I/O: the real, mutable
source of truth is the `plans`/`entitlements` rows the seed migration
(`<conference plans and entitlements>`) inserts and an admin can change
afterwards from `apps/admin`'s Conference Plans page. What lives here is
narrower and doesn't drift with admin edits:

- the plan *codes* (stable identifiers other code branches on, e.g.
  `resolve_conference_plan_code_for_user`'s fallback)
- the entitlement *keys* (so a typo in a router/service doesn't silently
  no-op against a key the seed data never used)
- the known conference *tool ids* (so the admin UI can render checkboxes
  instead of asking someone to type a JSON array by hand, and so
  `app/domain/meetings/entitlements.py` has a fixed vocabulary to gate
  against)
- `DEFAULT_ENTITLEMENTS`, the permissive fallback used when no
  `PlanService` is wired at all (every existing test call site) or a
  plan/entitlement row is missing — unlimited, every tool on, so a
  misconfiguration never locks a real meeting out by accident.
"""

from dataclasses import dataclass, field

# --- plan codes (product="conference" in the `plans` table) -----------

FREE_PLAN_CODE = "conference_free"
PRO_PLAN_CODE = "conference_pro"
PREMIUM_PLAN_CODE = "conference_premium"
ENTERPRISE_PLAN_CODE = "conference_enterprise"

CONFERENCE_PLAN_CODES = (
    FREE_PLAN_CODE,
    PRO_PLAN_CODE,
    PREMIUM_PLAN_CODE,
    ENTERPRISE_PLAN_CODE,
)

# --- entitlement keys (`entitlements.key`, scoped under "conference.") -

# Matches the exact key name `Entitlement`'s own docstring (app/models/
# billing.py) and the admin Pricing page's placeholder text already used
# as their example — and `Meeting.max_participants`, the column this
# resolves into at `create_meeting` time.
MAX_GUESTS_KEY = "conference.max_participants"
MAX_DURATION_MINUTES_KEY = "conference.max_duration_minutes"
MAX_MEETINGS_PER_MONTH_KEY = "conference.max_meetings_per_month"
TOOLS_KEY = "conference.tools"

# --- known tool ids (`conference.tools`, a JSON array of these) -------
# Each one maps to a real, already-built `MeetingService` capability
# (docs/DITSALA_MEET_SPEC.md §9) — nothing here is aspirational. Only
# RECORDING, BREAKOUT_ROOMS, and ANALYTICS are actually enforced today
# (`app/domain/meetings/entitlements.py`'s `require_tool` call sites in
# `service.py`); the rest are informational — shown in the plans/tools
# comparison screen as "what this tier includes" even though the
# underlying endpoint doesn't (yet) check for them, same disclosed-cut
# pattern as everything else in this codebase that ships a real gap
# instead of a fake gate. TRANSLATION in particular is intentionally
# never gated — an explicit product decision (see CLAUDE.md's Conference
# Room section) that basic multilingual chat stays free on every tier.

TOOL_TRANSLATION = "translation"
TOOL_POLLS_AND_QNA = "polls_qna"
TOOL_RECORDING = "recording"
TOOL_TRANSCRIPTION = "transcription"
TOOL_AI_NOTES = "ai_notes"
TOOL_BREAKOUT_ROOMS = "breakout_rooms"
TOOL_WEBINAR_REGISTRATION = "webinar_registration"
TOOL_ANALYTICS = "analytics"
TOOL_PRIORITY_SUPPORT = "priority_support"

ALL_TOOL_IDS = (
    TOOL_TRANSLATION,
    TOOL_POLLS_AND_QNA,
    TOOL_RECORDING,
    TOOL_TRANSCRIPTION,
    TOOL_AI_NOTES,
    TOOL_BREAKOUT_ROOMS,
    TOOL_WEBINAR_REGISTRATION,
    TOOL_ANALYTICS,
    TOOL_PRIORITY_SUPPORT,
)

# Tools this codebase's `MeetingService` actually gates on today — see
# the module docstring above.
ENFORCED_TOOL_IDS = (TOOL_RECORDING, TOOL_BREAKOUT_ROOMS, TOOL_ANALYTICS)


@dataclass(frozen=True)
class ConferenceEntitlements:
    """What one plan actually grants — resolved from the four
    entitlement keys above via `app/domain/meetings/entitlements.py`'s
    `resolve_conference_entitlements`. `None` on either limit means
    "unlimited" (matches how `Meeting.scheduled_duration_minutes` and
    `Meeting.max_participants` already use `None` for "no cap")."""

    max_guests: int | None
    max_duration_minutes: int | None
    max_meetings_per_month: int | None
    tools: frozenset[str] = field(default_factory=frozenset)

    def has_tool(self, tool_id: str) -> bool:
        return tool_id in self.tools


# The permissive fallback — see module docstring's third paragraph.
DEFAULT_ENTITLEMENTS = ConferenceEntitlements(
    max_guests=None,
    max_duration_minutes=None,
    max_meetings_per_month=None,
    tools=frozenset(ALL_TOOL_IDS),
)
