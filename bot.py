import os
import logging
import re
import asyncio
import uuid
import subprocess
import time  # Импортируем модуль time
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    FSInputFile,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineQuery,
    InlineQueryResultVideo,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest  # Для обработки ошибок API
import yt_dlp
from dotenv import load_dotenv

load_dotenv()

# --- Конфигурация ---
API_TOKEN = os.getenv("BOT_TOKEN")
FFMPEG_PATH = "bin/ffmpeg"

# --- Установка FFmpeg (остается без изменений) ---
def install_ffmpeg():
    if not os.path.exists(FFMPEG_PATH):
        logging.info("FFmpeg не найден, начинается скачивание...")
        try:
            os.makedirs("bin", exist_ok=True)
            ffmpeg_url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
            archive_path = "ffmpeg.tar.xz"
            subprocess.run(
                ["curl", "-L", "-o", archive_path, ffmpeg_url], check=True
            )
            logging.info("Архив FFmpeg скачан.")
            temp_dir = "ffmpeg_temp"
            os.makedirs(temp_dir, exist_ok=True)
            subprocess.run(
                ["tar", "-xJf", archive_path, "-C", temp_dir, "--strip-components=1"],
                check=True,
            )
            os.rename(os.path.join(temp_dir, "ffmpeg"), FFMPEG_PATH)
            os.chmod(FFMPEG_PATH, 0o755)
            os.remove(archive_path)
            os.rmdir(temp_dir)
            logging.info("FFmpeg успешно установлен!")
        except Exception as e:
            logging.error(f"Не удалось установить FFmpeg: {e}")

# --- Настройка логирования и инициализация бота (без изменений) ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# ... (Состояния FSM и Клавиатуры остаются без изменений) ...
class DownloadState(StatesGroup):
    url = State()

def create_main_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📥 TikTok")],
            [KeyboardButton(text="📸 Instagram")],
            [KeyboardButton(text="🎥 YouTube")],
            [KeyboardButton(text="🐦 X (Twitter)")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    return keyboard
# --- Обновленная функция скачивания ---
def download_video_from_url(
    url: str, platform: str, progress_hook: callable | None = None
) -> str | None:
    """
    Универсальная функция для скачивания видео с передачей прогресс-хука.
    """
    try:
        unique_id = uuid.uuid4()
        output_template = f"downloads/{platform}/{unique_id}.%(ext)s"
        os.makedirs(f"downloads/{platform}", exist_ok=True)

        ydl_opts = {
            "quiet": True,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": output_template,
            "noplaylist": True,
            "merge_output_format": "mp4",
            "ffmpeg_location": FFMPEG_PATH,
            # 'proxy': 'YOUR_PROXY_URL' # Раскомментируйте, если используете прокси
        }

        # <<< НОВОЕ: Добавляем хук в опции, если он был передан
        if progress_hook:
            ydl_opts["progress_hooks"] = [progress_hook]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logging.info(f"Начинаю скачивание с {platform}: {url}")
            info_dict = ydl.extract_info(url, download=True)

            base_path = f"downloads/{platform}/{unique_id}"
            for ext in ["mp4", "mkv", "webm"]:
                video_file = f"{base_path}.{ext}"
                if os.path.exists(video_file):
                    logging.info(f"Видео успешно скачано: {video_file}")
                    return video_file

            logging.error(f"Ошибка: скачанный файл не найден для {url}")
            return None

    except yt_dlp.utils.DownloadError as e:
        logging.error(f"Ошибка yt-dlp при скачивании с {platform} ({url}): {e}")
        return None
    except Exception as e:
        logging.error(f"Непредвиденная ошибка при скачивании с {platform} ({url}): {e}")
        return None

def get_platform_from_url(url: str) -> str | None:
    # ... (эта функция без изменений)
    if "tiktok.com" in url: return "tiktok"
    if "instagram.com" in url: return "instagram"
    if "youtube.com" in url or "youtu.be" in url: return "youtube"
    if "twitter.com" in url or "x.com" in url: return "twitter"
    return None

# --- Обработчики команд и сообщений (cmd_start и handle_platform_choice без изменений) ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    logging.info(f"Пользователь {message.from_user.id} запустил бота.")
    await state.clear()
    await message.reply(
        "👋 Привет! Я бот для скачивания видео.\n\n"
        "Просто отправь мне ссылку на видео, или выбери платформу ниже.",
        reply_markup=create_main_keyboard(),
    )

@dp.message(lambda message: message.text in ["📥 TikTok", "📸 Instagram", "🎥 YouTube", "🐦 X (Twitter)"])
async def handle_platform_choice(message: types.Message, state: FSMContext):
    await message.reply(
        "Отправьте мне ссылку на видео.", reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(DownloadState.url)


# --- <<< ЗДЕСЬ ОСНОВНЫЕ ИЗМЕНЕНИЯ >>> ---
@dp.message(DownloadState.url)
@dp.message(lambda message: message.text and message.text.startswith("http"))
async def process_video_link(message: types.Message, state: FSMContext):
    url = message.text.strip()
    await state.clear()

    platform = get_platform_from_url(url)
    if not platform:
        await message.reply("Не могу определить платформу по этой ссылке.")
        return

    # Отправляем начальное сообщение, которое будем редактировать
    loading_message = await message.reply("📥 Подготовка к загрузке...")

    # --- Создание прогресс-хука ---
    last_update_time = 0
    
    def progress_hook(d):
        nonlocal last_update_time
        if d["status"] == "downloading":
            current_time = time.time()
            # Ограничиваем частоту обновлений (например, раз в 1.5 секунды)
            if current_time - last_update_time < 1.5:
                return

            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)

            if total > 0:
                percent = downloaded / total * 100
                speed = d.get("speed", 0) or 0
                speed_mbps = speed / 1024 / 1024
                
                # Создаем текстовый прогресс-бар
                progress_bar = "".join(
                    ["█" if i < percent / 10 else "░" for i in range(10)]
                )
                
                status_text = (
                    f"📥 **Скачиваю видео...**\n"
                    f"`{progress_bar}` {percent:.1f}%\n"
                    f"Скорость: {speed_mbps:.2f} МБ/с"
                )

                try:
                    # Запускаем асинхронную задачу редактирования сообщения
                    # из синхронной функции (хука)
                    asyncio.run_coroutine_threadsafe(
                        loading_message.edit_text(status_text, parse_mode="Markdown"),
                        asyncio.get_running_loop()
                    )
                    last_update_time = current_time
                except TelegramBadRequest:
                    # Игнорируем ошибку, если текст сообщения не изменился
                    pass
    
    # Запускаем скачивание в отдельном потоке, передавая наш хук
    video_file = await asyncio.to_thread(
        download_video_from_url, url, platform, progress_hook
    )

    # Меняем текст после завершения скачивания
    await loading_message.edit_text("📤 Отправляю видео...")

    if video_file:
        try:
            video_input = FSInputFile(video_file)
            await message.reply_video(video_input)
            await loading_message.delete() # Удаляем статусное сообщение
            logging.info(f"Видео с {platform} успешно отправлено.")
        except Exception as e:
            logging.error(f"Ошибка при отправке видео: {e}")
            await loading_message.edit_text("⚠️ Ошибка при отправке видео.")
        finally:
            try:
                os.remove(video_file)
                logging.info(f"Файл {video_file} удален.")
            except OSError as e:
                logging.error(f"Ошибка при удалении файла {video_file}: {e}")
    else:
        await loading_message.edit_text("❌ Не удалось скачать видео по этой ссылке.")

# --- Инлайн-режим (остается без изменений) ---

@dp.inline_query()
async def inline_handler(query: InlineQuery):
    url = query.query.strip()
    results = []

    if not url.startswith("http"):
        return

    platform = get_platform_from_url(url)
    if platform:
        logging.info(f"Инлайн-запрос на скачивание с {platform}: {url}")
        
        video_file_path = None
        try:
            # Используем гибридный подход и для инлайн-режима
            if platform == "tiktok":
                video_file_path = await asyncio.to_thread(download_video_from_tiktok_legacy, url)
            else:
                # Для инлайн-режима прогресс-бар не нужен
                video_file_path = await asyncio.to_thread(download_video_from_url, url, platform)

            if video_file_path:
                video_file = FSInputFile(video_file_path)
                
                # Загружаем видео в чат с пользователем, чтобы получить file_id
                msg = await bot.send_video(
                    chat_id=query.from_user.id, 
                    video=video_file, 
                    caption="Загрузка для инлайн-режима..."
                )
                video_file_id = msg.video.file_id
                await msg.delete()

                results.append(
                    InlineQueryResultVideo(
                        id=str(uuid.uuid4()),
                        video_file_id=video_file_id,
                        title=f"Скачать видео с {platform.capitalize()}",
                        caption=f"Видео скачано с помощью вашего бота", # Можете указать @username
                        mime_type="video/mp4",
                    )
                )
        except Exception as e:
            logging.error(f"Ошибка в инлайн-режиме при обработке файла: {e}")
        finally:
            # Обязательно удаляем локальный файл после всех операций
            if video_file_path and os.path.exists(video_file_path):
                os.remove(video_file_path)
                logging.info(f"Инлайн-файл {video_file_path} удален.")

    await query.answer(results, cache_time=1)

# --- Основная функция запуска ---

async def main():
    logging.info("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    install_ffmpeg()
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
    asyncio.run(main())