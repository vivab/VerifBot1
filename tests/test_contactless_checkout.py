"""One-tap anonymous verification checkout regression tests."""
import os
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("OWNER_ID", "1234567")
os.environ.setdefault("CRYPTOPAY_TOKEN", "TEST_TOKEN")

from bot.database.db import Database
from bot.database.models import EntryType, OrderStatus, UserRole
from bot.handlers import user as user_handlers, seller as seller_handlers


def fake_callback(user_id: int, product_id: int, message_id: int = 777):
    message = SimpleNamespace(
        chat=SimpleNamespace(id=user_id),
        message_id=message_id,
        edit_text=AsyncMock(),
        answer=AsyncMock(),
    )
    return SimpleNamespace(
        data=f"confirm_buy:{product_id}",
        from_user=SimpleNamespace(id=user_id),
        message=message,
        answer=AsyncMock(),
    )


class ContactlessCheckoutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "store.sqlite"))
        await self.db.connect()
        self.buyer = 98101
        self.seller = 98102
        await self.db.add_user(self.buyer, None, "Buyer")
        await self.db.add_user(self.seller, None, "Seller")
        await self.db.update_user_role(self.seller, UserRole.SELLER)
        await self.db.set_balance(self.buyer, 25)

    async def asyncTearDown(self):
        await self.db.close()
        self.tmp.cleanup()

    async def _checkout(self, product_id, message_id=777):
        callback = fake_callback(self.buyer, product_id, message_id)
        state = SimpleNamespace(clear=AsyncMock())
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch.object(user_handlers, "db", self.db):
            await user_handlers.confirm_buy(callback, state, bot)
        return callback, state, bot

    async def test_free_verification_requires_no_contact_and_charges_nothing(self):
        pid = await self.db.add_product("Free promotional order", 0, 0, EntryType.TELEGRAM)
        callback, state, bot = await self._checkout(pid)
        state.clear.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once()
        body = callback.message.edit_text.await_args.args[0]
        self.assertIn("Бесплатно", body)
        self.assertIn("анонимный чат", body)
        self.assertNotIn("Введите номер", body)
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 25)
        orders = await self.db.get_user_orders(self.buyer)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].status, OrderStatus.PENDING)
        self.assertEqual(orders[0].buyer_price, 0)
        self.assertIsNone(orders[0].entry_data)
        self.assertGreater(bot.send_message.await_count, 0)
        self.assertIsNone(await self.db.chat_recipient(orders[0].id, self.buyer))
        await self._checkout(pid)
        self.assertEqual(len(await self.db.get_user_orders(self.buyer)), 1)
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 25)
        await self.db.conn.execute(
            "UPDATE orders SET created_at=? WHERE id=?",
            ((datetime.utcnow() - timedelta(hours=1, minutes=1)).isoformat(), orders[0].id)
        )
        await self.db.conn.commit()
        self.assertEqual(
            await self.db.refund_pending_verification_order(self.buyer, orders[0].id), 0
        )

    async def test_paid_checkout_and_anonymous_chat_after_acceptance(self):
        pid = await self.db.add_product("Paid", 5, 3, EntryType.EMAIL)
        callback, _, _ = await self._checkout(pid)
        self.assertIn("Списано: 5.00 USDT", callback.message.edit_text.await_args.args[0])
        await self._checkout(pid)
        self.assertEqual((await self.db.get_user(self.buyer)).balance, 20)
        orders = await self.db.get_user_orders(self.buyer)
        self.assertEqual(len(orders), 1)
        self.assertIsNone(orders[0].entry_data)
        self.assertTrue(await self.db.take_order(orders[0].id, self.seller))
        self.assertEqual(await self.db.chat_recipient(orders[0].id, self.buyer), self.seller)
        self.assertIsNotNone(await self.db.queue_chat_message(
            orders[0].id, self.buyer, "Hello", "en"
        ))
        self.assertEqual(await self.db.complete_verification_and_pay_seller(
            orders[0].id, self.seller
        ), 3)

    async def test_zero_price_old_offer_has_no_positive_payout(self):
        pid = await self.db.add_product("Old zero-priced offer", 0, 9, EntryType.EMAIL)
        await self._checkout(pid)
        order = (await self.db.get_user_orders(self.buyer))[0]
        self.assertEqual(order.seller_price, 0)
        await self.db.take_order(order.id, self.seller)
        self.assertEqual(
            await self.db.complete_verification_and_pay_seller(order.id, self.seller), 0
        )
        self.assertEqual((await self.db.get_user(self.seller)).balance, 0)

    async def test_old_contact_form_is_disabled(self):
        message = SimpleNamespace(answer=AsyncMock())
        state = SimpleNamespace(clear=AsyncMock())
        await user_handlers.retired_contact_form(message, state)
        state.clear.assert_awaited_once()
        self.assertIn("больше не нужны", message.answer.await_args.args[0])

    async def test_seller_never_displays_legacy_credentials(self):
        pid = await self.db.add_product("Existing order", 3, 1, EntryType.EMAIL)
        oid, error = await self.db.create_paid_verification_order(
            self.buyer, pid, None, "old-order"
        )
        self.assertIsNone(error)
        await self.db.take_order(oid, self.seller)
        await self.db.conn.execute(
            "UPDATE orders SET entry_data=? WHERE id=?",
            ('{"email":"private@example.org","password":"DO_NOT_SEND"}', oid)
        )
        await self.db.conn.commit()
        cb = SimpleNamespace(
            data=f"view_order:{oid}",
            from_user=SimpleNamespace(id=self.seller),
            message=SimpleNamespace(edit_text=AsyncMock()),
            answer=AsyncMock(),
        )
        with patch.object(seller_handlers, "db", self.db):
            await seller_handlers.view_order(cb)
        body = cb.message.edit_text.await_args.args[0]
        self.assertIn("анонимный чат", body)
        self.assertNotIn("private@example.org", body)
        self.assertNotIn("DO_NOT_SEND", body)


if __name__ == "__main__":
    unittest.main()
