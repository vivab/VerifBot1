import os
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("OWNER_ID", "1234567")
os.environ.setdefault("CRYPTOPAY_TOKEN", "TEST_TOKEN")

from bot.database.db import Database
from bot.database.models import EntryType, OrderStatus
from bot.services.cryptopay import _positive_amount, CryptoPayService
from unittest.mock import AsyncMock


class VerificationAccountingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tempdir.name) / "shop.db"))
        await self.db.connect()
        self.buyer_id, self.seller_id = 920001, 920002
        await self.db.add_user(self.buyer_id, None, "Buyer")
        await self.db.add_user(self.seller_id, None, "Seller")
        await self.db.set_balance(self.buyer_id, 25)
        self.product_id = await self.db.add_product("Test KYC", 5, 3, EntryType.TELEGRAM)

    async def asyncTearDown(self):
        await self.db.close()
        self.tempdir.cleanup()

    async def test_no_charge_before_purchase(self):
        buyer = await self.db.get_user(self.buyer_id)
        self.assertEqual(buyer.balance, 25)
        self.assertEqual(buyer.verifications_bought, 0)

    async def test_checkout_and_refund_are_idempotent(self):
        key = "checkout-for-refund"
        order_id, error = await self.db.create_paid_verification_order(
            self.buyer_id, self.product_id, {"contact": "@testuser"}, key
        )
        self.assertIsNone(error)
        second_order, error = await self.db.create_paid_verification_order(
            self.buyer_id, self.product_id, {"contact": "@testuser"}, key
        )
        self.assertEqual(second_order, order_id)
        self.assertIsNone(error)
        buyer = await self.db.get_user(self.buyer_id)
        self.assertEqual(buyer.balance, 20)
        self.assertEqual(buyer.turnover, 5)
        self.assertEqual(buyer.verifications_bought, 1)
        # Advance a newly placed order past the mandatory one-hour hold.
        # A refund before that timestamp is intentionally forbidden.
        self.assertIsNone(
            await self.db.refund_pending_verification_order(self.buyer_id, order_id)
        )
        await self.db.conn.execute(
            "UPDATE orders SET created_at=? WHERE id=?",
            ((datetime.utcnow() - timedelta(hours=1, minutes=1)).isoformat(), order_id)
        )
        await self.db.conn.commit()
        self.assertEqual(
            await self.db.refund_pending_verification_order(self.buyer_id, order_id), 5
        )
        self.assertIsNone(
            await self.db.refund_pending_verification_order(self.buyer_id, order_id)
        )
        buyer = await self.db.get_user(self.buyer_id)
        self.assertEqual(buyer.balance, 25)
        self.assertEqual(buyer.turnover, 0)
        self.assertEqual(buyer.verifications_bought, 0)
        self.assertEqual((await self.db.get_order(order_id)).status, OrderStatus.CANCELLED)

    async def test_seller_payout_only_once(self):
        order_id, error = await self.db.create_paid_verification_order(
            self.buyer_id, self.product_id, {"contact": "+491234567890"}, "payout"
        )
        self.assertIsNone(error)
        self.assertTrue(await self.db.take_order(order_id, self.seller_id))
        self.assertIsNone(
            await self.db.refund_pending_verification_order(self.buyer_id, order_id)
        )
        self.assertEqual(
            await self.db.complete_verification_and_pay_seller(order_id, self.seller_id), 3
        )
        self.assertIsNone(
            await self.db.complete_verification_and_pay_seller(order_id, self.seller_id)
        )
        seller = await self.db.get_user(self.seller_id)
        self.assertEqual(seller.balance, 3)
        self.assertEqual(seller.earned, 3)
        self.assertEqual(seller.verifications_done, 1)
        self.assertEqual((await self.db.get_order(order_id)).status, OrderStatus.COMPLETED)

    async def test_insufficient_balance_causes_no_order(self):
        await self.db.set_balance(self.buyer_id, 2)
        order_id, error = await self.db.create_paid_verification_order(
            self.buyer_id, self.product_id, {"contact": "@buyer1"}, "no-money"
        )
        self.assertIsNone(order_id)
        self.assertIn("Недостаточно", error)
        self.assertEqual((await self.db.get_user(self.buyer_id)).balance, 2)

    async def test_paid_invoice_credited_once(self):
        await self.db.save_invoice(1020304, self.buyer_id, 7, "topup")
        self.assertEqual(await self.db.credit_paid_invoice_once(self.buyer_id, 1020304), 7)
        self.assertIsNone(await self.db.credit_paid_invoice_once(self.buyer_id, 1020304))
        self.assertEqual((await self.db.get_user(self.buyer_id)).balance, 32)

    async def test_cryptopay_amount_and_invoice_mapping(self):
        self.assertEqual(_positive_amount(2.5), "2.5")
        with self.assertRaises(ValueError):
            _positive_amount(float("nan"))
        client = CryptoPayService()
        client._request = AsyncMock(return_value=[
            {"invoice_id": 1234, "status": "paid"},
            {"invoice_id": 1235, "status": "active"}
        ])
        self.assertTrue(await client.check_invoice_paid(1234))
        self.assertFalse(await client.check_invoice_paid(1235))

    async def test_cannot_refund_other_user_order(self):
        order_id, error = await self.db.create_paid_verification_order(
            self.buyer_id, self.product_id, {"contact": "@buyer1"}, "ownership-check"
        )
        self.assertIsNone(error)
        self.assertIsNone(
            await self.db.refund_pending_verification_order(self.seller_id, order_id)
        )
        self.assertEqual((await self.db.get_user(self.buyer_id)).balance, 20)


if __name__ == "__main__":
    unittest.main()
