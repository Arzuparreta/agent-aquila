"""Rotate the Key Encryption Key (KEK).

The KEK wraps every per-row Data Encryption Key (DEK) stored in
``user_ai_provider_configs.wrapped_dek``. Rotating it means:

1. Load the *current* KEK (env or ``backend/.secrets/fernet.key``).
2. Generate a new KEK.
3. For every row that has a ``wrapped_dek``: unwrap with the old KEK,
   re-wrap with the new KEK, write back. The plaintext DEK lives only in
   memory inside one transaction and is dropped on commit. The actual
   ciphertext (the API key) is **never** touched, so this is fast and
   restartable.
4. Persist the new KEK back to disk (or print it for the operator to
   move into a secret manager).

Usage (inside the backend container, where the same KEK file is
mounted):

    docker compose exec backend python -m app.scripts.rotate_kek \\
        [--print-only] [--keep-old-file]

Flags:

- ``--print-only``  Print the new KEK to stdout and **do not** write it
  to ``backend/.secrets/fernet.key``. Use this if your KEK lives in an
  env var / secret manager and you want to roll it out yourself.
- ``--keep-old-file`` After a successful rotation, copy the old KEK
  file to ``fernet.key.<timestamp>.old`` instead of overwriting it.
  Useful for manual rollback windows.

Safety:

- The script aborts before touching the database if the current KEK
  cannot decrypt the first row it sees (otherwise the rotation would
  produce unreadable data). Re-run after fixing the env first.
- All updates happen in **one** transaction. If anything fails the
  database is rolled back and the on-disk KEK file is left untouched.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.envelope_crypto import (
    KeyDecryptError,
    _kek_file_path,
    _persist_kek_to_file,
    kek_source,
    load_kek,
    rewrap_dek,
)
from app.models.user_ai_provider_config import UserAIProviderConfig


_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"


async def _rewrap_all(new_kek: Fernet) -> tuple[int, int]:
    """Re-wrap every DEK in the DB. Returns (rewrapped, skipped)."""
    rewrapped = 0
    skipped = 0
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(UserAIProviderConfig))
        ).scalars().all()
        if not rows:
            print(f"{_DIM}No rows in user_ai_provider_configs — nothing to re-wrap.{_RESET}")
            return 0, 0

        for row in rows:
            if not row.wrapped_dek:
                skipped += 1
                continue
            scope = f"user={row.user_id} provider={row.provider_kind}"
            try:
                row.wrapped_dek = rewrap_dek(row.wrapped_dek, new_kek, scope=scope)
            except KeyDecryptError as exc:
                # Abort the whole rotation: a partial rewrap with a mix
                # of old/new wraps is the worst possible state.
                print(f"\n{_RED}ABORT{_RESET} — could not unwrap DEK for {scope}: {exc.reason}")
                print(
                    f"{_DIM}      The current KEK cannot read this row. Fix the KEK source "
                    f"({kek_source()}) and try again.{_RESET}"
                )
                await db.rollback()
                raise SystemExit(2) from exc
            rewrapped += 1
        await db.commit()
    return rewrapped, skipped


def _backup_old_kek_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_suffix(path.suffix + f".{stamp}.old")
    shutil.copy2(path, backup)
    return backup


def _print_summary(*, source: str, rewrapped: int, skipped: int, new_kek_value: str, wrote_path: Path | None) -> None:
    print()
    print(f"{_GREEN}KEK rotation complete.{_RESET}")
    print(f"  Old source     : {source}")
    print(f"  Rewrapped DEKs : {rewrapped}")
    if skipped:
        print(f"  Skipped (no wrapped_dek) : {skipped}")
    if wrote_path:
        print(f"  New KEK file   : {wrote_path}")
    else:
        print(f"  {_YELLOW}New KEK was NOT written to disk (--print-only).{_RESET}")
        print(f"  Set this in your secret manager / env, then restart the backend:")
        print(f"  {_DIM}FERNET_ENCRYPTION_KEY={new_kek_value}{_RESET}")
    print()
    print(f"{_DIM}Restart the backend and worker so they reload the new KEK before the next request.{_RESET}")


async def main_async(args: argparse.Namespace) -> int:
    print(f"Loading current KEK ({kek_source()})…")
    try:
        load_kek()
    except Exception as exc:  # noqa: BLE001 — we want to print, not crash
        print(f"{_RED}Could not load current KEK: {exc}{_RESET}")
        return 2
    source_before = kek_source()

    new_kek_value = Fernet.generate_key().decode("utf-8")
    new_kek = Fernet(new_kek_value.encode("utf-8"))

    print("Re-wrapping every stored DEK with the new KEK…")
    rewrapped, skipped = await _rewrap_all(new_kek)

    wrote_path: Path | None = None
    if not args.print_only:
        path = _kek_file_path()
        if args.keep_old_file:
            backup = _backup_old_kek_file(path)
            if backup is not None:
                print(f"{_DIM}Saved previous KEK to {backup}{_RESET}")
        _persist_kek_to_file(path, new_kek_value)
        wrote_path = path

    _print_summary(
        source=source_before,
        rewrapped=rewrapped,
        skipped=skipped,
        new_kek_value=new_kek_value,
        wrote_path=wrote_path,
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Don't write the new KEK to backend/.secrets/fernet.key — print it instead.",
    )
    parser.add_argument(
        "--keep-old-file",
        action="store_true",
        help="Back up the old KEK file with a timestamp suffix before overwriting.",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
