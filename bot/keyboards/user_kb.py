from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Product, UserRole
from bot.i18n import tr
from bot.keyboards.pagination import page_slice, add_page_arrows


def main_menu(role: UserRole, lang: str = "ru") -> ReplyKeyboardMarkup:
    def b(key):
        return KeyboardButton(text=tr(lang, key))
    buttons = [
        [b("catalog"), b("profile")],
        [b("topup"), b("support")],
        [b("channel"), b("chats"), b("language")],
    ]
    if role in (UserRole.SELLER, UserRole.ADMIN, UserRole.OWNER):
        buttons.append([b("orders"), b("upload")])
    if role in (UserRole.ADMIN, UserRole.OWNER):
        buttons.append([b("owner" if role == UserRole.OWNER else "admin")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def catalog_keyboard(products: list[Product], page: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    chunk, page, previous, following = page_slice(products, page)
    for p in chunk:
        b.button(text=f"{p.name} — {p.buyer_price}$"[:60], callback_data=f"buy:{p.id}")
    add_page_arrows(b, page, previous, following, "catvpage")
    b.button(text="◀️ Назад", callback_data="catalog")
    b.adjust(1)
    return b.as_markup()


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
    builder.button(text="📦 Мои покупки", callback_data="my_purchases")
    builder.button(text="💬 Мои чаты", callback_data="chat:list")
    builder.button(text="🌐 Language / Язык", callback_data="language:menu")
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


def verification_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить заказ — вернуть средства",
                   callback_data=f"cancel_verification:{order_id}")
    builder.button(text="💬 Чат по заказу", callback_data=f"chat:open:{order_id}")
    builder.button(text="📦 Мои покупки", callback_data="my_purchases")
    builder.adjust(1)
    return builder.as_markup()


def purchase_history_keyboard(pending_orders) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order in pending_orders:
        builder.button(
            text=f"❌ Отменить заказ #{order.id}",
            callback_data=f"cancel_verification:{order.id}"
        )
    builder.button(text="💬 Мои чаты", callback_data="chat:list")
    builder.button(text="◀️ Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()
