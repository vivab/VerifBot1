import aiosqlite
import json
from datetime import datetime, timedelta
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
                purpose TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS manuals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                buyer_price REAL NOT NULL,
                delivery_type TEXT NOT NULL DEFAULT 'text',
                content_text TEXT,
                file_id TEXT,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS tg_offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country TEXT NOT NULL,
                age_label TEXT NOT NULL,
                buyer_price REAL NOT NULL,
                seller_price REAL NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS tg_stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country TEXT NOT NULL,
                age_label TEXT NOT NULL,
                phone TEXT NOT NULL,
                session_string TEXT,
                session_type TEXT NOT NULL DEFAULT 'string',
                is_sold INTEGER NOT NULL DEFAULT 0,
                seller_id INTEGER,
                added_at TEXT NOT NULL
            );
        """)
        await self.conn.commit()
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS verification_checkouts (
                checkout_key TEXT PRIMARY KEY,
                buyer_id INTEGER NOT NULL,
                order_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS verification_refunds (
                order_id INTEGER PRIMARY KEY,
                buyer_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await self.conn.commit()
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                body TEXT,
                sender_language TEXT NOT NULL DEFAULT 'ru',
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                attempted_at TEXT,
                created_at TEXT NOT NULL,
                delivered_at TEXT
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_pending "
            "ON chat_messages(status, id)"
        )
        await self.conn.commit()
        try:
            await self.conn.execute("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'ru'")
            await self.conn.commit()
        except aiosqlite.OperationalError as error:
            if "duplicate column" not in str(error).lower():
                raise
        # Миграции для старых БД
        try:
            await self.conn.execute("ALTER TABLE orders ADD COLUMN category TEXT DEFAULT 'verification'")
            await self.conn.commit()
        except Exception:
            pass
        try:
            await self.conn.execute("ALTER TABLE orders ADD COLUMN stock_id INTEGER")
            await self.conn.commit()
        except Exception:
            pass
        try:
            await self.conn.execute("ALTER TABLE orders ADD COLUMN phone TEXT")
            await self.conn.commit()
        except Exception:
            pass
        try:
            await self.conn.execute("ALTER TABLE orders ADD COLUMN auto_complete_at TEXT")
            await self.conn.commit()
        except Exception:
            pass
        try:
            await self.conn.execute("ALTER TABLE products ADD COLUMN category TEXT DEFAULT 'verification'")
            await self.conn.commit()
        except Exception:
            pass

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

    # ──────────────────── LANGUAGE AND ORDER CHAT ────────────────────

    async def get_language(self, user_id: int) -> str:
        async with self.conn.execute(
            "SELECT language FROM users WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        value = row["language"] if row else "ru"
        return value if value in ("ru", "en", "de", "es", "tr") else "ru"

    async def set_language(self, user_id: int, language: str) -> bool:
        if language not in ("ru", "en", "de", "es", "tr"):
            return False
        result = await self.conn.execute(
            "UPDATE users SET language = ? WHERE user_id = ?",
            (language, user_id)
        )
        await self.conn.commit()
        return result.rowcount == 1

    async def chat_recipient(self, order_id: int, sender_id: int):
        """Only actual buyer and assigned seller of accepted verification may chat."""
        async with self.conn.execute(
            """SELECT buyer_id, seller_id FROM orders WHERE id = ?
               AND (category = 'verification' OR category IS NULL)
               AND seller_id IS NOT NULL
               AND status IN ('in_progress', 'completed')""", (order_id,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        if sender_id == row["buyer_id"]:
            return row["seller_id"]
        if sender_id == row["seller_id"]:
            return row["buyer_id"]
        return None

    async def get_chat_orders(self, user_id: int, limit: int = 12):
        async with self.conn.execute(
            """SELECT id, product_name, status FROM orders
               WHERE (buyer_id = ? OR seller_id = ?)
               AND (category = 'verification' OR category IS NULL)
               AND seller_id IS NOT NULL
               AND status IN ('in_progress', 'completed')
               ORDER BY id DESC LIMIT ?""", (user_id, user_id, limit)
        ) as cur:
            return await cur.fetchall()

    async def queue_chat_message(self, order_id: int, sender_id: int,
                                 body: str, sender_language: str):
        """Atomic authorization and durable message queue; no profile identifiers sent."""
        if not body or len(body) > 1500:
            return None
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA busy_timeout=5000")
            await conn.execute("BEGIN IMMEDIATE")
            try:
                async with conn.execute(
                    """SELECT buyer_id, seller_id FROM orders WHERE id = ?
                       AND (category = 'verification' OR category IS NULL)
                       AND seller_id IS NOT NULL
                       AND status IN ('in_progress', 'completed')""",
                    (order_id,)
                ) as cur:
                    row = await cur.fetchone()
                if not row or sender_id not in row:
                    await conn.rollback()
                    return None
                receiver = row[1] if sender_id == row[0] else row[0]
                result = await conn.execute(
                    """INSERT INTO chat_messages
                       (order_id, sender_id, receiver_id, body,
                        sender_language, status, created_at)
                       VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                    (order_id, sender_id, receiver, body, sender_language,
                     datetime.utcnow().isoformat())
                )
                await conn.commit()
                return result.lastrowid
            except Exception:
                await conn.rollback()
                raise

    async def get_undelivered_chat_ids(self, limit: int = 30):
        async with self.conn.execute(
            """SELECT id FROM chat_messages
               WHERE status = 'pending' OR
               (status = 'sending' AND attempted_at <= ?)
               ORDER BY id LIMIT ?""",
            ((datetime.utcnow() - timedelta(minutes=2)).isoformat(), limit)
        ) as cur:
            return [row["id"] for row in await cur.fetchall()]

    async def claim_chat_message(self, message_id: int):
        """Claim for delivery; two workers cannot send the same queued entry."""
        now = datetime.utcnow().isoformat()
        old = (datetime.utcnow() - timedelta(minutes=2)).isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA busy_timeout=5000")
            await conn.execute("BEGIN IMMEDIATE")
            try:
                updated = await conn.execute(
                    """UPDATE chat_messages
                       SET status = 'sending', attempts = attempts + 1, attempted_at = ?
                       WHERE id = ? AND (status = 'pending' OR
                       (status = 'sending' AND attempted_at <= ?))""",
                    (now, message_id, old)
                )
                if updated.rowcount != 1:
                    await conn.rollback()
                    return None
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    """SELECT id, order_id, sender_id, receiver_id, body,
                       sender_language FROM chat_messages WHERE id = ?""",
                    (message_id,)
                ) as cur:
                    row = await cur.fetchone()
                await conn.commit()
                return dict(row) if row else None
            except Exception:
                await conn.rollback()
                raise

    async def set_chat_delivery(self, message_id: int, delivered: bool):
        """Do not retain delivered chat body in SQLite after Telegram receives it."""
        if delivered:
            await self.conn.execute(
                """UPDATE chat_messages SET status = 'sent', body = NULL,
                   delivered_at = ? WHERE id = ? AND status = 'sending'""",
                (datetime.utcnow().isoformat(), message_id)
            )
        else:
            await self.conn.execute(
                """UPDATE chat_messages SET status = 'pending'
                   WHERE id = ? AND status = 'sending'""",
                (message_id,)
            )
        await self.conn.commit()

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

    async def debit_if_sufficient(self, user_id: int, amount: float) -> bool:
        """Списывает стоимость, только если баланс достаточен."""
        if amount < 0:
            return False
        cursor = await self.conn.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
            (amount, user_id, amount)
        )
        await self.conn.commit()
        return cursor.rowcount == 1

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

    async def create_paid_verification_order(
        self, buyer_id: int, product_id: int, entry_data: dict, checkout_key: str
    ):
        """Charge and create order atomically. Repeated checkout never charges twice."""
        if not checkout_key or len(checkout_key) > 128:
            return None, "Некорректный идентификатор покупки."
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA busy_timeout=5000")
            await conn.execute("BEGIN IMMEDIATE")
            try:
                async with conn.execute(
                    "SELECT buyer_id, order_id FROM verification_checkouts WHERE checkout_key = ?",
                    (checkout_key,),
                ) as cur:
                    previous = await cur.fetchone()
                if previous:
                    await conn.rollback()
                    if previous[0] != buyer_id:
                        return None, "Покупка принадлежит другому пользователю."
                    return previous[1], None
                async with conn.execute(
                    """SELECT id, name, buyer_price, seller_price, entry_type
                       FROM products WHERE id = ? AND is_active = 1""",
                    (product_id,),
                ) as cur:
                    product = await cur.fetchone()
                if not product:
                    await conn.rollback()
                    return None, "Позиция больше недоступна."
                price = float(product[2])
                if not 0 < price < 1000000:
                    await conn.rollback()
                    return None, "Некорректная цена позиции. Напишите в поддержку."
                debit = await conn.execute(
                    """UPDATE users SET balance = balance - ?,
                       turnover = turnover + ?, verifications_bought = verifications_bought + 1
                       WHERE user_id = ? AND balance >= ?""",
                    (price, price, buyer_id, price),
                )
                if debit.rowcount != 1:
                    await conn.rollback()
                    return None, f"Недостаточно средств. Нужно {price:.2f}$."
                result = await conn.execute(
                    """INSERT INTO orders
                       (buyer_id, product_id, product_name, buyer_price, seller_price,
                        entry_type, status, entry_data, category, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'verification', ?)""",
                    (
                        buyer_id, product[0], product[1], price, product[3],
                        product[4], OrderStatus.PENDING.value,
                        json.dumps(entry_data, ensure_ascii=False), now
                    ),
                )
                order_id = result.lastrowid
                await conn.execute(
                    """INSERT INTO verification_checkouts
                       (checkout_key, buyer_id, order_id, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (checkout_key, buyer_id, order_id, now),
                )
                await conn.commit()
                return order_id, None
            except Exception:
                await conn.rollback()
                raise

    async def refund_pending_verification_order(self, buyer_id: int, order_id: int):
        """Refund once, only before a seller accepts the verification."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA busy_timeout=5000")
            await conn.execute("BEGIN IMMEDIATE")
            try:
                async with conn.execute(
                    """SELECT buyer_price FROM orders
                       WHERE id = ? AND buyer_id = ?
                         AND status = 'pending' AND seller_id IS NULL
                         AND (category = 'verification' OR category IS NULL)""",
                    (order_id, buyer_id),
                ) as cur:
                    row = await cur.fetchone()
                if not row:
                    await conn.rollback()
                    return None
                amount = float(row[0])
                updated = await conn.execute(
                    """UPDATE orders SET status = 'cancelled', entry_data = NULL
                       WHERE id = ? AND buyer_id = ?
                         AND status = 'pending' AND seller_id IS NULL
                         AND (category = 'verification' OR category IS NULL)""",
                    (order_id, buyer_id),
                )
                if updated.rowcount != 1:
                    await conn.rollback()
                    return None
                await conn.execute(
                    """UPDATE users SET balance = balance + ?,
                       turnover = MAX(0, turnover - ?),
                       verifications_bought = MAX(0, verifications_bought - 1)
                       WHERE user_id = ?""",
                    (amount, amount, buyer_id),
                )
                await conn.execute(
                    """INSERT INTO verification_refunds
                       (order_id, buyer_id, amount, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (order_id, buyer_id, amount, datetime.utcnow().isoformat()),
                )
                await conn.commit()
                return amount
            except Exception:
                await conn.rollback()
                raise

    async def complete_verification_and_pay_seller(self, order_id: int, seller_id: int):
        """Order completion and seller payout in one transaction, once."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA busy_timeout=5000")
            await conn.execute("BEGIN IMMEDIATE")
            try:
                async with conn.execute(
                    """SELECT seller_price FROM orders WHERE id = ?
                       AND seller_id = ? AND status = 'in_progress'
                       AND (category = 'verification' OR category IS NULL)""",
                    (order_id, seller_id),
                ) as cur:
                    row = await cur.fetchone()
                if not row:
                    await conn.rollback()
                    return None
                updated = await conn.execute(
                    """UPDATE orders SET status = 'completed', completed_at = ?,
                       entry_data = NULL WHERE id = ? AND seller_id = ?
                       AND status = 'in_progress'""",
                    (datetime.utcnow().isoformat(), order_id, seller_id),
                )
                if updated.rowcount != 1:
                    await conn.rollback()
                    return None
                amount = float(row[0])
                await conn.execute(
                    """UPDATE users SET balance = balance + ?, earned = earned + ?,
                       verifications_done = verifications_done + 1
                       WHERE user_id = ?""", (amount, amount, seller_id),
                )
                await conn.commit()
                return amount
            except Exception:
                await conn.rollback()
                raise

    async def get_order(self, order_id: int) -> Optional[Order]:
        async with self.conn.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_order(row)

    def _row_to_order(self, row) -> Order:
        keys = row.keys() if hasattr(row, "keys") else []
        def g(k, default=None):
            try:
                return row[k] if k in keys else default
            except Exception:
                return default
        et = g("entry_type") or "none"
        try:
            entry = EntryType(et)
        except Exception:
            entry = EntryType.NONE
        st = g("status") or "pending"
        try:
            status = OrderStatus(st)
        except Exception:
            status = OrderStatus.PENDING
        return Order(
            id=row["id"],
            buyer_id=row["buyer_id"],
            seller_id=g("seller_id"),
            product_id=g("product_id"),
            product_name=row["product_name"],
            buyer_price=row["buyer_price"],
            seller_price=row["seller_price"],
            entry_type=entry,
            status=status,
            entry_data=g("entry_data"),
            category=g("category") or "verification",
            stock_id=g("stock_id"),
            phone=g("phone"),
            created_at=datetime.fromisoformat(row["created_at"]),
            taken_at=datetime.fromisoformat(row["taken_at"]) if g("taken_at") else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if g("completed_at") else None,
            auto_complete_at=datetime.fromisoformat(row["auto_complete_at"]) if g("auto_complete_at") else None,
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

    async def credit_paid_invoice_once(self, user_id: int, invoice_id: int):
        """Credit already-verified CryptoPay invoice at most once."""
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA busy_timeout=5000")
            await conn.execute("BEGIN IMMEDIATE")
            try:
                async with conn.execute(
                    """SELECT amount FROM invoices WHERE invoice_id = ?
                       AND user_id = ? AND status = 'active' AND purpose = 'topup'""",
                    (invoice_id, user_id),
                ) as cursor:
                    row = await cursor.fetchone()
                if not row:
                    await conn.rollback()
                    return None
                amount = float(row[0])
                if not 0 < amount < 1000000:
                    await conn.rollback()
                    return None
                cursor = await conn.execute(
                    """UPDATE invoices SET status = 'paid'
                       WHERE invoice_id = ? AND user_id = ? AND status = 'active'""",
                    (invoice_id, user_id),
                )
                if cursor.rowcount != 1:
                    await conn.rollback()
                    return None
                await conn.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                    (amount, user_id)
                )
                await conn.commit()
                return amount
            except Exception:
                await conn.rollback()
                raise

    async def mark_invoice_paid(self, invoice_id: int):
        await self.conn.execute(
            "UPDATE invoices SET status = 'paid' WHERE invoice_id = ?",
            (invoice_id,)
        )
        await self.conn.commit()


    # ──────────────────── MANUALS ────────────────────

    async def add_manual(self, name: str, buyer_price: float, delivery_type: str,
                         content_text: str = None, file_id: str = None) -> int:
        cur = await self.conn.execute(
            """INSERT INTO manuals (name, buyer_price, delivery_type, content_text, file_id)
               VALUES (?, ?, ?, ?, ?)""",
            (name, buyer_price, delivery_type, content_text, file_id)
        )
        await self.conn.commit()
        return cur.lastrowid

    async def get_manual(self, manual_id: int):
        async with self.conn.execute("SELECT * FROM manuals WHERE id = ?", (manual_id,)) as c:
            return await c.fetchone()

    async def get_all_manuals(self, only_active: bool = True):
        q = "SELECT * FROM manuals"
        if only_active:
            q += " WHERE is_active = 1"
        q += " ORDER BY id"
        async with self.conn.execute(q) as c:
            return await c.fetchall()

    async def delete_manual(self, manual_id: int) -> bool:
        cursor = await self.conn.execute(
            "UPDATE manuals SET is_active = 0 WHERE id = ? AND is_active = 1",
            (manual_id,)
        )
        await self.conn.commit()
        return cursor.rowcount == 1

    async def list_active_manuals(self, limit: int = 9, offset: int = 0):
        async with self.conn.execute(
            """SELECT id, name, buyer_price FROM manuals
               WHERE is_active = 1 ORDER BY id DESC LIMIT ? OFFSET ?""",
            (limit, offset)
        ) as cursor:
            return await cursor.fetchall()

    # ──────────────────── TG OFFERS / STOCK ────────────────────

    async def add_tg_offer(self, country: str, age_label: str, buyer_price: float, seller_price: float) -> int:
        cur = await self.conn.execute(
            """INSERT INTO tg_offers (country, age_label, buyer_price, seller_price)
               VALUES (?, ?, ?, ?)""",
            (country, age_label, buyer_price, seller_price)
        )
        await self.conn.commit()
        return cur.lastrowid

    async def list_active_tg_offers(self, limit: int = 9, offset: int = 0):
        async with self.conn.execute(
            """SELECT id, country, age_label, buyer_price FROM tg_offers
               WHERE is_active = 1 ORDER BY id DESC LIMIT ? OFFSET ?""",
            (limit, offset)
        ) as cursor:
            return await cursor.fetchall()

    async def delete_tg_offer(self, offer_id: int) -> bool:
        cursor = await self.conn.execute(
            "UPDATE tg_offers SET is_active = 0 WHERE id = ? AND is_active = 1",
            (offer_id,)
        )
        await self.conn.commit()
        return cursor.rowcount == 1

    async def list_unsold_tg_stock(self, limit: int = 9, offset: int = 0):
        async with self.conn.execute(
            """SELECT id, country, age_label, phone FROM tg_stock
               WHERE is_sold = 0 ORDER BY id DESC LIMIT ? OFFSET ?""",
            (limit, offset)
        ) as cursor:
            return await cursor.fetchall()

    async def get_unsold_tg_stock(self, stock_id: int):
        async with self.conn.execute(
            """SELECT id, country, age_label, phone FROM tg_stock
               WHERE id = ? AND is_sold = 0""", (stock_id,)
        ) as cursor:
            return await cursor.fetchone()

    async def remove_unsold_tg_stock(self, stock_id: int) -> bool:
        """Remove only unsold stock; preserve delivered orders and wipe session."""
        cursor = await self.conn.execute(
            """UPDATE tg_stock SET is_sold = 2, session_string = NULL
               WHERE id = ? AND is_sold = 0""", (stock_id,)
        )
        await self.conn.commit()
        return cursor.rowcount == 1

    async def get_tg_countries(self):
        async with self.conn.execute(
            "SELECT DISTINCT country FROM tg_offers WHERE is_active = 1 ORDER BY country"
        ) as c:
            return [r["country"] for r in await c.fetchall()]

    async def get_tg_offers_by_country(self, country: str):
        async with self.conn.execute(
            "SELECT * FROM tg_offers WHERE country = ? AND is_active = 1 ORDER BY id",
            (country,)
        ) as c:
            return await c.fetchall()

    async def get_tg_offer(self, offer_id: int):
        async with self.conn.execute("SELECT * FROM tg_offers WHERE id = ?", (offer_id,)) as c:
            return await c.fetchone()

    async def count_tg_stock(self, country: str, age_label: str) -> int:
        async with self.conn.execute(
            "SELECT COUNT(*) FROM tg_stock WHERE country = ? AND age_label = ? AND is_sold = 0",
            (country, age_label)
        ) as c:
            row = await c.fetchone()
            return row[0]

    async def take_tg_stock(self, country: str, age_label: str):
        """Берёт один не проданный акк. Возвращает row или None."""
        async with self.conn.execute(
            """SELECT * FROM tg_stock
               WHERE country = ? AND age_label = ? AND is_sold = 0
               ORDER BY id LIMIT 1""",
            (country, age_label)
        ) as c:
            row = await c.fetchone()
        if not row:
            return None
        cursor = await self.conn.execute(
            "UPDATE tg_stock SET is_sold = 1 WHERE id = ? AND is_sold = 0",
            (row["id"],)
        )
        await self.conn.commit()
        return row if cursor.rowcount == 1 else None

    async def add_tg_stock(self, country: str, age_label: str, phone: str,
                           session_string: str = None, session_type: str = "string",
                           seller_id: int = None) -> int:
        now = datetime.utcnow().isoformat()
        cur = await self.conn.execute(
            """INSERT INTO tg_stock
               (country, age_label, phone, session_string, session_type, seller_id, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (country, age_label, phone, session_string, session_type, seller_id, now)
        )
        await self.conn.commit()
        return cur.lastrowid

    async def get_tg_stock(self, stock_id: int):
        async with self.conn.execute("SELECT * FROM tg_stock WHERE id = ?", (stock_id,)) as c:
            return await c.fetchone()

    async def create_tg_account_order(self, buyer_id: int, offer, stock, hours: int = 3) -> int:
        from datetime import timedelta
        now = datetime.utcnow()
        auto_at = (now + timedelta(hours=hours)).isoformat()
        cur = await self.conn.execute(
            """INSERT INTO orders
               (buyer_id, product_id, product_name, buyer_price, seller_price,
                entry_type, status, category, stock_id, phone, created_at, auto_complete_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                buyer_id,
                offer["id"],
                f"TG {offer['country']} {offer['age_label']}",
                offer["buyer_price"],
                offer["seller_price"],
                "none",
                "awaiting_code",
                "tg_account",
                stock["id"],
                stock["phone"],
                now.isoformat(),
                auto_at,
            )
        )
        await self.conn.commit()
        return cur.lastrowid

    async def create_manual_order(self, buyer_id: int, manual) -> int:
        now = datetime.utcnow().isoformat()
        cur = await self.conn.execute(
            """INSERT INTO orders
               (buyer_id, product_id, product_name, buyer_price, seller_price,
                entry_type, status, category, created_at, completed_at)
               VALUES (?, ?, ?, ?, 0, 'none', 'completed', 'manual', ?, ?)""",
            (buyer_id, manual["id"], manual["name"], manual["buyer_price"], now, now)
        )
        await self.conn.commit()
        return cur.lastrowid



# Глобальный экземпляр
db = Database()
