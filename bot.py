import logging
from flask import Flask
from threading import Thread
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    PhotoSize,
    Voice,
    VideoNote,
    Video
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
from aiogram.utils.executor import start_webhook
from dotenv import load_dotenv
import os
import asyncio
import re
import signal
import uuid
from typing import Dict, List, Set, Optional

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

# Конфигурация
ADMIN_ID = 7618960051  # ID администратора
VIP_PRICE = "299 руб./мес"  # Стоимость VIP статуса
BOT_USERNAME = "AnonimChatByXBot"  # Юзернейм бота без @
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', '')}{WEBHOOK_PATH}"

# Инициализация Flask
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return "Bot is running", 200

# Хранилища данных
vip_users: Set[int] = set()
active_users: Dict[int, Dict[str, Optional[int | str]]] = {}  # {user_id: {"partner_id": int, "username": str}}
waiting_users: List[int] = []  # Очередь ожидания
user_data_cache: Dict[int, Dict[str, Optional[str]]] = {}  # {user_id: {"username": str, "first_name": str}}
duo_links: Dict[str, int] = {}  # {link_id: creator_id}

# Регулярное выражение для обнаружения ссылок
URL_PATTERN = re.compile(r'https?://\S+')

# Загрузка токена
load_dotenv()
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not API_TOKEN:
    logger.error("Токен бота не найден! Проверьте файл .env")
    raise ValueError("Токен бота не найден! Проверьте файл .env")

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


# Клавиатуры
def get_menu_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с кнопкой меню"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="📱 Меню"))
    return builder.as_markup(resize_keyboard=True)


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Основная клавиатура"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="/find"))
    builder.add(KeyboardButton(text="/stop"))
    builder.add(KeyboardButton(text="/next"))
    builder.add(KeyboardButton(text="/vip"))
    builder.add(KeyboardButton(text="/duo"))
    builder.adjust(2, 2)
    return builder.as_markup(resize_keyboard=True)


def get_vip_keyboard() -> ReplyKeyboardMarkup:
    """VIP клавиатура"""
    return get_main_keyboard()  # Используем ту же клавиатуру


def get_confirm_keyboard(action: str) -> InlineKeyboardBuilder:
    """Клавиатура подтверждения"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_{action}_yes"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"confirm_{action}_no")
    )
    return builder.as_markup()


async def save_user_info(user) -> None:
    """Сохранение информации о пользователе"""
    user_data_cache[user.id] = {
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name
    }


def get_user_log_info(user_id: int) -> str:
    """Форматирование информации о пользователе для логов"""
    user = user_data_cache.get(user_id, {})
    username = f"@{user.get('username')}" if user.get("username") else "без username"
    first_name = user.get("first_name", "неизвестно")
    last_name = f" {user.get('last_name')}" if user.get("last_name") else ""
    return f"{user_id} ({first_name}{last_name} {username})"


async def forward_to_admin(user_id: int, file_id: str, content_type: str) -> None:
    """Пересылка медиафайла администратору"""
    try:
        user_info = user_data_cache.get(user_id, {})
        username = user_info.get("username", "неизвестно")
        caption = f"Медиа от {get_user_log_info(user_id)}"

        send_methods = {
            "photo": bot.send_photo,
            "voice": bot.send_voice,
            "video": bot.send_video,
            "video_note": bot.send_video_note
        }

        if content_type in send_methods:
            await send_methods[content_type](
                chat_id=ADMIN_ID,
                **{content_type: file_id},
                caption=caption if content_type != "video_note" else None
            )
            if content_type == "video_note":
                await bot.send_message(ADMIN_ID, caption)

        logger.info(f"Медиа {content_type} от {get_user_log_info(user_id)} переслано администратору")
    except Exception as e:
        logger.error(f"Ошибка пересылки медиа администратору: {e}", exc_info=True)


async def stop_chat(user_id: int, initiator: bool = True) -> Optional[int]:
    """Завершение чата"""
    if user_id not in active_users:
        return None

    partner_info = active_users[user_id]
    partner_id = partner_info["partner_id"]

    # Удаляем информацию о чате
    del active_users[user_id]
    if partner_id in active_users:
        del active_users[partner_id]

    logger.info(f"Чат между {get_user_log_info(user_id)} и {get_user_log_info(partner_id)} завершен")

    messages = {
        user_id: "❌ Чат завершён. Ищем нового собеседника..." if initiator else "❌ Собеседник покинул чат",
        partner_id: "❌ Собеседник покинул чат. Используйте /find для нового поиска."
    }

    for uid, text in messages.items():
        await bot.send_message(uid, text, reply_markup=get_menu_keyboard())

    return partner_id


async def find_partner_logic(user_id: int) -> bool:
    """Логика поиска собеседника"""
    for i, partner_id in enumerate(waiting_users):
        if partner_id != user_id:
            waiting_users.pop(i)
            active_users.update({
                user_id: {"partner_id": partner_id, "username": user_data_cache.get(user_id, {}).get("username")},
                partner_id: {"partner_id": user_id, "username": user_data_cache.get(partner_id, {}).get("username")}
            })

            logger.info(f"Создан чат между {get_user_log_info(user_id)} и {get_user_log_info(partner_id)}")

            message = "✅ Собеседник найден! Общайтесь анонимно.\nДля открытия меню нажмите '📱 Меню'"
            await asyncio.gather(
                bot.send_message(user_id, message, reply_markup=get_menu_keyboard()),
                bot.send_message(partner_id, message, reply_markup=get_menu_keyboard())
            )
            return True
    return False


async def forward_message(sender_id: int, receiver_id: int, content: str, content_type: str) -> bool:
    """Универсальная функция пересылки сообщений"""
    try:
        send_methods = {
            "text": (bot.send_message, {"text": f"👤: {content}"}),
            "photo": (bot.send_photo, {"photo": content, "caption": "📷 Фото от собеседника"}),
            "voice": (bot.send_voice, {"voice": content, "caption": "🎤 Голосовое от собеседника"}),
            "video_note": (bot.send_video_note, {"video_note": content}),
            "video": (bot.send_video, {"video": content, "caption": "🎥 Видео от собеседника"})
        }

        if content_type in send_methods:
            method, params = send_methods[content_type]
            await method(receiver_id, reply_markup=get_menu_keyboard(), **params)

        logger.info(
            f"{content_type.capitalize()} от {get_user_log_info(sender_id)} отправлено {get_user_log_info(receiver_id)}")
        return True
    except Exception as e:
        logger.error(f"Ошибка отправки {content_type}: {e}", exc_info=True)
        await stop_chat(sender_id, initiator=False)
        return False


# Обработчики команд
@dp.message(Command("start"))
async def handle_start(message: Message) -> None:
    """Обработчик команды /start"""
    args = message.text.split()
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    # Обработка Duo ссылки
    if len(args) > 1 and args[1].startswith("duo_"):
        link_id = args[1][4:]
        creator_id = duo_links.get(link_id)

        if not creator_id:
            await message.answer("❌ Ссылка недействительна или устарела")
            return

        if user_id == creator_id:
            await message.answer("❌ Нельзя начать диалог с самим собой")
            return

        if creator_id in active_users or user_id in active_users:
            await message.answer("❌ Один из пользователей уже в другом диалоге")
            return

        # Создаем чат
        active_users.update({
            user_id: {"partner_id": creator_id, "username": user.username},
            creator_id: {"partner_id": user_id, "username": user_data_cache.get(creator_id, {}).get("username")}
        })

        del duo_links[link_id]

        # Уведомляем пользователей
        success_message = "✅ Диалог создан! Общайтесь анонимно."
        await asyncio.gather(
            bot.send_message(user_id, success_message, reply_markup=get_menu_keyboard()),
            bot.send_message(creator_id, success_message, reply_markup=get_menu_keyboard())
        )
        logger.info(f"Создан Duo чат между {user_id} и {creator_id}")
        return

    # Стандартное приветствие
    welcome_message = (
        "👋 Привет! Это анонимный чат-бот.\n"
        "Доступные команды:\n"
        "/find - найти собеседника\n"
        "/stop - выйти из чата\n"
        "/next - сменить собеседника\n"
        "/vip - информация о VIP-статусе\n"
        "/duo - создать ссылку для диалога\n\n"
        "Для открытия меню нажмите кнопку '📱 Меню'"
    )
    await message.answer(welcome_message, reply_markup=get_menu_keyboard())
    logger.info(f"Пользователь {get_user_log_info(user_id)} запустил бота")


@dp.message(Command("duo"))
async def create_duo_link(message: Message) -> None:
    """Создание приватной ссылки для диалога"""
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    if user_id in active_users:
        await message.answer("❌ Вы уже в чате. Сначала завершите текущий диалог с помощью /stop")
        return

    link_id = str(uuid.uuid4())
    duo_links[link_id] = user_id

    duo_link = f"https://t.me/{BOT_USERNAME}?start=duo_{link_id}"

    await message.answer(
        f"🔗 Ваша ссылка для диалога:\n\n{duo_link}\n\n"
        "Отправьте эту ссылку другу, чтобы начать приватный диалог.",
        reply_markup=get_menu_keyboard()
    )
    logger.info(f"Пользователь {get_user_log_info(user_id)} создал Duo ссылку: {link_id}")


@dp.message(Command("vip"))
async def vip_info(message: Message) -> None:
    """Информация о VIP статусе"""
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
            f"💰 Стоимость: {VIP_PRICE}\n"
            f"Для покупки напишите администратору",
            reply_markup=get_vip_keyboard()
        )


@dp.message(Command("find"))
async def find_partner(message: Message) -> None:
    """Поиск собеседника"""
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    if user_id in active_users:
        await message.reply("⚠️ Вы уже в чате! Используйте /stop чтобы выйти.")
        return

    if user_id in waiting_users:
        await message.answer("Вы уже в очереди на поиск")
        return

    if not await find_partner_logic(user_id):
        waiting_users.append(user_id)
        logger.info(
            f"Пользователь {get_user_log_info(user_id)} добавлен в очередь. Размер очереди: {len(waiting_users)}")
        await message.reply("🔍 Ищем собеседника... Ожидайте.", reply_markup=get_menu_keyboard())


@dp.message(Command("stop"))
async def stop_chat_handler(message: Message) -> None:
    """Завершение чата"""
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    if user_id not in active_users:
        await message.answer("❌ Вы не в чате. Используйте /find для поиска собеседника.")
        return

    logger.info(f"Пользователь {get_user_log_info(user_id)} хочет выйти из чата")
    await message.answer(
        "⚠️ Вы уверены, что хотите завершить чат?",
        reply_markup=get_confirm_keyboard("stop")
    )


@dp.message(Command("next"))
async def next_partner(message: Message) -> None:
    """Смена собеседника"""
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
async def process_confirmation(callback_query: CallbackQuery) -> None:
    """Обработка подтверждения действий"""
    user_id = callback_query.from_user.id
    action, response = callback_query.data.split("_")[1:3]

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
            await find_partner_logic(user_id)

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
            "❌ Действие отменено. Продолжаем общение.",
            reply_markup=get_menu_keyboard()
        )


# Обработчики медиа
@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    """Обработка фото"""
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    await forward_to_admin(user_id, message.photo[-1].file_id, "photo")

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        await forward_message(user_id, partner_id, message.photo[-1].file_id, "photo")
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_menu_keyboard()
        )


@dp.message(F.voice)
async def handle_voice(message: Message) -> None:
    """Обработка голосовых сообщений"""
    user = message.from_user
    await save_user_info(user)
    user_id = user.id

    await forward_to_admin(user_id, message.voice.file_id, "voice")

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        await forward_message(user_id, partner_id, message.voice.file_id, "voice")
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_menu_keyboard()
        )


@dp.message(F.video_note)
async def handle_video_note(message: Message) -> None:
    """Обработка видеосообщений (кружков)"""
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

    await forward_to_admin(user_id, message.video_note.file_id, "video_note")

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        await forward_message(user_id, partner_id, message.video_note.file_id, "video_note")
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_menu_keyboard()
        )


@dp.message(F.video)
async def handle_video(message: Message) -> None:
    """Обработка видео"""
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

    await forward_to_admin(user_id, message.video.file_id, "video")

    if user_id in active_users:
        partner_id = active_users[user_id]["partner_id"]
        await forward_message(user_id, partner_id, message.video.file_id, "video")
    else:
        await message.reply(
            "❌ Вы не в чате. Используйте /find для поиска собеседника.",
            reply_markup=get_menu_keyboard()
        )


@dp.message(F.text)
async def send_text_message(message: Message) -> None:
    """Обработка текстовых сообщений"""
    user = message.from_user
    await save_user_info(user)
    user_id = user.id
    text = message.text

    if text == "📱 Меню":
        await message.answer(
            "Меню:",
            reply_markup=get_vip_keyboard() if user_id in vip_users else get_main_keyboard()
        )
        return

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


@dp.message()
async def unhandled_message(message: Message) -> None:
    """Обработчик неучтенных сообщений"""
    logger.debug(f"Необработанное сообщение типа: {message.content_type}")


async def on_startup(dp: Dispatcher) -> None:
    """Обработчик запуска бота в режиме webhook"""
    if os.getenv("USE_WEBHOOK", "").lower() == "true":
        await bot.set_webhook(WEBHOOK_URL)
        logger.info("Webhook установлен")


async def on_shutdown(dp: Dispatcher) -> None:
    """Обработчик завершения работы"""
    logger.info("Завершение работы бота...")
    if os.getenv("USE_WEBHOOK", "").lower() == "true":
        await bot.delete_webhook()
    # Закрываем все активные чаты
    for user_id in list(active_users.keys()):
        await stop_chat(user_id, initiator=False)
    await dp.storage.close()
    await dp.storage.wait_closed()
    logger.info("Бот выключен")


def run_flask():
    """Запуск Flask сервера для health checks"""
    port = int(os.getenv("PORT", 5000))
    flask_app.run(host='0.0.0.0', port=port)


async def polling_main() -> None:
    """Основная функция запуска бота в режиме polling"""
    # Обработка сигналов завершения
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(
        signal.SIGTERM,
        lambda: asyncio.create_task(on_shutdown(dp))
    )

    restart_delay = 5
    max_restart_delay = 60
    while True:
        try:
            logger.info("Запуск бота в режиме polling...")
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot, close_bot_session=True)
        except Exception as e:
            logger.error(f"Ошибка: {e}. Перезапуск через {restart_delay} сек...", exc_info=True)
            await asyncio.sleep(restart_delay)
            restart_delay = min(restart_delay * 1.5, max_restart_delay)
            try:
                await bot.session.close()
            except:
                pass


def webhook_main() -> None:
    """Основная функция запуска бота в режиме webhook"""
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
        host='0.0.0.0',
        port=int(os.getenv("WEBHOOK_PORT", 3000))
    )


if __name__ == '__main__':
    try:
        if os.getenv("USE_WEBHOOK", "").lower() == "true":
            logger.info("Запуск в режиме webhook")
            webhook_main()
        else:
            logger.info("Запуск в режиме polling")
            asyncio.run(polling_main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен по запросу пользователя")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)