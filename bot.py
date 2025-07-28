import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession  # Добавьте этот импорт
from dotenv import load_dotenv
import os
import asyncio

load_dotenv()
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not API_TOKEN:
    raise ValueError("Токен бота не найден! Проверьте файл .env")

# Настройка прокси (примеры, попробуйте разные)
PROXY_URLS = [
    "http://103.169.142.235:80",  # Пример прокси 1
    "http://156.225.72.46:80", # Пример прокси 2
    "http://185.162.229.161:80"  # Пример прокси 3
]

for proxy_url in PROXY_URLS:
    try:
        session = AiohttpSession(proxy=proxy_url)
        logging.info(f"Пробуем прокси: {proxy_url}")
        break
    except Exception as e:
        logging.warning(f"Прокси {proxy_url} не работает: {e}")
else:
    raise ConnectionError("Не удалось подключиться ни к одному прокси")

logging.basicConfig(level=logging.INFO)
bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML"),
    session=session
)
dp = Dispatcher()


# Словарь для хранения пар пользователей
active_users = {}
waiting_users = []

@dp.message(Command("start"))
async def start(message: Message):
    await message.reply("👋 Привет! Это анонимный чат-бот. Напиши /find, чтобы найти собеседника.")

@dp.message(Command("find"))
async def find_partner(message: Message):
    user_id = message.from_user.id

    if user_id in active_users:
        await message.reply("❌ Ты уже в чате! Напиши /stop, чтобы выйти.")
        return

    if waiting_users and waiting_users[0] != user_id:
        partner_id = waiting_users.pop(0)
        active_users[user_id] = partner_id
        active_users[partner_id] = user_id

        await bot.send_message(user_id, "✅ Собеседник найден! Пиши сообщение — оно отправится анонимно.")
        await bot.send_message(partner_id, "✅ Собеседник найден! Пиши сообщение — оно отправится анонимно.")
    else:
        if user_id not in waiting_users:
            waiting_users.append(user_id)
        await message.reply("🔍 Ищем собеседника...")

@dp.message(Command("stop"))
async def stop_chat(message: Message):
    user_id = message.from_user.id

    if user_id in active_users:
        partner_id = active_users[user_id]
        del active_users[user_id]
        del active_users[partner_id]

        await bot.send_message(user_id, "❌ Чат завершён. Напиши /find, чтобы начать новый.")
        await bot.send_message(partner_id, "❌ Собеседник покинул чат. Напиши /find, чтобы найти нового.")
    else:
        await message.reply("❌ Ты не в чате. Напиши /find, чтобы начать.")

@dp.message(F.text)
async def send_message(message: Message):
    user_id = message.from_user.id

    if user_id in active_users:
        partner_id = active_users[user_id]
        await bot.send_message(partner_id, f"👤: {message.text}")
    else:
        await message.reply("❌ Напиши /find, чтобы найти собеседника.")

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())