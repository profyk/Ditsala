"""
Bootstraps a normal-tier user account directly in the database, fully
`active` with phone + PIN already set — for testing the app when the
real phone-verification path (Twilio) isn't wired up yet. Same
out-of-band posture as create_admin.py: this bypasses OTP verification
entirely, so it's a testing/bootstrap tool, not something a real signup
should ever go through.

Usage (from backend/):
    uv run python scripts/create_test_user.py --phone +27821234567 --name "Test User"
"""

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import hash_secret, is_weak_pin, validate_pin_strength
from app.models.accounts import User
from app.repositories.users import UserRepository


def _read_password(prompt: str) -> str:
    """Duplicated from create_admin.py/reset_admin_password.py rather
    than imported — `scripts/` isn't a package, and importing across
    sibling scripts creates a module-name collision under mypy (each
    script is its own top-level module when run directly)."""
    if sys.stdin.isatty():
        return getpass.getpass(prompt)
    print(prompt, end="", file=sys.stderr, flush=True)
    return sys.stdin.readline().rstrip("\n")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone", required=True, help="E.164, e.g. +27821234567")
    parser.add_argument("--name", required=True, dest="display_name")
    args = parser.parse_args()

    pin = _read_password("PIN (6 digits): ")
    confirm = _read_password("Confirm PIN: ")
    if pin != confirm:
        print("PINs did not match.", file=sys.stderr)
        raise SystemExit(1)
    if not validate_pin_strength(pin):
        print("PIN must be exactly 6 digits.", file=sys.stderr)
        raise SystemExit(1)
    if is_weak_pin(pin):
        print("That PIN is too easy to guess — pick a less predictable one.", file=sys.stderr)
        raise SystemExit(1)

    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        users = UserRepository(session)

        if await users.get_by_phone(args.phone) is not None:
            print(f"A user with phone {args.phone!r} already exists.", file=sys.stderr)
            raise SystemExit(1)

        now = datetime.now(UTC)
        user = await users.add(
            User(
                phone=args.phone,
                phone_verified_at=now,
                display_name=args.display_name,
                account_state="active",
                account_tier="normal",
                ditsala_code_hash=hash_secret(pin),
                code_set_at=now,
            )
        )
        await session.commit()
        print(f"Created active test user {user.display_name!r} ({user.phone}).")
        print("Log in with this phone number + PIN on the login screen.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
