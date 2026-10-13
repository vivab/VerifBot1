FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/bot.db

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && python -c "import aiogram, telegram, telethon, aiosqlite; print('Dependencies OK')"

COPY . .
RUN mkdir -p /app/data

CMD ["python", "run.py"]
