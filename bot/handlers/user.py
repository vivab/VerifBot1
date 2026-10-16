import json
import re
import secrets
from html import escape
from aiogram import Router, F, Bot
import logging
from decimal import Decimal, InvalidOperation
from aiogram.types import InlineKeyboardMarkup
from bot.keyboards.pagination import PAGE_SIZE, page_slice
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext

from bot.database.db import db
from bot.database.models import UserRole, EntryType, OrderStatus
from bot.keyboards.user_kb import (
    catalog_keyboard, back_keyboard, confirm_buy_keyboard,
    profile_keyboard, topup_amounts_keyboard, cancel_keyboard, main_menu,
    invoice_keyboard, verification_order_keyboard, purchase_history_keyboard
)
from bot.keyboards.catalog_kb import (
    categories_keyboard, manuals_keyboard, confirm_manual_keyboard,
    tg_countries_keyboard, tg_ages_keyboard, confirm_tg_keyboard, tg_order_keyboard
)
from bot.config import settings as app_settings
from bot.keyboards.seller_kb import new_order_keyboard
from bot.states.states import TopUpStates, BuyStates, WithdrawStates
from bot.services.cryptopay import cryptopay
from bot.config import settings
from bot.i18n import tr, menu_variants

router = Router()
logger = logging.getLogger(__name__)


# ──────────────────── КАТАЛОГ ────────────────────

@router.message(F.text.in_(menu_variants("catalog")))
async def catalog(message: Message):
    await message.answer(
        "🛍️ <b>Каталог</b>\n\nВыберите категорию:",
        reply_markup=categories_keyboard(),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "catalog")
async def catalog_cb(callback: CallbackQuery):
    await callback.message.edit_text(
        "🛍️ <b>Каталог</b>\n\nВыберите категорию:",
        reply_markup=categories_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "cat:verification")
async def cat_verification(callback: CallbackQuery):
    products = await db.get_all_products(only_active=True)
    if not products:
        await callback.message.edit_text("📭 Верификаций пока нет.", reply_markup=categories_keyboard())
        await callback.answer()
        return
    await callback.message.edit_text(
        "👥 <b>Верификации</b>\n\nВыберите позицию:",
        reply_markup=catalog_keyboard(products),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catvpage:"))
async def cat_verification_page(callback: CallbackQuery):
    page = max(0, int(callback.data.rsplit(":", 1)[1]))
    products = await db.get_all_products()
    await callback.message.edit_text(
        f"👥 <b>Верификации</b> — страница {page + 1}\n\nВыберите позицию:",
        reply_markup=catalog_keyboard(products, page)
    )
    await callback.answer()


@router.callback_query(F.data == "cat:manual")
async def cat_manual(callback: CallbackQuery):
    manuals = await db.get_all_manuals(only_active=True)
    if not manuals:
        await callback.message.edit_text("📭 Мануалов пока нет.", reply_markup=categories_keyboard())
        await callback.answer()
        return
    await callback.message.edit_text(
        "📘 <b>Мануалы</b>\n\nВыберите:",
        reply_markup=manuals_keyboard(manuals),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catmpage:"))
async def cat_manual_page(callback: CallbackQuery):
    page = max(0, int(callback.data.rsplit(":", 1)[1]))
    manuals = await db.get_all_manuals()
    await callback.message.edit_text(
        f"📘 <b>Мануалы</b> — страница {page + 1}\n\nВыберите:",
        reply_markup=manuals_keyboard(manuals, page)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("manual:"))
async def manual_view(callback: CallbackQuery):
    mid = int(callback.data.split(":")[1])
    m = await db.get_manual(mid)
    if not m or not m["is_active"]:
        await callback.answer("Недоступно", show_alert=True)
        return
    user = await db.get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"📘 <b>{m['name']}</b>\n\n💰 Цена: <b>{m['buyer_price']}$</b>\n"
        f"Ваш баланс: {user.balance:.2f}$",
        reply_markup=confirm_manual_keyboard(mid),
        parse_mode="HTML"
    )
    sticker_id = await db.get_item_sticker("manual", mid)
    if sticker_id:
        try:
            await callback.message.answer_sticker(sticker_id)
        except Exception:
            logger.warning("Cannot send manual sticker #%s", mid)
    await callback.answer()


@router.callback_query(F.data.startswith("buy_manual:"))
async def buy_manual(callback: CallbackQuery):
    mid = int(callback.data.split(":")[1])
    m = await db.get_manual(mid)
    if not m or (not m["file_id"] and not m["content_text"]):
        await callback.answer("Мануал недоступен.", show_alert=True)
        return
    try:
        order_id, fresh, error = await db.buy_manual_paid(callback.from_user.id, mid)
    except Exception:
        logger.exception("Manual purchase failed")
        await callback.answer("Ошибка покупки. Проверьте «Мои покупки».", show_alert=True)
        return
    if error:
        await callback.answer(error, show_alert=True)
        return
    try:
        if m["file_id"]:
            await callback.message.answer_document(m["file_id"])
        else:
            await callback.message.answer_document(
                BufferedInputFile(m["content_text"].encode("utf-8"),
                                  filename=f"manual_{mid}.txt"))
    except Exception:
        logger.exception("Manual delivery failed for order %d", order_id)
        await callback.answer(
            "Оплата сохранена. Файл временно не отправлен; повторно нажмите «Купить» "
            "или откройте «Мои покупки» — второй раз деньги не спишутся.",
            show_alert=True
        )
        return
    await callback.answer("Мануал получен")
    try:
        await callback.message.edit_text(
            f"✅ Мануал отправлен документом .txt.\nЗаказ #{order_id}."
            + ("\nСписано один раз." if fresh else "\nПовторная выдача бесплатно.")
        )
    except Exception:
        pass

@router.callback_query(F.data == "cat:tg")
async def cat_tg(callback: CallbackQuery):
    countries = await db.get_tg_countries()
    if not countries:
        await callback.message.edit_text("📭 Аккаунтов пока нет.", reply_markup=categories_keyboard())
        await callback.answer()
        return
    await callback.message.edit_text(
        "📱 <b>Telegram аккаунты</b>\n\nВыберите страну:",
        reply_markup=tg_countries_keyboard(countries),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catcpage:"))
async def tg_country_page(callback: CallbackQuery):
    page = max(0, int(callback.data.rsplit(":", 1)[1]))
    countries = await db.get_tg_countries()
    await callback.message.edit_text(
        f"📱 Страны — страница {page + 1}\n\nВыберите:",
        reply_markup=tg_countries_keyboard(countries, page)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tg_cidx:"))
async def tg_country_index(callback: CallbackQuery):
    index = int(callback.data.rsplit(":", 1)[1])
    countries = await db.get_tg_countries()
    if index < 0 or index >= len(countries):
        await callback.answer("Список изменился, откройте каталог заново.", show_alert=True)
        return
    country = countries[index]
    offers = await db.get_tg_offers_by_country(country)
    await callback.message.edit_text(
        f"📱 <b>{escape(country)}</b>\n\nВыберите тип:",
        reply_markup=tg_ages_keyboard(index, offers)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("catopage:"))
async def tg_offers_page(callback: CallbackQuery):
    _, index, number = callback.data.split(":")
    idx, page = int(index), max(0, int(number))
    countries = await db.get_tg_countries()
    if idx < 0 or idx >= len(countries):
        await callback.answer("Обновите каталог.", show_alert=True)
        return
    offers = await db.get_tg_offers_by_country(countries[idx])
    await callback.message.edit_text(
        f"📱 <b>{escape(countries[idx])}</b> — страница {page + 1}",
        reply_markup=tg_ages_keyboard(idx, offers, page)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tg_country:"))
async def tg_country(callback: CallbackQuery):
    country = callback.data.split(":", 1)[1]
    offers = await db.get_tg_offers_by_country(country)
    if not offers:
        await callback.answer("Нет предложений", show_alert=True)
        return
    lines = []
    for o in offers:
        stock = await db.count_tg_stock(o["country"], o["age_label"])
        lines.append(f"{o['age_label']} — {o['buyer_price']}$ (в наличии: {stock})")
    countries = await db.get_tg_countries()
    country_index = countries.index(country) if country in countries else 0
    await callback.message.edit_text(
        f"📱 <b>{escape(country)}</b>\n\nВыберите:",
        reply_markup=tg_ages_keyboard(country_index, offers),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tg_offer:"))
async def tg_offer_view(callback: CallbackQuery):
    oid = int(callback.data.split(":")[1])
    o = await db.get_tg_offer(oid)
    if not o or not o["is_active"]:
        await callback.answer("Не найдено", show_alert=True)
        return
    stock = await db.count_tg_stock(o["country"], o["age_label"])
    user = await db.get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"📱 <b>{o['country']}</b> — {o['age_label']}\n\n"
        f"💰 Цена: <b>{o['buyer_price']}$</b>\n"
        f"В наличии: {stock}\n"
        f"Ваш баланс: {user.balance:.2f}$",
        reply_markup=confirm_tg_keyboard(oid),
        parse_mode="HTML"
    )
    sticker_id = await db.get_item_sticker("tg_offer", oid)
    if sticker_id:
        try:
            await callback.message.answer_sticker(sticker_id)
        except Exception:
            logger.warning("Cannot send offer sticker #%s", oid)
    await callback.answer()


@router.callback_query(F.data.startswith("buy_tg:"))
async def buy_tg(callback: CallbackQuery):
    oid = int(callback.data.split(":")[1])
    # The same button/message can be clicked twice. Idempotency key stops double debit.
    key = f"tg:{callback.from_user.id}:{callback.message.chat.id}:{callback.message.message_id}:{oid}"
    try:
        order_id, error = await db.buy_tg_paid(
            callback.from_user.id, oid, key,
            hours=getattr(app_settings, "TG_ORDER_HOURS", 3)
        )
    except Exception:
        logger.exception("TG account checkout failed")
        await callback.answer("Ошибка оформления; проверьте историю покупок.", show_alert=True)
        return
    if error:
        await callback.answer(error, show_alert=True)
        return
    order = await db.get_order(order_id)
    await callback.message.edit_text(
        f"✅ Покупка оформлена! Заказ #{order_id}\n\n"
        f"Товар: {escape(order.product_name)}\n"
        f"Номер: <code>{escape(order.phone or '—')}</code>\n"
        "Чтобы восстановить покупку, откройте «Мои покупки».\n"
        "Никому не передавайте коды входа и пароли.",
        reply_markup=tg_order_keyboard(order_id)
    )
    await callback.answer("Покупка подтверждена")

@router.callback_query(F.data.startswith("tg_code:"))
async def tg_request_code(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)
    if not order or order.buyer_id != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    if order.status == OrderStatus.COMPLETED:
        await callback.answer("Заказ уже завершён", show_alert=True)
        return
    stock = await db.get_tg_stock(order.stock_id) if order.stock_id else None
    if not stock or not stock["session_string"]:
        await callback.answer("Сессия аккаунта недоступна. Напишите в поддержку.", show_alert=True)
        return
    from bot.services import telegram_client as tg
    ok, code_or_err = await tg.get_last_login_code(stock["session_string"])
    if not ok:
        await callback.answer(f"Не удалось: {code_or_err}", show_alert=True)
        return
    await callback.message.answer(
        f"📩 Код для заказа #{order_id}:\n\n<code>{code_or_err}</code>",
        parse_mode="HTML"
    )
    await callback.answer("Код отправлен")


@router.callback_query(F.data.startswith("tg_done:"))
async def tg_complete(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[1])
    order = await db.get_order(order_id)
    if not order or order.buyer_id != callback.from_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return
    if order.status == OrderStatus.COMPLETED:
        await callback.answer("Уже завершён", show_alert=True)
        return
    await db.complete_order(order_id)
    await callback.message.edit_text(f"✅ Заказ #{order_id} завершён. Удачного использования!")
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
        f"📋 Способ связи: {'Email' if product.entry_type == EntryType.EMAIL else 'Telegram'}\n" 
        f"🔐 Код и пароль покупатель вводит самостоятельно.\n\n"
        f"Ваш баланс: {user.balance:.2f}$"
    )
    await callback.message.edit_text(text, reply_markup=confirm_buy_keyboard(product_id), parse_mode="HTML")
    sticker_id = await db.get_item_sticker("verification", product_id)
    if sticker_id:
        try:
            await callback.message.answer_sticker(sticker_id)
        except Exception:
            logger.warning("Cannot send verification sticker #%s", product_id)
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_buy:"))
async def confirm_buy(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split(":")[1])
    product = await db.get_product(product_id)
    if not product or not product.is_active:
        await callback.answer("Позиция недоступна", show_alert=True)
        return

    user = await db.get_user(callback.from_user.id)
    if not user or user.balance < product.buyer_price:
        await callback.answer(
            "Недостаточно средств. Пополните баланс и попробуйте снова.",
            show_alert=True,
        )
        return

    # На этом шаге НЕ списываем средства. Отмена безопасна.
    await state.clear()
    await state.update_data(product_id=product_id, checkout_key=secrets.token_hex(16))
    if product.entry_type == EntryType.EMAIL:
        await state.set_state(BuyStates.waiting_email)
        prompt = (
            "📧 Укажите email для связи по заказу.\n"
            "Не присылайте пароль или код — авторизацию выполняйте самостоятельно."
        )
    else:
        await state.set_state(BuyStates.waiting_phone)
        prompt = (
            "📱 Укажите контакт Telegram: @username либо номер "
            "телефона в формате +79001234567.\n\n"
            "Это способ связи, а НЕ вход в аккаунт. "
            "Не передавайте никому коды подтверждения.\n\n"
            "💳 Сумма спишется только после создания заказа. "
            "До этого «Отмена» бесплатна."
        )
    await callback.message.edit_text(prompt, reply_markup=cancel_keyboard())
    await callback.answer()


async def _finish_verification_order(message: Message, state: FSMContext, bot: Bot, contact: dict):
    data = await state.get_data()
    product_id = data.get("product_id")
    checkout_key = data.get("checkout_key")
    if not product_id or not checkout_key:
        await state.clear()
        await message.answer("Сессия покупки устарела. Вернитесь в каталог.")
        return

    try:
        order_id, error = await db.create_paid_verification_order(
            message.from_user.id, product_id, contact, checkout_key
        )
    except Exception:
        await message.answer(
            "⚠️ Не удалось оформить заказ. Повторите попытку или обратитесь в поддержку. "
            "Если заказ уже появился, проверьте «Мои покупки»."
        )
        return
    if error:
        await message.answer(f"❌ {error}\nСредства не списаны. Можете отменить оформление.")
        return

    await state.clear()
    order = await db.get_order(order_id)
    await message.answer(
        f"✅ Заказ #{order_id} создан! Списано: {order.buyer_price:.2f}$.\n\n"
        "Пока продавец не принял заказ, его можно отменить с полным возвратом.\n"
        "🔐 Коды входа, пароли и Telegram-сессии продавцу не передавайте.",
        reply_markup=verification_order_keyboard(order_id),
    )
    sellers = await db.get_users_by_role(UserRole.SELLER)
    admins = await db.get_users_by_role(UserRole.ADMIN)
    owners = await db.get_users_by_role(UserRole.OWNER)
    recipients = {u.user_id for u in sellers + admins + owners}
    notify = (
        f"🆕 <b>Новый заказ #{order_id}</b>\n"
        f"Сервис: <b>{escape(order.product_name)}</b>\n"
        f"Оплата продавцу: <b>{order.seller_price:.2f}$</b>\n"
        "Авторизацию выполняет сам покупатель. Не просите коды или пароли."
    )
    for uid in recipients:
        try:
            await bot.send_message(
                uid, notify, reply_markup=new_order_keyboard(order_id)
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("cancel_verification:"))
async def cancel_verification_order(callback: CallbackQuery):
    try:
        order_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Некорректный номер заказа.", show_alert=True)
        return
    refunded = await db.refund_pending_verification_order(callback.from_user.id, order_id)
    if refunded is None:
        await callback.answer(
            "Автовозврат недоступен: заказ уже взят в работу, завершён, "
            "отменён или принадлежит другому пользователю. Обратитесь в поддержку.",
            show_alert=True,
        )
        return
    user = await db.get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"✅ Заказ #{order_id} отменён.\n"
        f"💰 Возвращено: {refunded:.2f}$.\n"
        f"Ваш баланс: {user.balance:.2f}$."
    )
    await callback.answer("Средства возвращены")


@router.callback_query(F.data == "my_purchases")
async def my_purchases(callback: CallbackQuery):
    orders = await db.get_user_orders(callback.from_user.id, limit=20)
    verifications = [o for o in orders if o.category == "verification"]
    if not verifications:
        await callback.message.answer("Пока нет заказов на верификацию.")
        await callback.answer()
        return
    labels = {
        OrderStatus.PENDING: "⏳ Ожидает продавца",
        OrderStatus.IN_PROGRESS: "🔄 В работе",
        OrderStatus.COMPLETED: "✅ Завершён",
        OrderStatus.CANCELLED: "❌ Отменён",
    }
    text = "📦 <b>Мои верификации</b>\n\n"
    for o in verifications[:12]:
        status = labels.get(o.status, o.status.value)
        text += f"#{o.id} — {escape(o.product_name)}: {status}\n"
    await callback.message.answer(
        text,
        reply_markup=purchase_history_keyboard(
            [o for o in verifications[:12] if o.status == OrderStatus.PENDING]
        ),
    )
    await callback.answer()


@router.message(BuyStates.waiting_entry_data)
async def deprecated_legacy_checkout(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "⚠️ Старое оформление отключено. Не отправляйте коды/пароли.\n"
        "Оформите заказ заново через каталог. "
        "Если прошлая версия списала деньги, напишите в поддержку."
    )

# ──────────────────── ПРОФИЛЬ ────────────────────

@router.message(F.text.in_(menu_variants("profile")))
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
        amount = Decimal((message.text or "").replace(",", ".").strip())
        if not amount.is_finite() or amount < 1 or amount > 10000 or amount.as_tuple().exponent < -2:
            raise ValueError
    except (InvalidOperation, ValueError):
        await message.answer("Введите сумму от 1 до 10000 USDT (например: 3.50).")
        return

    user = await db.get_user(message.from_user.id)
    if not user:
        await state.clear()
        await message.answer("Сначала нажмите /start.")
        return
    reservation, error = await db.reserve_withdrawal(message.from_user.id, float(amount))
    if error:
        await message.answer(f"❌ {error}")
        return

    await state.clear()
    try:
        result = await cryptopay.transfer_to_user(
            message.from_user.id, reservation["amount"], reservation["spend_id"]
        )
    except Exception:
        logger.exception("CryptoPay withdrawal #%d not confirmed", reservation["id"])
        try:
            # If the network failed after processing, the same spend_id MUST NOT
            # be retried as a new withdrawal. Check provider before determining outcome.
            previous = await cryptopay.get_transfer_by_spend_id(reservation["spend_id"])
        except Exception:
            previous = None
        if not previous:
            await db.mark_withdrawal(reservation["id"], "review")
            await message.answer(
                f"⏳ Вывод #{reservation['id']} требует проверки. "
                "Сумма зарезервирована, чтобы не списать и не отправить её дважды. "
                "Обратитесь в поддержку с номером вывода."
            )
            return
        result = previous

    status = result.get("status", "completed")
    if status == "returned":
        await db.refund_returned_withdrawal(reservation["id"])
        await message.answer("↩️ Crypto Bot вернул перевод. Деньги вновь на балансе.")
        return
    if status not in ("completed", "pending"):
        await db.mark_withdrawal(reservation["id"], "review",
                                 result.get("transfer_id"))
        await message.answer("⏳ Неизвестный статус перевода. Поддержка проверит.")
        return
    await db.mark_withdrawal(reservation["id"],
                             "sent" if status == "completed" else "review",
                             result.get("transfer_id"))
    await message.answer(
        f"✅ Вывод #{reservation['id']} на {reservation['amount']:.2f} USDT "
        "отправлен на ваш Crypto Bot. "
        + ("Ожидается завершение перевода." if status == "pending" else "Проверьте кошелёк."),
        reply_markup=main_menu(user.role, await db.get_language(user.user_id))
    )

# ──────────────────── ПОПОЛНЕНИЕ ────────────────────

@router.message(F.text.in_(menu_variants("topup")))
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

    # Атомарное разовое зачисление: двойная кнопка не удвоит баланс.
    amount = await db.credit_paid_invoice_once(callback.from_user.id, invoice_id)
    if amount is None:
        await callback.answer("Счёт уже зачислен или недоступен", show_alert=True)
        return

    user = await db.get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"✅ Оплата подтверждена!\n\n"
        f"На баланс зачислено: <b>{amount}$</b>\n"
        f"Текущий баланс: <b>{user.balance:.2f}$</b>",
        parse_mode="HTML",
        reply_markup=back_keyboard()
    )
    await callback.answer("Баланс пополнен!")




@router.message(BuyStates.waiting_phone)
async def buy_phone(message: Message, state: FSMContext, bot: Bot):
    contact = (message.text or "").strip().replace(" ", "")
    if not (re.fullmatch(r"\+[1-9]\d{7,14}", contact) or
            re.fullmatch(r"@[A-Za-z0-9_]{5,32}", contact)):
        await message.answer(
            "Введите @username или номер в формате +79001234567."
        )
        return
    await _finish_verification_order(message, state, bot, {"contact": contact})


@router.message(BuyStates.waiting_email)
async def buy_email(message: Message, state: FSMContext, bot: Bot):
    email = (message.text or "").strip()
    if not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}", email):
        await message.answer("Введите email в корректном формате без пароля.")
        return
    await _finish_verification_order(message, state, bot, {"email": email})


@router.message(BuyStates.waiting_code)
@router.message(BuyStates.waiting_email_pass)
async def deprecated_login_step(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "⚠️ Старый запрос кода/пароля отключён. Не отправляйте данные для входа.\n"
        "Заново оформите заказ через каталог. Если предыдущая версия списала "
        "средства, обратитесь в поддержку для проверки возврата."
    )

# ──────────────────── ПОДДЕРЖКА / КАНАЛ ────────────────────

@router.message(F.text.in_(menu_variants("support")))
async def support(message: Message):
    username = await db.get_setting("support_username") or settings.SUPPORT_USERNAME
    await message.answer(
        f"🎗️ По всем вопросам пишите:\n{username}",
        reply_markup=back_keyboard()
    )


@router.message(F.text.in_(menu_variants("channel")))
async def channel(message: Message):
    url = await db.get_setting("channel_url") or settings.CHANNEL_URL
    await message.answer(
        f"🛜 Наш канал:\n{url}",
        reply_markup=back_keyboard()
    )
