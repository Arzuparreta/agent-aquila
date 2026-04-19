"""Delete a user and dependent rows (DB CASCADE).

Usage (inside the backend container)::

    python -m app.scripts.delete_user --email 'spam@e.com' --yes
    python -m app.scripts.delete_user --user-id 456 --yes

Requires ``--yes`` to avoid accidental deletion.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.user import User


async def _delete_one(db: AsyncSession, *, user_id: int | None, email: str | None) -> User:
    if user_id is not None:
        row = await db.get(User, user_id)
        if row is None:
            raise SystemExit(f"No user with id={user_id}")
        return row
    if email is not None:
        res = await db.execute(select(User).where(User.email == email))
        row = res.scalar_one_or_none()
        if row is None:
            raise SystemExit(f"No user with email={email!r}")
        return row
    raise SystemExit("Pass --user-id or --email")


async def main_async(args: argparse.Namespace) -> int:
    if not args.yes:
        print("Refusing to delete without --yes", file=sys.stderr)
        return 2
    async with AsyncSessionLocal() as db:
        user = await _delete_one(db, user_id=args.user_id, email=args.email)
        uid, em = user.id, user.email
        await db.delete(user)
        await db.commit()
    print(f"Deleted user id={uid} email={em!r}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Delete a user row (CASCADE dependents).")
    p.add_argument("--user-id", type=int, default=None)
    p.add_argument("--email", type=str, default=None)
    p.add_argument("--yes", action="store_true", help="Confirm deletion")
    args = p.parse_args()
    if args.user_id is None and args.email is None:
        p.error("Provide --user-id or --email")
    if args.user_id is not None and args.email is not None:
        p.error("Use only one of --user-id or --email")
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
