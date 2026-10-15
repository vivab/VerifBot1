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
