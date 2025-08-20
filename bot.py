#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import asyncio
import json
from datetime import datetime
from typing import List, Optional, Union, Any, Tuple, Dict

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove, ContentType, InlineQuery, InlineQueryResultArticle,
    InputTextMessageContent, InlineQueryResultVideo, InlineQueryResultCachedVideo
)
from aiogram.filters import Command, CommandStart, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
import aiosqlite

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = "8417638218:AAGfO3ubY0ruAVsoF9-stdUM9U7nLDvTXg4"
ADMINS = [123661460]
DB_PATH = "media_bot.db"
PAGE_SIZE = 10
BOT_USERNAME = "your_bot_username"  # Replace with your bot username without @

# Initialize bot and dispatcher
try:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
except Exception as e:
    logger.error(f"Failed to initialize bot: {e}")
    exit(1)

# States
class UploadStates(StatesGroup):
    waiting_for_type = State()
    waiting_for_movie_metadata = State()
    waiting_for_series_metadata = State()
    waiting_for_season_metadata = State()
    waiting_for_episode_metadata = State()
    waiting_for_alternative_names = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast_message = State()
    waiting_for_user_message = State()

# Database initialization
async def init_database():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            
            # Users table for stats and messaging
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    joined_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_active DATETIME DEFAULT CURRENT_TIMESTAMP,
                    message_count INTEGER DEFAULT 0
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS movies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    year INTEGER,
                    description TEXT,
                    tags TEXT,
                    file_id TEXT NOT NULL,
                    poster_file_id TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    views INTEGER DEFAULT 0,
                    downloads INTEGER DEFAULT 0
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS series (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    tags TEXT,
                    poster_file_id TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    views INTEGER DEFAULT 0
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS seasons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_id INTEGER NOT NULL,
                    season_number INTEGER NOT NULL,
                    FOREIGN KEY (series_id) REFERENCES series (id) ON DELETE CASCADE
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    season_id INTEGER NOT NULL,
                    episode_number INTEGER NOT NULL,
                    title TEXT,
                    file_id TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    views INTEGER DEFAULT 0,
                    downloads INTEGER DEFAULT 0,
                    FOREIGN KEY (season_id) REFERENCES seasons (id) ON DELETE CASCADE
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS alternative_names (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_type TEXT NOT NULL,
                    content_id INTEGER NOT NULL,
                    name TEXT NOT NULL
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    content_id INTEGER,
                    content_type TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await db.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

# Database operations
class Database:
    # User management
    @staticmethod
    async def add_or_update_user(user_id: int, username: str, first_name: str, last_name: str):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """INSERT OR REPLACE INTO users 
                    (user_id, username, first_name, last_name, last_active) 
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    (user_id, username, first_name, last_name)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Error updating user: {e}")

    @staticmethod
    async def increment_user_message_count(user_id: int):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE users SET message_count = message_count + 1 WHERE user_id = ?",
                    (user_id,)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Error incrementing message count: {e}")

    @staticmethod
    async def get_all_users():
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("SELECT * FROM users")
                return await cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting users: {e}")
            return []

    # Content management
    @staticmethod
    async def add_movie(title: str, year: int, description: str, tags: str, file_id: str, poster_file_id: str = None):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO movies (title, year, description, tags, file_id, poster_file_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (title, year, description, tags, file_id, poster_file_id)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Error adding movie: {e}")
            return False

    @staticmethod
    async def add_series(title: str, description: str, tags: str, poster_file_id: str = None) -> int:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    "INSERT INTO series (title, description, tags, poster_file_id) VALUES (?, ?, ?, ?)",
                    (title, description, tags, poster_file_id)
                )
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding series: {e}")
            return -1

    @staticmethod
    async def add_season(series_id: int, season_number: int) -> int:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    "INSERT INTO seasons (series_id, season_number) VALUES (?, ?)",
                    (series_id, season_number)
                )
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding season: {e}")
            return -1

    @staticmethod
    async def add_episode(season_id: int, episode_number: int, title: str, file_id: str):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO episodes (season_id, episode_number, title, file_id) VALUES (?, ?, ?, ?)",
                    (season_id, episode_number, title, file_id)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Error adding episode: {e}")
            return False

    @staticmethod
    async def add_alternative_name(content_type: str, content_id: int, name: str):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO alternative_names (content_type, content_id, name) VALUES (?, ?, ?)",
                    (content_type, content_id, name)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Error adding alternative name: {e}")
            return False

    # Search and retrieval
    @staticmethod
    async def search_content(query: str) -> List[Tuple]:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                # Search movies
                movie_cursor = await db.execute(
                    "SELECT 'movie' as type, id, title, year, description, file_id FROM movies WHERE title LIKE ? OR description LIKE ? OR tags LIKE ?",
                    (f"%{query}%", f"%{query}%", f"%{query}%")
                )
                movies = await movie_cursor.fetchall()
                
                # Search series
                series_cursor = await db.execute(
                    "SELECT 'series' as type, id, title, NULL as year, description, NULL as file_id FROM series WHERE title LIKE ? OR description LIKE ? OR tags LIKE ?",
                    (f"%{query}%", f"%{query}%", f"%{query}%")
                )
                series = await series_cursor.fetchall()
                
                return movies + series
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    @staticmethod
    async def get_movie_by_id(movie_id: int):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("SELECT * FROM movies WHERE id = ?", (movie_id,))
                return await cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting movie: {e}")
            return None

    @staticmethod
    async def get_series_by_id(series_id: int):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("SELECT * FROM series WHERE id = ?", (series_id,))
                return await cursor.fetchone()
        except Exception as e:
            logger.error(f"Error getting series: {e}")
            return None

    @staticmethod
    async def get_episodes_by_series(series_id: int):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    """SELECT e.* FROM episodes e 
                    JOIN seasons s ON e.season_id = s.id 
                    WHERE s.series_id = ? ORDER BY s.season_number, e.episode_number""",
                    (series_id,)
                )
                return await cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting episodes: {e}")
            return []

    @staticmethod
    async def increment_view(content_type: str, content_id: int):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                if content_type == 'movie':
                    await db.execute("UPDATE movies SET views = views + 1 WHERE id = ?", (content_id,))
                elif content_type == 'episode':
                    await db.execute("UPDATE episodes SET views = views + 1 WHERE id = ?", (content_id,))
                elif content_type == 'series':
                    await db.execute("UPDATE series SET views = views + 1 WHERE id = ?", (content_id,))
                await db.commit()
        except Exception as e:
            logger.error(f"Error incrementing view: {e}")

    # Stats
    @staticmethod
    async def get_stats():
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                stats = {}
                
                # User stats
                cursor = await db.execute("SELECT COUNT(*) FROM users")
                stats['total_users'] = (await cursor.fetchone())[0]
                
                cursor = await db.execute("SELECT COUNT(*) FROM users WHERE date(last_active) = date('now')")
                stats['active_today'] = (await cursor.fetchone())[0]
                
                # Content stats
                cursor = await db.execute("SELECT COUNT(*) FROM movies")
                stats['total_movies'] = (await cursor.fetchone())[0]
                
                cursor = await db.execute("SELECT COUNT(*) FROM series")
                stats['total_series'] = (await cursor.fetchone())[0]
                
                cursor = await db.execute("SELECT COUNT(*) FROM episodes")
                stats['total_episodes'] = (await cursor.fetchone())[0]
                
                # View stats
                cursor = await db.execute("SELECT SUM(views) FROM movies")
                stats['movie_views'] = (await cursor.fetchone())[0] or 0
                
                cursor = await db.execute("SELECT SUM(views) FROM episodes")
                stats['episode_views'] = (await cursor.fetchone())[0] or 0
                
                return stats
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}

# Keyboard helpers
def get_main_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="🎬 فیلم‌ها", callback_data="show_movies"),
         InlineKeyboardButton(text="📺 سریال‌ها", callback_data="show_series")],
        [InlineKeyboardButton(text="🔍 جستجو", callback_data="search")]
    ]
    if is_admin:
        keyboard.append([InlineKeyboardButton(text="⚙️ پنل ادمین", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📊 آمار کامل", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📤 ارسال پیام به کاربران", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="✉️ ارسال پیام به کاربر", callback_data="admin_message_user")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_content_keyboard(content_type: str, content_id: int, file_id: str) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📥 دریافت فایل", callback_data=f"get_{content_type}_{content_id}")],
        [InlineKeyboardButton(text="🔗 اشتراک‌گذاری", callback_data=f"share_{content_type}_{content_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Handlers
@dp.message(CommandStart())
async def cmd_start(message: Message):
    # Track user
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name or ""
    
    await Database.add_or_update_user(user_id, username, first_name, last_name)
    
    # Check for deep link
    args = message.text.split()
    is_admin = user_id in ADMINS
    
    if len(args) > 1:
        deep_link = args[1]
        await handle_deep_link(message, deep_link, is_admin)
    else:
        welcome_text = """
        🤖 به ربات مدیا خوش آمدید!

        🔍 می‌توانید فیلم و سریال جستجو کنید
        🎬 محتوای مورد نظر خود را پیدا کنید
        📺 از تماشای محتوا لذت ببرید

        برای شروع از دکمه‌های زیر استفاده کنید:
        """
        await message.answer(welcome_text, reply_markup=get_main_keyboard(is_admin))

async def handle_deep_link(message: Message, deep_link: str, is_admin: bool):
    try:
        if deep_link.startswith('movie_'):
            movie_id = int(deep_link.split('_')[1])
            movie = await Database.get_movie_by_id(movie_id)
            if movie:
                await Database.increment_view('movie', movie_id)
                await message.answer_video(
                    movie[5],  # file_id
                    caption=f"🎬 {movie[1]} ({movie[2]})\n\n{movie[3]}\n\n🏷️ {movie[4]}",
                    reply_markup=get_content_keyboard('movie', movie_id, movie[5])
                )
            else:
                await message.answer("❌ فیلم مورد نظر یافت نشد.")
        
        elif deep_link.startswith('series_'):
            series_id = int(deep_link.split('_')[1])
            series = await Database.get_series_by_id(series_id)
            if series:
                await Database.increment_view('series', series_id)
                episodes = await Database.get_episodes_by_series(series_id)
                
                response = f"📺 {series[1]}\n\n{series[2]}\n\n🏷️ {series[3]}\n\n📋 لیست اپیزودها:\n"
                for ep in episodes:
                    response += f"• قسمت {ep[3]}: {ep[2] or 'بدون عنوان'}\n"
                
                await message.answer(response)
            else:
                await message.answer("❌ سریال مورد نظر یافت نشد.")
        
        else:
            await message.answer("لینک معتبر نیست.")
    
    except Exception as e:
        logger.error(f"Deep link error: {e}")
        await message.answer("❌ خطا در پردازش لینک.")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = """
    📖 راهنمای ربات:

    /start - شروع ربات
    /help - راهنما
    /search - جستجوی محتوا
    /admin - پنل مدیریت (فقط ادمین)

    👨‍💼 ادمین‌ها می‌توانند:
    • آپلود محتوا با ارسال ویدیو
    • ویرایش اطلاعات
    • مدیریت محتوا
    """
    await message.answer(help_text)

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMINS:
        await message.answer("❌ شما دسترسی ادمین ندارید.")
        return
    await message.answer("⚙️ پنل مدیریت ادمین", reply_markup=get_admin_keyboard())

# Callback handlers
@dp.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    is_admin = callback.from_user.id in ADMINS
    await callback.message.edit_text(
        "🤖 به ربات مدیا خوش آمدید!",
        reply_markup=get_main_keyboard(is_admin)
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ دسترسی denied")
        return
    
    await callback.message.edit_text(
        "⚙️ پنل مدیریت ادمین",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ دسترسی denied")
        return
    
    stats = await Database.get_stats()
    stats_text = f"""
    📊 آمار کامل ربات:

    👥 کاربران:
    • کل کاربران: {stats.get('total_users', 0)}
    • کاربران فعال امروز: {stats.get('active_today', 0)}

    🎬 محتوا:
    • فیلم‌ها: {stats.get('total_movies', 0)}
    • سریال‌ها: {stats.get('total_series', 0)}
    • اپیزودها: {stats.get('total_episodes', 0)}

    👀 بازدیدها:
    • بازدید فیلم‌ها: {stats.get('movie_views', 0)}
    • بازدید اپیزودها: {stats.get('episode_views', 0)}
    """
    
    await callback.message.edit_text(stats_text, reply_markup=get_admin_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ دسترسی denied")
        return
    
    await callback.message.answer("📤 لطفا پیام خود برای ارسال به همه کاربران را وارد کنید:")
    await state.set_state(AdminStates.waiting_for_broadcast_message)
    await callback.answer()

@dp.callback_query(F.data == "admin_message_user")
async def admin_message_user_callback(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ دسترسی denied")
        return
    
    users = await Database.get_all_users()
    if not users:
        await callback.message.answer("❌ کاربری وجود ندارد.")
        return
    
    users_list = "👥 لیست کاربران:\n\n"
    for i, user in enumerate(users, 1):
        users_list += f"{i}. {user[2]} {user[3]} (@{user[1] or 'بدون یوزرنیم'}) - ID: {user[0]}\n"
    
    await callback.message.answer(f"{users_list}\nلطفا ID کاربر مورد نظر را وارد کنید:")
    await state.set_state(AdminStates.waiting_for_user_message)
    await callback.answer()

@dp.message(AdminStates.waiting_for_broadcast_message)
async def process_broadcast_message(message: Message, state: FSMContext):
    users = await Database.get_all_users()
    success_count = 0
    fail_count = 0
    
    for user in users:
        try:
            await bot.send_message(user[0], f"📢 پیام از ادمین:\n\n{message.text}")
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to send message to user {user[0]}: {e}")
            fail_count += 1
    
    await message.answer(f"✅ پیام به {success_count} کاربر ارسال شد.\n❌ {fail_count} ارسال ناموفق.")
    await state.clear()

@dp.message(AdminStates.waiting_for_user_message)
async def process_user_message(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
        await state.update_data(target_user_id=user_id)
        await message.answer("لطفا پیام خود را وارد کنید:")
        await state.set_state(AdminStates.waiting_for_broadcast_message)
    except ValueError:
        await message.answer("❌ لطفا یک ID معتبر وارد کنید.")

# ... (rest of the handlers for search, upload, etc. remain similar but enhanced)

@dp.callback_query(F.data.startswith("get_"))
async def get_content_callback(callback: CallbackQuery):
    data = callback.data.split('_')
    content_type = data[1]
    content_id = int(data[2])
    
    if content_type == 'movie':
        movie = await Database.get_movie_by_id(content_id)
        if movie:
            await Database.increment_view('movie', content_id)
            await callback.message.answer_video(
                movie[5],
                caption=f"🎬 {movie[1]} ({movie[2]})\n\n{movie[3]}\n\n🏷️ {movie[4]}"
            )
    elif content_type == 'episode':
        # Similar logic for episodes
        pass
    
    await callback.answer()

@dp.callback_query(F.data.startswith("share_"))
async def share_content_callback(callback: CallbackQuery):
    data = callback.data.split('_')
    content_type = data[1]
    content_id = int(data[2])
    
    share_url = f"https://t.me/{BOT_USERNAME}?start={content_type}_{content_id}"
    await callback.message.answer(f"🔗 لینک اشتراک‌گذاری:\n{share_url}")
    await callback.answer()

# Inline query handler for search
@dp.inline_query()
async def inline_search(query: InlineQuery):
    results = await Database.search_content(query.query)
    inline_results = []
    
    for result in results[:15]:
        content_type, content_id, title, year, description, file_id = result
        year_text = f" ({year})" if year else ""
        
        if content_type == 'movie' and file_id:
            inline_results.append(InlineQueryResultCachedVideo(
                id=str(content_id),
                video_file_id=file_id,
                title=f"{title}{year_text}",
                description=description[:100] if description else "",
                caption=f"🎬 {title}{year_text}\n\n{description or 'بدون توضیح'}"
            ))
    
    await query.answer(inline_results, cache_time=300)

# Error handler
@dp.errors()
async def error_handler(event, exception):
    logger.error(f"Error occurred: {exception}")

# Main function
async def main():
    await init_database()
    print("✅ Database initialized")
    print("🚀 Starting bot...")
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    print("🤖 Starting Persian Media Bot...")
    if BOT_TOKEN == "YOUR_ACTUAL_BOT_TOKEN_HERE":
        print("❌ ERROR: Please replace BOT_TOKEN")
    else:
        asyncio.run(main())
