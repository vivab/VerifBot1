from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Order
from bot.keyboards.pagination import page_slice, add_page_arrows


def new_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Принять заказ ✅", callback_data=f"take_order:{order_id}")
    builder.button(text="Отказаться ❌", callback_data=f"reject_order:{order_id}")
    builder.adjust(1)
    return builder.as_markup()


def active_order_keyboard(order_id: int, with_email_code: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💬 Чат с покупателем", callback_data=f"chat:open:{order_id}")
    builder.button(text="Завершить заказ ✅", callback_data=f"complete_order:{order_id}")
    builder.button(text="Отказаться от заказа ❌", callback_data=f"cancel_taken:{order_id}")
    builder.adjust(1)
    return builder.as_markup()


def my_orders_keyboard(orders: list[Order], page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    chunk, page, previous, following = page_slice(orders, page)
    for o in chunk:
        builder.button(text=f"#{o.id} {o.product_name}"[:60], callback_data=f"view_order:{o.id}")
        builder.button(text=f"💬 Чат #{o.id}", callback_data=f"chat:open:{o.id}")
    add_page_arrows(builder, page, previous, following, "sellerorders")
    builder.button(text="💬 Старые верификации", callback_data="chat:list")
    builder.button(text="◀️ Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()
