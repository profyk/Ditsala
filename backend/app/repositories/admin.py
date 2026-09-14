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


class SystemConfigRepository(Repository[SystemConfig]):
    """
    SystemConfig's primary key is `key: str`, not a UUID — use
    `get_by_key`, not the inherited `Repository.get` (typed for a UUID PK
    and not meaningful here).
    """

    model = SystemConfig

    async def get_by_key(self, key: str) -> SystemConfig | None:
        return await self.session.get(SystemConfig, key)
