"""Regression tests for the store's catalog assets, pagination, wallet and payouts."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("OWNER_ID", "1234567")
os.environ.setdefault("CRYPTOPAY_TOKEN", "TEST_TOKEN")

from bot.database.db import Database
from bot.database.models import EntryType
from bot.keyboards.pagination import page_slice
from bot.services.cryptopay import CryptoPayService


class UpgradeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "store.sqlite"))
        await self.db.connect()
        self.buyer = 911004
        self.seller = 911005
        await self.db.add_user(self.buyer, None, "buyer")
        await self.db.add_user(self.seller, None, "seller")
        await self.db.set_balance(self.buyer, 100)

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def test_five_slots_pagination(self):
        data = list(range(12))
        self.assertEqual(page_slice(data, 0)[0], [0, 1, 2, 3, 4])
        self.assertEqual(page_slice(data, 1)[0], [5, 6, 7, 8, 9])
        self.assertEqual(page_slice(data, 2)[0], [10, 11])
        self.assertFalse(page_slice(data, 2)[3])

    async def test_sticker_from_telegram_file_id_saved_without_manual_input(self):
        product = await self.db.add_product("Test", 3, 2, EntryType.TELEGRAM)
        self.assertTrue(await self.db.set_item_sticker("verification", product, "sticker-file-abc"))
        self.assertEqual(await self.db.get_item_sticker("verification", product), "sticker-file-abc")
        manual = await self.db.add_manual("Guide", 2, "text", content_text="Useful")
        self.assertTrue(await self.db.set_item_sticker("manual", manual, "file-def"))
        self.assertEqual(await self.db.get_item_sticker("manual", manual), "file-def")

    async def test_automatic_wallet_transfer_has_spend_id(self):
        service = CryptoPayService()
        service._request = AsyncMock(return_value={"transfer_id": 111, "status": "completed"})
        result = await service.transfer_to_user(self.buyer, 5.5, "jaegerstore-42")
        self.assertEqual(result["transfer_id"], 111)
        method, kwargs = service._request.await_args.args
        self.assertEqual(method, "transfer")
        self.assertEqual(kwargs["user_id"], self.buyer)
        self.assertEqual(kwargs["spend_id"], "jaegerstore-42")

    async def test_withdrawal_reserve_once(self):
        first, error = await self.db.reserve_withdrawal(self.buyer, 12)
        self.assertIsNone(error)
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 88)
        second, error = await self.db.reserve_withdrawal(self.buyer, 12)
        self.assertIsNone(second)
        self.assertIn("обрабатывается", error)
        await self.db.mark_withdrawal(first["id"], "sent", "988")
        third, error = await self.db.reserve_withdrawal(self.buyer, 12)
        self.assertIsNone(error)
        self.assertNotEqual(first["spend_id"], third["spend_id"])
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 76)


    async def test_returned_withdrawal_refunded_exactly_once(self):
        reserved, error = await self.db.reserve_withdrawal(self.buyer, 8)
        self.assertIsNone(error)
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 92)
        self.assertTrue(await self.db.refund_returned_withdrawal(reserved["id"]))
        self.assertFalse(await self.db.refund_returned_withdrawal(reserved["id"]))
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 100)

    async def test_wallet_check_list_is_throttled(self):
        reserved, error = await self.db.reserve_withdrawal(self.buyer, 4)
        self.assertIsNone(error)
        self.assertEqual(len(await self.db.open_withdrawals()), 1)
        await self.db.mark_withdrawal_checked(reserved["id"])
        self.assertEqual(await self.db.open_withdrawals(), [])

    async def test_pending_crypto_invoice_resumes_after_restart(self):
        await self.db.save_invoice(775401, self.buyer, 12, "topup")
        self.assertTrue(any(row["invoice_id"] == 775401
                            for row in await self.db.get_recent_pending_invoices()))
        await self.db.close()
        await self.db.connect()
        self.assertEqual(await self.db.credit_paid_invoice_once(self.buyer, 775401), 12)
        self.assertIsNone(await self.db.credit_paid_invoice_once(self.buyer, 775401))
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 112)

    async def test_manual_purchase_idempotent(self):
        manual = await self.db.add_manual("Manual", 5, "text", content_text="read")
        order_a, fresh, error = await self.db.buy_manual_paid(self.buyer, manual)
        self.assertIsNone(error)
        self.assertTrue(fresh)
        order_b, fresh, error = await self.db.buy_manual_paid(self.buyer, manual)
        self.assertIsNone(error)
        self.assertFalse(fresh)
        self.assertEqual(order_a, order_b)
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 95)

    async def test_telegram_item_purchase_transaction(self):
        await self.db.set_balance(self.buyer, 14)
        offer = await self.db.add_tg_offer("Spain", "1 year", 10, 3)
        stock = await self.db.add_tg_stock("Spain", "1 year", "+34123456789",
                                          seller_id=self.seller)
        order_a, error = await self.db.buy_tg_paid(self.buyer, offer, "stock-order-1")
        self.assertIsNone(error)
        order_b, error = await self.db.buy_tg_paid(self.buyer, offer, "stock-order-1")
        self.assertEqual(order_a, order_b)
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 4)
        self.assertEqual((await self.db.get_user(self.seller)).balance, 3)
        self.assertTrue((await self.db.get_tg_stock(stock))["is_sold"])
        order_c, error = await self.db.buy_tg_paid(self.buyer, offer, "stock-order-2")
        self.assertIsNone(order_c)
        self.assertEqual(error, "Нет в наличии.")
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 4)

    async def test_migration_preserves_wallet_and_orders(self):
        product = await self.db.add_product("Existing", 2, 1, EntryType.EMAIL)
        await self.db.close()
        await self.db.connect()
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 100)
        self.assertTrue((await self.db.get_product(product)).is_active)


if __name__ == "__main__":
    unittest.main()
