import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc

from app.models.admin import (
    AdminPermission,
    AdminRole,
    AdminRolePermission,
    AdminUser,
    AuditLog,
    SystemConfig,
)
from app.repositories.base import Repository


class AdminUserRepository(Repository[AdminUser]):
    model = AdminUser

    async def get_by_email(self, email: str) -> AdminUser | None:
        result = await self.session.execute(self._select().where(AdminUser.email == email))
        return result.scalar_one_or_none()


class AdminRoleRepository(Repository[AdminRole]):
    model = AdminRole

    async def get_by_name(self, name: str) -> AdminRole | None:
        result = await self.session.execute(self._select().where(AdminRole.name == name))
        return result.scalar_one_or_none()


class AdminPermissionRepository(Repository[AdminPermission]):
    model = AdminPermission


class AdminRolePermissionRepository(Repository[AdminRolePermission]):
    model = AdminRolePermission


class AuditLogRepository(Repository[AuditLog]):
    """
    Append-only at the DB grant level (§30) — this repository has no
    `update`/`delete` method by design; the base class's are inherited but
    the DB will reject them for every role except the table owner, and no
    application code path should ever call them here.
    """

    model = AuditLog

    async def list_filtered(
        self,
        *,
        actor_id: uuid.UUID | None = None,
        action: str | None = None,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        stmt = self._select()
        if actor_id is not None:
            stmt = stmt.where(AuditLog.actor_id == actor_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if target_type is not None:
            stmt = stmt.where(AuditLog.target_type == target_type)
        if target_id is not None:
            stmt = stmt.where(AuditLog.target_id == target_id)
        stmt = stmt.order_by(desc(AuditLog.created_at)).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_target(self, target_type: str, target_id: uuid.UUID) -> list[AuditLog]:
        return await self.list_filtered(target_type=target_type, target_id=target_id, limit=500)


class SystemConfigRepository(Repository[SystemConfig]):
    """
    SystemConfig's primary key is `key: str`, not a UUID — use
    `get_by_key`, not the inherited `Repository.get` (typed for a UUID PK
    and not meaningful here).
    """

    model = SystemConfig

    async def get_by_key(self, key: str) -> SystemConfig | None:
        return await self.session.get(SystemConfig, key)

    async def list_all(self) -> list[SystemConfig]:
        result = await self.session.execute(self._select().order_by(SystemConfig.key))
        return list(result.scalars().all())

    async def upsert(
        self, *, key: str, value: dict[str, Any], updated_by_admin_id: uuid.UUID
    ) -> SystemConfig:
        """§28.8: every change is audit-logged with before/after by the
        caller (`AdminService.set_system_config`) — this just persists it."""
        existing = await self.get_by_key(key)
        if existing is not None:
            existing.value = value
            existing.updated_at = datetime.now(UTC)
            existing.updated_by_admin_id = updated_by_admin_id
            return existing
        return await self.add(
            SystemConfig(
                key=key,
                value=value,
                updated_at=datetime.now(UTC),
                updated_by_admin_id=updated_by_admin_id,
            )
        )
