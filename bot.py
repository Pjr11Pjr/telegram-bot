import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
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
        logging.FileHandler("bot.log", encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


# Создаем клавиатуру команд
def get_command_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/find"), KeyboardButton(text="/stop"), KeyboardButton(text="/next")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


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
active_users = {}  # {user_id: {"partner_id": int, "username": str}}
waiting_users = []  # Очередь ожидания
user_data_cache = {}  # {user_id: {"username": str, "first_name": str}}


async def save_user_info(user):
    """Сохраняет информацию о пользователе в кеш"""
    user_data_cache[user.id] = {
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name
    }


def get_user_log_info(user_id):
    """Возвращает строку для логирования с информацией о пользователе"""
    user = user_data_cache.get(user_id, {})
    username = f"@{user.get('username')}" if user.get('username') else "без username"
    first_name = user.get('first_name', 'неизвестно')
    last_name = f" {user.get('last_name')}" if user.get('last_name') else ""
    return f"{user_id} ({first_name}{last_name} {username})"


async def stop_chat(user_id: int, initiator: bool = True):
    """Общая функция для завершения чата"""
    if user_id in active_users:
        partner_info = active_users[user_id]
        partner_id = partner_info["partner_id"]

        del active_users[user_id]
        del active_users[partner_id]

        logger.info(f"Чат между {get_user_log_info(user_id)} и {get_user_log_info(partner_id)} завершен")
        if initiator:
            await bot.send_message(
                user_id,
                "❌ Чат завершён. Ищем нового собеседника...",
                reply_markup=get_command_keyboard()
            )
            await bot.send_message(
                partner_id,
                "❌ Собеседник покинул чат. Используйте /find для нового поиска.",
                reply_markup=get_command_keyboard()
            )
        return partner_id
    return None


@dp.message(Command("start"))
async def start(message: Message):
    user = message.from_user
    await save_user_info(user)
    logger.info(f"Пользователь {get_user_log_info(user.id)} запустил бота")
    await message.reply(
        "👋 Привет! Это анонимный чат-бот.\n"
        "Доступные команды:\n"
        "/find - найти собеседника\n"
        "/stop - выйти из чата\n"
        "/next - сменить собеседника\n"
        "/health - проверка работы бота",
        reply_markup=get_command_keyboard()
    )


@dp.message(Command("health"))
async def health_check(message: Message):
    """Эндпоинт для проверки работы на Render"""
    await message.answer("✅ Бот активен и работает")
    logger.info(f"Health check от {get_user_log_info(message.from_user.id)}")


@dp.message(Command("find"))
async def find_partner(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id
    logger.info(f"Пользователь {get_user_log_info(user_id)} ищет собеседника")

    if user_id in active_users:
        await message.reply("⚠️ Вы уже в чате! Используйте /stop чтобы выйти.")
        return

    # Проверяем очередь на наличие партнера
    for i, partner_id in enumerate(waiting_users):
        if partner_id != user_id:
            # Нашли подходящего партнера
            waiting_users.pop(i)
            active_users[user_id] = {
                "partner_id": partner_id,
                "username": user.username
            }
            active_users[partner_id] = {
                "partner_id": user_id,
                "username": user_data_cache.get(partner_id, {}).get("username")
            }

            logger.info(f"Создан чат между {get_user_log_info(user_id)} и {get_user_log_info(partner_id)}")
            await bot.send_message(
                user_id,
                "✅ Собеседник найден! Общайтесь анонимно.",
                reply_markup=ReplyKeyboardRemove()
            )
            await bot.send_message(
                partner_id,
                "✅ Собеседник найден! Общайтесь анонимно.",
                reply_markup=ReplyKeyboardRemove()
            )
            return

    # Если партнера нет, добавляем в очередь
    if user_id not in waiting_users:
        waiting_users.append(user_id)
        logger.info(
            f"Пользователь {get_user_log_info(user_id)} добавлен в очередь. Размер очереди: {len(waiting_users)}")
        await message.reply("🔍 Ищем собеседника... Ожидайте.")


@dp.message(Command("stop"))
async def stop_chat_handler(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id
    logger.info(f"Пользователь {get_user_log_info(user_id)} хочет выйти из чата")
    await stop_chat(user_id)
    await message.answer(
        "🗑️ Чат завершён. Для нового общения используйте /find",
        reply_markup=get_command_keyboard()
    )


@dp.message(Command("next"))
async def next_partner(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id
    logger.info(f"Пользователь {get_user_log_info(user_id)} запросил нового собеседника")

    # Завершаем текущий чат
    partner_id = await stop_chat(user_id)

    # Добавляем в очередь и сразу ищем нового
    if user_id not in waiting_users:
        waiting_users.append(user_id)

    await message.answer("🔄 Ищем нового собеседника...")
    await find_partner(message)


@dp.message(F.text)
async def send_message(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id
    text = message.text

    # Логируем с обрезанием длинных сообщений
    log_text = text if len(text) <= 50 else f"{text[:50]}..."
    logger.info(f"Сообщение от {get_user_log_info(user_id)}: {log_text}")

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        try:
            await bot.send_message(partner_id, f"👤: {text}")
            logger.debug(f"Сообщение переслано {get_user_log_info(user_id)} → {get_user_log_info(partner_id)}")
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            await stop_chat(user_id, initiator=False)
    else:
        await message.reply("❌ Вы не в чате. Используйте /find для поиска собеседника.")


async def main():
    """Основной цикл с перезапуском при ошибках"""
    restart_delay = 5
    while True:
        try:
            logger.info("Запуск бота...")
            await dp.start_polling(bot, close_bot_session=True)
        except Exception as e:
            logger.error(f"Ошибка: {e}. Перезапуск через {restart_delay} сек...")
            await asyncio.sleep(restart_delay)
            restart_delay = min(restart_delay * 2, 60)  # Экспоненциальная задержка


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен по запросу пользователя")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")