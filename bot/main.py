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
from bot.handlers import common, user, seller, owner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


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


async def on_startup(bot: Bot):
    await db.connect()
    try:
        await cryptopay.start()
    except Exception as e:
        logger.error(f"CryptoPay start failed: {e}")
    me = await bot.get_me()
    logger.info(f"Bot started: @{me.username}")
    import asyncio
    asyncio.create_task(auto_complete_tg_orders(bot))


async def on_shutdown(bot: Bot):
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
