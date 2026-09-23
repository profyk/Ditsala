"""
Unit tests for `app/domain/meetings/analytics.py` — pure, no database.
Builds `MeetingParticipant` instances directly (never persisted) since
`build_meeting_analytics` only ever reads already-loaded attributes.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.domain.meetings.analytics import build_meeting_analytics
from app.models.meetings import MeetingParticipant

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _participant(
    *,
    role: str = "participant",
    is_guest: bool = False,
    joined_at: datetime | None = None,
    left_at: datetime | None = None,
    admission_status: str = "admitted",
) -> MeetingParticipant:
    p = MeetingParticipant(
        meeting_id=uuid.uuid4(),
        user_id=None if is_guest else uuid.uuid4(),
        guest_display_name="Guest" if is_guest else None,
        role=role,
        livekit_participant_identity=str(uuid.uuid4()),
        admission_status=admission_status,
        joined_at=joined_at,
        left_at=left_at,
    )
    p.id = uuid.uuid4()
    return p


def test_empty_meeting_has_zeroed_report() -> None:
    report = build_meeting_analytics(meeting_id=uuid.uuid4(), participants=[], as_of=_T0)
    assert report.unique_attendees == 0
    assert report.guest_attendees == 0
    assert report.total_attendance_seconds == 0
    assert report.average_attendance_seconds == 0.0
    assert report.peak_concurrent_attendees == 0


def test_never_joined_waiting_participant_counted_in_rows_not_attendance() -> None:
    participants = [_participant(joined_at=None, admission_status="waiting")]
    report = build_meeting_analytics(meeting_id=uuid.uuid4(), participants=participants, as_of=_T0)
    assert report.total_participant_rows == 1
    assert report.unique_attendees == 0


def test_removed_participant_excluded_entirely() -> None:
    participants = [
        _participant(joined_at=_T0, left_at=_T0 + timedelta(minutes=5)),
        _participant(joined_at=_T0, admission_status="removed"),
    ]
    report = build_meeting_analytics(meeting_id=uuid.uuid4(), participants=participants, as_of=_T0)
    assert report.total_participant_rows == 1
    assert report.unique_attendees == 1


def test_still_present_participant_counts_up_to_as_of() -> None:
    as_of = _T0 + timedelta(minutes=10)
    participants = [_participant(joined_at=_T0, left_at=None)]
    report = build_meeting_analytics(
        meeting_id=uuid.uuid4(), participants=participants, as_of=as_of
    )
    assert report.attendees[0].attended_seconds == 600
    assert report.total_attendance_seconds == 600


def test_guest_attendee_counted_separately() -> None:
    participants = [
        _participant(joined_at=_T0, left_at=_T0 + timedelta(minutes=1), is_guest=True),
        _participant(joined_at=_T0, left_at=_T0 + timedelta(minutes=1), is_guest=False),
    ]
    report = build_meeting_analytics(meeting_id=uuid.uuid4(), participants=participants, as_of=_T0)
    assert report.unique_attendees == 2
    assert report.guest_attendees == 1


def test_average_attendance_seconds() -> None:
    participants = [
        _participant(joined_at=_T0, left_at=_T0 + timedelta(minutes=10)),
        _participant(joined_at=_T0, left_at=_T0 + timedelta(minutes=20)),
    ]
    report = build_meeting_analytics(meeting_id=uuid.uuid4(), participants=participants, as_of=_T0)
    # (600 + 1200) / 2 = 900
    assert report.average_attendance_seconds == 900.0


def test_peak_concurrency_sweep_line() -> None:
    # A: [0, 30) — present the whole window.
    # B: [10, 20) — overlaps A only.
    # C: [25, 40) — overlaps A only, after B has left.
    # Peak should be 2 (A+B during [10,20), A+C during [25,30)), never 3.
    participants = [
        _participant(joined_at=_T0, left_at=_T0 + timedelta(minutes=30)),
        _participant(
            joined_at=_T0 + timedelta(minutes=10), left_at=_T0 + timedelta(minutes=20)
        ),
        _participant(
            joined_at=_T0 + timedelta(minutes=25), left_at=_T0 + timedelta(minutes=40)
        ),
    ]
    report = build_meeting_analytics(meeting_id=uuid.uuid4(), participants=participants, as_of=_T0)
    assert report.peak_concurrent_attendees == 2


def test_peak_concurrency_all_overlapping() -> None:
    participants = [
        _participant(joined_at=_T0, left_at=_T0 + timedelta(minutes=60)) for _ in range(4)
    ]
    report = build_meeting_analytics(meeting_id=uuid.uuid4(), participants=participants, as_of=_T0)
    assert report.peak_concurrent_attendees == 4


def test_display_name_falls_back_to_user_id_when_not_a_guest() -> None:
    p = _participant(joined_at=_T0, left_at=_T0 + timedelta(minutes=1), is_guest=False)
    report = build_meeting_analytics(meeting_id=uuid.uuid4(), participants=[p], as_of=_T0)
    assert report.attendees[0].display_name == str(p.user_id)


def test_display_name_uses_guest_label_when_guest() -> None:
    p = _participant(joined_at=_T0, left_at=_T0 + timedelta(minutes=1), is_guest=True)
    report = build_meeting_analytics(meeting_id=uuid.uuid4(), participants=[p], as_of=_T0)
    assert report.attendees[0].display_name == "Guest"
