from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Product, UserRole


def main_menu(role: UserRole) -> ReplyKeyboardMarkup:
    """Главное меню в зависимости от роли."""
    buttons = [
        [KeyboardButton(text="🛍️ Каталог"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="🤑 Пополнить"), KeyboardButton(text="🎗️ Поддержка")],
        [KeyboardButton(text="🛜 Наш канал")],
    ]

    if role in (UserRole.SELLER, UserRole.ADMIN, UserRole.OWNER):
        buttons.append([KeyboardButton(text="📋 Мои заказы"), KeyboardButton(text="📦 Загрузить акк")])

    if role in (UserRole.ADMIN, UserRole.OWNER):
        panel_text = "👑 Панель владельца" if role == UserRole.OWNER else "🛠 Админ-панель"
        buttons.append([KeyboardButton(text=panel_text)])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def catalog_keyboard(products: list[Product]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in products:
        builder.button(
            text=f"{p.name} — {p.buyer_price}$",
            callback_data=f"buy:{p.id}"
        )
    builder.button(text="◀️ Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def back_keyboard(callback: str = "back_main") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data=callback)
    return builder.as_markup()


def confirm_buy_keyboard(product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Купить", callback_data=f"confirm_buy:{product_id}")
    builder.button(text="◀️ Назад", callback_data="catalog")
    builder.adjust(1)
    return builder.as_markup()


def profile_keyboard(has_balance: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💸 Вывод", callback_data="withdraw")
    builder.button(text="◀️ Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def topup_amounts_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for amount in [5, 10, 20, 50, 100]:
        builder.button(text=f"{amount}$", callback_data=f"topup:{amount}")
    builder.button(text="Другая сумма", callback_data="topup:custom")
    builder.button(text="◀️ Назад", callback_data="back_main")
    builder.adjust(3, 2, 1)
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel")
    return builder.as_markup()


def invoice_keyboard(invoice_id: int) -> InlineKeyboardMarkup:
    """Кнопка проверки оплаты после создания счёта."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Я оплатил — проверить", callback_data=f"check_pay:{invoice_id}")
    builder.button(text="◀️ Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()
