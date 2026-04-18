"""Seed realistic artist-manager data (contacts, deals, emails, events).

Run from repo `backend/`:

 python -m app.scripts.seed

Optional env: SEED_USER_EMAIL, SEED_USER_PASSWORD (default demo@example.com / demo123).
"""

from __future__ import annotations

import asyncio
import os
import random
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.contact import Contact
from app.models.deal import Deal
from app.models.email import Email
from app.models.event import Event
from app.models.user import User

ROLES = ["venue", "promoter", "press", "agent", "band_member", "fan", "other"]
DEAL_STATUSES = ["new", "contacted", "negotiating", "won", "lost"]


async def seed() -> None:
    email_addr = os.environ.get("SEED_USER_EMAIL", "demo@example.com")
    password = os.environ.get("SEED_USER_PASSWORD", "demo123")

    async with AsyncSessionLocal() as session:
        existing = await session.scalar(select(func.count()).select_from(Contact))
        if existing and int(existing) >= 10:
            print("Database already has contacts; skipping seed. Delete data or trim contacts to re-run.")
            return

        result = await session.execute(select(User).where(User.email == email_addr))
        user = result.scalar_one_or_none()
        if not user:
            user = User(email=email_addr, hashed_password=hash_password(password), full_name="Demo Manager", is_active=True)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            print(f"Created user {email_addr} / {password}")

        contacts: list[Contact] = []
        for i in range(20):
            role = ROLES[i % len(ROLES)]
            c = Contact(
                name=f"Contact {i + 1} ({role})",
                email=f"contact{i + 1}@example.com" if i % 3 else None,
                phone=f"+1-555-01{i:02d}" if i % 2 == 0 else None,
                role=role,
                notes=f"Notes for {role} #{i + 1}. Territory EU/US." if i % 4 == 0 else None,
            )
            session.add(c)
            contacts.append(c)
        await session.flush()

        deals: list[Deal] = []
        for i in range(10):
            contact = contacts[(i * 2) % len(contacts)]
            status = DEAL_STATUSES[i % len(DEAL_STATUSES)]
            amount = random.choice([2500, 5000, 7500, 12000, None])
            d = Deal(
                contact_id=contact.id,
                title=f"Booking opportunity #{i + 1}",
                status=status,
                amount=amount,
                currency="EUR" if amount else None,
                notes="Hold for summer festival slot" if i % 2 == 0 else None,
            )
            session.add(d)
            deals.append(d)
        await session.flush()

        today = date.today()
        events: list[Event] = []
        for i in range(5):
            deal = deals[i % len(deals)]
            ev = Event(
                deal_id=deal.id if i % 2 == 0 else None,
                venue_name=f"Venue Hall {i + 1}",
                event_date=today + timedelta(days=14 + i * 7),
                city=random.choice(["Madrid", "Barcelona", "Lisbon", "Paris", None]),
                status="confirmed" if i % 2 == 0 else "tentative",
                notes="Load-in 16:00" if i % 2 == 0 else None,
            )
            session.add(ev)
            events.append(ev)
        await session.flush()

        subjects = [
            "Re: Summer festival booking",
            "Press request — interview slot",
            "Contract draft for club show",
            "Quick question on travel",
            "Concert offer — June weekend",
            "Show logistics and backline",
            "Invoice attached",
            "Booking inquiry downtown venue",
            "Radio promo availability",
            "Rehearsal schedule conflict",
        ]
        bodies = [
            "We would love to confirm the date and fee.",
            "Can you send the tech rider?",
            "Please review the attached PDF.",
            "Following up on our call.",
            "The promoter is asking for a hold.",
        ]
        base = datetime.now(UTC) - timedelta(days=30)
        for i in range(30):
            c = contacts[i % len(contacts)]
            subj = subjects[i % len(subjects)]
            if i % 7 == 0:
                subj = "Concert booking — offer attached"
            received = base + timedelta(hours=i * 17)
            e = Email(
                contact_id=c.id,
                sender_email=c.email or f"guest{i}@venue.example",
                sender_name=c.name,
                subject=subj,
                body=bodies[i % len(bodies)],
                received_at=received,
            )
            session.add(e)

        await session.commit()
        print(f"Seeded {len(contacts)} contacts, {len(deals)} deals, {len(events)} events, 30 emails.")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
