from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.i18n import LANGUAGE_NAMES, tr


def languages_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, name in LANGUAGE_NAMES.items():
        builder.button(text=name, callback_data=f"language:set:{code}")
    builder.adjust(2)
    return builder.as_markup()


def chat_orders_keyboard(orders, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in orders:
        builder.button(
            text=f"💬 #{order['id']} {order['product_name']}"[:60],
            callback_data=f"chat:open:{order['id']}"
        )
    builder.adjust(1)
    return builder.as_markup()


def chat_open_keyboard(order_id: int, lang: str):
    builder = InlineKeyboardBuilder()
    builder.button(text=tr(lang, "chat_read"), callback_data=f"chat:open:{order_id}")
    builder.adjust(1)
    return builder.as_markup()
