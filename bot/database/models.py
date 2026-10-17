from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


class UserRole(str, Enum):
    USER = "user"
    SELLER = "seller"
    ADMIN = "admin"
    OWNER = "owner"


class OrderStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    AWAITING_CODE = "awaiting_code"


class EntryType(str, Enum):
    EMAIL = "email"
    TELEGRAM = "telegram"
    NONE = "none"


class CategoryType(str, Enum):
    VERIFICATION = "verification"
    MANUAL = "manual"
    TG_ACCOUNT = "tg_account"


class ManualDelivery(str, Enum):
    TEXT = "text"
    FILE = "file"
    BOTH = "both"


@dataclass
class User:
    user_id: int
    username: Optional[str]
    full_name: str
    role: UserRole
    balance: float
    turnover: float
    verifications_bought: int
    verifications_done: int
    earned: float
    registered_at: datetime
    is_banned: bool = False


@dataclass
class Product:
    id: int
    name: str
    buyer_price: float
    seller_price: float
    entry_type: EntryType
    is_active: bool = True
    category: str = "verification"


@dataclass
class Manual:
    id: int
    name: str
    buyer_price: float
    delivery_type: str
    content_text: Optional[str]
    file_id: Optional[str]
    is_active: bool = True


@dataclass
class TgAccountStock:
    id: int
    country: str
    age_label: str
    phone: str
    session_string: Optional[str]
    session_type: str
    is_sold: bool
    seller_id: Optional[int]
    added_at: datetime


@dataclass
class TgAccountOffer:
    id: int
    country: str
    age_label: str
    buyer_price: float
    seller_price: float
    is_active: bool = True


@dataclass
class Order:
    id: int
    buyer_id: int
    seller_id: Optional[int]
    product_id: Optional[int]
    product_name: str
    buyer_price: float
    seller_price: float
    entry_type: EntryType
    status: OrderStatus
    entry_data: Optional[str]
    category: str = "verification"
    stock_id: Optional[int] = None
    phone: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    taken_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    auto_complete_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None
