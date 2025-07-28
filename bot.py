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
        logging.FileHandler("bot.log")
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not API_TOKEN:
    logger.error("Токен бота не найден! Проверьте файл .env")
    raise ValueError("Токен бота не найден! Проверьте файл .env")

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# Словари для хранения данных
active_users = {}  # {user_id: partner_id}
waiting_users = []  # Очередь ожидания
user_states = {}  # Дополнительный словарь состояний


async def stop_chat(user_id: int):
    """Общая функция для завершения чата"""
    if user_id in active_users:
        partner_id = active_users[user_id]
        del active_users[user_id]
        del active_users[partner_id]

        logger.info(f"Чат между {user_id} и {partner_id} завершен")
        await bot.send_message(user_id, "❌ Чат завершён. Используйте /find для нового поиска.")
        await bot.send_message(partner_id, "❌ Собеседник покинул чат. Используйте /find для нового поиска.")
        return partner_id
    return None


@dp.message(Command("start"))
async def start(message: Message):
    logger.info(f"Пользователь {message.from_user.id} запустил бота")
    await message.reply(
        "👋 Привет! Это анонимный чат-бот.\n"
        "Доступные команды:\n"
        "/find - найти собеседника\n"
        "/stop - выйти из чата\n"
        "/next - сменить собеседника"
    )


@dp.message(Command("find"))
async def find_partner(message: Message):
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} ищет собеседника")

    if user_id in active_users:
        await message.reply("❌ Вы уже в чате! Используйте /stop чтобы выйти.")
        return

    # Проверяем очередь на наличие партнера
    for i, partner_id in enumerate(waiting_users):
        if partner_id != user_id:
            # Нашли подходящего партнера
            waiting_users.pop(i)
            active_users[user_id] = partner_id
            active_users[partner_id] = user_id

            logger.info(f"Создан чат между {user_id} и {partner_id}")
            await bot.send_message(user_id, "✅ Собеседник найден! Общайтесь анонимно.")
            await bot.send_message(partner_id, "✅ Собеседник найден! Общайтесь анонимно.")
            return

    # Если партнера нет, добавляем в очередь
    if user_id not in waiting_users:
        waiting_users.append(user_id)
        logger.info(f"Пользователь {user_id} добавлен в очередь. Размер очереди: {len(waiting_users)}")
        await message.reply("🔍 Ищем собеседника... Ожидайте.")


@dp.message(Command("stop"))
async def stop_chat_handler(message: Message):
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} хочет выйти из чата")
    await stop_chat(user_id)


@dp.message(Command("next"))
async def next_partner(message: Message):
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил нового собеседника")

    # Завершаем текущий чат
    partner_id = await stop_chat(user_id)

    # Ищем нового собеседника
    if partner_id is None and user_id not in waiting_users:
        waiting_users.append(user_id)

    await find_partner(message)


@dp.message(F.text)
async def send_message(message: Message):
    user_id = message.from_user.id

    if user_id in active_users:
        partner_id = active_users[user_id]
        logger.info(f"Пересылка сообщения от {user_id} к {partner_id}")
        try:
            await bot.send_message(partner_id, f"👤: {message.text}")
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}")
            await stop_chat(user_id)
    else:
        await message.reply("❌ Вы не в чате. Используйте /find для поиска собеседника.")


async def on_shutdown():
    """Обработчик корректного завершения работы"""
    logger.info("Завершение работы бота...")
    await bot.session.close()


async def main():
    logger.info("Запуск бота...")
    try:
        await dp.start_polling(bot, close_bot_session=True, on_shutdown=on_shutdown)
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