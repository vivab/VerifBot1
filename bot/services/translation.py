"""Optional LibreTranslate translation. Fail open, never lose chat messages."""
import logging
from dataclasses import dataclass
import aiohttp
from bot.config import settings

logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    text: str
    translated: bool = False
    reason: str = ""


async def translate_chat(text: str, source_language: str, target_language: str):
    if source_language == target_language:
        return TranslationResult(text)
    # Configure your own or managed LibreTranslate endpoint. No secret in source code.
    if not settings.TRANSLATION_URL:
        return TranslationResult(text, False, "not_configured")
    request = {
        "q": text,
        "source": "auto",
        "target": target_language,
        "format": "text",
    }
    if settings.TRANSLATION_API_KEY:
        request["api_key"] = settings.TRANSLATION_API_KEY
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=12)
        ) as session:
            async with session.post(
                settings.TRANSLATION_URL, json=request
            ) as response:
                response.raise_for_status()
                data = await response.json()
        translation = data.get("translatedText")
        if isinstance(translation, str) and translation.strip():
            return TranslationResult(translation.strip(), True)
    except Exception as exc:
        logger.warning("Translation service failed: %s", type(exc).__name__)
    return TranslationResult(text, False, "provider_error")
