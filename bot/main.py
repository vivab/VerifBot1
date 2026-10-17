import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.database.db import db
from bot.services.cryptopay import cryptopay
from bot.services.order_timeouts import pending_verification_timeout_worker
from bot.handlers import common, user, seller, owner, chat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)
_background_tasks = []


async def auto_complete_tg_orders(bot: Bot):
    """Авто-завершение TG-аккаунт заказов по таймеру."""
    import asyncio
    from datetime import datetime
    while True:
        try:
            await asyncio.sleep(60)
            async with db.conn.execute(
                """SELECT id, buyer_id FROM orders
                   WHERE status = 'awaiting_code' AND auto_complete_at IS NOT NULL
                   AND auto_complete_at <= ?""",
                (datetime.utcnow().isoformat(),)
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                await db.complete_order(row["id"])
                try:
                    await bot.send_message(
                        row["buyer_id"],
                        f"⏰ Заказ #{row['id']} автоматически завершён (истекло время)."
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"auto_complete error: {e}")


async def reconcile_wallet(bot: Bot):
    """Reconcile paid invoices and pending Crypto Bot transfers without double credit."""
    while True:
        try:
            for row in await db.get_recent_pending_invoices():
                try:
                    if await cryptopay.check_invoice_paid(row["invoice_id"]):
                        credited = await db.credit_paid_invoice_once(
                            row["user_id"], row["invoice_id"]
                        )
                        if credited is not None:
                            try:
                                await bot.send_message(
                                    row["user_id"],
                                    f"✅ Пополнение {credited:.2f} USDT подтверждено! Баланс обновлён."
                                )
                            except Exception:
                                pass
                except Exception as error:
                    logger.warning("Topup #%s check failed: %s",
                                   row["invoice_id"], type(error).__name__)

            for row in await db.open_withdrawals():
                await db.mark_withdrawal_checked(row["id"])
                try:
                    transfer = await cryptopay.get_transfer_by_spend_id(row["spend_id"])
                    if transfer is None:
                        # Same spend_id: Crypto Pay accepts only one transfer for it.
                        transfer = await cryptopay.transfer_to_user(
                            row["user_id"], row["amount"], row["spend_id"]
                        )
                    status = transfer.get("status", "completed")
                    if status == "returned":
                        if await db.refund_returned_withdrawal(row["id"]):
                            try:
                                await bot.send_message(
                                    row["user_id"],
                                    f"↩️ Вывод #{row['id']} возвращён Crypto Bot. "
                                    f"{row['amount']:.2f} USDT вновь на вашем балансе."
                                )
                            except Exception:
                                pass
                    elif status == "completed":
                        await db.mark_withdrawal(
                            row["id"], "sent", transfer.get("transfer_id")
                        )
                        try:
                            await bot.send_message(
                                row["user_id"], f"✅ Вывод #{row['id']} завершён Crypto Bot."
                            )
                        except Exception:
                            pass
                except Exception as error:
                    logger.warning("Withdrawal #%s needs reconciliation: %s",
                                   row["id"], type(error).__name__)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Wallet reconciliation failed")
        await asyncio.sleep(60)


async def on_startup(bot: Bot):
    await db.connect()
    try:
        await cryptopay.start()
    except Exception as e:
        logger.error(f"CryptoPay start failed: {e}")
    me = await bot.get_me()
    logger.info(f"Bot started: @{me.username}")
    _background_tasks.append(asyncio.create_task(auto_complete_tg_orders(bot)))
    _background_tasks.append(asyncio.create_task(chat.chat_delivery_worker(bot)))
    _background_tasks.append(asyncio.create_task(reconcile_wallet(bot)))
    _background_tasks.append(asyncio.create_task(pending_verification_timeout_worker(bot)))


async def on_shutdown(bot: Bot):
    for task in _background_tasks:
        task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()
    await cryptopay.close()
    await db.close()
    logger.info("Bot stopped")


async def main():
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Роутеры
    dp.include_router(common.router)
    dp.include_router(user.router)
    dp.include_router(seller.router)
    dp.include_router(owner.router)
    dp.include_router(chat.router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Удаляем вебхук на всякий случай (long polling)
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
