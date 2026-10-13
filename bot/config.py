from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    BOT_TOKEN: str
    OWNER_ID: int

    CRYPTOPAY_TOKEN: str
    CRYPTOPAY_TESTNET: bool = False

    SUPPORT_USERNAME: str = "@support"
    CHANNEL_URL: str = "https://t.me/channel"

    # Telegram Client API (my.telegram.org) — для входа в аккаунты
    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = ""

    DB_PATH: str = "data/bot.db"

    # Авто-завершение заказа TG-аккаунта (часы)
    TG_ORDER_HOURS: int = 3


settings = Settings()
