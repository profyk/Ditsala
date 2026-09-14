"""
SQLAlchemy models, one module per bounded context, mirroring
docs/DITSALA_MASTER_SPEC.md §4. Every table is created exclusively via
Alembic migrations (§7.5) — this package is the source of truth that
autogenerate diffs against, never used to create tables directly.

Import every model module here so Base.metadata is complete when
migrations/env.py imports Base from this package.
"""

from app.models.accounts import (  # noqa: F401
    EmailVerification,
    KycDocument,
    KycFaceVerification,
    NextOfKin,
    PhoneVerification,
    User,
)
from app.models.admin import (  # noqa: F401
    AdminPermission,
    AdminRole,
    AdminRolePermission,
    AdminUser,
    AuditLog,
    SystemConfig,
)
from app.models.base import Base  # noqa: F401
from app.models.calls import Call, CallParticipant  # noqa: F401
from app.models.circle import Block, Contact, ContactRequest, Invitation, Report  # noqa: F401
from app.models.crypto import IdentityKey, OneTimePrekey, SenderKey, SignedPrekey  # noqa: F401
from app.models.devices import (  # noqa: F401
    AccountRecoveryRequest,
    Device,
    LoginAttempt,
    Session,
)
from app.models.location import (  # noqa: F401
    LocationAccessLog,
    LocationPing,
    LocationShare,
    SosEvent,
    SosNotification,
)
from app.models.messaging import (  # noqa: F401
    Conversation,
    ConversationMember,
    MediaObject,
    Message,
    MessageReceipt,
)
from app.models.push import PushToken  # noqa: F401
