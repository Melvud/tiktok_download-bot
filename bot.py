import os
import logging
import re
import asyncio
import uuid
import subprocess
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
import yt_dlp
from dotenv import load_dotenv

# Загрузка переменных окружения из .env файла
load_dotenv()

# --- Конфигурация ---
API_TOKEN = os.getenv("BOT_TOKEN")
FFMPEG_PATH = "bin/ffmpeg"  # Путь к исполняемому файлу ffmpeg

# --- Установка FFmpeg ---
def install_ffmpeg():
    """
    Проверяет наличие FFmpeg и скачивает его, если он отсутствует.
    Эта функция предназначена для Linux-подобных систем.
    """
    if not os.path.exists(FFMPEG_PATH):
        logging.info("FFmpeg не найден, начинается скачивание...")
        try:
            os.makedirs("bin", exist_ok=True)
            # URL для статической сборки FFmpeg для amd64
            ffmpeg_url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
            archive_path = "ffmpeg.tar.xz"

            # Скачивание архива
            subprocess.run(
                ["curl", "-L", "-o", archive_path, ffmpeg_url], check=True
            )
            logging.info("Архив FFmpeg скачан.")

            # Распаковка и перемещение
            temp_dir = "ffmpeg_temp"
            os.makedirs(temp_dir, exist_ok=True)
            subprocess.run(
                ["tar", "-xJf", archive_path, "-C", temp_dir, "--strip-components=1"],
                check=True,
            )
            os.rename(os.path.join(temp_dir, "ffmpeg"), FFMPEG_PATH)

            # Предоставление прав на выполнение
            os.chmod(FFMPEG_PATH, 0o755)

            # Очистка
            os.remove(archive_path)
            os.rmdir(temp_dir)

            logging.info("FFmpeg успешно установлен!")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error(f"Не удалось установить FFmpeg: {e}")
            logging.error(
                "Пожалуйста, установите FFmpeg вручную или убедитесь, что 'curl' и 'tar' доступны в вашей системе."
            )
            # В зависимости от критичности, можно либо продолжить, либо завершить работу
            # exit(1) # Раскомментируйте, если FFmpeg является обязательным для работы
        except Exception as e:
            logging.error(f"Произошла непредвиденная ошибка при установке FFmpeg: {e}")


# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- Инициализация бота и диспетчера ---
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- Состояния FSM ---
class DownloadState(StatesGroup):
    url = State()

# --- Клавиатуры ---
def create_main_keyboard():
    """Создает главную клавиатуру с выбором платформ."""
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

# --- Функции скачивания ---
def download_video_from_url(url: str, platform: str) -> str | None:
    """
    Универсальная функция для скачивания видео с использованием yt-dlp.
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
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logging.info(f"Начинаю скачивание с {platform}: {url}")
            info_dict = ydl.extract_info(url, download=True)
            
            base_path = f"downloads/{platform}/{unique_id}"
            for ext in ['mp4', 'mkv', 'webm']:
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
    """Определяет платформу по URL."""
    if "tiktok.com" in url:
        return "tiktok"
    if "instagram.com" in url:
        return "instagram"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "twitter.com" in url or "x.com" in url:
        return "twitter"
    return None

# --- Обработчики команд и сообщений ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Обработчик команды /start."""
    logging.info(f"Пользователь {message.from_user.id} запустил бота.")
    await state.clear()
    await message.reply(
        "👋 Привет! Я бот для скачивания видео.\n\n"
        "Просто отправь мне ссылку на видео, или выбери платформу ниже.",
        reply_markup=create_main_keyboard(),
    )

@dp.message(lambda message: message.text in ["📥 TikTok", "📸 Instagram", "🎥 YouTube", "🐦 X (Twitter)"])
async def handle_platform_choice(message: types.Message, state: FSMContext):
    """Обработчик для кнопок выбора платформы."""
    await message.reply(
        "Отправьте мне ссылку на видео.", reply_markup=types.ReplyKeyboardRemove()
    )
    await state.set_state(DownloadState.url)

@dp.message(DownloadState.url)
@dp.message(lambda message: message.text and message.text.startswith("http"))
async def process_video_link(message: types.Message, state: FSMContext):
    """Обрабатывает полученную ссылку на видео."""
    url = message.text.strip()
    await state.clear()

    platform = get_platform_from_url(url)
    if not platform:
        await message.reply("Не могу определить платформу по этой ссылке. Пожалуйста, убедитесь, что ссылка верна.")
        return

    loading_message = await message.reply("📥 Видео загружается, пожалуйста, подождите...")

    video_file = await asyncio.to_thread(download_video_from_url, url, platform)
    
    await loading_message.delete()

    if video_file:
        try:
            video_input = FSInputFile(video_file)
            await message.reply_video(video_input)
            logging.info(f"Видео с {platform} успешно отправлено пользователю {message.from_user.id}.")
        except Exception as e:
            logging.error(f"Ошибка при отправке видео: {e}")
            await message.reply("⚠️ Произошла ошибка при отправке видео. Возможно, файл слишком большой.")
        finally:
            try:
                os.remove(video_file)
                logging.info(f"Файл {video_file} удален.")
            except OSError as e:
                logging.error(f"Ошибка при удалении файла {video_file}: {e}")
    else:
        await message.reply("❌ Не удалось скачать видео по этой ссылке. Пожалуйста, попробуйте другую.")

# --- Обработчик инлайн-режима ---

@dp.inline_query()
async def inline_handler(query: InlineQuery):
    """Обрабатывает инлайн-запросы."""
    url = query.query.strip()
    results = []

    if url.startswith("http"):
        platform = get_platform_from_url(url)
        if platform:
            logging.info(f"Инлайн-запрос на скачивание с {platform}: {url}")
            
            video_file_path = download_video_from_url(url, platform)

            if video_file_path:
                try:
                    video_file = FSInputFile(video_file_path)
                    
                    msg = await bot.send_video(chat_id=query.from_user.id, video=video_file, caption="Загрузка для инлайн-режима...")
                    video_file_id = msg.video.file_id
                    await msg.delete()

                    results.append(
                        InlineQueryResultVideo(
                            id=str(uuid.uuid4()),
                            video_file_id=video_file_id,
                            title=f"Скачать видео с {platform.capitalize()}",
                            caption=f"Видео с {platform}",
                            mime_type="video/mp4",
                        )
                    )
                except Exception as e:
                    logging.error(f"Ошибка в инлайн-режиме при обработке файла: {e}")
                finally:
                    if os.path.exists(video_file_path):
                        os.remove(video_file_path)

    await query.answer(results, cache_time=1)

async def main():
    """Основная функция для запуска бота."""
    logging.info("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    # 1. Устанавливаем FFmpeg, если его нет
    install_ffmpeg()
    
    # 2. Создаем папку для загрузок, если ее нет
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
        
    # 3. Запускаем бота
    asyncio.run(main())