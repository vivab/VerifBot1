from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Product


def owner_panel_keyboard(is_owner: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text="👥 Добавить верификацию", callback_data="owner:add_product")
    builder.button(text="🗑 Удалить позицию", callback_data="owner:delete_product")
    builder.button(text="✏️ Изменить позицию", callback_data="owner:edit_product")

    if is_owner:
        builder.button(text="💰 Цены покупателей", callback_data="owner:buyer_prices")
        builder.button(text="💵 Цены продавцов", callback_data="owner:seller_prices")

    builder.button(text="👤 Добавить продавца", callback_data="owner:add_seller")
    if is_owner:
        builder.button(text="🛡 Добавить админа", callback_data="owner:add_admin")

    builder.button(text="📘 Добавить мануал", callback_data="owner:add_manual")
    builder.button(text="📱 Добавить TG-позицию", callback_data="owner:add_tg_offer")
    if is_owner:
        builder.button(text="🗑 Удалить мануал", callback_data="owner:remove_manual")
        builder.button(text="🗑 Удалить TG-аккаунт", callback_data="owner:remove_tg_stock")
        builder.button(text="🗑 Удалить TG-позицию", callback_data="owner:remove_tg_offer")
    builder.button(text="📢 Рассылка", callback_data="owner:broadcast")
    builder.button(text="🔗 Ссылка поддержки", callback_data="owner:support_link")
    builder.button(text="📡 Ссылка канала", callback_data="owner:channel_link")
    builder.button(text="📊 Статистика", callback_data="owner:stats")

    builder.button(text="◀️ Назад", callback_data="back_main")
    builder.adjust(1)
    return builder.as_markup()


def products_list_keyboard(products: list[Product], action: str) -> InlineKeyboardMarkup:
    """action = delete / edit / view"""
    builder = InlineKeyboardBuilder()
    for p in products:
        status = "✅" if p.is_active else "❌"
        builder.button(
            text=f"{status} {p.name} (покуп: {p.buyer_price}$ / прод: {p.seller_price}$)",
            callback_data=f"owner:{action}:{p.id}"
        )
    builder.button(text="◀️ Назад", callback_data="owner:panel")
    builder.adjust(1)
    return builder.as_markup()


def entry_type_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📧 Почта", callback_data="entry:email")
    builder.button(text="📱 Telegram аккаунт", callback_data="entry:telegram")
    builder.button(text="❌ Отмена", callback_data="owner:panel")
    builder.adjust(1)
    return builder.as_markup()


def confirm_keyboard(yes_cb: str, no_cb: str = "owner:panel") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да", callback_data=yes_cb)
    builder.button(text="❌ Нет", callback_data=no_cb)
    builder.adjust(2)
    return builder.as_markup()


def cancel_to_panel() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="owner:panel")
    return builder.as_markup()


def catalog_delete_list_keyboard(rows, kind: str, page: int, more: bool) -> InlineKeyboardMarkup:
    """Show only unsold/active items. Never display Telegram sessions."""
    builder = InlineKeyboardBuilder()
    for row in rows:
        if kind == "manual":
            label = f"📘 #{row['id']} {row['name']} — {row['buyer_price']}$"
        elif kind == "tg_offer":
            label = f"📱 #{row['id']} {row['country']} / {row['age_label']}"
        else:
            digits = row["phone"][-4:]
            label = f"📦 #{row['id']} {row['country']} / {row['age_label']} ••••{digits}"
        builder.button(
            text=label[:62],
            callback_data=f"owner:remove:{kind}:ask:{row['id']}:{page}"
        )
    if page > 0:
        builder.button(text="◀️ Предыдущая", callback_data=f"owner:remove:{kind}:page:{page-1}")
    if more:
        builder.button(text="Следующая ▶️", callback_data=f"owner:remove:{kind}:page:{page+1}")
    builder.button(text="↩️ Панель владельца", callback_data="owner:panel")
    builder.adjust(1)
    return builder.as_markup()


def catalog_delete_confirm_keyboard(kind: str, item_id: int, page: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Да, убрать из продажи",
        callback_data=f"owner:remove:{kind}:yes:{item_id}:{page}"
    )
    builder.button(text="❌ Отмена", callback_data=f"owner:remove:{kind}:page:{page}")
    builder.adjust(1)
    return builder.as_markup()
