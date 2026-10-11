import json
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.database.db import db
from bot.database.models import UserRole, EntryType, OrderStatus
from bot.keyboards.user_kb import (
    catalog_keyboard, back_keyboard, confirm_buy_keyboard,
    profile_keyboard, topup_amounts_keyboard, cancel_keyboard, main_menu,
    invoice_keyboard
)
from bot.keyboards.seller_kb import new_order_keyboard
from bot.states.states import TopUpStates, BuyStates, WithdrawStates
from bot.services.cryptopay import cryptopay
from bot.config import settings

router = Router()


# ──────────────────── КАТАЛОГ ────────────────────

@router.message(F.text == "🛍️ Каталог")
async def catalog(message: Message):
    products = await db.get_all_products(only_active=True)
    if not products:
        await message.answer("📭 Каталог пока пуст.", reply_markup=back_keyboard())
        return

    text = "🛍️ <b>Каталог верификаций</b>\n\nВыберите нужную позицию:"
    await message.answer(text, reply_markup=catalog_keyboard(products), parse_mode="HTML")


@router.callback_query(F.data == "catalog")
async def catalog_cb(callback: CallbackQuery):
    products = await db.get_all_products(only_active=True)
    if not products:
        await callback.message.edit_text("📭 Каталог пока пуст.", reply_markup=back_keyboard())
        await callback.answer()
        return

    text = "🛍️ <b>Каталог верификаций</b>\n\nВыберите нужную позицию:"
    await callback.message.edit_text(text, reply_markup=catalog_keyboard(products), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("buy:"))
async def buy_product(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[1])
    product = await db.get_product(product_id)
    if not product or not product.is_active:
        await callback.answer("Позиция недоступна", show_alert=True)
        return

    user = await db.get_user(callback.from_user.id)
    text = (
        f"<b>{product.name}</b>\n\n"
        f"💰 Цена: <b>{product.buyer_price}$</b>\n"
        f"🔑 Способ входа: {'Почта' if product.entry_type == EntryType.EMAIL else 'Telegram аккаунт'}\n\n"
        f"Ваш баланс: {user.balance:.2f}$"
    )
    await callback.message.edit_text(text, reply_markup=confirm_buy_keyboard(product_id), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_buy:"))
async def confirm_buy(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    product = await db.get_product(product_id)
    if not product or not product.is_active:
        await callback.answer("Позиция недоступна", show_alert=True)
        return

    user = await db.get_user(callback.from_user.id)

    if user.balance < product.buyer_price:
        await callback.answer(
            f"Недостаточно средств. Нужно {product.buyer_price}$, у вас {user.balance:.2f}$",
            show_alert=True
        )
        return

    await db.update_balance(user.user_id, -product.buyer_price)
    await db.add_turnover(user.user_id, product.buyer_price)

    await state.set_state(BuyStates.waiting_entry_data)
    await state.update_data(product_id=product_id)

    if product.entry_type == EntryType.EMAIL:
        text = (
            "📧 Отправьте данные для входа в формате:\n\n"
            "<code>email@example.com\nпароль</code>\n\n"
            "(каждая строка — отдельно)"
        )
    else:
        text = (
            "📱 Отправьте данные Telegram-аккаунта в формате:\n\n"
            "<code>+79001234567\nкод_из_смс</code>\n\n"
            "(номер и код — каждая строка отдельно)"
        )

    await callback.message.edit_text(text, reply_markup=cancel_keyboard(), parse_mode="HTML")
    await callback.answer()


@router.message(BuyStates.waiting_entry_data)
async def process_entry_data(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    product_id = data.get("product_id")
    product = await db.get_product(product_id)

    if not product:
        await message.answer("Ошибка: позиция не найдена.")
        await state.clear()
        return

    lines = [l.strip() for l in message.text.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        await message.answer("Неверный формат. Отправьте две строки: логин и пароль/код.")
        return

    if product.entry_type == EntryType.EMAIL:
        entry_data = {"email": lines[0], "password": lines[1]}
    else:
        entry_data = {"phone": lines[0], "code": lines[1]}

    order_id = await db.create_order(
        buyer_id=message.from_user.id,
        product=product,
        entry_data=entry_data
    )

    await state.clear()
    await message.answer(
        f"✅ Заказ <b>#{order_id}</b> создан!\n"
        f"Сервис: {product.name}\n"
        f"Ожидайте, продавцы уже получили уведомление.",
        parse_mode="HTML",
        reply_markup=main_menu((await db.get_user(message.from_user.id)).role)
    )

    sellers = await db.get_users_by_role(UserRole.SELLER)
    admins = await db.get_users_by_role(UserRole.ADMIN)
    owners = await db.get_users_by_role(UserRole.OWNER)
    recipients = {u.user_id for u in sellers + admins + owners}

    entry_label = "Почта" if product.entry_type == EntryType.EMAIL else "Telegram аккаунт"
    notify_text = (
        f"🆕 <b>Новый заказ! #{order_id}</b>\n\n"
        f"Сервис: <b>{product.name}</b>\n"
        f"Оплата продавцу: <b>{product.seller_price}$</b>\n"
        f"Вход через: {entry_label}"
    )

    for uid in recipients:
        try:
            await bot.send_message(
                uid,
                notify_text,
                reply_markup=new_order_keyboard(order_id),
                parse_mode="HTML"
            )
        except Exception:
            pass


# ──────────────────── ПРОФИЛЬ ────────────────────

@router.message(F.text == "👤 Профиль")
async def profile(message: Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start")
        return

    role_names = {
        UserRole.USER: "Пользователь",
        UserRole.SELLER: "Продавец",
        UserRole.ADMIN: "Админ",
        UserRole.OWNER: "Владелец",
    }

    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"Ник: @{user.username or '—'}\n"
        f"ID: <code>{user.user_id}</code>\n"
        f"С нами с: {user.registered_at.strftime('%d.%m.%Y')}\n"
        f"Баланс: <b>{user.balance:.2f}$</b>\n"
        f"Оборот: {user.turnover:.2f}$\n"
        f"Куплено верификаций: {user.verifications_bought}\n"
        f"Статус: <b>{role_names.get(user.role, user.role)}</b>"
    )

    if user.role in (UserRole.SELLER, UserRole.ADMIN, UserRole.OWNER):
        text += (
            f"\n\n📦 Выполнено верификаций: {user.verifications_done}\n"
            f"💵 Заработано: {user.earned:.2f}$"
        )

    await message.answer(text, reply_markup=profile_keyboard(), parse_mode="HTML")


# ──────────────────── ВЫВОД ────────────────────

@router.callback_query(F.data == "withdraw")
async def withdraw_start(callback: CallbackQuery, state: FSMContext):
    user = await db.get_user(callback.from_user.id)
    if user.balance <= 0:
        await callback.answer("Баланс пуст", show_alert=True)
        return

    await state.set_state(WithdrawStates.waiting_amount)
    await callback.message.edit_text(
        f"💸 <b>Вывод средств</b>\n\n"
        f"Ваш баланс: <b>{user.balance:.2f}$</b>\n\n"
        f"Введите сумму для вывода (минимум 1$):\n"
        f"Средства будут отправлены чеком в @CryptoBot",
        reply_markup=cancel_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(WithdrawStates.waiting_amount)
async def withdraw_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").strip())
    except ValueError:
        await message.answer("Введите число, например: 10")
        return

    if amount < 1:
        await message.answer("Минимальная сумма вывода — 1$")
        return

    user = await db.get_user(message.from_user.id)
    if amount > user.balance:
        await message.answer(f"Недостаточно средств. Баланс: {user.balance:.2f}$")
        return

    await db.update_balance(user.user_id, -amount)

    try:
        check = await cryptopay.create_check(amount=amount)
        await message.answer(
            f"✅ Чек на <b>{amount}$</b> создан!\n\n"
            f"🔗 {check['bot_check_url']}\n\n"
            f"Перейдите по ссылке и активируйте чек в @CryptoBot",
            parse_mode="HTML",
            reply_markup=main_menu(user.role)
        )
    except Exception as e:
        await db.update_balance(user.user_id, amount)
        await message.answer(f"❌ Ошибка создания чека: {e}\nСредства возвращены на баланс.")

    await state.clear()


# ──────────────────── ПОПОЛНЕНИЕ ────────────────────

@router.message(F.text == "🤑 Пополнить")
async def topup(message: Message):
    await message.answer(
        "🤑 <b>Пополнение баланса</b>\n\nВыберите сумму или введите свою:",
        reply_markup=topup_amounts_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("topup:"))
async def topup_amount(callback: CallbackQuery, state: FSMContext):
    value = callback.data.split(":")[1]

    if value == "custom":
        await state.set_state(TopUpStates.waiting_amount)
        await callback.message.edit_text(
            "Введите сумму пополнения в $ (например: 15.5):",
            reply_markup=cancel_keyboard()
        )
        await callback.answer()
        return

    amount = float(value)
    await _create_topup_invoice(callback, amount)


@router.message(TopUpStates.waiting_amount)
async def topup_custom_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", ".").strip())
    except ValueError:
        await message.answer("Введите число, например: 10")
        return

    if amount < 1:
        await message.answer("Минимальная сумма — 1$")
        return

    await state.clear()
    try:
        invoice = await cryptopay.create_invoice(
            amount=amount,
            description=f"Пополнение баланса на {amount}$",
            payload=f"topup:{message.from_user.id}"
        )
        await db.save_invoice(invoice["invoice_id"], message.from_user.id, amount, "topup")

        await message.answer(
            f"💳 Счёт на <b>{amount}$</b> создан.\n\n"
            f"Оплатите по ссылке:\n{invoice['bot_invoice_url']}\n\n"
            f"После оплаты нажмите кнопку ниже:",
            parse_mode="HTML",
            reply_markup=invoice_keyboard(invoice["invoice_id"])
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка создания счёта: {e}")


async def _create_topup_invoice(callback: CallbackQuery, amount: float):
    try:
        invoice = await cryptopay.create_invoice(
            amount=amount,
            description=f"Пополнение баланса на {amount}$",
            payload=f"topup:{callback.from_user.id}"
        )
        await db.save_invoice(invoice["invoice_id"], callback.from_user.id, amount, "topup")

        await callback.message.edit_text(
            f"💳 Счёт на <b>{amount}$</b> создан.\n\n"
            f"Оплатите по ссылке:\n{invoice['bot_invoice_url']}\n\n"
            f"После оплаты нажмите кнопку ниже:",
            parse_mode="HTML",
            reply_markup=invoice_keyboard(invoice["invoice_id"])
        )
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка создания счёта: {e}")
    await callback.answer()


@router.callback_query(F.data.startswith("check_pay:"))
async def check_payment(callback: CallbackQuery):
    """Проверяет оплату инвойса и зачисляет баланс."""
    invoice_id = int(callback.data.split(":")[1])
    row = await db.get_invoice(invoice_id)

    if not row:
        await callback.answer("Счёт не найден", show_alert=True)
        return

    if row["status"] == "paid":
        await callback.answer("Этот счёт уже зачислен", show_alert=True)
        return

    if row["user_id"] != callback.from_user.id:
        await callback.answer("Это не ваш счёт", show_alert=True)
        return

    try:
        paid = await cryptopay.check_invoice_paid(invoice_id)
    except Exception as e:
        await callback.answer(f"Ошибка проверки: {e}", show_alert=True)
        return

    if not paid:
        await callback.answer("Оплата ещё не поступила. Подождите минуту и нажмите снова.", show_alert=True)
        return

    amount = float(row["amount"])
    await db.mark_invoice_paid(invoice_id)
    await db.update_balance(callback.from_user.id, amount)

    user = await db.get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"✅ Оплата подтверждена!\n\n"
        f"На баланс зачислено: <b>{amount}$</b>\n"
        f"Текущий баланс: <b>{user.balance:.2f}$</b>",
        parse_mode="HTML",
        reply_markup=back_keyboard()
    )
    await callback.answer("Баланс пополнен!")


# ──────────────────── ПОДДЕРЖКА / КАНАЛ ────────────────────

@router.message(F.text == "🎗️ Поддержка")
async def support(message: Message):
    username = await db.get_setting("support_username") or settings.SUPPORT_USERNAME
    await message.answer(
        f"🎗️ По всем вопросам пишите:\n{username}",
        reply_markup=back_keyboard()
    )


@router.message(F.text == "🛜 Наш канал")
async def channel(message: Message):
    url = await db.get_setting("channel_url") or settings.CHANNEL_URL
    await message.answer(
        f"🛜 Наш канал:\n{url}",
        reply_markup=back_keyboard()
    )
