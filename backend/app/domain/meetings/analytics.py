"""
Meeting attendance analytics — a new Conference Room feature (Premium/
Enterprise, gated via `conference.tools` including `"analytics"`, see
`app/domain/billing/conference_plans.py`). Computed entirely from
`meeting_participants.joined_at`/`left_at`, which every meeting already
records — no new table, no new tracking. Kept as pure functions over
already-loaded rows (no I/O) so it's directly unit-testable without a
database, same reasoning as `entitlements.py`.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.models.meetings import MeetingParticipant


@dataclass(frozen=True)
class ParticipantAttendance:
    participant_id: uuid.UUID
    display_name: str
    role: str
    is_guest: bool
    joined_at: datetime | None
    left_at: datetime | None
    # Still-present participants (`left_at is None` but `joined_at` set)
    # are counted up to `as_of` — a live meeting's report is "as of now,"
    # not "0 seconds so far."
    attended_seconds: int


@dataclass(frozen=True)
class MeetingAnalyticsReport:
    meeting_id: uuid.UUID
    as_of: datetime
    # A waiting-room participant who was never admitted counts here but
    # not in `unique_attendees` — invited/attempted vs. actually present.
    total_participant_rows: int
    unique_attendees: int
    guest_attendees: int
    total_attendance_seconds: int
    average_attendance_seconds: float
    # A real sweep-line max-concurrency count, not an approximation —
    # the actual answer to "how many people were in the room at once,
    # at the busiest point," which peak headcount alone (e.g. a live
    # participant count polled once) can't reconstruct after the fact.
    peak_concurrent_attendees: int
    attendees: list[ParticipantAttendance] = field(default_factory=list)


def _attended_seconds(
    joined_at: datetime | None, left_at: datetime | None, as_of: datetime
) -> int:
    if joined_at is None:
        return 0
    end = left_at if left_at is not None else as_of
    if end <= joined_at:
        return 0
    return int((end - joined_at).total_seconds())


def _peak_concurrent(participants: list[MeetingParticipant], as_of: datetime) -> int:
    """Classic sweep-line: +1 at each join, -1 at each leave (or `as_of`
    for someone still present), sorted by time, tracking the running
    total's maximum. O(n log n), fine at meeting-room scale (at most a
    few hundred participant rows)."""
    events: list[tuple[datetime, int]] = []
    for p in participants:
        if p.joined_at is None:
            continue
        events.append((p.joined_at, 1))
        end = p.left_at if p.left_at is not None else as_of
        if end > p.joined_at:
            events.append((end, -1))
    # Process leaves before joins that land on the exact same instant,
    # so a same-timestamp handoff doesn't get double-counted as +2.
    events.sort(key=lambda e: (e[0], e[1]))
    running = 0
    peak = 0
    for _, delta in events:
        running += delta
        peak = max(peak, running)
    return peak


def build_meeting_analytics(
    *,
    meeting_id: uuid.UUID,
    participants: list[MeetingParticipant],
    as_of: datetime,
) -> MeetingAnalyticsReport:
    attendees = [
        ParticipantAttendance(
            participant_id=p.id,
            display_name=p.guest_display_name or str(p.user_id),
            role=p.role,
            is_guest=p.user_id is None,
            joined_at=p.joined_at,
            left_at=p.left_at,
            attended_seconds=_attended_seconds(p.joined_at, p.left_at, as_of),
        )
        for p in participants
        if p.admission_status != "removed"
    ]
    actually_attended = [a for a in attendees if a.joined_at is not None]
    total_seconds = sum(a.attended_seconds for a in actually_attended)
    return MeetingAnalyticsReport(
        meeting_id=meeting_id,
        as_of=as_of,
        total_participant_rows=len(attendees),
        unique_attendees=len(actually_attended),
        guest_attendees=sum(1 for a in actually_attended if a.is_guest),
        total_attendance_seconds=total_seconds,
        average_attendance_seconds=(
            total_seconds / len(actually_attended) if actually_attended else 0.0
        ),
        peak_concurrent_attendees=_peak_concurrent(
            [p for p in participants if p.admission_status != "removed"], as_of
        ),
        attendees=attendees,
    )
