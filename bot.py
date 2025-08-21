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
    InputTextMessageContent, InlineQueryResultVideo, InlineQueryResultCachedVideo,
    ChatJoinRequest
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
BOT_TOKEN = "YOUR_ACTUAL_BOT_TOKEN_HERE"
ADMINS = [123456789]
DB_PATH = "media_bot.db"
PAGE_SIZE = 10
BOT_USERNAME = "your_bot_username"
REQUIRED_CHANNELS = ["@channel1", "@channel2"]  # Replace with your channel usernames

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
    waiting_for_quality = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast_message = State()
    waiting_for_user_message = State()
    waiting_for_user_id = State()

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
                    message_count INTEGER DEFAULT 0,
                    has_joined_channels BOOLEAN DEFAULT FALSE
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS movies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    year INTEGER,
                    description TEXT,
                    tags TEXT,
                    poster_file_id TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    views INTEGER DEFAULT 0,
                    downloads INTEGER DEFAULT 0,
                    category TEXT
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
                    views INTEGER DEFAULT 0,
                    category TEXT
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
                CREATE TABLE IF NOT EXISTS quality_options (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_type TEXT NOT NULL,
                    content_id INTEGER NOT NULL,
                    quality TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    file_size INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
    async def update_user_channel_status(user_id: int, has_joined: bool):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE users SET has_joined_channels = ? WHERE user_id = ?",
                    (has_joined, user_id)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Error updating user channel status: {e}")

    @staticmethod
    async def get_user_channel_status(user_id: int) -> bool:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    "SELECT has_joined_channels FROM users WHERE user_id = ?",
                    (user_id,)
                )
                result = await cursor.fetchone()
                return result[0] if result else False
        except Exception as e:
            logger.error(f"Error getting user channel status: {e}")
            return False

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
    async def add_movie(title: str, year: int, description: str, tags: str, poster_file_id: str = None, category: str = None):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    "INSERT INTO movies (title, year, description, tags, poster_file_id, category) VALUES (?, ?, ?, ?, ?, ?)",
                    (title, year, description, tags, poster_file_id, category)
                )
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding movie: {e}")
            return -1

    @staticmethod
    async def add_quality_option(content_type: str, content_id: int, quality: str, file_id: str, file_size: int = None):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO quality_options (content_type, content_id, quality, file_id, file_size) VALUES (?, ?, ?, ?, ?)",
                    (content_type, content_id, quality, file_id, file_size)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Error adding quality option: {e}")
            return False

    @staticmethod
    async def get_quality_options(content_type: str, content_id: int):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    "SELECT * FROM quality_options WHERE content_type = ? AND content_id = ? ORDER BY quality",
                    (content_type, content_id)
                )
                return await cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting quality options: {e}")
            return []

    @staticmethod
    async def add_series(title: str, description: str, tags: str, poster_file_id: str = None, category: str = None) -> int:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    "INSERT INTO series (title, description, tags, poster_file_id, category) VALUES (?, ?, ?, ?, ?)",
                    (title, description, tags, poster_file_id, category)
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
    async def add_episode(season_id: int, episode_number: int, title: str):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    "INSERT INTO episodes (season_id, episode_number, title) VALUES (?, ?, ?)",
                    (season_id, episode_number, title)
                )
                await db.commit()
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding episode: {e}")
            return -1

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
                    "SELECT 'movie' as type, id, title, year, description, category FROM movies WHERE title LIKE ? OR description LIKE ? OR tags LIKE ?",
                    (f"%{query}%", f"%{query}%", f"%{query}%")
                )
                movies = await movie_cursor.fetchall()
                
                # Search series
                series_cursor = await db.execute(
                    "SELECT 'series' as type, id, title, NULL as year, description, category FROM series WHERE title LIKE ? OR description LIKE ? OR tags LIKE ?",
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
    async def get_all_movies(sort_by: str = "newest", category: str = None, page: int = 0):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                order_by = "created_at DESC" if sort_by == "newest" else "year DESC" if sort_by == "year" else "title ASC"
                where_clause = "WHERE category = ?" if category else ""
                params = [category] if category else []
                params.append(PAGE_SIZE)
                params.append(page * PAGE_SIZE)
                
                cursor = await db.execute(
                    f"SELECT * FROM movies {where_clause} ORDER BY {order_by} LIMIT ? OFFSET ?",
                    params
                )
                return await cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting movies: {e}")
            return []

    @staticmethod
    async def get_all_series(sort_by: str = "newest", category: str = None, page: int = 0):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                order_by = "created_at DESC" if sort_by == "newest" else "title ASC"
                where_clause = "WHERE category = ?" if category else ""
                params = [category] if category else []
                params.append(PAGE_SIZE)
                params.append(page * PAGE_SIZE)
                
                cursor = await db.execute(
                    f"SELECT * FROM series {where_clause} ORDER BY {order_by} LIMIT ? OFFSET ?",
                    params
                )
                return await cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting series: {e}")
            return []

    @staticmethod
    async def get_movie_categories():
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("SELECT DISTINCT category FROM movies WHERE category IS NOT NULL")
                return [row[0] for row in await cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting movie categories: {e}")
            return []

    @staticmethod
    async def get_series_categories():
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("SELECT DISTINCT category FROM series WHERE category IS NOT NULL")
                return [row[0] for row in await cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting series categories: {e}")
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

    @staticmethod
    async def increment_download(content_type: str, content_id: int):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                if content_type == 'movie':
                    await db.execute("UPDATE movies SET downloads = downloads + 1 WHERE id = ?", (content_id,))
                elif content_type == 'episode':
                    await db.execute("UPDATE episodes SET downloads = downloads + 1 WHERE id = ?", (content_id,))
                await db.commit()
        except Exception as e:
            logger.error(f"Error incrementing download: {e}")

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
                
                cursor = await db.execute("SELECT COUNT(*) FROM users WHERE has_joined_channels = TRUE")
                stats['channel_members'] = (await cursor.fetchone())[0]
                
                # Content stats
                cursor = await db.execute("SELECT COUNT(*) FROM movies")
                stats['total_movies'] = (await cursor.fetchone())[0]
                
                cursor = await db.execute("SELECT COUNT(*) FROM series")
                stats['total_series'] = (await cursor.fetchone())[0]
                
                cursor = await db.execute("SELECT COUNT(*) FROM episodes")
                stats['total_episodes'] = (await cursor.fetchone())[0]
                
                cursor = await db.execute("SELECT COUNT(*) FROM quality_options")
                stats['total_quality_options'] = (await cursor.fetchone())[0]
                
                # View stats
                cursor = await db.execute("SELECT SUM(views) FROM movies")
                stats['movie_views'] = (await cursor.fetchone())[0] or 0
                
                cursor = await db.execute("SELECT SUM(views) FROM episodes")
                stats['episode_views'] = (await cursor.fetchone())[0] or 0
                
                cursor = await db.execute("SELECT SUM(downloads) FROM movies")
                stats['movie_downloads'] = (await cursor.fetchone())[0] or 0
                
                cursor = await db.execute("SELECT SUM(downloads) FROM episodes")
                stats['episode_downloads'] = (await cursor.fetchone())[0] or 0
                
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

def get_movies_main_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="🆕 جدیدترین‌ها", callback_data="movies_newest")],
        [InlineKeyboardButton(text="📅 بر اساس سال", callback_data="movies_by_year")],
        [InlineKeyboardButton(text="🏷️ دسته‌بندی‌ها", callback_data="movies_categories")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_series_main_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="🆕 جدیدترین‌ها", callback_data="series_newest")],
        [InlineKeyboardButton(text="🏷️ دسته‌بندی‌ها", callback_data="series_categories")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_movies_keyboard(movies: List[Tuple], page: int = 0, sort_by: str = "newest", category: str = None) -> InlineKeyboardMarkup:
    keyboard = []
    for movie in movies[page*5:(page+1)*5]:
        keyboard.append([InlineKeyboardButton(
            text=f"🎬 {movie[1]} ({movie[2]})" if movie[2] else f"🎬 {movie[1]}",
            callback_data=f"movie_{movie[0]}"
        )])
    
    # Pagination
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⏪ قبلی", callback_data=f"movies_page_{page-1}_{sort_by}_{category or ''}"))
    if len(movies) > (page+1)*5:
        nav_buttons.append(InlineKeyboardButton(text="⏩ بعدی", callback_data=f"movies_page_{page+1}_{sort_by}_{category or ''}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="show_movies")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_series_keyboard(series: List[Tuple], page: int = 0, sort_by: str = "newest", category: str = None) -> InlineKeyboardMarkup:
    keyboard = []
    for serie in series[page*5:(page+1)*5]:
        keyboard.append([InlineKeyboardButton(
            text=f"📺 {serie[1]}",
            callback_data=f"series_{serie[0]}"
        )])
    
    # Pagination
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⏪ قبلی", callback_data=f"series_page_{page-1}_{sort_by}_{category or ''}"))
    if len(series) > (page+1)*5:
        nav_buttons.append(InlineKeyboardButton(text="⏩ بعدی", callback_data=f"series_page_{page+1}_{sort_by}_{category or ''}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    
    keyboard.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="show_series")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_categories_keyboard(categories: List[str], content_type: str) -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for i, category in enumerate(categories):
        row.append(InlineKeyboardButton(text=category, callback_data=f"{content_type}_category_{category}"))
        if (i + 1) % 2 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"show_{content_type}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_quality_keyboard(quality_options: List[Tuple], content_type: str, content_id: int) -> InlineKeyboardMarkup:
    keyboard = []
    for quality in quality_options:
        quality_text = f"📦 {quality[3]}"
        if quality[5]:  # file_size
            size_mb = quality[5] / (1024 * 1024)
            quality_text += f" ({size_mb:.1f}MB)"
        keyboard.append([InlineKeyboardButton(
            text=quality_text,
            callback_data=f"download_{content_type}_{content_id}_{quality[0]}"
        )])
    
    # Add share button
    keyboard.append([InlineKeyboardButton(
        text="🔗 اشتراک‌گذاری",
        callback_data=f"share_{content_type}_{content_id}"
    )])
    
    keyboard.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"show_{content_type}")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_content_keyboard(content_type: str, content_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📥 دریافت فایل", callback_data=f"get_{content_type}_{content_id}")],
        [InlineKeyboardButton(text="🔗 اشتراک‌گذاری", callback_data=f"share_{content_type}_{content_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_channel_join_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    for channel in REQUIRED_CHANNELS:
        keyboard.append([InlineKeyboardButton(text=f"🔗 عضویت در {channel}", url=f"https://t.me/{channel[1:]}")])
    keyboard.append([InlineKeyboardButton(text="✅ من عضو شدم", callback_data="check_membership")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Channel membership check
async def check_channel_membership(user_id: int) -> bool:
    """
    IMPORTANT: For this to work properly, your bot must:
    1. Be an admin in all the required channels
    2. Have 'Get Members' permission in those channels
    3. The channels must be public or the bot must be added to private channels
    
    In production, you would use:
    await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
    """
    return await Database.get_user_channel_status(user_id)

# Handlers
@dp.message(CommandStart())
async def cmd_start(message: Message):
    # Track user
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name or ""
    
    await Database.add_or_update_user(user_id, username, first_name, last_name)
    
    # Check channel membership
    is_member = await check_channel_membership(user_id)
    is_admin = user_id in ADMINS
    
    if not is_member:
        await message.answer(
            "👋 برای استفاده از ربات، لطفا در کانال‌های زیر عضو شوید:",
            reply_markup=get_channel_join_keyboard()
        )
        return
    
    # Check for deep link
    args = message.text.split()
    
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

@dp.callback_query(F.data == "check_membership")
async def check_membership_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    # In a real scenario, you would verify actual membership using Telegram API
    # For now, we'll simulate it by updating the database
    await Database.update_user_channel_status(user_id, True)
    
    is_admin = user_id in ADMINS
    await callback.message.edit_text(
        "✅ از عضویت شما متشکریم! حالا می‌توانید از ربات استفاده کنید.",
        reply_markup=get_main_keyboard(is_admin)
    )
    await callback.answer()

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
    • عضو کانال‌ها: {stats.get('channel_members', 0)}

    🎬 محتوا:
    • فیلم‌ها: {stats.get('total_movies', 0)}
    • سریال‌ها: {stats.get('total_series', 0)}
    • اپیزودها: {stats.get('total_episodes', 0)}
    • کیفیت‌های مختلف: {stats.get('total_quality_options', 0)}

    👀 بازدیدها:
    • بازدید فیلم‌ها: {stats.get('movie_views', 0)}
    • بازدید اپیزودها: {stats.get('episode_views', 0)}

    📥 دانلودها:
    • دانلود فیلم‌ها: {stats.get('movie_downloads', 0)}
    • دانلود اپیزودها: {stats.get('episode_downloads', 0)}
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
    for i, user in enumerate(users[:10], 1):
        users_list += f"{i}. {user[2]} {user[3]} (@{user[1] or 'بدون یوزرنیم'}) - ID: {user[0]}\n"
    
    await callback.message.answer(f"{users_list}\nلطفا ID کاربر مورد نظر را وارد کنید:")
    await state.set_state(AdminStates.waiting_for_user_id)
    await callback.answer()

@dp.message(AdminStates.waiting_for_user_id)
async def process_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
        await state.update_data(target_user_id=user_id)
        await message.answer("لطفا پیام خود را وارد کنید:")
        await state.set_state(AdminStates.waiting_for_broadcast_message)
    except ValueError:
        await message.answer("❌ لطفا یک ID معتبر وارد کنید.")

@dp.message(AdminStates.waiting_for_broadcast_message)
async def process_broadcast_message(message: Message, state: FSMContext):
    data = await state.get_data()
    target_user_id = data.get('target_user_id')
    
    if target_user_id:
        # Send to specific user
        try:
            await bot.send_message(target_user_id, f"📢 پیام از ادمین:\n\n{message.text}")
            await message.answer(f"✅ پیام به کاربر {target_user_id} ارسال شد.")
        except Exception as e:
            await message.answer(f"❌ خطا در ارسال پیام: {e}")
    else:
        # Broadcast to all users
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

@dp.callback_query(F.data == "search")
async def search_callback(callback: CallbackQuery):
    await callback.message.answer("🔍 لطفا عبارت جستجو را وارد کنید:")
    await callback.answer()

@dp.message(Command("search"))
async def cmd_search(message: Message):
    await message.answer("🔍 لطفا عبارت جستجو را وارد کنید:")

@dp.message(F.text & ~F.text.startswith('/'))
async def handle_search(message: Message):
    if len(message.text) < 2:
        await message.answer("❌ عبارت جستجو باید حداقل ۲ کاراکتر باشد.")
        return
    
    try:
        results = await Database.search_content(message.text)
        if not results:
            await message.answer("❌ نتیجه‌ای یافت نشد.")
            return
        
        response = "🔍 نتایج جستجو:\n\n"
        for i, result in enumerate(results[:5], 1):
            content_type, content_id, title, year, description, category = result
            year_text = f" ({year})" if year else ""
            emoji = "🎬" if content_type == "movie" else "📺"
            response += f"{i}. {emoji} {title}{year_text}\n"
        
        await message.answer(response)
    except Exception as e:
        await message.answer("❌ خطایی در جستجو رخ داد.")

@dp.callback_query(F.data.startswith("download_"))
async def download_quality_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await check_channel_membership(user_id):
        await callback.message.answer(
            "❌ برای دانلود باید در کانال‌ها عضو باشید.",
            reply_markup=get_channel_join_keyboard()
        )
        await callback.answer()
        return
    
    data = callback.data.split('_')
    content_type = data[1]
    content_id = int(data[2])
    quality_id = int(data[3])
    
    # Get the specific quality option
    quality_options = await Database.get_quality_options(content_type, content_id)
    selected_quality = None
    for quality in quality_options:
        if quality[0] == quality_id:
            selected_quality = quality
            break
    
    if selected_quality:
        await Database.increment_download(content_type, content_id)
        await callback.message.answer_video(
            selected_quality[4],  # file_id
            caption=f"📥 دانلود با کیفیت {selected_quality[3]}"
        )
    else:
        await callback.message.answer("❌ کیفیت مورد نظر یافت نشد.")
    await callback.answer()

@dp.callback_query(F.data.startswith("get_"))
async def get_content_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await check_channel_membership(user_id):
        await callback.message.answer(
            "❌ برای دانلود باید در کانال‌ها عضو باشید.",
            reply_markup=get_channel_join_keyboard()
        )
        await callback.answer()
        return
    
    data = callback.data.split('_')
    content_type = data[1]
    content_id = int(data[2])
    
    quality_options = await Database.get_quality_options(content_type, content_id)
    if quality_options:
        await callback.message.answer(
            "🎯 لطفا کیفیت مورد نظر را انتخاب کنید:",
            reply_markup=get_quality_keyboard(quality_options, content_type, content_id)
        )
    else:
        await callback.message.answer("❌ فایلی برای دانلود موجود نیست.")
    await callback.answer()

@dp.callback_query(F.data.startswith("share_"))
async def share_content_callback(callback: CallbackQuery):
    data = callback.data.split('_')
    content_type = data[1]
    content_id = int(data[2])
    
    share_url = f"https://t.me/{BOT_USERNAME}?start={content_type}_{content_id}"
    await callback.message.answer(f"🔗 لینک اشتراک‌گذاری:\n{share_url}")
    await callback.answer()

@dp.callback_query(F.data == "show_movies")
async def show_movies_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "🎬 فیلم‌ها را بر اساس چه معیاری می‌خواهید مشاهده کنید؟",
        reply_markup=get_movies_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "show_series")
async def show_series_callback(callback: CallbackQuery):
    await callback.message.edit_text(
        "📺 سریال‌ها را بر اساس چه معیاری می‌خواهید مشاهده کنید؟",
        reply_markup=get_series_main_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "movies_newest")
async def movies_newest_callback(callback: CallbackQuery):
    movies = await Database.get_all_movies("newest")
    if not movies:
        await callback.message.answer("❌ هیچ فیلمی موجود نیست.")
        await callback.answer()
        return
    
    await callback.message.edit_text(
        "🎬 جدیدترین فیلم‌ها:",
        reply_markup=get_movies_keyboard(movies, 0, "newest")
    )
    await callback.answer()

@dp.callback_query(F.data == "movies_by_year")
async def movies_by_year_callback(callback: CallbackQuery):
    movies = await Database.get_all_movies("year")
    if not movies:
        await callback.message.answer("❌ هیچ فیلمی موجود نیست.")
        await callback.answer()
        return
    
    await callback.message.edit_text(
        "🎬 فیلم‌ها بر اساس سال:",
        reply_markup=get_movies_keyboard(movies, 0, "year")
    )
    await callback.answer()

@dp.callback_query(F.data == "movies_categories")
async def movies_categories_callback(callback: CallbackQuery):
    categories = await Database.get_movie_categories()
    if not categories:
        await callback.message.answer("❌ هیچ دسته‌بندی‌ای موجود نیست.")
        await callback.answer()
        return
    
    await callback.message.edit_text(
        "🏷️ انتخاب دسته‌بندی فیلم:",
        reply_markup=get_categories_keyboard(categories, "movies")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("movies_category_"))
async def movies_category_callback(callback: CallbackQuery):
    category = callback.data.split('_')[2]
    movies = await Database.get_all_movies("newest", category)
    if not movies:
        await callback.message.answer(f"❌ هیچ فیلمی در دسته‌بندی {category} موجود نیست.")
        await callback.answer()
        return
    
    await callback.message.edit_text(
        f"🎬 فیلم‌های دسته‌بندی {category}:",
        reply_markup=get_movies_keyboard(movies, 0, "newest", category)
    )
    await callback.answer()

@dp.callback_query(F.data == "series_newest")
async def series_newest_callback(callback: CallbackQuery):
    series = await Database.get_all_series("newest")
    if not series:
        await callback.message.answer("❌ هیچ سریالی موجود نیست.")
        await callback.answer()
        return
    
    await callback.message.edit_text(
        "📺 جدیدترین سریال‌ها:",
        reply_markup=get_series_keyboard(series, 0, "newest")
    )
    await callback.answer()

@dp.callback_query(F.data == "series_categories")
async def series_categories_callback(callback: CallbackQuery):
    categories = await Database.get_series_categories()
    if not categories:
        await callback.message.answer("❌ هیچ دسته‌بندی‌ای موجود نیست.")
        await callback.answer()
        return
    
    await callback.message.edit_text(
        "🏷️ انتخاب دسته‌بندی سریال:",
        reply_markup=get_categories_keyboard(categories, "series")
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("series_category_"))
async def series_category_callback(callback: CallbackQuery):
    category = callback.data.split('_')[2]
    series = await Database.get_all_series("newest", category)
    if not series:
        await callback.message.answer(f"❌ هیچ سریالی در دسته‌بندی {category} موجود نیست.")
        await callback.answer()
        return
    
    await callback.message.edit_text(
        f"📺 سریال‌های دسته‌بندی {category}:",
        reply_markup=get_series_keyboard(series, 0, "newest", category)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("movies_page_"))
async def movies_page_callback(callback: CallbackQuery):
    data = callback.data.split('_')
    page = int(data[2])
    sort_by = data[3]
    category = data[4] if len(data) > 4 and data[4] != '' else None
    
    movies = await Database.get_all_movies(sort_by, category, page)
    await callback.message.edit_reply_markup(reply_markup=get_movies_keyboard(movies, page, sort_by, category))
    await callback.answer()

@dp.callback_query(F.data.startswith("series_page_"))
async def series_page_callback(callback: CallbackQuery):
    data = callback.data.split('_')
    page = int(data[2])
    sort_by = data[3]
    category = data[4] if len(data) > 4 and data[4] != '' else None
    
    series = await Database.get_all_series(sort_by, category, page)
    await callback.message.edit_reply_markup(reply_markup=get_series_keyboard(series, page, sort_by, category))
    await callback.answer()

@dp.callback_query(F.data.startswith("movie_"))
async def movie_detail_callback(callback: CallbackQuery):
    movie_id = int(callback.data.split('_')[1])
    movie = await Database.get_movie_by_id(movie_id)
    if movie:
        await Database.increment_view('movie', movie_id)
        response = f"🎬 {movie[1]} ({movie[2]})\n\n{movie[3]}\n\n🏷️ {movie[4]}"
        if movie[9]:  # category
            response += f"\n📂 دسته‌بندی: {movie[9]}"
        
        await callback.message.answer(response, reply_markup=get_content_keyboard('movie', movie_id))
    else:
        await callback.message.answer("❌ فیلم مورد نظر یافت نشد.")
    await callback.answer()

@dp.callback_query(F.data.startswith("series_"))
async def series_detail_callback(callback: CallbackQuery):
    series_id = int(callback.data.split('_')[1])
    series = await Database.get_series_by_id(series_id)
    if series:
        await Database.increment_view('series', series_id)
        episodes = await Database.get_episodes_by_series(series_id)
        
        response = f"📺 {series[1]}\n\n{series[2]}\n\n🏷️ {series[3]}"
        if series[7]:  # category
            response += f"\n📂 دسته‌بندی: {series[7]}"
        
        response += "\n\n📋 لیست اپیزودها:\n"
        for ep in episodes:
            response += f"• قسمت {ep[3]}: {ep[2] or 'بدون عنوان'}\n"
        
        await callback.message.answer(response, reply_markup=get_content_keyboard('series', series_id))
    else:
        await callback.message.answer("❌ سریال مورد نظر یافت نشد.")
    await callback.answer()

# Media upload handler
@dp.message(F.content_type.in_({ContentType.VIDEO, ContentType.DOCUMENT}))
async def handle_media_upload(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await message.answer("❌ فقط ادمین‌ها می‌توانند محتوا آپلود کنند.")
        return

    # Get file_id from video or document
    file_id = None
    if message.video:
        file_id = message.video.file_id
    elif message.document:
        # Check if it's a video file
        mime_type = getattr(message.document, 'mime_type', '')
        if mime_type and mime_type.startswith('video/'):
            file_id = message.document.file_id
    
    if not file_id:
        await message.answer("❌ لطفا یک فایل ویدیویی ارسال کنید.")
        return

    await state.update_data(file_id=file_id)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 فیلم", callback_data="upload_movie")],
        [InlineKeyboardButton(text="📺 سریال", callback_data="upload_series")]
    ])
    
    await message.answer(
        "📝 لطفا نوع محتوای آپلود شده را انتخاب کنید:",
        reply_markup=keyboard
    )
    await state.set_state(UploadStates.waiting_for_type)

# Upload type callbacks
@dp.callback_query(F.data == "upload_movie")
async def upload_movie_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🎬 لطفا اطلاعات فیلم را به این فرمت وارد کنید:\n"
        "عنوان | سال | توضیحات | تگ‌ها | دسته‌بندی (اختیاری)\n\n"
        "مثال:\n"
        "اینترلستلر | 2014 | فیلمی درباره سفر در فضا | علمی تخیلی,فضا,کریستوفر نولان | علمی تخیلی"
    )
    await state.set_state(UploadStates.waiting_for_movie_metadata)
    await callback.answer()

@dp.callback_query(F.data == "upload_series")
async def upload_series_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📺 لطفا اطلاعات سریال را به این فرمت وارد کنید:\n"
        "عنوان | توضیحات | تگ‌ها | دسته‌بندی (اختیاری)\n\n"
        "مثال:\n"
        "بریکینگ بد | سریال درباره یک معلم شیمی که متافی می‌سازد | درام,جنایی,متافی | درام"
    )
    await state.set_state(UploadStates.waiting_for_series_metadata)
    await callback.answer()

# Movie metadata handler
@dp.message(UploadStates.waiting_for_movie_metadata)
async def process_movie_metadata(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        parts = message.text.split('|')
        if len(parts) < 4:
            await message.answer("❌ فرمت وارد شده صحیح نیست. لطفا از فرمت گفته شده استفاده کنید.")
            return
        
        title = parts[0].strip()
        year = int(parts[1].strip())
        description = parts[2].strip()
        tags = parts[3].strip()
        category = parts[4].strip() if len(parts) > 4 else None
        
        movie_id = await Database.add_movie(title, year, description, tags, None, category)
        if movie_id == -1:
            await message.answer("❌ خطا در اضافه کردن فیلم.")
            await state.clear()
            return
        
        await state.update_data(content_type='movie', content_id=movie_id)
        await message.answer(
            "✅ اطلاعات فیلم ذخیره شد! حالا کیفیت‌ها را اضافه کنید:\n"
            "فرمت: کیفیت | file_id\n\n"
            "مثال:\n"
            "1080p | file_id_here\n"
            "720p | file_id_here\n\n"
            "پس از اتمام 'تمام' بنویسید."
        )
        await state.set_state(UploadStates.waiting_for_quality)
        
    except ValueError as e:
        await message.answer(f"❌ خطا در فرمت داده‌ها: {e}")
    except Exception as e:
        await message.answer(f"❌ خطا در پردازش اطلاعات: {e}")
        await state.clear()

# Series metadata handler
@dp.message(UploadStates.waiting_for_series_metadata)
async def process_series_metadata(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        parts = message.text.split('|')
        if len(parts) < 3:
            await message.answer("❌ فرمت وارد شده صحیح نیست. لطفا از فرمت گفته شده استفاده کنید.")
            return
        
        title = parts[0].strip()
        description = parts[1].strip()
        tags = parts[2].strip()
        category = parts[3].strip() if len(parts) > 3 else None
        
        series_id = await Database.add_series(title, description, tags, None, category)
        if series_id == -1:
            await message.answer("❌ خطا در اضافه کردن سریال.")
            await state.clear()
            return
            
        await state.update_data(series_id=series_id)
        
        await message.answer("✅ سریال اضافه شد! حالا شماره فصل را وارد کنید:")
        await state.set_state(UploadStates.waiting_for_season_metadata)
        
    except Exception as e:
        await message.answer(f"❌ خطا در پردازش اطلاعات: {e}")
        await state.clear()

# Season metadata handler
@dp.message(UploadStates.waiting_for_season_metadata)
async def process_season_metadata(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        season_number = int(message.text.strip())
        
        season_id = await Database.add_season(data['series_id'], season_number)
        if season_id == -1:
            await message.answer("❌ خطا در اضافه کردن فصل.")
            await state.clear()
            return
            
        await state.update_data(season_id=season_id)
        
        await message.answer(
            "📝 لطفا اطلاعات اپیزود را وارد کنید:\n"
            "شماره اپیزود | عنوان (اختیاری)\n\n"
            "مثال:\n"
            "1 | قسمت اول"
        )
        await state.set_state(UploadStates.waiting_for_episode_metadata)
        
    except ValueError:
        await message.answer("❌ لطفا یک عدد معتبر وارد کنید:")
    except Exception as e:
        await message.answer(f"❌ خطا: {e}")
        await state.clear()

# Episode metadata handler
@dp.message(UploadStates.waiting_for_episode_metadata)
async def process_episode_metadata(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        parts = message.text.split('|')
        episode_number = int(parts[0].strip())
        title = parts[1].strip() if len(parts) > 1 else f"قسمت {episode_number}"
        
        episode_id = await Database.add_episode(data['season_id'], episode_number, title)
        if episode_id == -1:
            await message.answer("❌ خطا در اضافه کردن اپیزود.")
            await state.clear()
            return
        
        await state.update_data(content_type='episode', content_id=episode_id)
        await message.answer(
            "✅ اپیزود اضافه شد! حالا کیفیت‌ها را اضافه کنید:\n"
            "فرمت: کیفیت | file_id\n\n"
            "مثال:\n"
            "1080p | file_id_here\n"
            "720p | file_id_here\n\n"
            "پس از اتمام 'تمام' بنویسید."
        )
        await state.set_state(UploadStates.waiting_for_quality)
        
    except Exception as e:
        await message.answer(f"❌ خطا: {e}")
        await state.clear()

# Quality upload handler
@dp.message(UploadStates.waiting_for_quality)
async def process_quality_upload(message: Message, state: FSMContext):
    if message.text.lower() in ['تمام', 'done', 'finish']:
        await message.answer("✅ فرآیند آپلود کامل شد!")
        await state.clear()
        return
    
    try:
        data = await state.get_data()
        content_type = data['content_type']
        content_id = data['content_id']
        
        # Expecting format: quality | file_id
        parts = message.text.split('|')
        if len(parts) < 2:
            await message.answer("❌ فرمت صحیح: کیفیت | file_id")
            return
        
        quality = parts[0].strip()
        file_id = parts[1].strip()
        
        success = await Database.add_quality_option(content_type, content_id, quality, file_id)
        if success:
            await message.answer(f"✅ کیفیت {quality} اضافه شد! کیفیت دیگر اضافه کنید یا 'تمام' بنویسید.")
        else:
            await message.answer("❌ خطا در اضافه کردن کیفیت.")
        
    except Exception as e:
        await message.answer(f"❌ خطا: {e}")

# Alternative names handler (for series)
@dp.message(UploadStates.waiting_for_alternative_names)
async def process_alternative_names(message: Message, state: FSMContext):
    if message.text.lower() in ['خیر', 'no', 'نه']:
        await message.answer("✅ فرآیند آپلود کامل شد!")
        await state.clear()
        return
    
    try:
        data = await state.get_data()
        success = await Database.add_alternative_name('series', data['series_id'], message.text)
        if success:
            await message.answer("✅ نام جایگزین اضافه شد! نام دیگر وارد کنید یا 'خیر' بفرستید.")
        else:
            await message.answer("❌ خطا در اضافه کردن نام جایگزین.")
            await state.clear()
    except Exception as e:
        await message.answer(f"❌ خطا: {e}")
        await state.clear()

async def handle_deep_link(message: Message, deep_link: str, is_admin: bool):
    try:
        if deep_link.startswith('movie_'):
            movie_id = int(deep_link.split('_')[1])
            movie = await Database.get_movie_by_id(movie_id)
            if movie:
                await Database.increment_view('movie', movie_id)
                response = f"🎬 {movie[1]} ({movie[2]})\n\n{movie[3]}\n\n🏷️ {movie[4]}"
                if movie[9]:  # category
                    response += f"\n📂 دسته‌بندی: {movie[9]}"
                
                await message.answer(response, reply_markup=get_content_keyboard('movie', movie_id))
            else:
                await message.answer("❌ فیلم مورد نظر یافت نشد.")
        
        elif deep_link.startswith('series_'):
            series_id = int(deep_link.split('_')[1])
            series = await Database.get_series_by_id(series_id)
            if series:
                await Database.increment_view('series', series_id)
                episodes = await Database.get_episodes_by_series(series_id)
                
                response = f"📺 {series[1]}\n\n{series[2]}\n\n🏷️ {series[3]}"
                if series[7]:  # category
                    response += f"\n📂 دسته‌بندی: {series[7]}"
                
                response += "\n\n📋 لیست اپیزودها:\n"
                for ep in episodes:
                    response += f"• قسمت {ep[3]}: {ep[2] or 'بدون عنوان'}\n"
                
                await message.answer(response, reply_markup=get_content_keyboard('series', series_id))
            else:
                await message.answer("❌ سریال مورد نظر یافت نشد.")
        
        else:
            await message.answer("لینک معتبر نیست.")
    
    except Exception as e:
        logger.error(f"Deep link error: {e}")
        await message.answer("❌ خطا در پردازش لینک.")

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
