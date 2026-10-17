import json
from html import escape
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery

from bot.database.db import db
from bot.i18n import menu_variants
from bot.keyboards.chat_kb import chat_open_keyboard
from bot.database.models import UserRole, OrderStatus, EntryType
from bot.keyboards.seller_kb import active_order_keyboard, my_orders_keyboard
from bot.keyboards.user_kb import main_menu, back_keyboard

router = Router()


def seller_filter(user_id_getter):
    """Простая проверка роли продавца+"""
    async def check(event):
        user = await db.get_user(user_id_getter(event))
        return user and user.role in (UserRole.SELLER, UserRole.ADMIN, UserRole.OWNER)
    return check


@router.message(F.text.in_(menu_variants("orders")))
async def my_orders(message: Message):
    user = await db.get_user(message.from_user.id)
    if not user or user.role not in (UserRole.SELLER, UserRole.ADMIN, UserRole.OWNER):
        await message.answer("Доступно только продавцам.")
        return

    orders = await db.get_seller_active_orders(user.user_id)
    if not orders:
        from bot.keyboards.chat_kb import chat_orders_keyboard
        chats = await db.get_chat_orders(user.user_id)
        await message.answer(
            "У вас нет активных заказов. Переписки по старым верификациям доступны ниже.",
            reply_markup=chat_orders_keyboard(chats, await db.get_language(user.user_id))
            if chats else back_keyboard()
        )
        return

    text = "📋 <b>Ваши активные заказы:</b>\n\n"
    for o in orders[:5]:
        text += f"#{o.id} — {o.product_name} ({o.seller_price}$)\n"
    if len(orders) > 5:
        text += "\nОстальные заказы смотрите кнопками ➡️."

    await message.answer(text, reply_markup=my_orders_keyboard(orders), parse_mode="HTML")


@router.callback_query(F.data.startswith("sellerorders:"))
async def seller_orders_page(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not user or user.role not in (UserRole.SELLER, UserRole.ADMIN, UserRole.OWNER):
        await callback.answer("Нет доступа", show_alert=True)
        return
    orders = await db.get_seller_active_orders(callback.from_user.id)
    page = max(0, min(10000, int(callback.data.rsplit(":", 1)[1])))
    await callback.message.edit_text(
        f"📋 Незавершённые заказы — страница {page + 1}",
        reply_markup=my_orders_keyboard(orders, page))
    await callback.answer()


@router.callback_query(F.data.startswith("take_order:"))
async def take_order(callback: CallbackQuery, bot: Bot):
    order_id = int(callback.data.split(":")[1])
    user = await db.get_user(callback.from_user.id)

    if not user or user.role not in (UserRole.SELLER, UserRole.ADMIN, UserRole.OWNER):
        await callback.answer("Только для продавцов", show_alert=True)
        return

    success = await db.take_order(order_id, user.user_id)
    if not success:
        await callback.answer("Заказ уже взят другим поставщиком ❌", show_alert=True)
        await callback.message.edit_text(
            callback.message.text + "\n\n❌ Заказ уже взят другим поставщиком."
        )
        return

    order = await db.get_order(order_id)
    text = (
        f"✅ Вы взяли заказ <b>#{order_id}</b>\n\n"
        f"Сервис: <b>{escape(order.product_name)}</b>\n"
        f"Оплата: <b>{order.seller_price:.2f} USDT</b>\n\n"
        "💬 Контакты покупателя не нужны.\n"
        "Покупатель может написать вам через анонимный чат, "
        "после его первого сообщения вы сможете отвечать.\n"
        "Если работу нужно отложить, сообщения всё равно будут приходить.\n\n"
        "После выполнения нажмите «Завершить заказ»."
    )

    await callback.message.edit_text(text, reply_markup=active_order_keyboard(order_id, with_email_code=False), parse_mode="HTML")
    await callback.answer("Заказ принят!")

    # Уведомляем покупателя
    try:
        await bot.send_message(
            order.buyer_id,
            f"📦 Ваш заказ <b>#{order_id}</b> ({order.product_name}) взят в работу продавцом.",
            parse_mode="HTML",
            reply_markup=chat_open_keyboard(order_id, await db.get_language(order.buyer_id))
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("reject_order:"))
async def reject_order(callback: CallbackQuery):
    await callback.message.edit_text(callback.message.text + "\n\nВы отказались от заказа.")
    await callback.answer()


@router.callback_query(F.data.startswith("view_order:"))
async def view_order(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)
    if not order or order.seller_id != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    text = (
        f"📦 Заказ <b>#{order.id}</b>\n\n"
        f"Сервис: <b>{escape(order.product_name)}</b>\n"
        f"Оплата: <b>{order.seller_price:.2f} USDT</b>\n\n"
        "💬 Вся переписка с покупателем — через анонимный чат."
    )

    await callback.message.edit_text(text, reply_markup=active_order_keyboard(order.id, with_email_code=False), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("complete_order:"))
async def complete_order(callback: CallbackQuery, bot: Bot):
    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)

    if not order or order.seller_id != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    if order.status != OrderStatus.IN_PROGRESS:
        await callback.answer("Заказ уже завершён или отменён", show_alert=True)
        return

    # Статус и начисление одной транзакцией: повторное нажатие безопасно.
    payout = await db.complete_verification_and_pay_seller(order_id, order.seller_id)
    if payout is None:
        await callback.answer("Заказ уже завершён или изменён", show_alert=True)
        return

    await callback.message.edit_text(
        f"✅ Заказ <b>#{order_id}</b> завершён!\n"
        f"Вам начислено <b>{payout:.2f}$</b>",
        parse_mode="HTML"
    )
    await callback.answer("Заказ завершён!")

    # Уведомляем покупателя
    try:
        await bot.send_message(
            order.buyer_id,
            f"✅ Ваш заказ <b>#{order_id}</b> ({order.product_name}) успешно выполнен!",
            parse_mode="HTML"
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("cancel_taken:"))
async def cancel_taken_order(callback: CallbackQuery, bot: Bot):
    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)

    if not order or order.seller_id != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    # Отказ только от действительно активного заказа; завершённый не открыть вновь.
    cursor = await db.conn.execute(
        """UPDATE orders SET seller_id = NULL, status = ?, taken_at = NULL
           WHERE id = ? AND seller_id = ? AND status = ?""",
        (OrderStatus.PENDING.value, order_id, callback.from_user.id,
         OrderStatus.IN_PROGRESS.value)
    )
    await db.conn.commit()
    if cursor.rowcount != 1:
        await callback.answer("Заказ уже изменился", show_alert=True)
        return

    await callback.message.edit_text(
        f"❌ Вы отказались от заказа #{order_id}. Покупатель может отменить его с возвратом."
    )
    await callback.answer()

    # Можно снова разослать продавцам, но для простоты оставляем как есть
    # (продавцы могут видеть в "Мои заказы" только свои)


# ──────────────────── ЗАГРУЗКА TG-АККАУНТА ────────────────────

from aiogram.fsm.context import FSMContext
from bot.states.states import SellerAddAccount
from bot.keyboards.user_kb import cancel_keyboard


AGE_OPTIONS = [
    "Новорег", "1 месяц", "3 месяца", "6 месяцев",
    "1 год", "2 года", "3 года", "5 лет", "10 лет", "15 лет"
]


@router.message(F.text.in_(menu_variants("upload")))
async def upload_start(message: Message, state: FSMContext):
    user = await db.get_user(message.from_user.id)
    if not user or user.role not in (UserRole.SELLER, UserRole.ADMIN, UserRole.OWNER):
        await message.answer("Только для продавцов.")
        return
    await state.set_state(SellerAddAccount.country)
    await message.answer(
        "📦 <b>Загрузка Telegram-аккаунта</b>\n\n"
        "Введите <b>страну</b> (например: Китай, Индия, Бельгия):",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )


@router.message(SellerAddAccount.country)
async def upload_country(message: Message, state: FSMContext):
    country = message.text.strip()
    if len(country) < 2:
        await message.answer("Слишком коротко. Введите страну:")
        return
    await state.update_data(country=country)
    await state.set_state(SellerAddAccount.age)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for a in AGE_OPTIONS:
        b.button(text=a, callback_data=f"up_age:{a}")
    b.button(text="❌ Отмена", callback_data="cancel")
    b.adjust(2)
    await message.answer(
        f"Страна: <b>{country}</b>\n\nВыберите возраст аккаунта:",
        reply_markup=b.as_markup(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("up_age:"), SellerAddAccount.age)
async def upload_age(callback: CallbackQuery, state: FSMContext):
    age = callback.data.split(":", 1)[1]
    await state.update_data(age_label=age)
    await state.set_state(SellerAddAccount.phone)
    await callback.message.edit_text(
        f"Возраст: <b>{age}</b>\n\nВведите номер телефона аккаунта:\n<code>+8613812345678</code>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(SellerAddAccount.phone)
async def upload_phone(message: Message, state: FSMContext):
    phone = message.text.strip().replace(" ", "")
    if not phone.startswith("+") or len(phone) < 10:
        await message.answer("Формат: +79001234567")
        return
    await state.update_data(phone=phone)
    await state.set_state(SellerAddAccount.method)

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="🔑 String Session", callback_data="up_method:session")
    b.button(text="📱 Номер + код (войти сейчас)", callback_data="up_method:phone_code")
    b.button(text="❌ Отмена", callback_data="cancel")
    b.adjust(1)
    await message.answer(
        f"Номер: <code>{phone}</code>\n\nКак добавить аккаунт?",
        reply_markup=b.as_markup(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("up_method:"), SellerAddAccount.method)
async def upload_method(callback: CallbackQuery, state: FSMContext):
    method = callback.data.split(":")[1]
    await state.update_data(method=method)

    if method == "session":
        await state.set_state(SellerAddAccount.session)
        await callback.message.edit_text(
            "Отправьте <b>string session</b> аккаунта одним сообщением.\n\n"
            "Её можно получить через Telethon / Pyrogram / готовые конвертеры tdata→session.",
            parse_mode="HTML"
        )
    else:
        data = await state.get_data()
        from bot.services import telegram_client as tg
        ok, msg = await tg.login_with_phone(data["phone"])
        if not ok:
            await callback.message.edit_text(
                f"❌ Не удалось отправить код: {msg}\n\n"
                "Проверьте TELEGRAM_API_ID/HASH на хосте или загрузите через String Session."
            )
            await state.clear()
            await callback.answer()
            return
        await state.set_state(SellerAddAccount.code)
        await callback.message.edit_text(
            f"✅ Код отправлен на <code>{data['phone']}</code>\n\n"
            "Введите код из Telegram/SMS:",
            parse_mode="HTML"
        )
    await callback.answer()


@router.message(SellerAddAccount.session)
async def upload_session(message: Message, state: FSMContext):
    session = message.text.strip()
    data = await state.get_data()

    from bot.services import telegram_client as tg
    ok, msg = await tg.check_session_alive(session)
    if not ok:
        await message.answer(
            f"⚠️ Сессия не прошла проверку: {msg}\n\n"
            "Отправьте другую session или /cancel"
        )
        return

    sid = await db.add_tg_stock(
        country=data["country"],
        age_label=data["age_label"],
        phone=data["phone"],
        session_string=session,
        session_type="string",
        seller_id=message.from_user.id,
    )
    await state.clear()
    user = await db.get_user(message.from_user.id)
    await message.answer(
        f"✅ Аккаунт #{sid} добавлен!\n"
        f"{data['country']} / {data['age_label']}\n"
        f"Номер: <code>{data['phone']}</code>",
        parse_mode="HTML",
        reply_markup=main_menu(user.role)
    )


@router.message(SellerAddAccount.code)
async def upload_code(message: Message, state: FSMContext):
    code = message.text.strip()
    data = await state.get_data()
    from bot.services import telegram_client as tg

    ok, msg, session = await tg.confirm_code(data["phone"], code)
    if not ok:
        if "пароль" in msg.lower() or "2fa" in msg.lower() or "password" in msg.lower():
            await state.set_state(SellerAddAccount.password_2fa)
            await state.update_data(code=code)
            await message.answer("Нужен облачный пароль 2FA. Отправьте его:")
            return
        await message.answer(f"❌ {msg}\nПопробуйте код ещё раз или отмените.")
        return

    sid = await db.add_tg_stock(
        country=data["country"],
        age_label=data["age_label"],
        phone=data["phone"],
        session_string=session,
        session_type="phone",
        seller_id=message.from_user.id,
    )
    await state.clear()
    await tg.disconnect_phone(data["phone"])
    user = await db.get_user(message.from_user.id)
    await message.answer(
        f"✅ Аккаунт #{sid} добавлен и проверен!\n"
        f"{data['country']} / {data['age_label']}\n"
        f"Номер: <code>{data['phone']}</code>",
        parse_mode="HTML",
        reply_markup=main_menu(user.role)
    )


@router.message(SellerAddAccount.password_2fa)
async def upload_2fa(message: Message, state: FSMContext):
    password = message.text.strip()
    data = await state.get_data()
    from bot.services import telegram_client as tg

    ok, msg, session = await tg.confirm_code(data["phone"], data.get("code", ""), password=password)
    if not ok:
        await message.answer(f"❌ {msg}")
        return

    sid = await db.add_tg_stock(
        country=data["country"],
        age_label=data["age_label"],
        phone=data["phone"],
        session_string=session,
        session_type="phone",
        seller_id=message.from_user.id,
    )
    await state.clear()
    await tg.disconnect_phone(data["phone"])
    user = await db.get_user(message.from_user.id)
    await message.answer(
        f"✅ Аккаунт #{sid} добавлен!\n"
        f"{data['country']} / {data['age_label']}\n"
        f"<code>{data['phone']}</code>",
        parse_mode="HTML",
        reply_markup=main_menu(user.role)
    )


@router.callback_query(F.data.startswith("email_code:"))
async def email_code_handler(callback: CallbackQuery):
    # Legacy buttons must not retrieve or forward authentication codes.
    await callback.answer(
        "Передача кодов входа отключена. Покупатель вводит их самостоятельно.",
        show_alert=True,
    )
