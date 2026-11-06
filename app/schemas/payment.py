from pydantic import BaseModel
from app.models.enums import PaymentStatus


class PaymentRequest(BaseModel):
    amount: float = 100.0
    payment_method: str = "credit_card"


class PaymentResponse(BaseModel):
    payment_id: int
    booking_id: int
    user_id: str
    seat_id: int
    amount: float
    status: PaymentStatus
    idempotent_replay: bool = False
