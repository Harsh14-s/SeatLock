from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.models.enums import BookingStatus


class HoldSeatRequest(BaseModel):
    seat_id: int
    user_id: str
    ttl_seconds: Optional[int] = None


class BookingResponse(BaseModel):
    id: int
    seat_id: int
    user_id: str
    status: BookingStatus
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)
