from enum import Enum
from dataclasses import dataclass
from typing import Optional
from datetime import datetime


class UserRole(str, Enum):
    USER = "user"
    SELLER = "seller"
    ADMIN = "admin"
    OWNER = "owner"


class OrderStatus(str, Enum):
    PENDING = "pending"          # Ожидает продавца
    IN_PROGRESS = "in_progress"  # Взят продавцом
    COMPLETED = "completed"      # Завершён
    CANCELLED = "cancelled"      # Отменён


class EntryType(str, Enum):
    EMAIL = "email"
    TELEGRAM = "telegram"


@dataclass
class User:
    user_id: int
    username: Optional[str]
    full_name: str
    role: UserRole
    balance: float
    turnover: float
    verifications_bought: int
    verifications_done: int      # только для продавцов
    earned: float                # только для продавцов
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


@dataclass
class Order:
    id: int
    buyer_id: int
    seller_id: Optional[int]
    product_id: int
    product_name: str
    buyer_price: float
    seller_price: float
    entry_type: EntryType
    status: OrderStatus
    # Данные входа (удаляются после завершения)
    entry_data: Optional[str]    # JSON: {"email": "...", "password": "..."} или {"phone": "...", "code": "..."}
    created_at: datetime
    taken_at: Optional[datetime]
    completed_at: Optional[datetime]


@dataclass
class SettingsDB:
    key: str
    value: str
