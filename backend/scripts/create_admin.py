"""
Bootstraps an admin account (docs/DITSALA_MASTER_SPEC.md §29) — there is
deliberately no public "create admin" API endpoint; admin accounts are
provisioned out-of-band by whoever runs this against a real database.
MFA enrollment isn't done here — the account's first login through
`POST /api/v1/admin/auth/login/start` detects `mfa_enrolled=False` and
walks the caller through TOTP enrollment automatically.

Usage (from backend/):
    uv run python scripts/create_admin.py --email admin@ditsala.app --role super_admin
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import (
    ADMIN_PASSWORD_MIN_LENGTH,
    hash_secret,
    validate_admin_password_strength,
)
from app.models.admin import AdminUser
from app.repositories.admin import AdminRoleRepository, AdminUserRepository


def _read_password(prompt: str) -> str:
    """`getpass.getpass` reads from the console directly on Windows,
    ignoring a piped/redirected stdin — falls back to a plain read when
    stdin isn't a real TTY (CI, `echo ... | python create_admin.py`)."""
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    print(prompt, end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().rstrip("\n")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--role",
        default="super_admin",
        choices=["super_admin", "kyc_reviewer", "trust_safety", "support_readonly"],
    )
    args = parser.parse_args()

    password = _read_password("Admin password: ")
    confirm = _read_password("Confirm password: ")
    if password != confirm:
        print("Passwords did not match.", file=sys.stderr)
        raise SystemExit(1)
    if not validate_admin_password_strength(password):
        print(
            f"Use at least {ADMIN_PASSWORD_MIN_LENGTH} characters for an admin password.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        admin_users = AdminUserRepository(session)
        admin_roles = AdminRoleRepository(session)

        if await admin_users.get_by_email(args.email) is not None:
            print(f"An admin with email {args.email!r} already exists.", file=sys.stderr)
            raise SystemExit(1)

        role = await admin_roles.get_by_name(args.role)
        if role is None:
            print(
                f"Role {args.role!r} not found — run `alembic upgrade head` first "
                "(it seeds the launch role set).",
                file=sys.stderr,
            )
            raise SystemExit(1)

        admin = await admin_users.add(
            AdminUser(email=args.email, password_hash=hash_secret(password), role_id=role.id)
        )
        await session.commit()
        print(f"Created admin {admin.email} ({args.role}). MFA enrollment happens on first login.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
