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


async def on_startup(bot: Bot):
    await db.connect()
    await cryptopay.start()
    me = await bot.get_me()
    logger.info(f"Bot started: @{me.username}")


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

    # Ð Ð¾ÑÑÐµÑÑ
    dp.include_router(common.router)
    dp.include_router(user.router)
    dp.include_router(seller.router)
    dp.include_router(owner.router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Ð£Ð´Ð°Ð»ÑÐµÐ¼ Ð²ÐµÐ±ÑÑÐº Ð½Ð° Ð²ÑÑÐºÐ¸Ð¹ ÑÐ»ÑÑÐ°Ð¹ (long polling)
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
