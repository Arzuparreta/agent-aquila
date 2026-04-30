"""Create an admin user (headless, for Docker init or CI).

Usage (inside the backend container)::

    python -m app.scripts.create_admin --email admin@example.com --password secret
    python -m app.scripts.create_admin --email admin@example.com --password secret --name "Admin"

If a user with the given email already exists, it is promoted to admin
(and the password is updated if --password is provided).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User


async def main_async(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(func.lower(User.email) == args.email.strip().lower())
        )
        user = result.scalar_one_or_none()

        if user is not None:
            user.is_admin = True
            if args.password:
                user.hashed_password = hash_password(args.password)
            await db.commit()
            print(f"Promoted existing user id={user.id} email={user.email!r} to admin")
            return 0

        user_count = await db.scalar(select(func.count()).select_from(User)) or 0
        user = User(
            email=args.email.strip().lower(),
            hashed_password=hash_password(args.password),
            full_name=args.name or None,
            is_admin=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        label = " (first user)" if user_count == 0 else ""
        print(f"Created admin user id={user.id} email={user.email!r}{label}")
        return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Create or promote an admin user.")
    p.add_argument("--email", type=str, required=True, help="User email address")
    p.add_argument("--password", type=str, required=True, help="User password (8+ chars)")
    p.add_argument("--name", type=str, default=None, help="Full name (optional)")
    args = p.parse_args()
    if len(args.password) < 8:
        p.error("Password must be at least 8 characters")
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
