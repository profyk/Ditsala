"""
Admin visibility and control over WebRTC calls (§27), platform-wide —
same new-capability shape as `AdminMeetingGovernanceService`
(`meetings_governance.py`): every call-scoped action elsewhere in this
codebase is participant-scoped, admin previously had zero visibility.
Kept as its own service for the same reason meetings governance is —
one small, distinct concern rather than folding into `AdminService`.

Unlike meetings, calls have no duration cap to extend — the only admin
override this covers is force-ending a live/ringing call (e.g. an abuse
report on an active call), which is all `docs/CLAUDE.md`'s own tracked
gap for this asked for. Ending delegates to `CallService.admin_end_call`
so the actual state-transition logic stays in one place; this service
adds the admin-specific concern of audit logging via the same generic
`audit_log` every other admin mutation uses.
"""

import uuid
from datetime import UTC, datetime

from app.domain.calls.service import CallError, CallService
from app.models.admin import AuditLog
from app.models.calls import Call
from app.repositories.admin import AuditLogRepository
from app.repositories.calls import CallRepository

LIVE_STATUSES = ("ringing", "active")


class CallGovernanceError(Exception):
    """Raised for governance preconditions a caller should turn into a 4xx, not a 500."""


class AdminCallGovernanceService:
    def __init__(
        self,
        *,
        calls: CallRepository,
        call_service: CallService,
        audit_log: AuditLogRepository,
    ) -> None:
        self._calls = calls
        self._call_service = call_service
        self._audit_log = audit_log

    async def list_live(self, *, limit: int = 200) -> list[Call]:
        return await self._calls.list_by_statuses(list(LIVE_STATUSES), limit=limit)

    async def get_call(self, call_id: uuid.UUID) -> Call:
        call = await self._calls.get(call_id)
        if call is None:
            raise CallGovernanceError("No such call.")
        return call

    async def end_call(self, *, admin_id: uuid.UUID, call_id: uuid.UUID, reason: str) -> Call:
        try:
            call = await self._call_service.admin_end_call(call_id=call_id)
        except CallError as exc:
            raise CallGovernanceError(str(exc)) from exc
        await self._audit_log.add(
            AuditLog(
                created_at=datetime.now(UTC),
                actor_type="admin",
                actor_id=admin_id,
                action="admin.call.ended",
                target_type="call",
                target_id=call_id,
                metadata_json={"reason": reason},
            )
        )
        return call
