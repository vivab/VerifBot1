from aiogram import Router, F, Bot
from html import escape
from math import isfinite
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.database.db import db
from bot.database.models import UserRole, EntryType
from bot.keyboards.owner_kb import (
    owner_panel_keyboard, products_list_keyboard, entry_type_keyboard,
    cancel_to_panel, confirm_keyboard, catalog_delete_list_keyboard,
    catalog_delete_confirm_keyboard
)
from bot.keyboards.user_kb import main_menu
from bot.states.states import (
    OwnerAddProduct, OwnerEditProduct, OwnerAddSeller, OwnerAddAdmin,
    OwnerBroadcast, OwnerSetLink, OwnerAddManual, OwnerAddTgOffer, OwnerSticker
)
from bot.config import settings
from bot.i18n import menu_variants

router = Router()


def is_owner_or_admin(user) -> bool:
    return user and user.role in (UserRole.ADMIN, UserRole.OWNER)


def is_owner(user) -> bool:
    return user and user.role == UserRole.OWNER




# ──────────────────── УДАЛЕНИЕ МАНУАЛОВ / TG-АККАУНТОВ / TG-ПОЗИЦИЙ ────────────────────

_DELETE_PAGE_SIZE = 5
_DELETE_KINDS = {
    "manual": "📘 Мануалы",
    "tg_stock": "📦 Непроданные Telegram-аккаунты",
    "tg_offer": "📱 Telegram-позиции",
}


async def _show_delete_catalog(callback: CallbackQuery, kind: str, page: int):
    offset = page * _DELETE_PAGE_SIZE
    if kind == "manual":
        rows = await db.list_active_manuals(_DELETE_PAGE_SIZE + 1, offset)
    elif kind == "tg_stock":
        rows = await db.list_unsold_tg_stock(_DELETE_PAGE_SIZE + 1, offset)
    else:
        rows = await db.list_active_tg_offers(_DELETE_PAGE_SIZE + 1, offset)
    await callback.message.edit_text(
        f"🗑 <b>{_DELETE_KINDS[kind]}</b>\n\n"
        + ("Выберите, что убрать из продажи:" if rows else "Здесь пока нет доступных позиций."),
        reply_markup=catalog_delete_list_keyboard(
            rows[:_DELETE_PAGE_SIZE], kind, page, len(rows) > _DELETE_PAGE_SIZE
        ),
    )


@router.callback_query(F.data.in_({
    "owner:remove_manual", "owner:remove_tg_stock", "owner:remove_tg_offer"
}))
async def owner_remove_start(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not is_owner(user):
        await callback.answer("Удаление доступно только владельцу.", show_alert=True)
        return
    kind = callback.data.removeprefix("owner:remove_")
    await _show_delete_catalog(callback, kind, 0)
    await callback.answer()


@router.callback_query(F.data.startswith("owner:remove:"))
async def owner_remove_action(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not is_owner(user):
        await callback.answer("Удаление доступно только владельцу.", show_alert=True)
        return

    parts = callback.data.split(":")
    try:
        if len(parts) not in (5, 6):
            raise ValueError
        _, _, kind, action, *args = parts
        if kind not in _DELETE_KINDS or action not in ("page", "ask", "yes"):
            raise ValueError
        if action == "page":
            if len(args) != 1:
                raise ValueError
            page = int(args[0])
            item_id = None
        else:
            if len(args) != 2:
                raise ValueError
            item_id, page = int(args[0]), int(args[1])
            if item_id <= 0:
                raise ValueError
        if not 0 <= page <= 10000:
            raise ValueError
    except (ValueError, TypeError):
        await callback.answer("Неверный запрос.", show_alert=True)
        return

    if action == "page":
        await _show_delete_catalog(callback, kind, page)
        await callback.answer()
        return

    if action == "ask":
        if kind == "manual":
            row = await db.get_manual(item_id)
            valid = bool(row and row["is_active"])
            item_name = f"Мануал «{escape(row['name'])}»" if valid else ""
        elif kind == "tg_stock":
            row = await db.get_unsold_tg_stock(item_id)
            valid = bool(row)
            item_name = (
                f"Аккаунт #{item_id}: {escape(row['country'])} / "
                f"{escape(row['age_label'])}, номер ••••{escape(row['phone'][-4:])}"
            ) if valid else ""
        else:
            row = await db.get_tg_offer(item_id)
            valid = bool(row and row["is_active"])
            item_name = (
                f"TG-позиция #{item_id}: {escape(row['country'])} / "
                f"{escape(row['age_label'])}"
            ) if valid else ""
        if not valid:
            await callback.answer("Уже удалено или недоступно.", show_alert=True)
            return
        await callback.message.edit_text(
            f"❗ <b>Подтвердите удаление из каталога</b>\n\n"
            f"{item_name}\n\n"
            "Проданные аккаунты не затрагиваются, а мануалы у прежних покупателей останутся.",
            reply_markup=catalog_delete_confirm_keyboard(kind, item_id, page),
        )
        await callback.answer()
        return

    if kind == "manual":
        removed = await db.delete_manual(item_id)
    elif kind == "tg_stock":
        removed = await db.remove_unsold_tg_stock(item_id)
    else:
        removed = await db.delete_tg_offer(item_id)
    await _show_delete_catalog(callback, kind, page)
    await callback.answer(
        "✅ Убрано из продажи." if removed else "Позиция уже удалена или была продана.",
        show_alert=True,
    )


# ──────────────────── ПАНЕЛЬ ────────────────────

@router.message(F.text.in_(menu_variants("owner") | menu_variants("admin")))
async def open_panel(message: Message):
    user = await db.get_user(message.from_user.id)
    if not is_owner_or_admin(user):
        await message.answer("Нет доступа.")
        return

    title = "👑 <b>Панель владельца</b>" if is_owner(user) else "🛠 <b>Админ-панель</b>"
    await message.answer(title, reply_markup=owner_panel_keyboard(is_owner=is_owner(user)), parse_mode="HTML")


@router.callback_query(F.data == "owner:panel")
async def panel_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db.get_user(callback.from_user.id)
    if not is_owner_or_admin(user):
        await callback.answer("Нет доступа", show_alert=True)
        return

    title = "👑 <b>Панель владельца</b>" if is_owner(user) else "🛠 <b>Админ-панель</b>"
    await callback.message.edit_text(title, reply_markup=owner_panel_keyboard(is_owner=is_owner(user)), parse_mode="HTML")
    await callback.answer()


# ──────────────────── ДОБАВИТЬ ПОЗИЦИЮ ────────────────────

@router.callback_query(F.data == "owner:add_product")
async def add_product_start(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    if not is_owner_or_admin(user):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(OwnerAddProduct.name)
    await callback.message.edit_text(
        "➕ <b>Добавление позиции</b>\n\nВведите название (например: Bybit):",
        reply_markup=cancel_to_panel(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(OwnerAddProduct.name)
async def add_product_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(OwnerAddProduct.buyer_price)
    await message.answer("Введите цену для <b>покупателя</b> ($):", parse_mode="HTML")


@router.message(OwnerAddProduct.buyer_price)
async def add_product_buyer_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", ".").strip())
    except ValueError:
        await message.answer("Введите число, например: 15")
        return
    await state.update_data(buyer_price=price)
    await state.set_state(OwnerAddProduct.seller_price)
    await message.answer("Введите цену для <b>продавца</b> ($):", parse_mode="HTML")


@router.message(OwnerAddProduct.seller_price)
async def add_product_seller_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", ".").strip())
    except ValueError:
        await message.answer("Введите число, например: 8")
        return
    await state.update_data(seller_price=price)
    await state.set_state(OwnerAddProduct.entry_type)
    await message.answer("Выберите способ входа:", reply_markup=entry_type_keyboard())


@router.callback_query(F.data.startswith("entry:"), OwnerAddProduct.entry_type)
async def add_product_entry(callback: CallbackQuery, state: FSMContext):
    entry = callback.data.split(":")[1]
    entry_type = EntryType.EMAIL if entry == "email" else EntryType.TELEGRAM
    data = await state.get_data()

    product_id = await db.add_product(
        name=data["name"],
        buyer_price=data["buyer_price"],
        seller_price=data["seller_price"],
        entry_type=entry_type
    )

    await state.update_data(sticker_kind="verification", sticker_id=product_id)
    await state.set_state(OwnerSticker.waiting)
    await callback.message.edit_text(
        f"✅ Позиция добавлена!\n\n"
        f"ID: {product_id}\n"
        f"Название: {data['name']}\n"
        f"Покупатель: {data['buyer_price']}$\n"
        f"Продавец: {data['seller_price']}$\n"
        f"Вход: {'Почта' if entry_type == EntryType.EMAIL else 'Telegram'}\n\n"
        "🎨 Теперь отправьте стикер для позиции (обычный, анимированный или Premium). "
        "Вводить ID не нужно. Для пропуска отправьте /skip.",
        reply_markup=cancel_to_panel()
    )
    await callback.answer()



@router.message(OwnerSticker.waiting)
async def save_catalog_sticker(message: Message, state: FSMContext):
    user = await db.get_user(message.from_user.id)
    if not is_owner_or_admin(user):
        await state.clear()
        return
    data = await state.get_data()
    kind, item_id = data.get("sticker_kind"), data.get("sticker_id")
    if not kind or not item_id:
        await state.clear()
        await message.answer("Не удалось определить позицию.")
        return
    if message.text and message.text.strip().lower() in ("/skip", "пропустить", "skip"):
        await state.clear()
        await message.answer("✅ Товар сохранён без стикера.",
                             reply_markup=owner_panel_keyboard(is_owner=is_owner(user)))
        return
    if not message.sticker:
        await message.answer("Пришлите Telegram-стикер (не файл и не ID) или /skip.")
        return
    result = await db.set_item_sticker(kind, item_id, message.sticker.file_id)
    await state.clear()
    await message.answer(
        "✅ Стикер сохранён!" if result else "⚠️ Стикер не сохранился.",
        reply_markup=owner_panel_keyboard(is_owner=is_owner(user))
    )


@router.callback_query(F.data.startswith("owner:delete_page:"))
@router.callback_query(F.data.startswith("owner:edit_page:"))
async def product_page(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not is_owner_or_admin(user):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, action, number = callback.data.split(":")
    action = action.removesuffix("_page")
    page = max(0, min(10000, int(number)))
    products = await db.get_all_products(only_active=(action == "edit"))
    await callback.message.edit_text(
        f"📋 Страница {page + 1}",
        reply_markup=products_list_keyboard(products, action, page)
    )
    await callback.answer()

# ──────────────────── УДАЛИТЬ / ИЗМЕНИТЬ ────────────────────

@router.callback_query(F.data == "owner:delete_product")
async def delete_product_list(callback: CallbackQuery):
    products = await db.get_all_products(only_active=False)
    if not products:
        await callback.answer("Нет позиций", show_alert=True)
        return
    await callback.message.edit_text(
        "🗑 Выберите позицию для удаления (деактивации):",
        reply_markup=products_list_keyboard(products, "delete")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("owner:delete:"))
async def delete_product_confirm(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[2])
    await db.delete_product(product_id)
    await callback.answer("Позиция деактивирована", show_alert=True)
    products = await db.get_all_products(only_active=False)
    await callback.message.edit_text(
        "🗑 Выберите позицию для удаления:",
        reply_markup=products_list_keyboard(products, "delete")
    )


@router.callback_query(F.data == "owner:edit_product")
async def edit_product_list(callback: CallbackQuery):
    products = await db.get_all_products(only_active=False)
    if not products:
        await callback.answer("Нет позиций", show_alert=True)
        return
    await callback.message.edit_text(
        "✏️ Выберите позицию для изменения:",
        reply_markup=products_list_keyboard(products, "edit")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("owner:edit:"))
async def edit_product_choose(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[2])
    product = await db.get_product(product_id)
    if not product:
        await callback.answer("Не найдено", show_alert=True)
        return

    await state.set_state(OwnerEditProduct.choose_field)
    await state.update_data(product_id=product_id)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="Название", callback_data="editfield:name")
    builder.button(text="Цена покупателя", callback_data="editfield:buyer_price")
    builder.button(text="Цена продавца", callback_data="editfield:seller_price")
    builder.button(text="Способ входа", callback_data="editfield:entry_type")
    builder.button(text="◀️ Назад", callback_data="owner:edit_product")
    builder.adjust(1)

    await callback.message.edit_text(
        f"✏️ Редактирование: <b>{product.name}</b>\nВыберите поле:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editfield:"), OwnerEditProduct.choose_field)
async def edit_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[1]
    await state.update_data(field=field)
    await state.set_state(OwnerEditProduct.new_value)

    if field == "entry_type":
        await callback.message.edit_text("Выберите новый способ входа:", reply_markup=entry_type_keyboard())
    else:
        labels = {
            "name": "новое название",
            "buyer_price": "новую цену для покупателя",
            "seller_price": "новую цену для продавца",
        }
        await callback.message.edit_text(f"Введите {labels.get(field, 'значение')}:", reply_markup=cancel_to_panel())
    await callback.answer()


@router.message(OwnerEditProduct.new_value)
async def edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data["field"]
    product_id = data["product_id"]

    if field in ("buyer_price", "seller_price"):
        try:
            value = float(message.text.replace(",", ".").strip())
        except ValueError:
            await message.answer("Введите число")
            return
        kwargs = {field: value}
    else:
        kwargs = {field: message.text.strip()}

    await db.update_product(product_id, **kwargs)
    await state.clear()
    user = await db.get_user(message.from_user.id)
    await message.answer("✅ Обновлено!", reply_markup=owner_panel_keyboard(is_owner=is_owner(user)))


@router.callback_query(F.data.startswith("entry:"), OwnerEditProduct.new_value)
async def edit_entry_type(callback: CallbackQuery, state: FSMContext):
    entry = callback.data.split(":")[1]
    entry_type = EntryType.EMAIL if entry == "email" else EntryType.TELEGRAM
    data = await state.get_data()
    await db.update_product(data["product_id"], entry_type=entry_type)
    await state.clear()
    user = await db.get_user(callback.from_user.id)
    await callback.message.edit_text("✅ Способ входа обновлён!", reply_markup=owner_panel_keyboard(is_owner=is_owner(user)))
    await callback.answer()


# ──────────────────── ДОБАВИТЬ ПРОДАВЦА / АДМИНА ────────────────────

@router.callback_query(F.data == "owner:add_seller")
async def add_seller_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(OwnerAddSeller.waiting_id)
    await callback.message.edit_text(
        "Введите Telegram ID пользователя, которого сделать продавцом:",
        reply_markup=cancel_to_panel()
    )
    await callback.answer()


@router.message(OwnerAddSeller.waiting_id)
async def add_seller_id(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("Введите числовой ID")
        return

    user = await db.get_user(uid)
    if not user:
        # Создаём пользователя
        await db.add_user(uid, None, f"User {uid}", UserRole.SELLER)
    else:
        await db.update_user_role(uid, UserRole.SELLER)

    await state.clear()
    me = await db.get_user(message.from_user.id)
    await message.answer(f"✅ Пользователь {uid} теперь продавец.", reply_markup=owner_panel_keyboard(is_owner=is_owner(me)))


@router.callback_query(F.data == "owner:add_admin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    if not is_owner(user):
        await callback.answer("Только владелец может добавлять админов", show_alert=True)
        return

    await state.set_state(OwnerAddAdmin.waiting_id)
    await callback.message.edit_text(
        "Введите Telegram ID пользователя, которого сделать админом:",
        reply_markup=cancel_to_panel()
    )
    await callback.answer()


@router.message(OwnerAddAdmin.waiting_id)
async def add_admin_id(message: Message, state: FSMContext):
    user = await db.get_user(message.from_user.id)
    if not is_owner(user):
        await message.answer("Нет доступа")
        return

    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("Введите числовой ID")
        return

    existing = await db.get_user(uid)
    if not existing:
        await db.add_user(uid, None, f"User {uid}", UserRole.ADMIN)
    else:
        await db.update_user_role(uid, UserRole.ADMIN)

    await state.clear()
    await message.answer(f"✅ Пользователь {uid} теперь админ.", reply_markup=owner_panel_keyboard(is_owner=True))


# ──────────────────── РАССЫЛКА ────────────────────

@router.callback_query(F.data == "owner:broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(OwnerBroadcast.waiting_message)
    await callback.message.edit_text(
        "📢 Отправьте сообщение для рассылки всем пользователям:",
        reply_markup=cancel_to_panel()
    )
    await callback.answer()


@router.message(OwnerBroadcast.waiting_message)
async def broadcast_send(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    # Получаем всех пользователей
    async with db.conn.execute("SELECT user_id FROM users") as cursor:
        rows = await cursor.fetchall()

    success = 0
    fail = 0
    for row in rows:
        try:
            await bot.copy_message(row["user_id"], message.chat.id, message.message_id)
            success += 1
        except Exception:
            fail += 1

    me = await db.get_user(message.from_user.id)
    await message.answer(
        f"📢 Рассылка завершена.\n✅ Доставлено: {success}\n❌ Ошибок: {fail}",
        reply_markup=owner_panel_keyboard(is_owner=is_owner(me))
    )


# ──────────────────── ССЫЛКИ ────────────────────

@router.callback_query(F.data == "owner:support_link")
async def support_link_start(callback: CallbackQuery, state: FSMContext):
    current = await db.get_setting("support_username") or settings.SUPPORT_USERNAME
    await state.set_state(OwnerSetLink.waiting_value)
    await state.update_data(link_key="support_username")
    await callback.message.edit_text(
        f"Текущая ссылка поддержки: {current}\n\nВведите новую (например @username):",
        reply_markup=cancel_to_panel()
    )
    await callback.answer()


@router.callback_query(F.data == "owner:channel_link")
async def channel_link_start(callback: CallbackQuery, state: FSMContext):
    current = await db.get_setting("channel_url") or settings.CHANNEL_URL
    await state.set_state(OwnerSetLink.waiting_value)
    await state.update_data(link_key="channel_url")
    await callback.message.edit_text(
        f"Текущая ссылка канала: {current}\n\nВведите новую URL:",
        reply_markup=cancel_to_panel()
    )
    await callback.answer()


@router.message(OwnerSetLink.waiting_value)
async def set_link(message: Message, state: FSMContext):
    data = await state.get_data()
    key = data["link_key"]
    await db.set_setting(key, message.text.strip())
    await state.clear()
    me = await db.get_user(message.from_user.id)
    await message.answer("✅ Сохранено!", reply_markup=owner_panel_keyboard(is_owner=is_owner(me)))


# ──────────────────── СТАТИСТИКА ────────────────────

@router.callback_query(F.data == "owner:stats")
async def stats(callback: CallbackQuery):
    total_users = await db.count_users()
    sellers = await db.count_by_role(UserRole.SELLER)
    admins = await db.count_by_role(UserRole.ADMIN)
    completed = await db.count_completed_orders()
    turnover = await db.get_total_turnover()
    earnings = await db.get_total_earnings()

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"🛒 Продавцов: {sellers}\n"
        f"🛡 Админов: {admins}\n"
        f"✅ Выполнено верификаций: {completed}\n"
        f"💰 Оборот: {turnover:.2f}$\n"
        f"💵 Заработок (прибыль): {earnings:.2f}$"
    )
    await callback.message.edit_text(text, reply_markup=owner_panel_keyboard(
        is_owner=is_owner(await db.get_user(callback.from_user.id))
    ), parse_mode="HTML")
    await callback.answer()


# Заглушки для кнопок цен (можно расширить позже)
@router.callback_query(F.data.in_({"owner:buyer_prices", "owner:seller_prices"}))
async def prices_stub(callback: CallbackQuery):
    await callback.answer("Цены меняются при редактировании позиций", show_alert=True)


# ──────────────────── МАНУАЛЫ / TG OFFERS (расширение) ────────────────────

# ──────────────────── МАНУАЛЫ (владелец / админ) ────────────────────

@router.callback_query(F.data == "owner:add_manual")
async def add_manual_start(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    if not is_owner_or_admin(user):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(OwnerAddManual.name)
    await callback.message.edit_text(
        "📘 <b>Новый мануал</b>\n\nВведите название:",
        reply_markup=cancel_to_panel()
    )
    await callback.answer()


@router.message(OwnerAddManual.name)
async def add_manual_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not 2 <= len(name) <= 120:
        await message.answer("Название должно содержать от 2 до 120 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(OwnerAddManual.price)
    await message.answer("Укажите цену для покупателя в $ (например: 5):")


@router.message(OwnerAddManual.price)
async def add_manual_price(message: Message, state: FSMContext):
    try:
        price = float((message.text or "").replace(",", ".").strip())
        if not isfinite(price) or price < 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректную цену, например: 5 или 2.50")
        return
    await state.update_data(price=price)
    await state.set_state(OwnerAddManual.content)
    await message.answer(
        "📄 Отправьте <b>.txt-файл</b> с мануалом или напишите текст одним сообщением.\n"
        "Если отправите текст, покупатель тоже получит его в виде файла .txt.",
        reply_markup=cancel_to_panel()
    )


@router.message(OwnerAddManual.content)
async def add_manual_content(message: Message, state: FSMContext):
    data = await state.get_data()
    file_id = None
    content_text = None
    if message.document:
        document = message.document
        if not (document.file_name or "").lower().endswith(".txt"):
            await message.answer("Пришлите файл с расширением .txt.")
            return
        if document.file_size and document.file_size > 2 * 1024 * 1024:
            await message.answer("Файл слишком большой (максимум 2 МБ).")
            return
        file_id = document.file_id
    elif message.text and not message.text.startswith("/"):
        content_text = message.text.strip()
        if not content_text:
            await message.answer("Текст не должен быть пустым.")
            return
    else:
        await message.answer("Отправьте .txt-документ или текст.")
        return

    mid = await db.add_manual(
        data["name"], data["price"],
        "file" if file_id else "text",
        content_text=content_text,
        file_id=file_id
    )
    await state.update_data(sticker_kind="manual", sticker_id=mid)
    await state.set_state(OwnerSticker.waiting)
    user = await db.get_user(message.from_user.id)
    await message.answer(
        f"✅ Мануал #{mid} «{escape(data['name'])}» добавлен!\n"
        f"Цена: {data['price']}$\nВыдача: файл .txt\n\n"
        "🎨 Отправьте стикер или /skip для пропуска.",
        reply_markup=cancel_to_panel()
    )

@router.message(F.text.startswith("/add_manual "))
async def cmd_add_manual(message: Message):
    user = await db.get_user(message.from_user.id)
    if not user or user.role.value not in ("admin", "owner"):
        return
    try:
        payload = message.text[len("/add_manual "):]
        name, price, *rest = payload.split("|")
        text = "|".join(rest).strip()
        mid = await db.add_manual(name.strip(), float(price.strip()), "text", content_text=text)
        await message.answer(f"✅ Мануал #{mid} «{name.strip()}» добавлен за {price.strip()}$")
    except Exception as e:
        await message.answer(f"Ошибка формата: {e}")


# ──────────────────── TG-ПОЗИЦИИ (владелец / админ) ────────────────────

@router.callback_query(F.data == "owner:add_tg_offer")
async def add_tg_offer_start(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    if not is_owner_or_admin(user):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(OwnerAddTgOffer.country)
    await callback.message.edit_text(
        "📱 <b>Новая Telegram-позиция</b>\n\n"
        "Введите страну аккаунтов, например: Китай",
        reply_markup=cancel_to_panel()
    )
    await callback.answer()


_AGE_LABELS = (
    "Новорег", "1 месяц", "3 месяца", "6 месяцев", "1 год",
    "2 года", "3 года", "5 лет", "10 лет", "15 лет"
)

def _owner_age_keyboard(page: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from bot.keyboards.pagination import page_slice, add_page_arrows
    builder = InlineKeyboardBuilder()
    chunk, page, previous, following = page_slice(_AGE_LABELS, page)
    for age in chunk:
        builder.button(text=age, callback_data=f"owner:tg_age:{age}")
    add_page_arrows(builder, page, previous, following, "owner:tg_age_page")
    builder.adjust(2)
    return builder.as_markup()


@router.callback_query(F.data.startswith("owner:tg_age_page:"), OwnerAddTgOffer.age)
async def owner_age_page(callback: CallbackQuery):
    page = max(0, min(2, int(callback.data.rsplit(":", 1)[1])))
    await callback.message.edit_text("Выберите возраст аккаунта:",
                                     reply_markup=_owner_age_keyboard(page))
    await callback.answer()


@router.message(OwnerAddTgOffer.country)
async def add_tg_offer_country(message: Message, state: FSMContext):
    country = (message.text or "").strip()
    if not 2 <= len(country) <= 50 or ":" in country:
        await message.answer("Введите корректную страну (2–50 символов).")
        return
    await state.update_data(country=country)
    await state.set_state(OwnerAddTgOffer.age)
    await message.answer("Выберите возраст аккаунта:", reply_markup=_owner_age_keyboard(0))


@router.callback_query(F.data.startswith("owner:tg_age:"), OwnerAddTgOffer.age)
async def add_tg_offer_age(callback: CallbackQuery, state: FSMContext):
    age = callback.data.split(":", 2)[2]
    await state.update_data(age=age)
    await state.set_state(OwnerAddTgOffer.buyer_price)
    await callback.message.edit_text(
        f"Возраст: <b>{escape(age)}</b>\n\nВведите цену покупателя ($):"
    )
    await callback.answer()


@router.message(OwnerAddTgOffer.buyer_price)
async def add_tg_offer_buyer_price(message: Message, state: FSMContext):
    try:
        price = float((message.text or "").replace(",", ".").strip())
        if not isfinite(price) or price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите цену больше нуля, например: 10")
        return
    await state.update_data(buyer_price=price)
    await state.set_state(OwnerAddTgOffer.seller_price)
    await message.answer("Введите цену продавца ($), например: 6")


@router.message(OwnerAddTgOffer.seller_price)
async def add_tg_offer_seller_price(message: Message, state: FSMContext):
    try:
        price = float((message.text or "").replace(",", ".").strip())
        if not isfinite(price) or price < 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректную цену продавца, например: 6")
        return
    data = await state.get_data()
    if price > data["buyer_price"]:
        await message.answer("Цена продавца не должна превышать цену покупателя.")
        return
    oid = await db.add_tg_offer(
        data["country"], data["age"], data["buyer_price"], price
    )
    await state.update_data(sticker_kind="tg_offer", sticker_id=oid)
    await state.set_state(OwnerSticker.waiting)
    user = await db.get_user(message.from_user.id)
    await message.answer(
        f"✅ Telegram-позиция #{oid} создана!\n"
        f"Страна: {escape(data['country'])}\n"
        f"Возраст: {escape(data['age'])}\n"
        f"Покупатель: {data['buyer_price']}$ / продавец: {price}$\n\n"
        "Чтобы добавить аккаунты в наличие, нажмите «📦 Загрузить акк» в главном меню.\n\n"
        "🎨 Отправьте стикер для позиции или /skip.",
        reply_markup=cancel_to_panel()
    )


@router.message(F.text.startswith("/add_tg_offer "))
async def cmd_add_tg_offer(message: Message):
    user = await db.get_user(message.from_user.id)
    if not user or user.role.value not in ("admin", "owner"):
        return
    # /add_tg_offer Китай|Новорег|10|6
    try:
        parts = message.text[len("/add_tg_offer "):].split("|")
        country, age, buyer, seller = [p.strip() for p in parts[:4]]
        oid = await db.add_tg_offer(country, age, float(buyer), float(seller))
        await message.answer(f"✅ Оффер #{oid}: {country} / {age} — покуп {buyer}$ / прод {seller}$")
    except Exception as e:
        await message.answer(f"Формат: /add_tg_offer Страна|Возраст|цена_покуп|цена_прод\n{e}")


@router.message(F.text.startswith("/add_tg_stock "))
async def cmd_add_tg_stock(message: Message):
    """Продавец/админ: /add_tg_stock Китай|Новорег|+7900...|session_string"""
    user = await db.get_user(message.from_user.id)
    if not user or user.role.value not in ("seller", "admin", "owner"):
        return
    try:
        parts = message.text[len("/add_tg_stock "):].split("|")
        country, age, phone, session = [p.strip() for p in parts[:4]]
        from bot.services import telegram_client as tg
        ok, msg = await tg.check_session_alive(session)
        if not ok:
            await message.answer(f"⚠️ Сессия не прошла проверку: {msg}\nВсё равно сохранить? Отправьте ещё раз с ! в начале session")
            # всё равно можно сохранить — продавец отвечает
        sid = await db.add_tg_stock(country, age, phone, session, "string", user.user_id)
        await message.answer(f"✅ Аккаунт #{sid} добавлен в сток ({country} / {age})")
    except Exception as e:
        await message.answer(
            f"Формат: /add_tg_stock Страна|Возраст|телефон|string_session\n{e}"
        )
