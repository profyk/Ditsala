import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base


class Repository[ModelT: Base]:
    """
    Thin data-access layer, one per aggregate (docs/DITSALA_MASTER_SPEC.md
    §3.2). Deliberately minimal in Phase 1 — business rules (state
    transitions, cross-aggregate invariants) belong in `domain/`, built out
    phase by phase; this layer only owns persistence.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id_: uuid.UUID) -> ModelT | None:
        return await self.session.get(self.model, id_)

    async def add(self, instance: ModelT) -> ModelT:
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        await self.session.delete(instance)
        await self.session.flush()

    def _select(self) -> Select[tuple[ModelT]]:
        return select(self.model)
