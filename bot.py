import os
import logging
import asyncio
import uuid
import subprocess
import time
from typing import Optional, Callable

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    FSInputFile,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineQuery,
    InlineQueryResultCachedVideo,
    ReplyKeyboardRemove,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import yt_dlp
from dotenv import load_dotenv

load_dotenv()

# --- Конфигурация ---
API_TOKEN = os.getenv("BOT_TOKEN")
FFMPEG_PATH = "bin/ffmpeg"
COOKIES_FILE = os.getenv("COOKIES_FILE", "ig_cookies.txt")

# --- Установка FFmpeg (если отсутствует) ---
def install_ffmpeg() -> None:
    if os.path.exists(FFMPEG_PATH):
        return
    try:
        os.makedirs("bin", exist_ok=True)
        ffmpeg_url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        archive_path = "ffmpeg.tar.xz"
        subprocess.run(["curl", "-L", "-o", archive_path, ffmpeg_url], check=True)
        logging.info("Архив FFmpeg скачан.")
        temp_dir = "ffmpeg_temp"
        os.makedirs(temp_dir, exist_ok=True)
        subprocess.run(["tar", "-xJf", archive_path, "-C", temp_dir, "--strip-components=1"], check=True)
        os.rename(os.path.join(temp_dir, "ffmpeg"), FFMPEG_PATH)
        os.chmod(FFMPEG_PATH, 0o755)
        os.remove(archive_path)
        os.rmdir(temp_dir)
        logging.info("FFmpeg успешно установлен!")
    except Exception as e:
        logging.error(f"Не удалось установить FFmpeg: {e}")

# --- Логирование и инициализация бота ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
if not API_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN в окружении (.env).")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- FSM и клавиатура ---
class DownloadState(StatesGroup):
    url = State()

def create_main_keyboard() -> ReplyKeyboardMarkup:
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

# --- Утилиты ---
def get_platform_from_url(url: str) -> Optional[str]:
    u = url.lower()
    if "tiktok.com" in u:
        return "tiktok"
    if "instagram.com" in u:
        return "instagram"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "twitter.com" in u or "x.com" in u:
        return "twitter"
    return None

# --- Скачивание ---
def download_video_from_url(
    url: str,
    platform: str,
    progress_hook: Optional[Callable[[dict], None]] = None,
) -> Optional[str]:
    try:
        unique_id = uuid.uuid4()
        output_template = f"downloads/{platform}/{unique_id}.%(ext)s"
        os.makedirs(f"downloads/{platform}", exist_ok=True)

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": output_template,
            "noplaylist": True,
            "merge_output_format": "mp4",
            "ffmpeg_location": FFMPEG_PATH,
            "retries": 5,
            "fragment_retries": 5,
            "concurrent_fragment_downloads": 1,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        }

        if platform == "instagram" and os.path.exists(COOKIES_FILE):
            ydl_opts["cookiefile"] = COOKIES_FILE
            logging.info(f"Использую cookiefile: {COOKIES_FILE}")

        if progress_hook:
            ydl_opts["progress_hooks"] = [progress_hook]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logging.info(f"Начинаю скачивание с {platform}: {url}")
            ydl.extract_info(url, download=True)
            base_path = f"downloads/{platform}/{unique_id}"
            for ext in ("mp4", "mkv", "webm"):
                video_file = f"{base_path}.{ext}"
                if os.path.exists(video_file):
                    logging.info(f"Видео успешно скачано: {video_file}")
                    return video_file

            logging.error(f"Ошибка: скачанный файл не найден для {url}")
            return None

    except Exception as e:
        logging.exception(f"Непредвиденная ошибка при скачивании с {platform} ({url}): {e}")
        return None

# --- Хэндлеры ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    logging.info(f"Пользователь {message.from_user.id} запустил бота.")
    await state.clear()
    await message.reply(
        "👋 Привет! Я бот для скачивания видео.\n\n"
        "Просто отправь мне ссылку на видео, или выбери платформу ниже.",
        reply_markup=create_main_keyboard(),
    )

@dp.message(lambda m: m.text in ["📥 TikTok", "📸 Instagram", "🎥 YouTube", "🐦 X (Twitter)"])
async def handle_platform_choice(message: types.Message, state: FSMContext):
    await message.reply("Отправьте мне ссылку на видео.", reply_markup=ReplyKeyboardRemove())
    await state.set_state(DownloadState.url)

@dp.message(DownloadState.url)
@dp.message(lambda m: m.text and m.text.startswith("http"))
async def process_video_link(message: types.Message, state: FSMContext):
    url = message.text.strip()
    await state.clear()

    platform = get_platform_from_url(url)
    if not platform:
        await message.reply("Не могу определить платформу по этой ссылке.", reply_markup=create_main_keyboard())
        return

    loading_message = await message.reply("📥 Подготовка к загрузке...")

    loop = asyncio.get_running_loop()
    last_update_time = 0.0

    def progress_hook(d: dict) -> None:
        nonlocal last_update_time
        try:
            if d.get("status") == "downloading":
                current_time = time.time()
                if current_time - last_update_time < 1.5:
                    return
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if total > 0:
                    percent = (d.get("downloaded_bytes") or 0) / total * 100.0
                    speed = d.get("speed") or 0.0
                    progress_bar = "".join("█" if i < percent / 10 else "░" for i in range(10))
                    status_text = (
                        "📥 **Скачиваю видео...**\n"
                        f"`{progress_bar}` {percent:.1f}%\n"
                        f"Скорость: {speed / 1024 / 1024:.2f} МБ/с"
                    )
                    fut = asyncio.run_coroutine_threadsafe(
                        loading_message.edit_text(status_text, parse_mode="Markdown"),
                        loop,
                    )
                    try:
                        fut.result(timeout=0)
                    except Exception:
                        pass
                    last_update_time = current_time
        except Exception as e:
            logging.debug(f"Ошибка в progress_hook: {e}")

    video_file = await asyncio.to_thread(download_video_from_url, url, platform, progress_hook)

    await loading_message.edit_text("📤 Отправляю видео...")
    if video_file:
        try:
            video_input = FSInputFile(video_file)
            await message.reply_video(video_input)
            await loading_message.delete()
            logging.info(f"Видео с {platform} успешно отправлено.")
            await message.answer("Спасибо за использование меня 🥰", reply_markup=create_main_keyboard())
        except Exception as e:
            logging.exception(f"Ошибка при отправке видео: {e}")
            await loading_message.edit_text("⚠️ Ошибка при отправке видео.")
            await message.answer("Попробуйте ещё раз или выберите платформу:", reply_markup=create_main_keyboard())
        finally:
            try:
                os.remove(video_file)
                logging.info(f"Файл {video_file} удален.")
            except OSError as e:
                logging.error(f"Ошибка при удалении файла {video_file}: {e}")
    else:
        await loading_message.edit_text("❌ Не удалось скачать видео по этой ссылке.")
        hint = "Это мог быть приватный/возрастной ролик или Instagram попросил вход. Попробуйте другую ссылку."
        if platform == "instagram":
            hint = "Instagram для этой ссылки требует вход или сработал лимит. Попробуйте другую публичную ссылку."
        await message.answer(hint, reply_markup=create_main_keyboard())

@dp.inline_query()
async def inline_handler(query: InlineQuery):
    url = (query.query or "").strip()
    results = []
    if not url.startswith("http"):
        await query.answer(results, cache_time=1)
        return

    platform = get_platform_from_url(url)
    if not platform:
        await query.answer(results, cache_time=1)
        return

    logging.info(f"Инлайн-запрос на скачивание с {platform}: {url}")
    video_file_path: Optional[str] = None
    try:
        video_file_path = await asyncio.to_thread(download_video_from_url, url, platform)
        if video_file_path:
            sent = await bot.send_video(chat_id=query.from_user.id, video=FSInputFile(video_file_path))
            file_id = sent.video.file_id
            await sent.delete()

            results.append(
                InlineQueryResultCachedVideo(
                    id=str(uuid.uuid4()),
                    video_file_id=file_id,
                    title="Видео",
                    description="Видео скачано вашим ботом",
                )
            )
    except Exception as e:
        logging.exception(f"Ошибка в инлайн-режиме при обработке файла: {e}")
    finally:
        if video_file_path and os.path.exists(video_file_path):
            os.remove(video_file_path)
            logging.info(f"Инлайн-файл {video_file_path} удален.")

    await query.answer(results, cache_time=1)

# --- Запуск ---
async def main():
    logging.info("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    install_ffmpeg()
    os.makedirs("downloads", exist_ok=True)
    asyncio.run(main())
