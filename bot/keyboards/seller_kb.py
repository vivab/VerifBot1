from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Order


def new_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Принять заказ ✅", callback_data=f"take_order:{order_id}")
    builder.button(text="Отказаться ❌", callback_data=f"reject_order:{order_id}")
    builder.adjust(1)
    return builder.as_markup()


def active_order_keyboard(order_id: int, with_email_code: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if with_email_code:
        builder.button(text="📩 Код из почты", callback_data=f"email_code:{order_id}")
    builder.button(text="Завершить заказ ✅", callback_data=f"complete_order:{order_id}")
    builder.button(text="Отказаться от заказа ❌", callback_data=f"cancel_taken:{order_id}")
    builder.adjust(1)
    return builder.as_markup()


def my_orders_keyboard(orders: list[Order]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for o in orders:
        builder.button(
            text=f"#{o.id} {o.product_name}",
            callback_data=f"view_order:{o.id}"
        )
    builder.button(text="◀️ Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()
