from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.models.enums import SeatStatus


class SeatBase(BaseModel):
    seat_number: str


class SeatResponse(SeatBase):
    id: int
    event_id: int
    status: SeatStatus
    held_by: Optional[str] = None
    held_until: Optional[datetime] = None
    version: int

    model_config = ConfigDict(from_attributes=True)
