"""
Unit tests for `app/domain/meetings/entitlements.py` — deliberately pure,
no database. `resolve_conference_entitlements`'s DB-touching branch (a
real `PlanService`) is covered indirectly by `test_meeting_service.py`'s
Conference Room plan tests instead; what's tested here is the actual
business-rule math (clamping, capacity, cap-exceeded, tool lookup) in
isolation, which is the whole point of keeping this module dependency-free.
"""

import uuid
from datetime import UTC, datetime

from app.domain.billing.conference_plans import ConferenceEntitlements
from app.domain.meetings.entitlements import (
    clamp_duration_minutes,
    count_active_participants,
    guest_capacity_exceeded,
    has_tool,
    total_minutes_exceeds_cap,
)
from app.models.meetings import MeetingParticipant


def _entitlements(**overrides: object) -> ConferenceEntitlements:
    defaults: dict[str, object] = {
        "max_guests": 25,
        "max_duration_minutes": 180,
        "max_meetings_per_month": None,
        "tools": frozenset({"recording"}),
    }
    defaults.update(overrides)
    return ConferenceEntitlements(**defaults)  # type: ignore[arg-type]


def _participant(
    *,
    admission_status: str = "admitted",
    joined_at: datetime | None = None,
    left_at: datetime | None = None,
) -> MeetingParticipant:
    return MeetingParticipant(
        meeting_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role="participant",
        livekit_participant_identity=str(uuid.uuid4()),
        admission_status=admission_status,
        joined_at=joined_at,
        left_at=left_at,
    )


class TestClampDurationMinutes:
    def test_clamps_down_to_plan_cap(self) -> None:
        assert clamp_duration_minutes(300, _entitlements(max_duration_minutes=180)) == 180

    def test_leaves_shorter_requests_untouched(self) -> None:
        assert clamp_duration_minutes(60, _entitlements(max_duration_minutes=180)) == 60

    def test_no_cap_means_no_clamp(self) -> None:
        assert clamp_duration_minutes(1000, _entitlements(max_duration_minutes=None)) == 1000

    def test_no_requested_duration_passes_through(self) -> None:
        assert clamp_duration_minutes(None, _entitlements(max_duration_minutes=180)) is None


class TestTotalMinutesExceedsCap:
    def test_exceeds(self) -> None:
        assert total_minutes_exceeds_cap(200, _entitlements(max_duration_minutes=180)) is True

    def test_within_cap(self) -> None:
        assert total_minutes_exceeds_cap(150, _entitlements(max_duration_minutes=180)) is False

    def test_at_exact_cap_does_not_exceed(self) -> None:
        assert total_minutes_exceeds_cap(180, _entitlements(max_duration_minutes=180)) is False

    def test_unlimited_never_exceeds(self) -> None:
        assert total_minutes_exceeds_cap(999_999, _entitlements(max_duration_minutes=None)) is False


class TestGuestCapacityExceeded:
    def test_at_cap_is_exceeded(self) -> None:
        assert guest_capacity_exceeded(5, max_guests=5) is True

    def test_below_cap_is_not_exceeded(self) -> None:
        assert guest_capacity_exceeded(4, max_guests=5) is False

    def test_unlimited_never_exceeded(self) -> None:
        assert guest_capacity_exceeded(10_000, max_guests=None) is False


class TestCountActiveParticipants:
    def test_counts_connected_and_waiting(self) -> None:
        participants = [
            _participant(admission_status="admitted", joined_at=datetime.now(UTC)),
            _participant(admission_status="waiting"),
            _participant(admission_status="removed"),
        ]
        assert count_active_participants(participants) == 2

    def test_admitted_but_never_actually_joined_does_not_count(self) -> None:
        # A participant row can exist as "admitted" with no joined_at yet
        # (e.g. a host's own row right after create_meeting, before they
        # ever call join()) — shouldn't occupy a seat until they actually connect.
        participants = [_participant(admission_status="admitted", joined_at=None)]
        assert count_active_participants(participants) == 0

    def test_someone_who_left_does_not_count(self) -> None:
        """The actual bug this guards against: `guest_join` mints a brand
        new participant row on every call (no way to recognize a
        returning guest), so a real person simply reconnecting — or a
        failed join being retried — must not permanently occupy a seat
        after they've left. Previously it did, and a handful of guests
        retrying a join could exhaust a whole meeting's guest cap with
        nobody actually in the room."""
        now = datetime.now(UTC)
        participants = [
            _participant(admission_status="admitted", joined_at=now, left_at=now),
        ]
        assert count_active_participants(participants) == 0

    def test_currently_connected_counts(self) -> None:
        participants = [
            _participant(admission_status="admitted", joined_at=datetime.now(UTC), left_at=None),
        ]
        assert count_active_participants(participants) == 1

    def test_removed_never_counts_even_if_still_connected(self) -> None:
        participants = [
            _participant(admission_status="removed", joined_at=datetime.now(UTC), left_at=None),
        ]
        assert count_active_participants(participants) == 0

    def test_waiting_participant_who_left_does_not_count(self) -> None:
        now = datetime.now(UTC)
        participants = [_participant(admission_status="waiting", left_at=now)]
        assert count_active_participants(participants) == 0

    def test_empty_list(self) -> None:
        assert count_active_participants([]) == 0


class TestHasTool:
    def test_present(self) -> None:
        assert has_tool(_entitlements(tools=frozenset({"recording"})), "recording") is True

    def test_absent(self) -> None:
        assert has_tool(_entitlements(tools=frozenset({"recording"})), "breakout_rooms") is False


# A quick sanity check that `ConferenceEntitlements` (a plain dataclass,
# imported by both this module and `service.py`) round-trips its own
# `has_tool` helper the same way `entitlements.has_tool` does above —
# guards against the two ever drifting if one gets refactored.
def test_conference_entitlements_has_tool_matches_free_function() -> None:
    ent = _entitlements(tools=frozenset({"polls_qna"}))
    assert ent.has_tool("polls_qna") == has_tool(ent, "polls_qna")


def test_now_is_timezone_aware_for_sanity() -> None:
    # Not testing the module above — just guards a footgun every function
    # in this file's sibling (`analytics.py`) relies on: comparing an
    # aware `joined_at`/`left_at` against a naive `as_of` raises, so every
    # caller must pass `datetime.now(UTC)`, never `datetime.now()`.
    assert datetime.now(UTC).tzinfo is not None
