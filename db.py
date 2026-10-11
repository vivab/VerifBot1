import aiosqlite
import json
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from bot.config import settings
from bot.database.models import User, UserRole, Product, EntryType, Order, OrderStatus


class Database:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.DB_PATH

    async def connect(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self._create_tables()
        await self._init_defaults()

    async def close(self):
        await self.conn.close()

    async def _create_tables(self):
        await self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                balance REAL NOT NULL DEFAULT 0,
                turnover REAL NOT NULL DEFAULT 0,
                verifications_bought INTEGER NOT NULL DEFAULT 0,
                verifications_done INTEGER NOT NULL DEFAULT 0,
                earned REAL NOT NULL DEFAULT 0,
                registered_at TEXT NOT NULL,
                is_banned INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                buyer_price REAL NOT NULL,
                seller_price REAL NOT NULL,
                entry_type TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_id INTEGER NOT NULL,
                seller_id INTEGER,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                buyer_price REAL NOT NULL,
                seller_price REAL NOT NULL,
                entry_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                entry_data TEXT,
                created_at TEXT NOT NULL,
                taken_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (buyer_id) REFERENCES users(user_id),
                FOREIGN KEY (seller_id) REFERENCES users(user_id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS invoices (
                invoice_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                purpose TEXT NOT NULL,  -- 'topup' или 'order:123'
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            );
        """)
        await self.conn.commit()

    async def _init_defaults(self):
        # Дефолтные настройки
        defaults = {
            "support_username": settings.SUPPORT_USERNAME,
            "channel_url": settings.CHANNEL_URL,
        }
        for key, value in defaults.items():
            await self.conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value)
            )
        await self.conn.commit()

        # Владелец
        owner = await self.get_user(settings.OWNER_ID)
        if not owner:
            await self.add_user(
                user_id=settings.OWNER_ID,
                username=None,
                full_name="Owner",
                role=UserRole.OWNER
            )

    # ──────────────────── USERS ────────────────────

    async def add_user(self, user_id: int, username: Optional[str], full_name: str,
                       role: UserRole = UserRole.USER) -> User:
        now = datetime.utcnow().isoformat()
        await self.conn.execute(
            """INSERT OR IGNORE INTO users 
               (user_id, username, full_name, role, registered_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, username, full_name, role.value, now)
        )
        await self.conn.commit()
        return await self.get_user(user_id)

    async def get_user(self, user_id: int) -> Optional[User]:
        async with self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return User(
                user_id=row["user_id"],
                username=row["username"],
                full_name=row["full_name"],
                role=UserRole(row["role"]),
                balance=row["balance"],
                turnover=row["turnover"],
                verifications_bought=row["verifications_bought"],
                verifications_done=row["verifications_done"],
                earned=row["earned"],
                registered_at=datetime.fromisoformat(row["registered_at"]),
                is_banned=bool(row["is_banned"]),
            )

    async def update_user_role(self, user_id: int, role: UserRole):
        await self.conn.execute(
            "UPDATE users SET role = ? WHERE user_id = ?",
            (role.value, user_id)
        )
        await self.conn.commit()

    async def update_balance(self, user_id: int, amount: float):
        await self.conn.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await self.conn.commit()

    async def set_balance(self, user_id: int, balance: float):
        await self.conn.execute(
            "UPDATE users SET balance = ? WHERE user_id = ?",
            (balance, user_id)
        )
        await self.conn.commit()

    async def add_turnover(self, user_id: int, amount: float):
        await self.conn.execute(
            "UPDATE users SET turnover = turnover + ?, verifications_bought = verifications_bought + 1 WHERE user_id = ?",
            (amount, user_id)
        )
        await self.conn.commit()

    async def add_seller_stats(self, user_id: int, amount: float):
        await self.conn.execute(
            "UPDATE users SET earned = earned + ?, verifications_done = verifications_done + 1 WHERE user_id = ?",
            (amount, user_id)
        )
        await self.conn.commit()

    async def get_users_by_role(self, role: UserRole) -> List[User]:
        async with self.conn.execute(
            "SELECT * FROM users WHERE role = ?", (role.value,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                User(
                    user_id=r["user_id"],
                    username=r["username"],
                    full_name=r["full_name"],
                    role=UserRole(r["role"]),
                    balance=r["balance"],
                    turnover=r["turnover"],
                    verifications_bought=r["verifications_bought"],
                    verifications_done=r["verifications_done"],
                    earned=r["earned"],
                    registered_at=datetime.fromisoformat(r["registered_at"]),
                    is_banned=bool(r["is_banned"]),
                )
                for r in rows
            ]

    async def count_users(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0]

    async def count_by_role(self, role: UserRole) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = ?", (role.value,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0]

    # ──────────────────── PRODUCTS ────────────────────

    async def add_product(self, name: str, buyer_price: float, seller_price: float,
                          entry_type: EntryType) -> int:
        cursor = await self.conn.execute(
            """INSERT INTO products (name, buyer_price, seller_price, entry_type)
               VALUES (?, ?, ?, ?)""",
            (name, buyer_price, seller_price, entry_type.value)
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def get_product(self, product_id: int) -> Optional[Product]:
        async with self.conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return Product(
                id=row["id"],
                name=row["name"],
                buyer_price=row["buyer_price"],
                seller_price=row["seller_price"],
                entry_type=EntryType(row["entry_type"]),
                is_active=bool(row["is_active"]),
            )

    async def get_all_products(self, only_active: bool = True) -> List[Product]:
        query = "SELECT * FROM products"
        if only_active:
            query += " WHERE is_active = 1"
        query += " ORDER BY id"
        async with self.conn.execute(query) as cursor:
            rows = await cursor.fetchall()
            return [
                Product(
                    id=r["id"],
                    name=r["name"],
                    buyer_price=r["buyer_price"],
                    seller_price=r["seller_price"],
                    entry_type=EntryType(r["entry_type"]),
                    is_active=bool(r["is_active"]),
                )
                for r in rows
            ]

    async def update_product(self, product_id: int, name: str = None,
                             buyer_price: float = None, seller_price: float = None,
                             entry_type: EntryType = None, is_active: bool = None):
        product = await self.get_product(product_id)
        if not product:
            return
        name = name if name is not None else product.name
        buyer_price = buyer_price if buyer_price is not None else product.buyer_price
        seller_price = seller_price if seller_price is not None else product.seller_price
        entry_type = entry_type if entry_type is not None else product.entry_type
        is_active = is_active if is_active is not None else product.is_active

        await self.conn.execute(
            """UPDATE products 
               SET name=?, buyer_price=?, seller_price=?, entry_type=?, is_active=?
               WHERE id=?""",
            (name, buyer_price, seller_price, entry_type.value, int(is_active), product_id)
        )
        await self.conn.commit()

    async def delete_product(self, product_id: int):
        await self.conn.execute(
            "UPDATE products SET is_active = 0 WHERE id = ?", (product_id,)
        )
        await self.conn.commit()

    # ──────────────────── ORDERS ────────────────────

    async def create_order(self, buyer_id: int, product: Product,
                           entry_data: dict) -> int:
        now = datetime.utcnow().isoformat()
        cursor = await self.conn.execute(
            """INSERT INTO orders 
               (buyer_id, product_id, product_name, buyer_price, seller_price,
                entry_type, status, entry_data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                buyer_id,
                product.id,
                product.name,
                product.buyer_price,
                product.seller_price,
                product.entry_type.value,
                OrderStatus.PENDING.value,
                json.dumps(entry_data, ensure_ascii=False),
                now,
            )
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def get_order(self, order_id: int) -> Optional[Order]:
        async with self.conn.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_order(row)

    def _row_to_order(self, row) -> Order:
        return Order(
            id=row["id"],
            buyer_id=row["buyer_id"],
            seller_id=row["seller_id"],
            product_id=row["product_id"],
            product_name=row["product_name"],
            buyer_price=row["buyer_price"],
            seller_price=row["seller_price"],
            entry_type=EntryType(row["entry_type"]),
            status=OrderStatus(row["status"]),
            entry_data=row["entry_data"],
            created_at=datetime.fromisoformat(row["created_at"]),
            taken_at=datetime.fromisoformat(row["taken_at"]) if row["taken_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        )

    async def take_order(self, order_id: int, seller_id: int) -> bool:
        """Атомарно берёт заказ. Возвращает True если удалось."""
        now = datetime.utcnow().isoformat()
        cursor = await self.conn.execute(
            """UPDATE orders 
               SET seller_id = ?, status = ?, taken_at = ?
               WHERE id = ? AND status = ? AND seller_id IS NULL""",
            (seller_id, OrderStatus.IN_PROGRESS.value, now, order_id, OrderStatus.PENDING.value)
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def complete_order(self, order_id: int):
        """Завершает заказ и удаляет entry_data."""
        now = datetime.utcnow().isoformat()
        await self.conn.execute(
            """UPDATE orders 
               SET status = ?, completed_at = ?, entry_data = NULL
               WHERE id = ?""",
            (OrderStatus.COMPLETED.value, now, order_id)
        )
        await self.conn.commit()

    async def cancel_order(self, order_id: int):
        await self.conn.execute(
            """UPDATE orders 
               SET status = ?, entry_data = NULL
               WHERE id = ?""",
            (OrderStatus.CANCELLED.value, order_id)
        )
        await self.conn.commit()

    async def get_pending_orders(self) -> List[Order]:
        async with self.conn.execute(
            "SELECT * FROM orders WHERE status = ? ORDER BY created_at",
            (OrderStatus.PENDING.value,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_order(r) for r in rows]

    async def get_seller_active_orders(self, seller_id: int) -> List[Order]:
        async with self.conn.execute(
            "SELECT * FROM orders WHERE seller_id = ? AND status = ? ORDER BY taken_at DESC",
            (seller_id, OrderStatus.IN_PROGRESS.value)
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_order(r) for r in rows]

    async def get_user_orders(self, user_id: int, limit: int = 20) -> List[Order]:
        async with self.conn.execute(
            "SELECT * FROM orders WHERE buyer_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_order(r) for r in rows]

    async def count_completed_orders(self) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) FROM orders WHERE status = ?",
            (OrderStatus.COMPLETED.value,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0]

    async def get_total_turnover(self) -> float:
        async with self.conn.execute(
            "SELECT COALESCE(SUM(buyer_price), 0) FROM orders WHERE status = ?",
            (OrderStatus.COMPLETED.value,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0]

    async def get_total_earnings(self) -> float:
        """Прибыль владельца = сумма (buyer_price - seller_price) по завершённым"""
        async with self.conn.execute(
            """SELECT COALESCE(SUM(buyer_price - seller_price), 0) 
               FROM orders WHERE status = ?""",
            (OrderStatus.COMPLETED.value,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0]

    # ──────────────────── SETTINGS ────────────────────

    async def get_setting(self, key: str) -> Optional[str]:
        async with self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
            return row["value"] if row else None

    async def set_setting(self, key: str, value: str):
        await self.conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        await self.conn.commit()

    # ──────────────────── INVOICES ────────────────────

    async def save_invoice(self, invoice_id: int, user_id: int, amount: float, purpose: str):
        now = datetime.utcnow().isoformat()
        await self.conn.execute(
            """INSERT INTO invoices (invoice_id, user_id, amount, purpose, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (invoice_id, user_id, amount, purpose, now)
        )
        await self.conn.commit()

    async def get_invoice(self, invoice_id: int):
        async with self.conn.execute(
            "SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)
        ) as cursor:
            return await cursor.fetchone()

    async def mark_invoice_paid(self, invoice_id: int):
        await self.conn.execute(
            "UPDATE invoices SET status = 'paid' WHERE invoice_id = ?",
            (invoice_id,)
        )
        await self.conn.commit()


# Глобальный экземпляр
db = Database()
