import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal, engine
from app.models.base import Base
from app.models.event import Event
from app.models.seat import Seat
from app.models.booking import Booking
from app.models.enums import SeatStatus


async def seed():
    print("[1/2] Creating database tables if they do not exist...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("[2/2] Seeding database with test event and seats...")
    async with AsyncSessionLocal() as session:
        # Check if event already exists
        result = await session.execute(select(Event).where(Event.title == "Coldplay - World Tour"))
        event = result.scalar_one_or_none()

        if not event:
            event = Event(title="Coldplay - World Tour", total_seats=100)
            session.add(event)
            await session.flush()  # Flush to get event.id

            seats = []
            for i in range(1, 101):
                row = chr(65 + (i - 1) // 10)  # A, B, C...
                col = ((i - 1) % 10) + 1
                seat_number = f"{row}{col}"
                seats.append(
                    Seat(
                        event_id=event.id,
                        seat_number=seat_number,
                        status=SeatStatus.AVAILABLE,
                        version=1,
                    )
                )

            session.add_all(seats)
            await session.commit()
            print(f"SUCCESS: Created Event '{event.title}' (ID: {event.id}) with {len(seats)} seats.")
        else:
            print(f"INFO: Event '{event.title}' already exists with ID: {event.id}.")


if __name__ == "__main__":
    asyncio.run(seed())
