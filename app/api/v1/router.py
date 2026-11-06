from fastapi import APIRouter
from app.api.v1.bookings import router as bookings_router
from app.api.v1.payments import router as payments_router

api_router = APIRouter()
api_router.include_router(bookings_router)
api_router.include_router(payments_router)
