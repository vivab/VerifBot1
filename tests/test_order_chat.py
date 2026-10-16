"""Persistent private order chat and localization tests without Telegram network."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("OWNER_ID", "1234567")
os.environ.setdefault("CRYPTOPAY_TOKEN", "TEST_TOKEN")

from bot.database.db import Database
from bot.database.models import EntryType
from bot.i18n import tr, menu_variants
from bot.services.translation import TranslationResult, translate_chat


class OrderChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tempdir.name) / "shop.db"))
        await self.db.connect()
        self.buyer_id, self.seller_id, self.stranger_id = 99101, 99102, 99103
        for uid in (self.buyer_id, self.seller_id, self.stranger_id):
            await self.db.add_user(uid, None, "Test")
        await self.db.set_balance(self.buyer_id, 20)
        product_id = await self.db.add_product("KYC Test", 5, 3, EntryType.TELEGRAM)
        self.order_id, error = await self.db.create_paid_verification_order(
            self.buyer_id, product_id, {"contact": "@testbuyer"}, "chat-checkout"
        )
        self.assertIsNone(error)

    async def asyncTearDown(self):
        await self.db.close()
        self.tempdir.cleanup()

    async def test_accepted_order_has_two_anonymous_chat_participants(self):
        self.assertIsNone(await self.db.chat_recipient(self.order_id, self.buyer_id))
        self.assertTrue(await self.db.take_order(self.order_id, self.seller_id))
        self.assertEqual(await self.db.chat_recipient(self.order_id, self.buyer_id),
                         self.seller_id)
        self.assertEqual(await self.db.chat_recipient(self.order_id, self.seller_id),
                         self.buyer_id)
        self.assertIsNone(await self.db.chat_recipient(self.order_id, self.stranger_id))
        self.assertEqual(len(await self.db.get_chat_orders(self.buyer_id)), 1)

    async def test_message_survives_chat_exit_and_bot_restart(self):
        await self.db.take_order(self.order_id, self.seller_id)
        self.assertTrue(await self.db.set_language(self.seller_id, "en"))
        message_id = await self.db.queue_chat_message(
            self.order_id, self.buyer_id, "Привет, продавец!", "ru"
        )
        self.assertIsNotNone(message_id)
        # Message is stored even with no active FSM state or live Telegram connection.
        self.assertIn(message_id, await self.db.get_undelivered_chat_ids())
        await self.db.close()
        await self.db.connect()
        self.assertIn(message_id, await self.db.get_undelivered_chat_ids())

        from bot.handlers import chat
        original_db = chat.db
        chat.db = self.db
        bot = AsyncMock()
        try:
            with patch.object(
                chat, "translate_chat",
                new=AsyncMock(return_value=TranslationResult("Hello, seller!", True))
            ):
                self.assertTrue(await chat._deliver_message(bot, message_id))
        finally:
            chat.db = original_db
        bot.send_message.assert_awaited_once()
        args, kwargs = bot.send_message.await_args
        self.assertEqual(args[0], self.seller_id)
        self.assertIn("Hello, seller!", args[1])
        self.assertNotIn("@testbuyer", args[1])
        self.assertIn("chat:open", str(kwargs["reply_markup"]))
        self.assertNotIn(message_id, await self.db.get_undelivered_chat_ids())
        async with self.db.conn.execute(
            "SELECT status, body FROM chat_messages WHERE id = ?", (message_id,)
        ) as cur:
            row = await cur.fetchone()
        self.assertEqual(row["status"], "sent")
        self.assertIsNone(row["body"])  # delivered content is not retained

    async def test_message_waits_for_telegram_outage_and_retries(self):
        await self.db.take_order(self.order_id, self.seller_id)
        # Buyer must initiate before seller is allowed to answer.
        self.assertIsNone(await self.db.queue_chat_message(
            self.order_id, self.seller_id, "Not first", "en"
        ))
        self.assertIsNotNone(await self.db.queue_chat_message(
            self.order_id, self.buyer_id, "Help", "ru"
        ))
        message_id = await self.db.queue_chat_message(
            self.order_id, self.seller_id, "Hello!", "en"
        )
        from bot.handlers import chat
        original_db = chat.db
        chat.db = self.db
        try:
            bot = AsyncMock()
            bot.send_message.side_effect = RuntimeError("Temporary network outage")
            self.assertFalse(await chat._deliver_message(bot, message_id))
            self.assertIn(message_id, await self.db.get_undelivered_chat_ids())
            bot.send_message.side_effect = None
            self.assertTrue(await chat._deliver_message(bot, message_id))
            self.assertNotIn(message_id, await self.db.get_undelivered_chat_ids())
        finally:
            chat.db = original_db

    async def test_nonparticipant_cannot_queue_message(self):
        await self.db.take_order(self.order_id, self.seller_id)
        self.assertIsNone(await self.db.queue_chat_message(
            self.order_id, self.stranger_id, "Unauthorized", "ru"
        ))

    async def test_chat_available_after_order_completed(self):
        await self.db.take_order(self.order_id, self.seller_id)
        await self.db.complete_verification_and_pay_seller(self.order_id, self.seller_id)
        self.assertEqual(await self.db.chat_recipient(self.order_id, self.buyer_id),
                         self.seller_id)


    async def test_seller_may_only_reply_to_buyer_in_old_completed_orders(self):
        await self.db.take_order(self.order_id, self.seller_id)
        await self.db.complete_verification_and_pay_seller(self.order_id, self.seller_id)
        self.assertIsNone(await self.db.queue_chat_message(
            self.order_id, self.seller_id, "First", "ru"
        ))
        self.assertIsNotNone(await self.db.queue_chat_message(
            self.order_id, self.buyer_id, "Need followup", "en"
        ))
        self.assertIsNotNone(await self.db.queue_chat_message(
            self.order_id, self.seller_id, "Answer", "ru"
        ))

    async def test_localized_menu_labels(self):
        self.assertEqual(tr("en", "language_saved"), "✅ Language updated.")
        self.assertIn("🛍️ Katalog", menu_variants("catalog"))
        self.assertIn("🛍️ Catalog", menu_variants("catalog"))
        self.assertEqual(await self.db.get_language(self.buyer_id), "ru")
        await self.db.set_language(self.buyer_id, "de")
        self.assertEqual(await self.db.get_language(self.buyer_id), "de")

    async def test_translation_is_truthful_when_not_configured(self):
        with patch("bot.services.translation.settings") as settings:
            settings.TRANSLATION_URL = ""
            settings.TRANSLATION_API_KEY = ""
            result = await translate_chat("Hello", "en", "ru")
        self.assertFalse(result.translated)
        self.assertEqual(result.text, "Hello")
        self.assertEqual(result.reason, "not_configured")


if __name__ == "__main__":
    unittest.main()
