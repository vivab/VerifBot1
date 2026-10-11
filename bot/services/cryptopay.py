import logging
from typing import Optional

from CryptoPayAPI.AioCryptoPay import AioCryptoPay
from CryptoPayAPI.types.asset import USDT

from bot.config import settings

logger = logging.getLogger(__name__)


class CryptoPayService:
    def __init__(self):
        self.client: Optional[AioCryptoPay] = None

    async def start(self):
        self.client = AioCryptoPay(
            token=settings.CRYPTOPAY_TOKEN,
            is_test_net=settings.CRYPTOPAY_TESTNET
        )
        me = await self.client.get_me()
        logger.info(f"CryptoPay connected: {me}")

    async def close(self):
        if self.client:
            await self.client.close()

    async def create_invoice(self, amount: float, description: str = "",
                             payload: str = "") -> dict:
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

    async def get_invoice(self, invoice_id: int):
        try:
            invoices = await self.client.get_invoices(invoice_ids=str(invoice_id))
            if invoices:
                return invoices[0] if isinstance(invoices, list) else invoices
        except Exception as e:
            logger.error(f"get_invoice error: {e}")
        return None

    async def check_invoice_paid(self, invoice_id: int) -> bool:
        invoice = await self.get_invoice(invoice_id)
        if invoice is None:
            return False
        status = getattr(invoice, "status", None) or (invoice.get("status") if isinstance(invoice, dict) else None)
        return status == "paid"

    async def create_check(self, amount: float, asset: str = "USDT") -> dict:
        check = await self.client.create_check(
            asset=USDT,
            amount=amount,
        )
        return {
            "check_id": check.check_id,
            "bot_check_url": check.bot_check_url,
            "amount": amount,
        }


cryptopay = CryptoPayService()
