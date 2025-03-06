import os
import logging
import re
import requests
import subprocess
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import yt_dlp
import instaloader
from dotenv import load_dotenv

FFMPEG_PATH = "bin/ffmpeg"
PROXY_URL = "http://L7LrDyxN:DCzRREze@92.119.201.253:63668"  # Замените на реальный прокси

INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

# Функция для авторизации в Instaloader
def login_instagram():
    L = instaloader.Instaloader()

    # Если у вас есть сохраненная сессия, загружаем её
    session_file = f"{INSTAGRAM_USERNAME}_session"
    if os.path.exists(session_file):
        L.load_session_from_file(INSTAGRAM_USERNAME)
        print("Загружена сессия из файла.")
    else:
        # Если нет, логинимся и сохраняем сессию
        try:
            L.context.log("Выполняется вход в Instagram...")
            L.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            L.save_session_to_file()  # Сохраняем сессию
            print("Успешный вход в Instagram и сохранение сессии.")
        except Exception as e:
            print(f"Ошибка при входе: {e}")
            return None
    return L

def install_ffmpeg():
    if not os.path.exists(FFMPEG_PATH):
        print("Скачиваем FFmpeg...")
        os.makedirs("bin", exist_ok=True)
        subprocess.run([
            "curl", "-L", "-o", FFMPEG_PATH,
            "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
        ])
        subprocess.run(["tar", "-xJf", FFMPEG_PATH, "-C", "bin", "--strip-components=1"])
        os.chmod(FFMPEG_PATH, 0o755)  # Даем права на выполнение
        print("FFmpeg установлен!")

install_ffmpeg()

load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")  # Читаем токен из переменной окружения
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Настроим логирование
logging.basicConfig(level=logging.INFO)

# Функции скачивания для каждой платформы

def download_video_from_tiktok(url):
    try:
        ydl_opts = {
            'quiet': True,
            'format': 'bestaudio/best',
            'outtmpl': 'downloads/tiktok/%(id)s.%(ext)s',  # Сохраняем в отдельной папке для TikTok
            'noplaylist': True,
            'extractaudio': False,
            'nooverwrites': True,
            'ffmpeg_location': FFMPEG_PATH,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logging.info(f"Начинаю скачивание видео с TikTok: {url}")
            info_dict = ydl.extract_info(url, download=True)
            video_file = f"downloads/tiktok/{info_dict['id']}.mp4"

            if os.path.exists(video_file):
                logging.info(f"Видео успешно скачано: {video_file}")
                return video_file
            else:
                logging.error(f"Ошибка: файл не найден по пути {video_file}")
                return None
    except Exception as e:
        logging.error(f"Ошибка при скачивании видео: {e}")
        return None

def download_video_from_twitter(url):
    try:
        ydl_opts = {
            'quiet': True,
            'format': 'bestvideo+bestaudio/best',  # Скачиваем видео и аудио в лучшем качестве
            'outtmpl': 'downloads/twitter/%(id)s.%(ext)s',
            'noplaylist': True,
            'extractaudio': False,  # Убедимся, что видео не будет извлечено как аудио
            'nooverwrites': True,
            'ffmpeg_location': FFMPEG_PATH,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            logging.info(f"Начинаю скачивание видео: {url}")
            info_dict = ydl.extract_info(url, download=True)
            video_file = f"downloads/twitter/{info_dict['id']}.mp4"

            if os.path.exists(video_file):
                logging.info(f"Видео успешно скачано: {video_file}")
                return video_file
            else:
                logging.error(f"Ошибка: файл не найден по пути {video_file}")
                return None
    except Exception as e:
        logging.error(f"Ошибка при скачивании видео с Twitter: {e}")
        return None

def download_video_from_reels(url):
    try:
        # Авторизация
        L = login_instagram()
        if L is None:
            return None  # Если не удалось авторизоваться, возвращаем None

        # Устанавливаем прокси при инициализации Instaloader
        L.context.proxy = PROXY_URL

        print(f"Начинаю скачивание видео: {url}")
        shortcode = url.split('/')[-2]  # Получаем shortcode из URL
        post = instaloader.Post.from_shortcode(L.context, shortcode)

        # Получаем URL видео
        video_url = post.video_url

        # Убедитесь, что папка для сохранения видео существует
        download_dir = 'downloads/reels'
        os.makedirs(download_dir, exist_ok=True)  # Создаем папку, если ее нет

        # Скачиваем видео
        video_file = f"{download_dir}/{shortcode}.mp4"
        video_data = requests.get(video_url, proxies={"http": PROXY_URL, "https": PROXY_URL})

        with open(video_file, 'wb') as f:
            f.write(video_data.content)

        if os.path.exists(video_file):
            print(f"Видео успешно скачано: {video_file}")
            return video_file
        else:
            print(f"Ошибка: файл не найден по пути {video_file}")
            return None
    except Exception as e:
        print(f"Ошибка при скачивании видео с Instagram Reels: {e}")
        return None

# Функция для безопасного создания имени файла
def sanitize_filename(filename):
    return re.sub(r'[^a-zA-Z0-9_\-\.]', '_', filename)

# Создание клавиатуры для выбора источника
def create_main_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Скачать с TikTok")],
            [KeyboardButton(text="Скачать с X(Twitter)")],
            [KeyboardButton(text="Скачать с Reels")],
        ],
        resize_keyboard=True
    )
    return keyboard

# Состояния FSM
class DownloadState(StatesGroup):
    platform = State()  # Состояние для выбора платформы
    url = State()       # Состояние для ввода ссылки

# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    logging.info("Получена команда /start")
    await message.reply(
        "Привет! Выберите, с какого сайта вы хотите скачать видео.",
        reply_markup=create_main_keyboard()
    )
    # Устанавливаем начальное состояние
    await state.set_state(DownloadState.platform)

# Обработчик выбора платформы
@dp.message(lambda message: message.text in ["Скачать с TikTok", "Скачать с X(Twitter)", "Скачать с Reels"])
async def handle_platform_choice(message: types.Message, state: FSMContext):
    # Сопоставляем названия кнопок с платформами
    platform_mapping = {
        "Скачать с TikTok": "tiktok",
        "Скачать с X(Twitter)": "twitter",
        "Скачать с Reels": "reels",
    }

    platform = platform_mapping.get(message.text)

    if platform:
        # Сохраняем выбранную платформу
        await state.update_data(platform=platform)
        await message.reply("Отправьте ссылку на видео.", reply_markup=types.ReplyKeyboardRemove())
        await state.set_state(DownloadState.url)  # Переход к состоянию ввода URL
    else:
        await message.reply("Произошла ошибка, попробуйте снова.", reply_markup=create_main_keyboard())

# Обработчик сообщений с ссылками
@dp.message(lambda message: message.text.startswith("http"))
async def download_video(message: types.Message, state: FSMContext):
    url = message.text.strip()

    # Получаем данные из состояния
    user_data = await state.get_data()
    platform = user_data.get("platform")  # Платформа будет сохранена в состоянии FSM

    logging.info(f"Скачиваем видео по ссылке: {url}")

    if platform is None:
        await message.reply("Вы не выбрали платформу. Пожалуйста, выберите платформу с помощью кнопок.")
        return

    # Проверка на валидность ссылки
    if not re.match(r'https?://(?:www\.)?.+', url):
        await message.reply("Пожалуйста, отправьте корректную ссылку.")
        return

    # Отправляем сообщение пользователю о начале загрузки
    loading_message = await message.reply("📥 Видео загружается, пожалуйста, подождите...")

    # В зависимости от платформы вызываем соответствующую функцию скачивания
    download_functions = {
        "tiktok": download_video_from_tiktok,
        "twitter": download_video_from_twitter,
        "reels": download_video_from_reels,
    }

    download_function = download_functions.get(platform)

    if download_function:
        video_file = download_function(url)
        if video_file is None:
            logging.error(f"Не удалось скачать видео с {url}.")
            await loading_message.edit_text("❌ Не удалось найти видео по данной ссылке. Попробуйте другую.")
        else:
            if os.path.exists(video_file):
                try:
                    # Создаем безопасное имя для файла
                    sanitized_filename = sanitize_filename(f"{os.path.basename(video_file)}")
                    logging.info(f"Отправляю видео: {sanitized_filename}")

                    # Передаем файл через FSInputFile
                    video_input = FSInputFile(video_file, filename=sanitized_filename)
                    await loading_message.delete()  # Удаляем сообщение "Видео загружается..."
                    await message.reply_video(video_input)
                    logging.info(f"Видео успешно отправлено.")
                except Exception as e:
                    logging.error(f"Ошибка при отправке видео: {e}")
                    await loading_message.edit_text("⚠️ Произошла ошибка при отправке видео. Попробуйте позже.")
                finally:
                    try:
                        # Удаляем файл только после отправки
                        os.remove(video_file)
                        logging.info(f"Файл {video_file} удален после отправки.")
                    except Exception as e:
                        logging.error(f"Ошибка при удалении файла {video_file}: {e}")
            else:
                logging.error(f"Видео не найдено по пути {video_file}.")
                await loading_message.edit_text("❌ Не удалось найти видео. Попробуйте другую ссылку.")
    else:
        logging.error("Неизвестная платформа.")
        await loading_message.edit_text("⚠️ Произошла ошибка, попробуйте выбрать платформу снова.")

    # Показываем клавиатуру после скачивания
    await message.reply(
        "Спасибо за использование меня 😊",
        reply_markup=create_main_keyboard()
    )

    # Возвращаем состояние к выбору платформы
    await state.set_state(DownloadState.platform)  # Возвращаем к выбору платформы


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())  # Запуск основного асинхронного цикла
