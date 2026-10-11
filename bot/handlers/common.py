from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from bot.database.db import db
from bot.database.models import UserRole
from bot.keyboards.user_kb import main_menu
from bot.config import settings

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = await db.get_user(message.from_user.id)

    if not user:
        user = await db.add_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name or "User",
        )
        # Если это владелец — уже стоит роль OWNER из _init_defaults
        if message.from_user.id == settings.OWNER_ID:
            await db.update_user_role(message.from_user.id, UserRole.OWNER)
            user = await db.get_user(message.from_user.id)

    text = (
        f"👋 Привет, <b>{message.from_user.first_name}</b>!\n\n"
        "Добро пожаловать в сервис верификаций.\n"
        "Выберите действие в меню ниже."
    )
    await message.answer(text, reply_markup=main_menu(user.role), parse_mode="HTML")


@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db.get_user(callback.from_user.id)
    await callback.message.delete()
    await callback.message.answer(
        "Главное меню:",
        reply_markup=main_menu(user.role if user else UserRole.USER)
    )
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cancel_action(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db.get_user(callback.from_user.id)
    await callback.message.edit_text("❌ Действие отменено.")
    await callback.message.answer(
        "Главное меню:",
        reply_markup=main_menu(user.role if user else UserRole.USER)
    )
    await callback.answer()
