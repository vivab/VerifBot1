from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    BOT_TOKEN: str
    OWNER_ID: int

    CRYPTOPAY_TOKEN: str
    CRYPTOPAY_TESTNET: bool = True

    # Дефолтные значения (можно менять через панель владельца)
    SUPPORT_USERNAME: str = "@support"
    CHANNEL_URL: str = "https://t.me/channel"

    # База данных
    DB_PATH: str = "data/bot.db"


settings = Settings()
