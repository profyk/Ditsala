"""
Resets an existing admin account's password (docs/DITSALA_MASTER_SPEC.md
§29) — same out-of-band provisioning posture as create_admin.py: no
public API endpoint for this, since it bypasses the account's own MFA.

Usage (from backend/):
    uv run python scripts/reset_admin_password.py --email admin@ditsala.app
"""

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import hash_secret
from app.repositories.admin import AdminUserRepository
from scripts.create_admin import _read_password


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    password = _read_password("New admin password: ")
    confirm = _read_password("Confirm password: ")
    if password != confirm:
        print("Passwords did not match.", file=sys.stderr)
        raise SystemExit(1)
    if len(password) < 12:
        print("Use at least 12 characters for an admin password.", file=sys.stderr)
        raise SystemExit(1)

    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        admin_users = AdminUserRepository(session)

        admin = await admin_users.get_by_email(args.email)
        if admin is None:
            print(f"No admin found with email {args.email!r}.", file=sys.stderr)
            raise SystemExit(1)

        admin.password_hash = hash_secret(password)
        await session.commit()
        print(f"Password reset for {admin.email}. Existing MFA enrollment is unaffected.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
