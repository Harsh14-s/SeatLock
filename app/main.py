import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings
from app.database import engine
from app.models.base import Base
import app.models  # Ensures all models are registered on Base.metadata
from app.api.v1.router import api_router
from app.workers.cleanup import background_cleanup_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Automatically create tables on startup if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Start background cleanup task
    cleanup_task = asyncio.create_task(background_cleanup_loop(interval_seconds=5))
    yield
    # Graceful shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="High-Concurrency Ticket Booking Backend with Zero Double-Bookings Guarantee.",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount API routers
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "project": settings.PROJECT_NAME}
