from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.keyboards.pagination import PAGE_SIZE, page_slice, add_page_arrows


def categories_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👥 Верификации", callback_data="cat:verification")
    b.button(text="📘 Мануалы", callback_data="cat:manual")
    b.button(text="📱 Telegram аккаунты", callback_data="cat:tg")
    b.button(text="◀️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


def manuals_keyboard(manuals, page: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    chunk, page, previous, following = page_slice(manuals, page)
    for m in chunk:
        b.button(text=f"{m['name']} — {m['buyer_price']}$"[:60],
                 callback_data=f"manual:{m['id']}")
    add_page_arrows(b, page, previous, following, "catmpage")
    b.button(text=f"Страница {page + 1}", callback_data="cat:manual")
    b.button(text="◀️ Назад", callback_data="catalog")
    b.adjust(1)
    return b.as_markup()


def confirm_manual_keyboard(manual_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Купить", callback_data=f"buy_manual:{manual_id}")
    b.button(text="◀️ Назад", callback_data="cat:manual")
    b.adjust(1)
    return b.as_markup()


def tg_countries_keyboard(countries: list, page: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    chunk, page, previous, following = page_slice(countries, page)
    for i, name in enumerate(chunk, start=page * PAGE_SIZE):
        b.button(text=name[:58], callback_data=f"tg_cidx:{i}")
    add_page_arrows(b, page, previous, following, "catcpage")
    b.button(text="◀️ Назад", callback_data="catalog")
    b.adjust(1)
    return b.as_markup()


def tg_ages_keyboard(country_index: int, offers, page: int = 0) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    chunk, page, previous, following = page_slice(offers, page)
    for o in chunk:
        b.button(text=f"{o['age_label']} — {o['buyer_price']}$",
                 callback_data=f"tg_offer:{o['id']}")
    add_page_arrows(b, page, previous, following, f"catopage:{country_index}")
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
