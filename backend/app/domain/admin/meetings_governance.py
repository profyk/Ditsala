"""
Admin visibility and control over Conference Room meetings, platform-
wide — a genuinely new admin capability. Every meeting-scoped action
everywhere else in this codebase (`app/domain/meetings/service.py`) is
host/co-host/participant-scoped; admin previously had zero visibility
into meetings at all. Kept as its own service, not folded into the
already-large `AdminService`, matching the existing precedent of
`KycReviewService` being split out for its own distinct concern.

Mutations (extend/end) delegate to `MeetingService.admin_extend_duration`/
`admin_end_meeting` — the actual "how a meeting's duration/status
changes" logic stays in one place — and add the admin-specific concern:
audit logging via the same generic `audit_log` every other admin
mutation in this codebase uses (no separate table).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.meetings.analytics import MeetingAnalyticsReport, build_meeting_analytics
from app.domain.meetings.service import MeetingError, MeetingService
from app.models.admin import AuditLog
from app.models.meetings import Meeting, MeetingParticipant
from app.repositories.admin import AuditLogRepository
from app.repositories.meetings import MeetingParticipantRepository, MeetingRepository

LIVE_AND_SCHEDULED_STATUSES = ("live", "scheduled")


class MeetingGovernanceError(Exception):
    """Raised for governance preconditions a caller should turn into a 4xx, not a 500."""


@dataclass(frozen=True)
class MeetingWithHostContext:
    """A meeting plus the two counts an admin list view actually needs at
    a glance — computed here rather than in the response schema so a
    second round-trip per row isn't needed."""

    meeting: Meeting
    active_participant_count: int


class AdminMeetingGovernanceService:
    def __init__(
        self,
        *,
        meetings: MeetingRepository,
        participants: MeetingParticipantRepository,
        meeting_service: MeetingService,
        audit_log: AuditLogRepository,
    ) -> None:
        self._meetings = meetings
        self._participants = participants
        self._meeting_service = meeting_service
        self._audit_log = audit_log

    async def _log(
        self,
        admin_id: uuid.UUID,
        action: str,
        *,
        target_id: uuid.UUID,
        metadata_json: dict[str, Any] | None = None,
    ) -> None:
        await self._audit_log.add(
            AuditLog(
                created_at=datetime.now(UTC),
                actor_type="admin",
                actor_id=admin_id,
                action=action,
                target_type="meeting",
                target_id=target_id,
                metadata_json=metadata_json,
            )
        )

    async def list_live_and_scheduled(
        self, *, limit: int = 200
    ) -> list[MeetingWithHostContext]:
        meetings = await self._meetings.list_by_statuses(
            list(LIVE_AND_SCHEDULED_STATUSES), limit=limit
        )
        result: list[MeetingWithHostContext] = []
        for meeting in meetings:
            participants = await self._participants.list_for_meeting(meeting.id)
            active = sum(1 for p in participants if p.left_at is None and p.joined_at is not None)
            result.append(MeetingWithHostContext(meeting=meeting, active_participant_count=active))
        return result

    async def get_meeting(self, meeting_id: uuid.UUID) -> Meeting:
        try:
            return await self._meeting_service.get_meeting(meeting_id)
        except MeetingError as exc:
            raise MeetingGovernanceError(str(exc)) from exc

    async def list_participants(self, meeting_id: uuid.UUID) -> list[MeetingParticipant]:
        await self.get_meeting(meeting_id)  # 404s a bad id before an empty-list false positive
        return await self._participants.list_for_meeting(meeting_id)

    async def get_analytics(self, meeting_id: uuid.UUID) -> MeetingAnalyticsReport:
        participants = await self.list_participants(meeting_id)
        return build_meeting_analytics(
            meeting_id=meeting_id, participants=participants, as_of=datetime.now(UTC)
        )

    async def extend_meeting(
        self, *, admin_id: uuid.UUID, meeting_id: uuid.UUID, additional_minutes: int, reason: str
    ) -> Meeting:
        try:
            meeting = await self._meeting_service.admin_extend_duration(
                meeting_id=meeting_id, additional_minutes=additional_minutes
            )
        except MeetingError as exc:
            raise MeetingGovernanceError(str(exc)) from exc
        await self._log(
            admin_id,
            "admin.meeting.extended",
            target_id=meeting_id,
            metadata_json={"additional_minutes": additional_minutes, "reason": reason},
        )
        return meeting

    async def end_meeting(
        self, *, admin_id: uuid.UUID, meeting_id: uuid.UUID, reason: str
    ) -> Meeting:
        try:
            meeting = await self._meeting_service.admin_end_meeting(meeting_id=meeting_id)
        except MeetingError as exc:
            raise MeetingGovernanceError(str(exc)) from exc
        await self._log(
            admin_id, "admin.meeting.ended", target_id=meeting_id, metadata_json={"reason": reason}
        )
        return meeting
