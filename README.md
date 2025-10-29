# Telegram TikTok & Instagram Downloader Bot

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-green.svg)](https://github.com/aiogram/aiogram)
[![Platform](https://img.shields.io/badge/Platform-Telegram-blue.svg)](https://telegram.org/)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)](https://opensource.org/licenses/MIT)

A high-performance, asynchronous Telegram bot built to download media from TikTok and Instagram directly through a chat interface.

This bot is designed for personal use or for a small, controlled group. It listens for messages containing links, downloads the media (no-watermark TikToks, Instagram videos, and photos), and sends them back to the user instantly. The entire system is locked down so that only pre-approved admin users can interact with it, ensuring privacy and resource control.

This repository serves as a practical example of building robust, efficient, and secure bots using modern Python libraries.

## ✨ Core Features

* **TikTok Downloader:** Automatically downloads TikTok videos **without the watermark**.
* **Instagram Downloader:** Grabs both videos and photos from Instagram posts.
* **Multi-Link Support:** Parses multiple links in a single message and processes all of them.
* **Secure & Private:** The bot is **admin-locked**. Only user IDs listed in the `.env` file can use its commands, preventing public abuse.
* **Fully Asynchronous:** Built with `asyncio`, `aiogram 3.x`, and `aiohttp` for non-blocking, high-performance operation. It can handle multiple requests concurrently without breaking a sweat.
* **Robust Error Handling:** Gracefully handles invalid links, download failures, and API errors, reporting the issue to the user.
* **Admin Notifications:** Automatically sends a notification to the admin user(s) on bot startup and shutdown, confirming its online status.

---

## 🛠️ Technology Stack & Architecture

This project uses a modern, asynchronous Python stack chosen for reliability and performance.

* **Bot Framework:** **aiogram 3.x** (`aiogram==3.1.1`) - A modern, fast, and asynchronous framework for building Telegram bots.
* **Language:** **Python 3**
* **Asynchronous Networking:**
    * **aiohttp**: Used to make asynchronous HTTP requests to the external TikTok downloading API.
    * **asyncio:** The core of the bot's concurrent operations.
* **Instagram Scraping:** **Instaloader** (`instaloader==4.10.1`) - A powerful library used to scrape post data and media from Instagram. It logs in using session cookies for reliable access.
* **Configuration:** **python-dotenv** - Manages all secret keys and configuration (like `BOT_TOKEN`) from a private `.env` file.
* **Logging:** Built-in Python logging configured for clear and informative console output.

---

## 🧠 How It Works: The Core Logic

The bot's operation is straightforward but demonstrates several key development patterns.

1.  **Initialization:** The bot starts, loads the `.env` file, and initializes the `aiogram` Dispatcher and Bot objects. It sends a startup message to the admins.
2.  **Message Handling:** The bot listens for any text message using the `MessageHandler`.
3.  **Access Control:** The *very first step* is checking if the `message.from_user.id` is in the `ADMINS` list loaded from the `.env` file. If not, the bot ignores the message completely.
4.  **URL Parsing:** If the user is an admin, the bot uses a regex pattern to find all URLs in the message text.
5.  **Platform-Specific Logic:** The bot loops through the found URLs:
    * **If a "tiktok.com" link is found:**
        1.  It sends a "Processing..." message to the user.
        2.  It calls the `download_tiktok_video` function.
        3.  This function makes an async `aiohttp` GET request to an external API (`api.tiktapi.com`) to get a direct, no-watermark video link.
        4.  It sends the final video back to the user using `bot.send_video`.
    * **If an "instagram.com" link is found:**
        1.  It calls the `download_instagram_media` function.
        2.  This function initializes `Instaloader` and logs in using the session data from `ig_cookies.txt`.
        3.  It downloads the post (video or photo) to a local `downloads` directory.
        4.  It sends the downloaded file(s) back to the user using `bot.send_video` or `bot.send_photo`.
        5.  It automatically cleans up the temporary files from the server.
---

## 👨‍💼 Looking for a Developer?

Hi! I'm the developer behind this project. I specialize in building high-quality, performant, and reliable bots, scrapers, and backend systems in Python.

If you're impressed by the clean architecture and efficiency of this bot, I'm confident I can bring the same level of expertise to your project.

* **Email:** `ivsilan2005@gmail.com`

Let's build something great together.
