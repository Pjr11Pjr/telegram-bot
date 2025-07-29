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
    Video,
    CallbackQuery
)
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from dotenv import load_dotenv
import os
import asyncio
import re
import signal

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

# Словари для хранения данных
active_users = {}  # {user_id: {"partner_id": int, "username": str}}
waiting_users = []  # Очередь ожидания
user_data_cache = {}  # {user_id: {"username": str, "first_name": str}}
menu_states = {}  # {user_id: bool} - открыто ли меню у пользователя


def get_menu_keyboard():
    """Клавиатура с кнопкой меню"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="📱 Меню"))
    return builder.as_markup(resize_keyboard=True)


def get_main_keyboard():
    """Основная клавиатура"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="/find"))
    builder.add(KeyboardButton(text="/stop"))
    builder.add(KeyboardButton(text="/next"))
    builder.add(KeyboardButton(text="/vip"))
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)


def get_vip_keyboard():
    """VIP клавиатура"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="/find"))
    builder.add(KeyboardButton(text="/stop"))
    builder.add(KeyboardButton(text="/next"))
    builder.add(KeyboardButton(text="/vip"))
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)


def get_confirm_keyboard(action: str):
    """Клавиатура подтверждения"""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="✅ Да",
        callback_data=f"confirm_{action}_yes"
    ))
    builder.add(InlineKeyboardButton(
        text="❌ Нет",
        callback_data=f"confirm_{action}_no"
    ))
    return builder.as_markup()


# Загрузка токена
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


async def save_user_info(user):
    """Сохранение информации о пользователе"""
    user_data_cache[user.id] = {
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name
    }


def get_user_log_info(user_id):
    """Форматирование информации о пользователе для логов"""
    user = user_data_cache.get(user_id, {})
    username = f"@{user.get('username')}" if user.get('username') else "без username"
    first_name = user.get('first_name', 'неизвестно')
    last_name = f" {user.get('last_name')}" if user.get('last_name') else ""
    return f"{user_id} ({first_name}{last_name} {username})"


async def stop_chat(user_id: int, initiator: bool = True):
    """Завершение чата"""
    if user_id in active_users:
        partner_info = active_users[user_id]
        partner_id = partner_info["partner_id"]

        # Удаляем информацию о чате
        del active_users[user_id]
        if partner_id in active_users:
            del active_users[partner_id]

        # Закрываем меню у обоих пользователей
        menu_states.pop(user_id, None)
        menu_states.pop(partner_id, None)

        logger.info(f"Чат между {get_user_log_info(user_id)} и {get_user_log_info(partner_id)} завершен")

        if initiator:
            await bot.send_message(
                user_id,
                "❌ Чат завершён. Ищем нового собеседника...",
                reply_markup=get_menu_keyboard()
            )
            await bot.send_message(
                partner_id,
                "❌ Собеседник покинул чат. Используйте /find для нового поиска.",
                reply_markup=get_menu_keyboard()
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
        "/vip - информация о VIP-статусе\n\n"
        "Для открытия меню нажмите кнопку '📱 Меню'",
        reply_markup=get_menu_keyboard()
    )


@dp.message(F.text == "📱 Меню")
async def show_menu(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id
    menu_states[user_id] = True

    if user_id in vip_users:
        await message.answer("Меню:", reply_markup=get_vip_keyboard())
    else:
        await message.answer("Меню:", reply_markup=get_main_keyboard())


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
                "✅ Собеседник найден! Общайтесь анонимно.\n"
                "Для открытия меню нажмите кнопку '📱 Меню'",
                reply_markup=get_menu_keyboard()
            )
            await bot.send_message(
                partner_id,
                "✅ Собеседник найден! Общайтесь анонимно.\n"
                "Для открытия меню нажмите кнопку '📱 Меню'",
                reply_markup=get_menu_keyboard()
            )
            return

    if user_id not in waiting_users:
        waiting_users.append(user_id)
        logger.info(
            f"Пользователь {get_user_log_info(user_id)} добавлен в очередь. Размер очереди: {len(waiting_users)}")
        await message.reply("🔍 Ищем собеседника... Ожидайте.", reply_markup=get_menu_keyboard())


@dp.message(Command("stop"))
async def stop_chat_handler(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id
    logger.info(f"Пользователь {get_user_log_info(user_id)} хочет выйти из чата")

    if user_id not in active_users:
        await message.answer("❌ Вы не в чате. Используйте /find для поиска собеседника.")
        return

    await message.answer(
        "⚠️ Вы уверены, что хотите завершить чат?",
        reply_markup=get_confirm_keyboard("stop")
    )


@dp.message(Command("next"))
async def next_partner(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    if user_id not in active_users:
        await message.answer("❌ Вы не в чате. Используйте /find для поиска собеседника.")
        return

    logger.info(f"Пользователь {get_user_log_info(user_id)} запросил подтверждение смены собеседника")
    await message.answer(
        "⚠️ Вы уверены, что хотите сменить собеседника?",
        reply_markup=get_confirm_keyboard("next")
    )


@dp.callback_query(lambda c: c.data.startswith("confirm_"))
async def process_confirmation(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    action = callback_query.data.split("_")[1]
    response = callback_query.data.split("_")[2]

    await bot.answer_callback_query(callback_query.id)

    if response == "yes":
        if action == "next":
            logger.info(f"Пользователь {get_user_log_info(user_id)} подтвердил смену собеседника")
            partner_id = await stop_chat(user_id, initiator=True)

            if user_id not in waiting_users:
                waiting_users.append(user_id)

            await bot.send_message(
                user_id,
                "🔄 Ищем нового собеседника...",
                reply_markup=get_menu_keyboard()
            )
            await find_partner(Message(chat=callback_query.message.chat, from_user=callback_query.from_user))

        elif action == "stop":
            logger.info(f"Пользователь {get_user_log_info(user_id)} подтвердил выход из чата")
            await stop_chat(user_id)
            await bot.send_message(
                user_id,
                "🗑️ Чат завершён. Для нового общения используйте /find",
                reply_markup=get_menu_keyboard()
            )
    else:
        logger.info(f"Пользователь {get_user_log_info(user_id)} отменил действие: {action}")
        await bot.send_message(
            user_id,
            f"❌ Действие отменено. Продолжаем общение.",
            reply_markup=get_menu_keyboard()
        )


async def forward_message(user_id: int, partner_id: int, content: str, content_type: str):
    """Универсальная функция пересылки сообщений"""
    try:
        if content_type == "text":
            await bot.send_message(
                partner_id,
                f"👤: {content}",
                reply_markup=get_menu_keyboard()
            )
        elif content_type == "photo":
            await bot.send_photo(
                partner_id,
                content,
                caption="📷 Фото от собеседника",
                reply_markup=get_menu_keyboard()
            )
        elif content_type == "voice":
            await bot.send_voice(
                partner_id,
                content,
                caption="🎤 Голосовое от собеседника",
                reply_markup=get_menu_keyboard()
            )
        elif content_type == "video_note":
            await bot.send_video_note(
                partner_id,
                content,
                reply_markup=get_menu_keyboard()
            )
        elif content_type == "video":
            await bot.send_video(
                partner_id,
                content,
                caption="🎥 Видео от собеседника",
                reply_markup=get_menu_keyboard()
            )

        logger.info(
            f"{content_type.capitalize()} от {get_user_log_info(user_id)} отправлено {get_user_log_info(partner_id)}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки {content_type}: {e}")
        await stop_chat(user_id, initiator=False)
        return False


@dp.message(F.photo)
async def handle_photo(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        await forward_message(user_id, partner_id, message.photo[-1].file_id, "photo")
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_menu_keyboard()
        )


@dp.message(F.voice)
async def handle_voice(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        await forward_message(user_id, partner_id, message.voice.file_id, "voice")
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_menu_keyboard()
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
            reply_markup=get_menu_keyboard()
        )
        return

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        await forward_message(user_id, partner_id, message.video_note.file_id, "video_note")
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_menu_keyboard()
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
            reply_markup=get_menu_keyboard()
        )
        return

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        await forward_message(user_id, partner_id, message.video.file_id, "video")
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_menu_keyboard()
        )


@dp.message(F.text)
async def send_message(message: Message):
    user = message.from_user
    await save_user_info(user)
    user_id = user.id
    text = message.text

    # Обработка команды меню
    if text == "📱 Меню":
        menu_states[user_id] = True
        if user_id in vip_users:
            await message.answer("Меню:", reply_markup=get_vip_keyboard())
        else:
            await message.answer("Меню:", reply_markup=get_main_keyboard())
        return

    # Проверка на ссылки
    if URL_PATTERN.search(text):
        await message.answer("⚠️ Отправка ссылок запрещена")
        logger.warning(f"Попытка отправить ссылку от {get_user_log_info(user_id)}")
        return

    log_text = text if len(text) <= 50 else f"{text[:50]}..."
    logger.info(f"Сообщение от {get_user_log_info(user_id)}: {log_text}")

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        await forward_message(user_id, partner_id, text, "text")
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_menu_keyboard()
        )


async def on_shutdown():
    """Обработчик завершения работы"""
    logger.info("Завершение работы бота...")
    # Закрываем все активные чаты
    for user_id in list(active_users.keys()):
        await stop_chat(user_id, initiator=False)
    await bot.session.close()


async def main():
    # Обработка сигналов завершения
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(
        signal.SIGTERM,
        lambda: asyncio.create_task(on_shutdown())
    )

    restart_delay = 5
    max_restart_delay = 60
    while True:
        try:
            logger.info("Запуск бота...")
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot, close_bot_session=True)
        except Exception as e:
            logger.error(f"Ошибка: {e}. Перезапуск через {restart_delay} сек...")
            await asyncio.sleep(restart_delay)
            restart_delay = min(restart_delay * 1.5, max_restart_delay)
            # Принудительно закрываем сессию перед перезапуском
            try:
                await bot.session.close()
            except:
                pass


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен по запросу пользователя")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")