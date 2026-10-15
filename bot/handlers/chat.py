"""Private order chat, durable delivery queue, and language selection.

Participant Telegram identifiers are never included in forwarded chat messages.
"""
import asyncio
import logging
from html import escape
from aiogram import Bot, Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.database.db import db
from bot.i18n import LANGUAGE_NAMES, menu_variants, tr
from bot.keyboards.chat_kb import (
    languages_keyboard, chat_orders_keyboard, chat_open_keyboard
)
from bot.states.states import ChatStates
from bot.services.translation import translate_chat

logger = logging.getLogger(__name__)
router = Router()


async def _deliver_message(bot: Bot, message_id: int) -> bool:
    row = await db.claim_chat_message(message_id)
    if not row:
        return False
    try:
        recipient = await db.chat_recipient(row["order_id"], row["sender_id"])
        # Recheck the buyer-seller pair in case an order has been cancelled or reassigned.
        if recipient != row["receiver_id"]:
            await db.set_chat_delivery(message_id, True)
            return False

        language = await db.get_language(recipient)
        source_lang = row["sender_language"]
        result = await translate_chat(row["body"], source_lang, language)
        order = await db.get_order(row["order_id"])
        role = "buyer" if row["sender_id"] == order.buyer_id else "seller"
        prefix = tr(language, "chat_received", order_id=row["order_id"],
                    role=tr(language, role))
        footer = ""
        if source_lang != language:
            if result.translated:
                footer = "\n\n" + tr(language, "translated")
            elif result.reason == "not_configured":
                footer = "\n\n" + tr(language, "chat_translate_off")
            else:
                footer = "\n\n" + tr(language, "chat_translate_fail")
        msg = prefix + "\n\n" + escape(result.text) + footer
        await bot.send_message(
            recipient, msg,
            reply_markup=chat_open_keyboard(row["order_id"], language),
            parse_mode="HTML",
        )
        await db.set_chat_delivery(message_id, True)
        return True
    except Exception as exc:
        logger.warning("Chat delivery failed for message #%d (%s)", message_id,
                       type(exc).__name__)
        await db.set_chat_delivery(message_id, False)
        return False


async def deliver_chat_backlog(bot: Bot):
    ids = await db.get_undelivered_chat_ids(limit=30)
    for message_id in ids:
        await _deliver_message(bot, message_id)


async def chat_delivery_worker(bot: Bot):
    """Retries pending messages even when both users have closed the chat."""
    while True:
        try:
            await deliver_chat_backlog(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Chat delivery background worker failed")
        await asyncio.sleep(20)


@router.message(Command("language"))
@router.message(F.text.in_(menu_variants("language")))
async def choose_language(message: Message):
    lang = await db.get_language(message.from_user.id)
    await message.answer(tr(lang, "language_choose"),
                         reply_markup=languages_keyboard())


@router.callback_query(F.data == "language:menu")
async def choose_language_callback(callback: CallbackQuery):
    lang = await db.get_language(callback.from_user.id)
    await callback.message.answer(tr(lang, "language_choose"),
                                  reply_markup=languages_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("language:set:"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split(":")[-1]
    if lang not in LANGUAGE_NAMES:
        await callback.answer("Unsupported language", show_alert=True)
        return
    if not await db.set_language(callback.from_user.id, lang):
        await callback.answer("Use /start first", show_alert=True)
        return
    from bot.keyboards.user_kb import main_menu
    user = await db.get_user(callback.from_user.id)
    await callback.message.answer(
        tr(lang, "language_saved"),
        reply_markup=main_menu(user.role, lang),
    )
    await callback.answer()


@router.message(Command("chats"))
@router.message(F.text.in_(menu_variants("chats")))
async def chat_list(message: Message, state: FSMContext):
    await state.clear()
    lang = await db.get_language(message.from_user.id)
    orders = await db.get_chat_orders(message.from_user.id)
    if not orders:
        await message.answer(tr(lang, "chat_empty"))
        return
    await message.answer(tr(lang, "chat_list"),
                         reply_markup=chat_orders_keyboard(orders, lang))


@router.callback_query(F.data == "chat:list")
async def chat_list_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await db.get_language(callback.from_user.id)
    orders = await db.get_chat_orders(callback.from_user.id)
    if not orders:
        await callback.message.answer(tr(lang, "chat_empty"))
    else:
        await callback.message.answer(tr(lang, "chat_list"),
                                      reply_markup=chat_orders_keyboard(orders, lang))
    await callback.answer()


@router.callback_query(F.data.startswith("chat:open:"))
async def chat_open(callback: CallbackQuery, state: FSMContext):
    try:
        order_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Invalid order", show_alert=True)
        return
    lang = await db.get_language(callback.from_user.id)
    recipient = await db.chat_recipient(order_id, callback.from_user.id)
    if recipient is None:
        await callback.answer(tr(lang, "chat_not_allowed"), show_alert=True)
        return
    await state.set_state(ChatStates.writing)
    await state.update_data(chat_order_id=order_id)
    await callback.message.answer(
        tr(lang, "chat_open", order_id=order_id) + "\n\n" +
        tr(lang, "chat_privacy"),
    )
    await callback.answer()


@router.message(Command("stopchat"))
async def close_chat(message: Message, state: FSMContext):
    await state.clear()
    lang = await db.get_language(message.from_user.id)
    await message.answer(tr(lang, "chat_exit"))


@router.message(ChatStates.writing)
async def chat_send(message: Message, state: FSMContext, bot: Bot):
    lang = await db.get_language(message.from_user.id)
    body = (message.text or "").strip()
    if not body or len(body) > 1500 or body.startswith("/"):
        await message.answer(tr(lang, "chat_not_text"))
        return

    data = await state.get_data()
    order_id = data.get("chat_order_id")
    if not order_id:
        await message.answer(tr(lang, "chat_prompt"))
        await state.clear()
        return
    message_id = await db.queue_chat_message(
        order_id, message.from_user.id, body, lang
    )
    if not message_id:
        await state.clear()
        await message.answer(tr(lang, "chat_not_allowed"))
        return
    delivered = await _deliver_message(bot, message_id)
    await message.answer(tr(lang, "chat_sent" if delivered else "chat_queued"))
