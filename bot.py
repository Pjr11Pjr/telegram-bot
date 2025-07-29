import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    PhotoSize,
    Voice,
    VideoNote,
    Video
)
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from dotenv import load_dotenv
import os
import asyncio
import re

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

# VIP пользователи (в реальном боте нужно хранить в БД)
vip_users = set()

# Регулярное выражение для обнаружения ссылок
URL_PATTERN = re.compile(r'https?://\S+')

# Словарь для хранения состояний подтверждения
confirmations = {}


def get_main_keyboard():
    """Клавиатура для основного меню"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="/find"))
    builder.add(KeyboardButton(text="/stop"))
    builder.add(KeyboardButton(text="/next"))
    builder.add(KeyboardButton(text="/vip"))
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)


def get_vip_keyboard():
    """Клавиатура с выделенной VIP-кнопкой"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="/find"))
    builder.add(KeyboardButton(text="/stop"))
    builder.add(KeyboardButton(text="/next"))
    builder.add(KeyboardButton(text="/vip"))
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)


def get_confirm_keyboard():
    """Инлайн-клавиатура для подтверждения действий"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="✅ Да",
        callback_data="confirm_next_yes"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Нет",
        callback_data="confirm_next_no"
    ))
    return builder.as_markup()


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
                reply_markup=get_main_keyboard()
            )
            await bot.send_message(
                partner_id,
                "❌ Собеседник покинул чат. Используйте /find для нового поиска.",
                reply_markup=get_main_keyboard()
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
        "/vip - информация о VIP-статусе",
        reply_markup=get_main_keyboard()
    )


@dp.message(Command("vip"))
async def vip_info(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    if user_id in vip_users:
        await message.answer(
            "🎉 У вас уже есть VIP-статус!\n\nВы можете отправлять видеосообщения и обычные видео",
            reply_markup=get_vip_keyboard()
        )
    else:
        await message.answer(
            "🔒 VIP-статус открывает дополнительные возможности:\n"
            "• Отправка видеосообщений (кружков)\n"
            "• Отправка обычных видео\n"
            "• Приоритет в поиске собеседника\n\n"
            "💰 Стоимость: 299 руб./мес\n"
            "Для покупки напишите @admin",
            reply_markup=get_vip_keyboard()
        )


@dp.message(Command("health"))
async def health_check(message: Message):
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
                reply_markup=get_main_keyboard()
            )
            await bot.send_message(
                partner_id,
                "✅ Собеседник найден! Общайтесь анонимно.",
                reply_markup=get_main_keyboard()
            )
            return

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
        reply_markup=get_main_keyboard()
    )


@dp.message(Command("next"))
async def confirm_next(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    if user_id not in active_users:
        await message.answer("❌ Вы не в чате. Используйте /find для поиска собеседника.")
        return

    logger.info(f"Пользователь {get_user_log_info(user_id)} запросил подтверждение смены собеседника")
    confirmations[user_id] = True  # Устанавливаем флаг ожидания подтверждения

    await message.answer(
        "⚠️ Вы уверены, что хотите сменить собеседника?",
        reply_markup=get_confirm_keyboard()
    )


@dp.callback_query(lambda c: c.data in ["confirm_next_yes", "confirm_next_no"])
async def process_confirmation(callback_query):
    user_id = callback_query.from_user.id
    await bot.answer_callback_query(callback_query.id)

    if callback_query.data == "confirm_next_yes":
        if user_id in confirmations:
            del confirmations[user_id]
            logger.info(f"Пользователь {get_user_log_info(user_id)} подтвердил смену собеседника")

            partner_id = await stop_chat(user_id, initiator=True)

            if user_id not in waiting_users:
                waiting_users.append(user_id)

            await bot.send_message(
                user_id,
                "🔄 Ищем нового собеседника...",
                reply_markup=get_main_keyboard()
            )
            await find_partner(Message(chat=callback_query.message.chat, from_user=callback_query.from_user))
    else:
        if user_id in confirmations:
            del confirmations[user_id]
        logger.info(f"Пользователь {get_user_log_info(user_id)} отменил смену собеседника")
        await bot.send_message(
            user_id,
            "✅ Остаемся с текущим собеседником.",
            reply_markup=get_main_keyboard()
        )


@dp.message(F.photo)
async def handle_photo(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        try:
            await bot.send_photo(
                partner_id,
                message.photo[-1].file_id,
                caption="📷 Фото от собеседника",
                reply_markup=get_main_keyboard()
            )
            logger.info(f"Фото от {get_user_log_info(user_id)} отправлено {get_user_log_info(partner_id)}")
        except Exception as e:
            logger.error(f"Ошибка отправки фото: {e}")
            await stop_chat(user_id, initiator=False)
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_main_keyboard()
        )


@dp.message(F.voice)
async def handle_voice(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        try:
            await bot.send_voice(
                partner_id,
                message.voice.file_id,
                caption="🎤 Голосовое от собеседника",
                reply_markup=get_main_keyboard()
            )
            logger.info(f"Голосовое от {get_user_log_info(user_id)} отправлено {get_user_log_info(partner_id)}")
        except Exception as e:
            logger.error(f"Ошибка отправки голосового: {e}")
            await stop_chat(user_id, initiator=False)
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_main_keyboard()
        )


@dp.message(F.video_note)
async def handle_video_note(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    if user_id not in vip_users:
        await message.answer(
            "🔒 Отправка видеосообщений доступна только VIP-пользователям\n"
            "Используйте команду /vip для получения информации",
            reply_markup=get_vip_keyboard()
        )
        return

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        try:
            await bot.send_video_note(
                partner_id,
                message.video_note.file_id,
                reply_markup=get_main_keyboard()
            )
            logger.info(f"Видеосообщение от {get_user_log_info(user_id)} отправлено {get_user_log_info(partner_id)}")
        except Exception as e:
            logger.error(f"Ошибка отправки видеосообщения: {e}")
            await stop_chat(user_id, initiator=False)
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_main_keyboard()
        )


@dp.message(F.video)
async def handle_video(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    if user_id not in vip_users:
        await message.answer(
            "🔒 Отправка обычных видео доступна только VIP-пользователям\n"
            "Используйте команду /vip для получения информации",
            reply_markup=get_vip_keyboard()
        )
        return

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        try:
            await bot.send_video(
                partner_id,
                message.video.file_id,
                caption="🎥 Видео от собеседника",
                reply_markup=get_main_keyboard()
            )
            logger.info(f"Видео от {get_user_log_info(user_id)} отправлено {get_user_log_info(partner_id)}")
        except Exception as e:
            logger.error(f"Ошибка отправки видео: {e}")
            await stop_chat(user_id, initiator=False)
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_main_keyboard()
        )


@dp.message(F.text)
async def send_message(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id
    text = message.text

    # Проверка на ссылки
    if URL_PATTERN.search(text):
        await message.answer("⚠️ Отправка ссылок запрещена")
        logger.warning(f"Попытка отправить ссылку от {get_user_log_info(user_id)}")
        return

    log_text = text if len(text) <= 50 else f"{text[:50]}..."
    logger.info(f"Сообщение от {get_user_log_info(user_id)}: {log_text}")

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        try:
            await bot.send_message(
                partner_id,
                f"👤: {text}",
                reply_markup=get_main_keyboard()
            )
            logger.debug(f"Сообщение переслано {get_user_log_info(user_id)} → {get_user_log_info(partner_id)}")
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            await stop_chat(user_id, initiator=False)
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_main_keyboard()
        )


async def main():
    restart_delay = 5
    while True:
        try:
            logger.info("Запуск бота...")
            await dp.start_polling(bot, close_bot_session=True)
        except Exception as e:
            logger.error(f"Ошибка: {e}. Перезапуск через {restart_delay} сек...")
            await asyncio.sleep(restart_delay)
            restart_delay = min(restart_delay * 2, 60)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен по запросу пользователя")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")