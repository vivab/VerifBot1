"""Точка входа для bothost / локального запуска."""
from bot.main import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
