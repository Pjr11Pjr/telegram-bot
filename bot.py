import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from dotenv import load_dotenv
import os
import asyncio

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log")  # Логи будут сохраняться в файл
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not API_TOKEN:
    logger.error("Токен бота не найден! Проверьте файл .env")
    raise ValueError("Токен бота не найден! Проверьте файл .env")

# Инициализация бота без прокси
bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# Словарь для хранения пар пользователей
active_users = {}
waiting_users = []


@dp.message(Command("start"))
async def start(message: Message):
    logger.info(f"Пользователь {message.from_user.id} запустил бота")
    await message.reply("👋 Привет! Это анонимный чат-бот. Напиши /find, чтобы найти собеседника.")


@dp.message(Command("find"))
async def find_partner(message: Message):
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} ищет собеседника")

    if user_id in active_users:
        logger.debug(f"Пользователь {user_id} уже в чате")
        await message.reply("❌ Ты уже в чате! Напиши /stop, чтобы выйти.")
        return

    if waiting_users and waiting_users[0] != user_id:
        partner_id = waiting_users.pop(0)
        active_users[user_id] = partner_id
        active_users[partner_id] = user_id

        logger.info(f"Создан чат между {user_id} и {partner_id}")
        await bot.send_message(user_id, "✅ Собеседник найден! Пиши сообщение — оно отправится анонимно.")
        await bot.send_message(partner_id, "✅ Собеседник найден! Пиши сообщение — оно отправится анонимно.")
    else:
        if user_id not in waiting_users:
            waiting_users.append(user_id)
            logger.info(f"Пользователь {user_id} добавлен в очередь ожидания")
        await message.reply("🔍 Ищем собеседника...")


@dp.message(Command("stop"))
async def stop_chat(message: Message):
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} хочет выйти из чата")

    if user_id in active_users:
        partner_id = active_users[user_id]
        del active_users[user_id]
        del active_users[partner_id]

        logger.info(f"Чат между {user_id} и {partner_id} завершен")
        await bot.send_message(user_id, "❌ Чат завершён. Напиши /find, чтобы начать новый.")
        await bot.send_message(partner_id, "❌ Собеседник покинул чат. Напиши /find, чтобы найти нового.")
    else:
        logger.debug(f"Пользователь {user_id} не в чате")
        await message.reply("❌ Ты не в чате. Напиши /find, чтобы начать.")


@dp.message(F.text)
async def send_message(message: Message):
    user_id = message.from_user.id
    logger.debug(f"Сообщение от {user_id}: {message.text}")

    if user_id in active_users:
        partner_id = active_users[user_id]
        logger.info(f"Пересылка сообщения от {user_id} к {partner_id}")
        await bot.send_message(partner_id, f"👤: {message.text}")
    else:
        logger.debug(f"Пользователь {user_id} не в чате")
        await message.reply("❌ Напиши /find, чтобы найти собеседника.")


async def main():
    logger.info("Запуск бота...")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка в работе бота: {e}")
    finally:
        logger.info("Бот остановлен")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен по запросу пользователя")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")