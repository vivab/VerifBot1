from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.i18n import LANGUAGE_NAMES, tr
from bot.keyboards.pagination import page_slice, add_page_arrows


def languages_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, name in LANGUAGE_NAMES.items():
        builder.button(text=name, callback_data=f"language:set:{code}")
    builder.adjust(2)
    return builder.as_markup()


def chat_orders_keyboard(orders, lang: str, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    chunk, page, previous, following = page_slice(orders, page)
    for order in chunk:
        builder.button(text=f"💬 #{order['id']} {order['product_name']}"[:60],
                       callback_data=f"chat:open:{order['id']}")
    add_page_arrows(builder, page, previous, following, "chat:list")
    builder.adjust(1)
    return builder.as_markup()


def chat_open_keyboard(order_id: int, lang: str):
    builder = InlineKeyboardBuilder()
    builder.button(text=tr(lang, "chat_read"), callback_data=f"chat:open:{order_id}")
    builder.adjust(1)
    return builder.as_markup()
