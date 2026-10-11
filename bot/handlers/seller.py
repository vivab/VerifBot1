import json
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery

from bot.database.db import db
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


@router.message(F.text == "📋 Мои заказы")
async def my_orders(message: Message):
    user = await db.get_user(message.from_user.id)
    if not user or user.role not in (UserRole.SELLER, UserRole.ADMIN, UserRole.OWNER):
        await message.answer("Доступно только продавцам.")
        return

    orders = await db.get_seller_active_orders(user.user_id)
    if not orders:
        await message.answer("У вас нет активных заказов.", reply_markup=back_keyboard())
        return

    text = "📋 <b>Ваши активные заказы:</b>\n\n"
    for o in orders:
        text += f"#{o.id} — {o.product_name} ({o.seller_price}$)\n"

    await message.answer(text, reply_markup=my_orders_keyboard(orders), parse_mode="HTML")


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
    entry = json.loads(order.entry_data) if order.entry_data else {}

    if order.entry_type == EntryType.EMAIL:
        creds = f"📧 Email: <code>{entry.get('email')}</code>\n🔑 Пароль: <code>{entry.get('password')}</code>"
    else:
        creds = f"📱 Телефон: <code>{entry.get('phone')}</code>\n🔢 Код: <code>{entry.get('code')}</code>"

    text = (
        f"✅ Вы взяли заказ <b>#{order_id}</b>\n\n"
        f"Сервис: <b>{order.product_name}</b>\n"
        f"Оплата: <b>{order.seller_price}$</b>\n\n"
        f"<b>Данные для входа:</b>\n{creds}\n\n"
        f"После выполнения нажмите «Завершить заказ»."
    )

    await callback.message.edit_text(text, reply_markup=active_order_keyboard(order_id), parse_mode="HTML")
    await callback.answer("Заказ принят!")

    # Уведомляем покупателя
    try:
        await bot.send_message(
            order.buyer_id,
            f"📦 Ваш заказ <b>#{order_id}</b> ({order.product_name}) взят в работу продавцом.",
            parse_mode="HTML"
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

    entry = json.loads(order.entry_data) if order.entry_data else {}
    if order.entry_type == EntryType.EMAIL:
        creds = f"📧 Email: <code>{entry.get('email')}</code>\n🔑 Пароль: <code>{entry.get('password')}</code>"
    else:
        creds = f"📱 Телефон: <code>{entry.get('phone')}</code>\n🔢 Код: <code>{entry.get('code')}</code>"

    text = (
        f"📦 Заказ <b>#{order.id}</b>\n\n"
        f"Сервис: <b>{order.product_name}</b>\n"
        f"Оплата: <b>{order.seller_price}$</b>\n\n"
        f"<b>Данные:</b>\n{creds}"
    )
    await callback.message.edit_text(text, reply_markup=active_order_keyboard(order.id), parse_mode="HTML")
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

    # Завершаем (удаляет entry_data)
    await db.complete_order(order_id)

    # Начисляем продавцу
    await db.update_balance(order.seller_id, order.seller_price)
    await db.add_seller_stats(order.seller_id, order.seller_price)

    await callback.message.edit_text(
        f"✅ Заказ <b>#{order_id}</b> завершён!\n"
        f"Вам начислено <b>{order.seller_price}$</b>",
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

    # Возвращаем заказ в pending (можно снова брать)
    # Но данные уже есть, просто сбрасываем seller
    from datetime import datetime
    await db.conn.execute(
        """UPDATE orders SET seller_id = NULL, status = ?, taken_at = NULL
           WHERE id = ?""",
        (OrderStatus.PENDING.value, order_id)
    )
    await db.conn.commit()

    await callback.message.edit_text(f"❌ Вы отказались от заказа #{order_id}. Он снова доступен другим продавцам.")
    await callback.answer()

    # Можно снова разослать продавцам, но для простоты оставляем как есть
    # (продавцы могут видеть в "Мои заказы" только свои)
