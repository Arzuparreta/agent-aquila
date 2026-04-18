from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.contact import ContactCreate, ContactRead, ContactUpdate
from app.schemas.deal import DealCreate, DealRead, DealUpdate
from app.schemas.email import EmailCreate, EmailRead
from app.schemas.event import EventCreate, EventRead, EventUpdate
from app.schemas.user import UserRead

__all__ = [
    "ContactCreate",
    "ContactRead",
    "ContactUpdate",
    "DealCreate",
    "DealRead",
    "DealUpdate",
    "EmailCreate",
    "EmailRead",
    "EventCreate",
    "EventRead",
    "EventUpdate",
    "LoginRequest",
    "RegisterRequest",
    "TokenResponse",
    "UserRead",
]
