"""Time-based refunds and stale seller-button regression tests.

No live payment provider, Telegram connection, or sleep is required.
"""
import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("OWNER_ID", "1234567")
os.environ.setdefault("CRYPTOPAY_TOKEN", "TEST_TOKEN")

from bot.database.db import Database
from bot.database.models import EntryType, OrderStatus, UserRole
from bot.handlers import user as user_handler, seller as seller_handler
from bot.services import order_timeouts


class TimedVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "orders.sqlite"))
        await self.db.connect()
        self.buyer, self.seller, self.other_seller = 930001, 930002, 930003
        for uid in [self.buyer, self.seller, self.other_seller]:
            await self.db.add_user(uid, None, "test")
        await self.db.update_user_role(self.seller, UserRole.SELLER)
        await self.db.update_user_role(self.other_seller, UserRole.SELLER)
        await self.db.set_balance(self.buyer, 40)
        self.product = await self.db.add_product("KYC", 10, 5, EntryType.NONE)
        self.order_id, error = await self.db.create_paid_verification_order(
            self.buyer, self.product, None, "timeout-test-one"
        )
        self.assertIsNone(error)

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def move_order_back(self, order_id, *, hours=0, minutes=0):
        await self.db.conn.execute(
            "UPDATE orders SET created_at=? WHERE id=?",
            ((datetime.utcnow() - timedelta(hours=hours, minutes=minutes)).isoformat(),
             order_id)
        )
        await self.db.conn.commit()

    async def test_one_hour_hold_is_enforced_in_atomic_transaction(self):
        self.assertIsNone(await self.db.refund_pending_verification_order(
            self.buyer, self.order_id
        ))
        await self.move_order_back(self.order_id, minutes=59)
        self.assertIsNone(await self.db.refund_pending_verification_order(
            self.buyer, self.order_id
        ))
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 30)
        self.assertEqual((await self.db.get_order(self.order_id)).status, OrderStatus.PENDING)
        await self.move_order_back(self.order_id, hours=1, minutes=1)
        self.assertEqual(
            await self.db.refund_pending_verification_order(self.buyer, self.order_id), 10
        )
        order = await self.db.get_order(self.order_id)
        self.assertEqual(order.cancel_reason, "buyer")
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertIsNone(await self.db.refund_pending_verification_order(
            self.buyer, self.order_id
        ))
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 40)
        self.assertEqual((await self.db.get_user(self.buyer)).verifications_bought, 0)

    async def test_timeout_requires_full_24_hours(self):
        await self.move_order_back(self.order_id, hours=23, minutes=59)
        self.assertEqual(await self.db.get_expired_pending_verification_ids(), [])
        self.assertIsNone(await self.db.cancel_pending_verification_order(
            self.order_id, reason="timeout"
        ))
        await self.move_order_back(self.order_id, hours=24, minutes=1)
        self.assertEqual(await self.db.get_expired_pending_verification_ids(),
                         [self.order_id])
        result = await self.db.cancel_pending_verification_order(
            self.order_id, reason="timeout"
        )
        self.assertEqual(result["amount"], 10)
        self.assertEqual(result["buyer_id"], self.buyer)
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 40)
        self.assertIsNone(await self.db.cancel_pending_verification_order(
            self.order_id, reason="timeout"
        ))
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 40)

    async def test_seller_cannot_accept_24h_old_order_even_before_worker(self):
        await self.move_order_back(self.order_id, hours=25)
        self.assertFalse(await self.db.take_order(self.order_id, self.seller))
        self.assertEqual((await self.db.get_order(self.order_id)).status, OrderStatus.PENDING)
        # Seller's failed click and background worker share this same operation.
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch.object(order_timeouts, "db", self.db):
            result = await order_timeouts.expire_order_if_needed(self.order_id, bot)
        self.assertEqual(result["reason"], "timeout")
        self.assertFalse(await self.db.take_order(self.order_id, self.other_seller))
        self.assertEqual((await self.db.get_order(self.order_id)).cancel_reason, "timeout")
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 40)
        destinations = [c.args[0] for c in bot.send_message.await_args_list]
        self.assertIn(self.buyer, destinations)
        self.assertIn(self.seller, destinations)

    async def test_accepted_order_stays_active_after_24_hours(self):
        self.assertTrue(await self.db.take_order(self.order_id, self.seller))
        await self.move_order_back(self.order_id, hours=25)
        self.assertEqual(await self.db.get_expired_pending_verification_ids(), [])
        self.assertIsNone(await self.db.cancel_pending_verification_order(
            self.order_id, reason="timeout"
        ))
        self.assertEqual((await self.db.get_order(self.order_id)).status,
                         OrderStatus.IN_PROGRESS)
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 30)

    async def test_buyer_cannot_cancel_other_buyers_order(self):
        await self.move_order_back(self.order_id, hours=2)
        self.assertIsNone(await self.db.cancel_pending_verification_order(
            self.order_id, buyer_id=self.seller, reason="buyer"
        ))
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 30)

    async def test_repeat_worker_processes_each_expired_order_once(self):
        await self.move_order_back(self.order_id, hours=25)
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch.object(order_timeouts, "db", self.db):
            self.assertEqual(await order_timeouts.expire_pending_orders_once(bot), 1)
            self.assertEqual(await order_timeouts.expire_pending_orders_once(bot), 0)
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 40)
        self.assertEqual((await self.db.get_order(self.order_id)).cancel_reason, "timeout")

    async def test_free_order_timeout_has_zero_refund(self):
        free = await self.db.add_product("Free", 0, 0, EntryType.NONE)
        oid, error = await self.db.create_paid_verification_order(
            self.buyer, free, None, "free-timeout"
        )
        self.assertIsNone(error)
        await self.move_order_back(oid, hours=25)
        result = await self.db.cancel_pending_verification_order(
            oid, reason="timeout"
        )
        self.assertEqual(result["amount"], 0)
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 30)

    async def test_buyer_cancel_after_timeout_is_recorded_as_timeout(self):
        await self.move_order_back(self.order_id, hours=25)
        result = await self.db.cancel_pending_verification_order(
            self.order_id, buyer_id=self.buyer, reason="buyer"
        )
        self.assertEqual(result["reason"], "timeout")
        self.assertEqual((await self.db.get_order(self.order_id)).cancel_reason, "timeout")

    async def test_buyer_callback_before_one_hour_shows_hold_warning(self):
        callback = SimpleNamespace(
            data=f"cancel_verification:{self.order_id}",
            from_user=SimpleNamespace(id=self.buyer),
            message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
            answer=AsyncMock()
        )
        with patch.object(user_handler, "db", self.db):
            await user_handler.cancel_verification_order(
                callback, SimpleNamespace(send_message=AsyncMock())
            )
        callback.answer.assert_awaited_once()
        self.assertIn("только после одного часа", callback.answer.await_args.args[0])
        callback.message.edit_text.assert_not_awaited()
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 30)

    async def test_buyer_callback_after_hour_notifies_sellers_and_refunds(self):
        await self.move_order_back(self.order_id, hours=2)
        callback = SimpleNamespace(
            data=f"cancel_verification:{self.order_id}",
            from_user=SimpleNamespace(id=self.buyer),
            message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
            answer=AsyncMock()
        )
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch.object(user_handler, "db", self.db), \
             patch.object(order_timeouts, "db", self.db):
            await user_handler.cancel_verification_order(callback, bot)
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 40)
        self.assertEqual((await self.db.get_order(self.order_id)).cancel_reason, "buyer")
        callback.message.edit_text.assert_awaited_once()
        self.assertIn("Продавцы больше не смогут",
                      callback.message.edit_text.await_args.args[0])
        sent = [c.args[1] for c in bot.send_message.await_args_list]
        self.assertTrue(any("Заказ отменён пользователем" in text for text in sent))

    async def test_stale_seller_button_explicitly_says_buyer_cancelled(self):
        await self.move_order_back(self.order_id, hours=2)
        await self.db.cancel_pending_verification_order(
            self.order_id, buyer_id=self.buyer, reason="buyer"
        )
        callback = SimpleNamespace(
            data=f"take_order:{self.order_id}",
            from_user=SimpleNamespace(id=self.seller),
            message=SimpleNamespace(text=f"New order #{self.order_id}",
                                    edit_text=AsyncMock()),
            answer=AsyncMock()
        )
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch.object(seller_handler, "db", self.db), \
             patch.object(order_timeouts, "db", self.db):
            await seller_handler.take_order(callback, bot)
        callback.answer.assert_awaited_once()
        self.assertIn("Заказ отменён пользователем",
                      callback.answer.await_args.args[0])
        self.assertFalse(await self.db.take_order(self.order_id, self.other_seller))

    async def test_buyer_vs_seller_race_does_not_both_succeed(self):
        await self.move_order_back(self.order_id, hours=2)
        buyer_cancel, seller_accept = await asyncio.gather(
            self.db.cancel_pending_verification_order(
                self.order_id, buyer_id=self.buyer, reason="buyer"
            ),
            self.db.take_order(self.order_id, self.seller)
        )
        self.assertNotEqual(bool(buyer_cancel), bool(seller_accept))
        order = await self.db.get_order(self.order_id)
        wallet = (await self.db.get_user(self.buyer)).balance
        if buyer_cancel:
            self.assertEqual(order.status, OrderStatus.CANCELLED)
            self.assertEqual(wallet, 40)
        else:
            self.assertEqual(order.status, OrderStatus.IN_PROGRESS)
            self.assertEqual(wallet, 30)


if __name__ == "__main__":
    unittest.main()
