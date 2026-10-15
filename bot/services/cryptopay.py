"""Minimal Crypto Pay API client built on aiohttp.

Official API reference: https://help.cr.bot/ru/articles/10279948-crypto-pay-api
No legacy CryptoPayAPI dependency; supports aiogram's aiohttp version.
"""
import logging
from decimal import Decimal, InvalidOperation

import aiohttp

from bot.config import settings

logger = logging.getLogger(__name__)


def _positive_amount(amount) -> str:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        raise ValueError("Некорректная сумма")
    if not value.is_finite() or value <= 0:
        raise ValueError("Сумма должна быть больше нуля")
    return format(value, "f")


class CryptoPayService:
    def __init__(self):
        self.session = None
        base = "testnet-pay.crypt.bot" if settings.CRYPTOPAY_TESTNET else "pay.crypt.bot"
        self.base_url = f"https://{base}/api"

    async def start(self):
        if not settings.CRYPTOPAY_TOKEN:
            raise RuntimeError("CRYPTOPAY_TOKEN отсутствует в переменных окружения")
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=25)
            )
        try:
            app = await self._request("getMe")
            logger.info("CryptoPay connected: app_id=%s", app.get("app_id"))
        except Exception:
            await self.close()
            raise

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None

    async def _request(self, method: str, params=None):
        if not self.session or self.session.closed:
            raise RuntimeError("CryptoPay не подключён. Проверьте токен и настройки хостинга.")
        async with self.session.post(
            f"{self.base_url}/{method}",
            json=params or {},
            headers={"Crypto-Pay-API-Token": settings.CRYPTOPAY_TOKEN},
        ) as response:
            response.raise_for_status()
            data = await response.json()
        if not data.get("ok"):
            raise RuntimeError(f"CryptoPay {method}: {data.get('error', 'API error')}")
        return data["result"]

    async def create_invoice(self, amount: float, description: str = "", payload: str = "") -> dict:
        price = _positive_amount(amount)
        invoice = await self._request(
            "createInvoice",
            {
                "asset": "USDT",
                "amount": price,
                "description": description[:1024] or f"Пополнение {price} USDT",
                "payload": payload[:4096],
                "expires_in": 3600,
            },
        )
        link = invoice.get("bot_invoice_url") or invoice.get("pay_url")
        if not link:
            raise RuntimeError("CryptoPay не вернул ссылку для оплаты")
        return {
            "invoice_id": int(invoice["invoice_id"]),
            "bot_invoice_url": link,
            "amount": float(price),
            "status": invoice.get("status", "active"),
        }

    async def get_invoice(self, invoice_id: int):
        result = await self._request("getInvoices", {"invoice_ids": str(invoice_id)})
        if isinstance(result, list):
            invoices = result
        elif isinstance(result, dict):
            invoices = result.get("items") or result.get("invoices") or []
        else:
            invoices = []
        for invoice in invoices:
            if int(invoice.get("invoice_id", -1)) == int(invoice_id):
                return invoice
        return None

    async def check_invoice_paid(self, invoice_id: int) -> bool:
        invoice = await self.get_invoice(invoice_id)
        return bool(invoice and invoice.get("status") == "paid")

    async def create_check(self, amount: float, asset: str = "USDT") -> dict:
        price = _positive_amount(amount)
        if asset != "USDT":
            raise ValueError("Доступен вывод только в USDT")
        check = await self._request("createCheck", {"asset": asset, "amount": price})
        link = check.get("bot_check_url")
        if not link:
            raise RuntimeError("CryptoPay не вернул ссылку на чек")
        return {
            "check_id": int(check["check_id"]),
            "bot_check_url": link,
            "amount": float(price),
        }


cryptopay = CryptoPayService()
