import uuid

from sqlalchemy import Boolean, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PushToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "push_tokens"

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    expo_push_token: Mapped[str] = mapped_column(String(256), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
