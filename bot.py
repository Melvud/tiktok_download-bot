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

# --- Помощники ---
def ffmpeg_bin() -> str:
    """Возвращает путь к ffmpeg: локальный бинарь или системный."""
    return FFMPEG_PATH if os.path.exists(FFMPEG_PATH) else "ffmpeg"

def ffprobe_bin() -> str:
    """Возвращает путь к ffprobe: локальный бинарь или системный."""
    local = "bin/ffprobe"
    return local if os.path.exists(local) else "ffprobe"

def install_ffmpeg() -> None:
    """Попытка скачать статический ffmpeg (Linux x86_64). На macOS/Windows поставьте системно."""
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
        # Переносим и ffmpeg, и ffprobe
        os.rename(os.path.join(temp_dir, "ffmpeg"), FFMPEG_PATH)
        if os.path.exists(os.path.join(temp_dir, "ffprobe")):
            os.rename(os.path.join(temp_dir, "ffprobe"), "bin/ffprobe")
            os.chmod("bin/ffprobe", 0o755)
        os.chmod(FFMPEG_PATH, 0o755)
        os.remove(archive_path)
        os.rmdir(temp_dir)
        logging.info("FFmpeg/FFprobe успешно установлены!")
    except Exception as e:
        logging.error(f"Не удалось установить FFmpeg: {e}")

def check_codecs(file_path: str) -> tuple[str, str]:
    """Возвращает (видеокодек, аудиокодек) через ffprobe, либо ('','') при ошибке."""
    try:
        vcodec = subprocess.check_output(
            [ffprobe_bin(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", file_path],
            timeout=30
        ).decode().strip()
        acodec = subprocess.check_output(
            [ffprobe_bin(), "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", file_path],
            timeout=30
        ).decode().strip()
        return vcodec, acodec
    except Exception as e:
        logging.error(f"Ошибка при проверке кодеков: {e}")
        return "", ""

def repack_to_mp4(input_path: str) -> Optional[str]:
    """Быстрый репак без перекодирования (минимальная нагрузка на CPU)."""
    try:
        base, _ = os.path.splitext(input_path)
        out = f"{base}_repack.mp4"
        subprocess.run(
            [ffmpeg_bin(), "-nostdin", "-loglevel", "error",
             "-y", "-i", input_path, "-c", "copy", "-movflags", "+faststart", out],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180
        )
        return out if os.path.exists(out) else None
    except subprocess.TimeoutExpired:
        logging.error("Репак превысил таймаут и был прерван.")
        return None
    except Exception as e:
        logging.error(f"Ошибка репака: {e}")
        return None

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

# --- Конвертация для iOS/Android (крайний вариант) ---
def convert_video_for_mobile(input_path: str) -> Optional[str]:
    """
    Перекод в mp4 (H.264 + AAC) для совместимости iOS/Android.
    Добавлены -nostdin, -loglevel error и таймаут, чтобы не зависало.
    Если аудио уже AAC — копируем его, чтобы снизить нагрузку.
    """
    try:
        base, _ext = os.path.splitext(input_path)
        output_path = f"{base}_ios.mp4"

        vcodec, acodec = check_codecs(input_path)
        audio_args = ["-c:a", "copy"] if acodec == "aac" else ["-c:a", "aac", "-b:a", "128k"]

        cmd = [
            ffmpeg_bin(), "-nostdin", "-loglevel", "error",
            "-y", "-i", input_path,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-profile:v", "high", "-level:v", "4.0",
            "-pix_fmt", "yuv420p",
            *audio_args,
            "-movflags", "+faststart",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            output_path,
        ]
        logging.info(f"Конвертирую в совместимый формат: {output_path}")
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
        return output_path if os.path.exists(output_path) else None
    except subprocess.TimeoutExpired:
        logging.error("Конвертация превысила таймаут и была прервана.")
        return None
    except subprocess.CalledProcessError as e:
        logging.error(f"Ошибка конвертации видео: {e}")
        return None
    except Exception as e:
        logging.exception(f"Неожиданная ошибка конвертации: {e}")
        return None

# --- Скачивание ---
def download_video_from_url(
    url: str,
    platform: str,
    progress_hook: Optional[Callable[[dict], None]] = None,
) -> Optional[str]:
    """
    Скачивает видео и возвращает путь к файлу (как скачано у источника).
    Репак/конвертация выполняются отдельно.
    """
    try:
        unique_id = uuid.uuid4()
        output_template = f"downloads/{platform}/{unique_id}.%(ext)s"
        os.makedirs(f"downloads/{platform}", exist_ok=True)

        # Базовые опции
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": output_template,
            "noplaylist": True,
            "ffmpeg_location": FFMPEG_PATH if os.path.exists(FFMPEG_PATH) else None,
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

        # Поддержка cookiefile только для Instagram (если файл есть)
        if platform == "instagram" and os.path.exists(COOKIES_FILE):
            ydl_opts["cookiefile"] = COOKIES_FILE
            logging.info(f"Использую cookiefile: {COOKIES_FILE}")

        # Форматная строка и merge-поведение — зависят от платформы
        if platform == "youtube":
            # Для YouTube делаем более гибкий выбор форматов, и НЕ форсим merge в mp4.
            ydl_opts["format"] = (
                "bv*[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/"
                "b[ext=mp4]/"
                "bv*+ba/b"
            )
            # Позволяем yt-dlp самому выбрать контейнер (mkv, webm), потом мы сами при необходимости репакнем/сконвертим
        else:
            # Для остальных стараемся сразу получить mp4+h264+aac
            ydl_opts["format"] = (
                "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/"
                "best[ext=mp4]/best"
            )
            ydl_opts["merge_output_format"] = "mp4"

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
        "Просто отправь мне ссылку на видео, или выбери платформу ниже.\n\n"
        "💡 Совет: ты можешь использовать меня прямо в любом чате!\n"
        "Для этого напиши: @tktdown_bot <ссылка>",
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

    # Скачиваем
    video_file = await asyncio.to_thread(download_video_from_url, url, platform, progress_hook)

    if not video_file:
        await loading_message.edit_text("❌ Не удалось скачать видео по этой ссылке.")
        hint = "Это мог быть приватный/возрастной ролик или Instagram попросил вход. Попробуйте другую ссылку."
        if platform == "instagram":
            hint = "Instagram для этой ссылки требует вход или сработал лимит. Попробуйте другую публичную ссылку."
        await message.answer(hint, reply_markup=create_main_keyboard())
        return

    # Проверяем кодеки и решаем, что делать
    vcodec, acodec = await asyncio.to_thread(check_codecs, video_file)
    path_to_send = video_file
    repacked_path = None
    converted_path = None

    if not (vcodec == "h264" and acodec == "aac"):
        # Сначала пробуем быстрый репак без перекодирования
        repacked_path = await asyncio.to_thread(repack_to_mp4, video_file)
        if repacked_path:
            rv, ra = await asyncio.to_thread(check_codecs, repacked_path)
            if rv == "h264" and ra == "aac":
                path_to_send = repacked_path
            else:
                # Только теперь — конвертация (с таймаутом и -nostdin)
                await loading_message.edit_text("🔧 Конвертирую видео для совместимости iOS/Android...")
                converted_path = await asyncio.to_thread(convert_video_for_mobile, video_file)
                path_to_send = converted_path or repacked_path or video_file
        else:
            # Репак не удался — сразу конвертируем
            await loading_message.edit_text("🔧 Конвертирую видео для совместимости iOS/Android...")
            converted_path = await asyncio.to_thread(convert_video_for_mobile, video_file)
            path_to_send = converted_path or video_file

    # Отправляем
    await loading_message.edit_text("📤 Отправляю видео...")
    try:
        video_input = FSInputFile(path_to_send)
        await message.reply_video(video_input)
        await loading_message.delete()
        logging.info(f"Видео с {platform} успешно отправлено.")
        await message.answer("Спасибо за использование меня 🥰", reply_markup=create_main_keyboard())
        await message.answer(
            "💡 Ты также можешь пользоваться inline-режимом:\n"
            "просто напиши @tktdown_bot <ссылка> прямо в любом чате.",
            reply_markup=create_main_keyboard(),
        )
    except Exception as e:
        logging.exception(f"Ошибка при отправке видео: {e}")
        await loading_message.edit_text("⚠️ Ошибка при отправке видео.")
        await message.answer("Попробуйте ещё раз или выберите платформу:", reply_markup=create_main_keyboard())
    finally:
        # Чистим файлы
        for p in {video_file, repacked_path, converted_path}:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                    logging.info(f"Файл {p} удален.")
                except OSError as e:
                    logging.error(f"Ошибка при удалении файла {p}: {e}")

# --- Инлайн режим ---
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
    repacked_path: Optional[str] = None
    converted_path: Optional[str] = None
    try:
        # Скачиваем
        video_file_path = await asyncio.to_thread(download_video_from_url, url, platform)
        if video_file_path:
            send_path = video_file_path
            vcodec, acodec = await asyncio.to_thread(check_codecs, video_file_path)
            if not (vcodec == "h264" and acodec == "aac"):
                repacked_path = await asyncio.to_thread(repack_to_mp4, video_file_path)
                if repacked_path:
                    rv, ra = await asyncio.to_thread(check_codecs, repacked_path)
                    if rv == "h264" and ra == "aac":
                        send_path = repacked_path
                    else:
                        converted_path = await asyncio.to_thread(convert_video_for_mobile, video_file_path)
                        send_path = converted_path or repacked_path or video_file_path
                else:
                    converted_path = await asyncio.to_thread(convert_video_for_mobile, video_file_path)
                    send_path = converted_path or video_file_path

            sent = await bot.send_video(chat_id=query.from_user.id, video=FSInputFile(send_path))
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
        for p in {video_file_path, repacked_path, converted_path}:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                    logging.info(f"Инлайн-файл {p} удален.")
                except OSError as e:
                    logging.error(f"Ошибка при удалении файла {p}: {e}")

    await query.answer(results, cache_time=1)

# --- Запуск ---
async def main():
    logging.info("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    install_ffmpeg()  # уберите, если FFmpeg уже установлен системно
    os.makedirs("downloads", exist_ok=True)
    asyncio.run(main())
