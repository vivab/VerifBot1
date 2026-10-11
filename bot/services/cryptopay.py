import logging
from typing import Optional

from bot.config import settings

logger = logging.getLogger(__name__)


class CryptoPayService:
    def __init__(self):
        self.client = None
        self.enabled = False

    async def start(self):
        try:
            from CryptoPayAPI.AioCryptoPay import AioCryptoPay

            self.client = AioCryptoPay(
                token=settings.CRYPTOPAY_TOKEN,
                is_test_net=settings.CRYPTOPAY_TESTNET
            )
            me = await self.client.get_me()
            self.enabled = True
            logger.info(f"CryptoPay OK: {me}")
        except Exception as e:
            self.enabled = False
            self.client = None
            logger.error(f"CryptoPay не подключился: {e}")
            logger.warning("Бот работает БЕЗ платежей и вывода. Исправь CRYPTOPAY_TOKEN.")

    async def close(self):
        if self.client:
            try:
                await self.client.close()
            except Exception:
                pass

    async def create_invoice(self, amount: float, description: str = "", payload: str = "") -> dict:
        if not self.enabled:
            raise Exception("CryptoPay не подключён. Проверь токен.")
        from CryptoPayAPI.types.asset import USDT
        invoice = await self.client.create_invoice(
            amount=amount,
            asset=USDT,
            description=description or f"Оплата {amount}$",
            payload=payload,
            expires_in=3600,
        )
        return {
            "invoice_id": invoice.invoice_id,
            "bot_invoice_url": invoice.bot_invoice_url,
            "amount": amount,
            "status": invoice.status,
        }

    async def create_check(self, amount: float, asset: str = "USDT") -> dict:
        if not self.enabled:
            raise Exception("CryptoPay не подключён. Проверь токен.")
        from CryptoPayAPI.types.asset import USDT
        check = await self.client.create_check(asset=USDT, amount=amount)
        return {
            "check_id": check.check_id,
            "bot_check_url": check.bot_check_url,
            "amount": amount,
        }


cryptopay = CryptoPayService()
