import enum


class SeatStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"


class BookingStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
