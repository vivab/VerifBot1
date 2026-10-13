"""
Работа с Telegram-аккаунтами через Telethon.
Нужны TELEGRAM_API_ID и TELEGRAM_API_HASH с https://my.telegram.org
"""
import logging
import asyncio
from typing import Optional, Tuple
from datetime import datetime, timedelta

from bot.config import settings

logger = logging.getLogger(__name__)

# Активные клиенты: order_id / stock_id -> TelegramClient
_clients: dict = {}


def _api_ok() -> bool:
    return bool(settings.TELEGRAM_API_ID and settings.TELEGRAM_API_HASH)


async def login_with_phone(phone: str) -> Tuple[bool, str]:
    """
    Начинает вход по номеру. Возвращает (ok, message).
    Код нужно будет подтвердить через confirm_code.
    """
    if not _api_ok():
        return False, "TELEGRAM_API_ID / TELEGRAM_API_HASH не заданы на хосте"

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(), settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH)
    await client.connect()
    try:
        await client.send_code_request(phone)
        _clients[f"phone:{phone}"] = client
        return True, "Код отправлен в Telegram на этот номер"
    except Exception as e:
        await client.disconnect()
        return False, str(e)


async def confirm_code(phone: str, code: str, password: str = None) -> Tuple[bool, str, Optional[str]]:
    """
    Подтверждает код. Возвращает (ok, message, session_string).
    """
    key = f"phone:{phone}"
    client = _clients.get(key)
    if not client:
        return False, "Сессия не найдена, запросите код заново", None

    try:
        from telethon.errors import SessionPasswordNeededError
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        if not password:
            return False, "Нужен облачный пароль 2FA. Отправьте пароль.", None
        await client.sign_in(password=password)
    except Exception as e:
        return False, str(e), None

    session_str = client.session.save()
    _clients[key] = client  # оставляем подключённым
    return True, "Вход выполнен", session_str


async def login_with_session(session_string: str) -> Tuple[bool, str, Optional[object]]:
    """Вход по string session. Возвращает (ok, msg, client)."""
    if not _api_ok():
        return False, "API_ID/HASH не заданы", None

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(session_string), settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return False, "Сессия невалидна", None
        me = await client.get_me()
        return True, f"OK @{me.username or me.id}", client
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return False, str(e), None


async def get_last_login_code(session_string: str) -> Tuple[bool, str]:
    """
    Ищет последний код входа в сообщениях от Telegram (777000).
    """
    ok, msg, client = await login_with_session(session_string)
    if not ok or not client:
        return False, msg

    try:
        # Служебный аккаунт Telegram
        codes = []
        async for message in client.iter_messages(777000, limit=10):
            if message.text:
                codes.append(message.text)
        await client.disconnect()
        if not codes:
            return False, "Кодов не найдено. Попробуйте запросить код входа ещё раз в приложении."
        return True, codes[0]
    except Exception as e:
        try:
            await client.disconnect()
        except Exception:
            pass
        return False, str(e)


async def check_session_alive(session_string: str) -> Tuple[bool, str]:
    ok, msg, client = await login_with_session(session_string)
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
    return ok, msg


async def disconnect_phone(phone: str):
    key = f"phone:{phone}"
    client = _clients.pop(key, None)
    if client:
        try:
            await client.disconnect()
        except Exception:
            pass
