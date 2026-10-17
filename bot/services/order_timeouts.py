"""24h timeout for unaccepted verification orders.

A persistent SQLite ledger guarantees exactly-once refunds. This worker
does not operate on accepted orders, Telegram account stock or manuals.
"""
import asyncio
import logging
from html import escape
from aiogram import Bot

from bot.database.db import db
from bot.database.models import UserRole

logger = logging.getLogger(__name__)


async def notify_sellers_order_closed(bot: Bot, order_id: int, reason: str):
    """Old Accept buttons remain safe; send proactive notices as well."""
    reason_text = (
        "❌ Заказ отменён пользователем."
        if reason == "buyer" else
        "⏰ Заказ отменён автоматически: в течение 24 часов никто не принял его."
    )
    users = []
    for role in (UserRole.SELLER, UserRole.ADMIN, UserRole.OWNER):
        users.extend(await db.get_users_by_role(role))
    for user_id in {user.user_id for user in users}:
        try:
            await bot.send_message(
                user_id,
                f"📦 Заказ #{order_id}\n{reason_text}\n"
                "Принять заказ больше нельзя."
            )
        except Exception:
            logger.warning("Unable to notify seller %s of cancelled order #%s",
                           user_id, order_id)


async def notify_expired_order(bot: Bot, result: dict):
    order_id = result["order_id"]
    buyer_id = result["buyer_id"]
    amount = result["amount"]
    try:
        await bot.send_message(
            buyer_id,
            f"⏰ Заказ #{order_id} автоматически отменён.\n\n"
            "Никто из продавцов не принял его за 24 часа.\n"
            f"💰 Возвращено на баланс: {amount:.2f} USDT.\n"
            "Вы можете оформить новую покупку в любое время."
        )
    except Exception:
        logger.warning("Unable to notify buyer %s of timeout #%s",
                       buyer_id, order_id)
    await notify_sellers_order_closed(bot, order_id, "timeout")


async def expire_order_if_needed(order_id: int, bot: Bot):
    """Also called by a seller's stale Accept button after 24h."""
    result = await db.cancel_pending_verification_order(
        order_id, reason="timeout"
    )
    if result:
        await notify_expired_order(bot, result)
    return result


async def expire_pending_orders_once(bot: Bot):
    ids = await db.get_expired_pending_verification_ids(limit=100)
    for order_id in ids:
        try:
            await expire_order_if_needed(order_id, bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Could not expire verification order #%s", order_id)
    return len(ids)


async def pending_verification_timeout_worker(bot: Bot):
    """Check immediately on launch, then every minute."""
    while True:
        try:
            await expire_pending_orders_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Verification timeout worker error")
        await asyncio.sleep(60)
