# Verification Bot — Telegram бот верификаций

Бот для продажи/выполнения верификаций (Bybit, Binance и т.д.) с ролями: покупатель, продавец, админ, владелец.

## Возможности

- Каталог позиций с разными ценами для покупателя и продавца
- Оплата и пополнение через **CryptoPay** (@CryptoBot)
- Авто-вывод чеком в CryptoBot
- Заказы: все продавцы получают уведомление → кто первый принял — тот и выполняет
- Данные входа удаляются после завершения заказа
- Панель владельца/админа: позиции, продавцы, админы, рассылка, статистика, ссылки

## Быстрый старт

### 1. Клонируй / создай репозиторий на GitHub

### 2. Создай `.env` из примера

```bash
cp .env.example .env
```

Заполни:

```env
BOT_TOKEN=токен_от_BotFather
OWNER_ID=твой_telegram_id
CRYPTOPAY_TOKEN=токен_из_@CryptoTestnetBot   # /pay → создать приложение
CRYPTOPAY_TESTNET=true
SUPPORT_USERNAME=@support
CHANNEL_URL=https://t.me/your_channel
```

### 3. Локальный запуск (тест)

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

### 4. Деплой на bothost.ru

1. Зарегистрируйся на [bothost.ru](https://bothost.ru)
2. Создай бота → выбери **Telegram** + **aiogram**
3. Подключи GitHub-репозиторий
4. Укажи переменные окружения (BOT_TOKEN, OWNER_ID, CRYPTOPAY_TOKEN и т.д.)
5. Главный файл: `run.py`
6. Deploy

Bothost сам поставит зависимости из `requirements.txt` и запустит контейнер.

## Структура

```
verification-bot/
├── bot/
│   ├── main.py          # Точка входа логики
│   ├── config.py
│   ├── database/        # SQLite + модели
│   ├── handlers/        # user / seller / owner
│   ├── keyboards/
│   ├── services/        # CryptoPay
│   └── states/
├── data/                # bot.db (создаётся автоматически)
├── run.py
├── requirements.txt
└── .env.example
```

## Роли

| Роль       | Возможности                                      |
|------------|--------------------------------------------------|
| Пользователь | Каталог, профиль, пополнение, вывод            |
| Продавец   | + Мои заказы, принимать/завершать заказы         |
| Админ      | + Админ-панель (без изменения цен и добавления админов) |
| Владелец   | Полный доступ                                    |

## Важно

- На **тестовой сети** CryptoPay используй `@CryptoTestnetBot`
- Для продакшена поставь `CRYPTOPAY_TESTNET=false` и токен от `@CryptoBot`
- OWNER_ID задаётся в `.env` — этот пользователь автоматически получает роль владельца

## BotHost: fix for python-telegram-bot not installed

This project uses aiogram 3, not python-telegram-bot. BotHost generated builds may run
`python -c 'import telegram'` during build even for aiogram bots.
The compatibility dependency is included in `requirements.txt` for this check.

- GitHub repository: `vivab/VerifBot1`, branch: `main`.
- Entry point: `run.py`.
- On BotHost press Update / Redeploy after changing the repository.
- Set `BOT_TOKEN`, `OWNER_ID`, `CRYPTOPAY_TOKEN` in BotHost environment variables.
- For Telegram client functionality also set `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`.
- Keep secrets in hosting settings, not in GitHub.
- Make sure BotHost persists `/app/data` so the SQLite database survives.

If the automatically generated build still fails:
1. In bot settings, open Additional settings.
2. Enable Use custom Dockerfile.
3. Save settings and Redeploy. The Dockerfile directly runs `python run.py`
   and sets `DB_PATH=/app/data/bot.db`.

If the build succeeds but the bot is offline, inspect runtime logs for
network, config or database errors (these are independent of build errors).

## Verification payment and refund safety

- Contact details collection does not debit the buyer.
- Checkout and order creation use one database transaction and an idempotency key.
- Buyers can cancel pending verification orders for a one-time full balance refund.
- Accepted orders require support review for a refund.
- A seller can only receive one payout for any completed verification order.
- Verification orders do not ask for login codes, passwords or Telegram sessions.
  The customer completes their own authorization in the provider app.
- Older abandoned checkouts may have lost balances without linked orders.
  Since the prior bot did not keep charge records, verify those claims
  individually before manually adjusting balances.

Automated tests: `python -m unittest discover -s tests -v`.

## Anonymous customer–seller chat

- Buyer and assigned seller can chat anonymously after a seller accepts a verification order.
- Both parties get a **Chat** button for the order and **My chats** in the main menu.
- Messages arrive as Telegram bot notifications even when neither participant has a chat open.
- If delivery fails, the message is queued in SQLite and retried periodically (around 20 s).
- Chat remains available after the order is completed. Cancelled or unassigned orders do not have access.
- Only accepted verification order buyer/seller IDs are authorized; participants' Telegram usernames and IDs are not disclosed in chat notifications.
- Successfully delivered messages are purged from SQLite; undelivered message text is kept until delivery.
- Chat currently supports text only (max 1500 characters). Do not send passwords, one-time codes or Telegram sessions.

## Language and automatic translation

Choose **🌐 Language** from the menu or use `/language`.
Supported: Russian (ru), English (en), German (de), Spanish (es), Turkish (tr).
The main menu, chat labels and notifications are localized. Some older catalog and admin screens still use Russian.

To enable message translation, configure a LibreTranslate-compatible HTTPS endpoint
and optional key in BotHost environment variables:

```env
TRANSLATION_URL=https://libretranslate.com/translate
TRANSLATION_API_KEY=YOUR_SECRET_API_KEY
```

A managed endpoint commonly requires an API key, whereas a self-hosted instance may not.
The translated text is delivered in the recipient's selected language. If translation
is unavailable or not configured, the original text is delivered with a clear notice.
**Privacy:** translation may transmit message text to the chosen external translation
provider; do not send account credentials, personal identity documents, or login codes.
Do not put translation credentials in the GitHub repository.

Tests: `python -m unittest discover -s tests -v`.

## Store upgrade (five items per page, optional stickers, payouts)

- Lists of verification offers, manuals, countries, Telegram offers, seller orders, owner
  offer edit/delete, and order chats use pages of up to five item slots with arrow buttons.
- Owner/admin creates a verification, manual or Telegram offer, then sends an actual
  Telegram sticker to the bot; no manual file ID is required. Send `/skip` for no sticker.
  The sticker is displayed as a separate Telegram message on the item's detail page.
- The sticker Bot API handles normal/animated/video sticker IDs. Telegram Premium
  visual effects are not guaranteed for messages sent by a bot; owner Premium status
  does not give the bot a personal Premium subscription.
- Balances represent USDT in the application. Top-ups require verified CryptoPay invoice
  and are credited exactly once; manual and Telegram-offer purchases debit atomically.
- A purchased text manual can be re-requested without another charge by clicking Buy again.
- Crypto Bot payouts are available from the profile to every role. They use Crypto Pay
  `transfer` with a unique `spend_id`, paid to the same Telegram user who owns the balance.
  Crypto Bot must have been started by the recipient. The app must enable transfers
  in Crypto Bot -> Crypto Pay -> My Apps -> Security -> Transfers.
- A failed/uncertain payout reserves the amount and flags it for reconciliation; it
  **does not** automatically refund and retry as a new transfer, which could pay twice.
- Seller cannot send first in an old/completed verification chat; the buyer starts and
  the seller can reply. Chat messages are durable while the seller is away.

Set the usual hosting environment variables, and deploy from branch `main`.
Keep the SQLite data directory mounted and persistent on BotHost. Test withdrawals
using a funded testnet app and own Telegram accounts before enabling real payouts.
