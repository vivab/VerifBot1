from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def categories_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👥 Верификации", callback_data="cat:verification")
    b.button(text="📘 Мануалы", callback_data="cat:manual")
    b.button(text="📱 Telegram аккаунты", callback_data="cat:tg")
    b.button(text="◀️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


def manuals_keyboard(manuals) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for m in manuals:
        b.button(text=f"{m['name']} — {m['buyer_price']}$", callback_data=f"manual:{m['id']}")
    b.button(text="◀️ Назад", callback_data="catalog")
    b.adjust(1)
    return b.as_markup()


def confirm_manual_keyboard(manual_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Купить", callback_data=f"buy_manual:{manual_id}")
    b.button(text="◀️ Назад", callback_data="cat:manual")
    b.adjust(1)
    return b.as_markup()


def tg_countries_keyboard(countries: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in countries:
        b.button(text=c, callback_data=f"tg_country:{c}")
    b.button(text="◀️ Назад", callback_data="catalog")
    b.adjust(2)
    return b.as_markup()


def tg_ages_keyboard(country: str, offers) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for o in offers:
        b.button(
            text=f"{o['age_label']} — {o['buyer_price']}$",
            callback_data=f"tg_offer:{o['id']}"
        )
    b.button(text="◀️ Назад", callback_data="cat:tg")
    b.adjust(1)
    return b.as_markup()


def confirm_tg_keyboard(offer_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Купить", callback_data=f"buy_tg:{offer_id}")
    b.button(text="◀️ Назад", callback_data="cat:tg")
    b.adjust(1)
    return b.as_markup()


def tg_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📩 Запросить код", callback_data=f"tg_code:{order_id}")
    b.button(text="Завершить заказ ✅", callback_data=f"tg_done:{order_id}")
    b.adjust(1)
    return b.as_markup()
