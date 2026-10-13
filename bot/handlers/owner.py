from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.database.db import db
from bot.database.models import UserRole, EntryType
from bot.keyboards.owner_kb import (
    owner_panel_keyboard, products_list_keyboard, entry_type_keyboard,
    cancel_to_panel, confirm_keyboard
)
from bot.keyboards.user_kb import main_menu
from bot.states.states import (
    OwnerAddProduct, OwnerEditProduct, OwnerAddSeller, OwnerAddAdmin,
    OwnerBroadcast, OwnerSetLink
)
from bot.config import settings

router = Router()


def is_owner_or_admin(user) -> bool:
    return user and user.role in (UserRole.ADMIN, UserRole.OWNER)


def is_owner(user) -> bool:
    return user and user.role == UserRole.OWNER


# ──────────────────── ПАНЕЛЬ ────────────────────

@router.message(F.text.in_({"👑 Панель владельца", "🛠 Админ-панель"}))
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

    await state.clear()
    await callback.message.edit_text(
        f"✅ Позиция добавлена!\n\n"
        f"ID: {product_id}\n"
        f"Название: {data['name']}\n"
        f"Покупатель: {data['buyer_price']}$\n"
        f"Продавец: {data['seller_price']}$\n"
        f"Вход: {'Почта' if entry_type == EntryType.EMAIL else 'Telegram'}",
        reply_markup=owner_panel_keyboard(is_owner=is_owner(await db.get_user(callback.from_user.id)))
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

@router.callback_query(F.data == "owner:add_manual")
async def add_manual_hint(callback: CallbackQuery):
    await callback.message.answer(
        "📘 Добавление мануала — временно через команду:\n"
        "<code>/add_manual Название|цена|текст мануала</code>\n\n"
        "Пример:\n"
        "<code>/add_manual Bybit KYC|5|1. Открой приложение...</code>",
        parse_mode="HTML"
    )
    await callback.answer()


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
