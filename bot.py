import os
import re
import logging
import asyncio
import uuid
from typing import Dict, List, Optional, Tuple, Union
from datetime import datetime

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
    KeyboardButton, InputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.utils.media_group import MediaGroupBuilder

# Database setup - using SQLite for simplicity
import sqlite3
from contextlib import contextmanager

# Configuration
BOT_TOKEN = "8417638218:AAGfO3ubY0ruAVsoF9-stdUM9U7nLDvTXg4"
ADMINS = [123661460]
DB_PATH = "media_bot.db"
BOT_USERNAME = "bdgfilm_bot"
REQUIRED_CHANNELS = ["@booodgeh"]
BASE_SHARE_URL = f"https://t.me/{BOT_USERNAME}?start="

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database setup
@contextmanager
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Movies table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                year INTEGER,
                description TEXT,
                tags TEXT,
                alternative_names TEXT,
                poster_file_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                share_uuid TEXT UNIQUE
            )
        ''')
        
        # Movie files table (for multiple qualities)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS movie_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                movie_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                quality TEXT NOT NULL,
                file_size INTEGER,
                duration INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (movie_id) REFERENCES movies (id) ON DELETE CASCADE
            )
        ''')
        
        # Series table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS series (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                tags TEXT,
                alternative_names TEXT,
                poster_file_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                share_uuid TEXT UNIQUE
            )
        ''')
        
        # Seasons table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS seasons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                series_id INTEGER NOT NULL,
                season_number INTEGER NOT NULL,
                title TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (series_id) REFERENCES series (id) ON DELETE CASCADE
            )
        ''')
        
        # Episodes table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                season_id INTEGER NOT NULL,
                episode_number INTEGER NOT NULL,
                title TEXT,
                alternative_names TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                share_uuid TEXT UNIQUE,
                FOREIGN KEY (season_id) REFERENCES seasons (id) ON DELETE CASCADE
            )
        ''')
        
        # Episode files table (for multiple qualities)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS episode_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                quality TEXT NOT NULL,
                file_size INTEGER,
                duration INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (episode_id) REFERENCES episodes (id) ON DELETE CASCADE
            )
        ''')
        
        # Users table for tracking channel membership
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_channels BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Genres table for better categorization
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS genres (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Movie genres relationship table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS movie_genres (
                movie_id INTEGER,
                genre_id INTEGER,
                PRIMARY KEY (movie_id, genre_id),
                FOREIGN KEY (movie_id) REFERENCES movies (id) ON DELETE CASCADE,
                FOREIGN KEY (genre_id) REFERENCES genres (id) ON DELETE CASCADE
            )
        ''')
        
        # Series genres relationship table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS series_genres (
                series_id INTEGER,
                genre_id INTEGER,
                PRIMARY KEY (series_id, genre_id),
                FOREIGN KEY (series_id) REFERENCES series (id) ON DELETE CASCADE,
                FOREIGN KEY (genre_id) REFERENCES genres (id) ON DELETE CASCADE
            )
        ''')
        
        # Insert default genres
        default_genres = [
            "اکشن", "ماجراجویی", "کمدی", "درام", "فانتزی", 
            "تاریخی", "ترسناک", "علمی تخیلی", "رمانتیک", "هیجان انگیز",
            "جنایی", "انیمیشن", "مستند", "بیوگرافی", "جنگی"
        ]
        
        for genre in default_genres:
            cursor.execute(
                "INSERT OR IGNORE INTO genres (name) VALUES (?)",
                (genre,)
            )
        
        conn.commit()

# Initialize database
init_db()

# States for FSM
class AdminStates(StatesGroup):
    waiting_for_movie_title = State()
    waiting_for_movie_year = State()
    waiting_for_movie_description = State()
    waiting_for_movie_tags = State()
    waiting_for_movie_genres = State()
    waiting_for_alternative_names = State()
    waiting_for_movie_files = State()
    
    waiting_for_series_title = State()
    waiting_for_series_description = State()
    waiting_for_series_tags = State()
    waiting_for_series_genres = State()
    waiting_for_series_alternative_names = State()
    
    waiting_for_season_number = State()
    waiting_for_season_title = State()
    waiting_for_season_description = State()
    
    waiting_for_episode_number = State()
    waiting_for_episode_title = State()
    waiting_for_episode_alternative_names = State()
    waiting_for_episode_files = State()
    
    waiting_for_edit_item = State()
    waiting_for_edit_field = State()
    waiting_for_edit_value = State()
    
    waiting_for_bulk_message = State()
    waiting_for_quality_selection = State()

# Utility functions
async def check_channel_membership(user_id: int) -> bool:
    """Check if user is member of all required channels"""
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in [types.ChatMemberStatus.LEFT, types.ChatMemberStatus.BANNED]:
                return False
        except Exception as e:
            logger.error(f"Error checking channel membership: {e}")
            return False
    return True

async def update_user_info(user: types.User):
    """Update or create user in database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO users (id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
            (user.id, user.username, user.first_name, user.last_name)
        )
        conn.commit()

async def is_admin(user_id: int) -> bool:
    """Check if user is admin"""
    return user_id in ADMINS

def create_main_keyboard() -> ReplyKeyboardMarkup:
    """Create main reply keyboard"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎬 فیلم ها"), KeyboardButton(text="📺 سریال ها")],
            [KeyboardButton(text="🔍 جستجو"), KeyboardButton(text="ℹ️ راهنما")]
        ],
        resize_keyboard=True
    )
    return keyboard

def create_admin_keyboard() -> ReplyKeyboardMarkup:
    """Create admin reply keyboard"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ افزودن فیلم"), KeyboardButton(text="➕ افزودن سریال")],
            [KeyboardButton(text="📊 آمار"), KeyboardButton(text="✏️ ویرایش محتوا")],
            [KeyboardButton(text="📤 ارسال همگانی"), KeyboardButton(text="🔗 لینک اشتراک")],
            [KeyboardButton(text="🔙 بازگشت به منوی اصلی")]
        ],
        resize_keyboard=True
    )
    return keyboard

def create_back_keyboard() -> ReplyKeyboardMarkup:
    """Create back button keyboard"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 بازگشت")]],
        resize_keyboard=True
    )
    return keyboard

def create_cancel_keyboard() -> ReplyKeyboardMarkup:
    """Create cancel button keyboard"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ لغو")]],
        resize_keyboard=True
    )
    return keyboard

def create_sorting_keyboard(content_type: str) -> InlineKeyboardMarkup:
    """Create sorting options keyboard"""
    keyboard = InlineKeyboardBuilder()
    
    if content_type == "movie":
        keyboard.add(
            InlineKeyboardButton(text="🆕 جدیدترین", callback_data="sort_movie_newest"),
            InlineKeyboardButton(text="🕰 قدیمی ترین", callback_data="sort_movie_oldest"),
            InlineKeyboardButton(text="🔤 الفبا (صعودی)", callback_data="sort_movie_asc"),
            InlineKeyboardButton(text="🔤 الفبا (نزولی)", callback_data="sort_movie_desc"),
            InlineKeyboardButton(text="🎭 بر اساس ژانر", callback_data="sort_movie_genre")
        )
    else:  # series
        keyboard.add(
            InlineKeyboardButton(text="🆕 جدیدترین", callback_data="sort_series_newest"),
            InlineKeyboardButton(text="🕰 قدیمی ترین", callback_data="sort_series_oldest"),
            InlineKeyboardButton(text="🔤 الفبا (صعودی)", callback_data="sort_series_asc"),
            InlineKeyboardButton(text="🔤 الفبا (نزولی)", callback_data="sort_series_desc"),
            InlineKeyboardButton(text="🎭 بر اساس ژانر", callback_data="sort_series_genre")
        )
    
    keyboard.adjust(2)
    return keyboard.as_markup()

def create_genres_keyboard() -> InlineKeyboardMarkup:
    """Create genres selection keyboard"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM genres ORDER BY name")
        genres = cursor.fetchall()
    
    keyboard = InlineKeyboardBuilder()
    for genre in genres:
        keyboard.add(InlineKeyboardButton(
            text=genre['name'],
            callback_data=f"genre_{genre['id']}"
        ))
    
    keyboard.adjust(3)
    return keyboard.as_markup()

def create_quality_keyboard(item_type: str, item_id: int) -> InlineKeyboardMarkup:
    """Create quality selection keyboard"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        if item_type == "movie":
            cursor.execute(
                "SELECT DISTINCT quality FROM movie_files WHERE movie_id = ? ORDER BY \
                CASE quality WHEN '4K' THEN 1 WHEN '1080p' THEN 2 WHEN '720p' THEN 3 WHEN '480p' THEN 4 ELSE 5 END",
                (item_id,)
            )
        else:  # episode
            cursor.execute(
                "SELECT DISTINCT quality FROM episode_files WHERE episode_id = ? ORDER BY \
                CASE quality WHEN '4K' THEN 1 WHEN '1080p' THEN 2 WHEN '720p' THEN 3 WHEN '480p' THEN 4 ELSE 5 END",
                (item_id,)
            )
        
        qualities = cursor.fetchall()
    
    if not qualities:
        return None
    
    keyboard = InlineKeyboardBuilder()
    for quality in qualities:
        keyboard.add(InlineKeyboardButton(
            text=quality['quality'],
            callback_data=f"quality_{item_type}_{item_id}_{quality['quality']}"
        ))
    
    keyboard.adjust(2)
    return keyboard.as_markup()

def generate_share_uuid() -> str:
    """Generate a unique UUID for sharing"""
    return str(uuid.uuid4())

# Middleware for checking channel membership
@dp.message.middleware
async def channel_membership_middleware(handler, event: types.Message, data: dict):
    # Skip check for admins
    if await is_admin(event.from_user.id):
        return await handler(event, data)
    
    # Skip check for certain commands
    if event.text in ["/start", "/help"] or event.text.startswith("/start "):
        return await handler(event, data)
    
    # Check if user has joined required channels
    user_id = event.from_user.id
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT joined_channels FROM users WHERE id = ?", (user_id,))
        user_data = cursor.fetchone()
        
        if user_data and user_data['joined_channels']:
            return await handler(event, data)
    
    # Check current membership status
    is_member = await check_channel_membership(user_id)
    
    if is_member:
        # Update user status in database
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET joined_channels = TRUE WHERE id = ?",
                (user_id,)
            )
            conn.commit()
        return await handler(event, data)
    else:
        # User hasn't joined all channels
        channels_text = "\n".join([f"🔹 {channel}" for channel in REQUIRED_CHANNELS])
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="عضویت در کانال ها", url=f"https://t.me/{REQUIRED_CHANNELS[0][1:]}")],
            [InlineKeyboardButton(text="بررسی عضویت", callback_data="check_membership")]
        ])
        await event.answer(
            f"⚠️ برای استفاده از ربات باید در کانال های زیر عضو شوید:\n\n{channels_text}\n\n"
            "پس از عضویت، روی دکمه «بررسی عضویت» کلیک کنید.",
            reply_markup=keyboard
        )
        return

# Callback query middleware for channel membership
@dp.callback_query.middleware
async def callback_channel_membership_middleware(handler, event: types.CallbackQuery, data: dict):
    # Skip check for admins
    if await is_admin(event.from_user.id):
        return await handler(event, data)
    
    # Skip check for membership check callback
    if event.data == "check_membership":
        return await handler(event, data)
    
    # Check if user has joined required channels
    user_id = event.from_user.id
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT joined_channels FROM users WHERE id = ?", (user_id,))
        user_data = cursor.fetchone()
        
        if user_data and user_data['joined_channels']:
            return await handler(event, data)
    
    # Check current membership status
    is_member = await check_channel_membership(user_id)
    
    if is_member:
        # Update user status in database
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET joined_channels = TRUE WHERE id = ?",
                (user_id,)
            )
            conn.commit()
        return await handler(event, data)
    else:
        # User hasn't joined all channels
        channels_text = "\n".join([f"🔹 {channel}" for channel in REQUIRED_CHANNELS])
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="عضویت در کانال ها", url=f"https://t.me/{REQUIRED_CHANNELS[0][1:]}")],
            [InlineKeyboardButton(text="بررسی عضویت", callback_data="check_membership")]
        ])
        await event.message.answer(
            f"⚠️ برای استفاده از ربات باید در کانال های زیر عضو شوید:\n\n{channels_text}\n\n"
            "پس از عضویت، روی دکمه «بررسی عضویت» کلیک کنید.",
            reply_markup=keyboard
        )
        await event.answer()
        return

# Command handlers
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Handle /start command"""
    await update_user_info(message.from_user)
    
    # Check if this is a share link
    if len(message.text.split()) > 1:
        start_param = message.text.split()[1]
        
        # Check if it's a share UUID
        if start_param.startswith("share_"):
            share_id = start_param[6:]
            
            # Check if it's a movie
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM movies WHERE share_uuid = ?", (share_id,))
                movie = cursor.fetchone()
                
                if movie:
                    # Show movie details
                    text = f"🎬 {movie['title']} ({movie['year']})\n\n"
                    if movie['description']:
                        text += f"📝 {movie['description']}\n\n"
                    if movie['tags']:
                        text += f"🏷 تگ ها: {movie['tags']}\n\n"
                    
                    text += "👇 برای دریافت لینک دانلود از دکمه زیر استفاده کنید:"
                    
                    # Create inline keyboard with download button
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬇️ دانلود فیلم", callback_data=f"download_movie_{movie['id']}")]
                    ])
                    
                    # Send poster if available
                    if movie['poster_file_id']:
                        await message.answer_photo(
                            movie['poster_file_id'],
                            caption=text,
                            reply_markup=keyboard
                        )
                    else:
                        await message.answer(text, reply_markup=keyboard)
                    
                    return
                
                # Check if it's an episode
                cursor.execute("SELECT * FROM episodes WHERE share_uuid = ?", (share_id,))
                episode = cursor.fetchone()
                
                if episode:
                    # Get season and series info
                    cursor.execute("""
                        SELECT s.*, se.title as series_title 
                        FROM seasons s 
                        JOIN series se ON s.series_id = se.id 
                        WHERE s.id = ?
                    """, (episode['season_id'],))
                    season = cursor.fetchone()
                    
                    text = f"📺 {season['series_title']} - فصل {season['season_number']} - قسمت {episode['episode_number']}\n\n"
                    if episode['title']:
                        text += f"📝 {episode['title']}\n\n"
                    
                    text += "👇 برای دریافت لینک دانلود از دکمه زیر استفاده کنید:"
                    
                    # Create inline keyboard with download button
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬇️ دانلود اپیزود", callback_data=f"download_episode_{episode['id']}")]
                    ])
                    
                    await message.answer(text, reply_markup=keyboard)
                    return
    
    welcome_text = (
        "🤖 به ربات دانلود فیلم و سریال خوش آمدید!\n\n"
        "🎬 در این ربات می‌توانید فیلم و سریال مورد نظر خود را جستجو و دانلود کنید.\n\n"
        "👇 از منوی زیر گزینه مورد نظر را انتخاب کنید:"
    )
    
    if await is_admin(message.from_user.id):
        await message.answer(welcome_text, reply_markup=create_admin_keyboard())
    else:
        await message.answer(welcome_text, reply_markup=create_main_keyboard())

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Handle /help command"""
    help_text = (
        "📖 راهنمای استفاده از ربات:\n\n"
        "🎬 فیلم ها - مشاهده و جستجوی فیلم ها\n"
        "📺 سریال ها - مشاهده و جستجوی سریال ها\n"
        "🔍 جستجو - جستجوی پیشرفته در محتوا\n\n"
        "💡 برای استفاده از ربات کافیست از دکمه های زیر استفاده کنید یا نام فیلم/سریال مورد نظر را تایپ کنید."
    )
    await message.answer(help_text)

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Handle /admin command"""
    if not await is_admin(message.from_user.id):
        await message.answer("⛔️ شما دسترسی ادمین ندارید.")
        return
    
    await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())

# Callback query handlers
@dp.callback_query(F.data == "check_membership")
async def check_membership_callback(callback: types.CallbackQuery):
    """Handle membership check callback"""
    user_id = callback.from_user.id
    is_member = await check_channel_membership(user_id)
    
    if is_member:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET joined_channels = TRUE WHERE id = ?",
                (user_id,)
            )
            conn.commit()
        
        await callback.message.edit_text(
            "✅ شما با موفقیت عضو همه کانال ها شده اید. اکنون می‌توانید از ربات استفاده کنید.",
            reply_markup=None
        )
        
        if await is_admin(user_id):
            await callback.message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        else:
            await callback.message.answer("منوی اصلی", reply_markup=create_main_keyboard())
    else:
        channels_text = "\n".join([f"🔹 {channel}" for channel in REQUIRED_CHANNELS])
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="عضویت در کانال ها", url=f"https://t.me/{REQUIRED_CHANNELS[0][1:]}")],
            [InlineKeyboardButton(text="بررسی عضویت", callback_data="check_membership")]
        ])
        await callback.message.edit_text(
            f"⚠️ هنوز در برخی کانال ها عضو نشده اید:\n\n{channels_text}",
            reply_markup=keyboard
        )
    
    await callback.answer()

# Text message handlers
@dp.message(F.text == "🔙 بازگشت")
async def handle_back(message: types.Message, state: FSMContext):
    """Handle back button"""
    await state.clear()
    if await is_admin(message.from_user.id):
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
    else:
        await message.answer("منوی اصلی", reply_markup=create_main_keyboard())

@dp.message(F.text == "🔙 بازگشت به منوی اصلی")
async def handle_back_to_main(message: types.Message, state: FSMContext):
    """Handle back to main menu button"""
    await state.clear()
    await message.answer("منوی اصلی", reply_markup=create_main_keyboard())

@dp.message(F.text == "❌ لغو")
async def handle_cancel(message: types.Message, state: FSMContext):
    """Handle cancel button"""
    await state.clear()
    if await is_admin(message.from_user.id):
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
    else:
        await message.answer("منوی اصلی", reply_markup=create_main_keyboard())

@dp.message(F.text == "🎬 فیلم ها")
async def handle_movies(message: types.Message):
    """Handle movies button"""
    # Show sorting options
    await message.answer(
        "🎬 لطفا روش مرتب سازی فیلم ها را انتخاب کنید:",
        reply_markup=create_sorting_keyboard("movie")
    )

@dp.message(F.text == "📺 سریال ها")
async def handle_series(message: types.Message):
    """Handle series button"""
    # Show sorting options
    await message.answer(
        "📺 لطفا روش مرتب سازی سریال ها را انتخاب کنید:",
        reply_markup=create_sorting_keyboard("series")
    )

@dp.message(F.text == "🔍 جستجو")
async def handle_search(message: types.Message):
    """Handle search button"""
    await message.answer(
        "🔍 برای جستجو، نام فیلم یا سریال مورد نظر خود را تایپ کنید.\n\n"
        "💡 می‌توانید بر اساس عنوان، سال تولید، یا تگ ها جستجو کنید.",
        reply_markup=create_back_keyboard()
    )

@dp.message(F.text == "ℹ️ راهنما")
async def handle_help(message: types.Message):
    """Handle help button"""
    await cmd_help(message)

# Admin handlers
@dp.message(F.text == "➕ افزودن فیلم")
async def handle_add_movie(message: types.Message, state: FSMContext):
    """Handle add movie button (admin only)"""
    if not await is_admin(message.from_user.id):
        await message.answer("⛔️ شما دسترسی ادمین ندارید.")
        return
    
    await message.answer(
        "🎬 لطفا عنوان فیلم را وارد کنید:",
        reply_markup=create_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_movie_title)

@dp.message(F.text == "➕ افزودن سریال")
async def handle_add_series(message: types.Message, state: FSMContext):
    """Handle add series button (admin only)"""
    if not await is_admin(message.from_user.id):
        await message.answer("⛔️ شما دسترسی ادمین ندارید.")
        return
    
    await message.answer(
        "📺 لطفا عنوان سریال را وارد کنید:",
        reply_markup=create_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_series_title)

@dp.message(F.text == "📊 آمار")
async def handle_stats(message: types.Message):
    """Handle stats button (admin only)"""
    if not await is_admin(message.from_user.id):
        await message.answer("⛔️ شما دسترسی ادمین ندارید.")
        return
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get movie count
        cursor.execute("SELECT COUNT(*) as count FROM movies")
        movie_count = cursor.fetchone()['count']
        
        # Get series count
        cursor.execute("SELECT COUNT(*) as count FROM series")
        series_count = cursor.fetchone()['count']
        
        # Get user count
        cursor.execute("SELECT COUNT(*) as count FROM users")
        user_count = cursor.fetchone()['count']
        
        # Get total movie files count
        cursor.execute("SELECT COUNT(*) as count FROM movie_files")
        movie_files_count = cursor.fetchone()['count']
        
        # Get total episode files count
        cursor.execute("SELECT COUNT(*) as count FROM episode_files")
        episode_files_count = cursor.fetchone()['count']
    
    stats_text = (
        "📊 آمار ربات:\n\n"
        f"🎬 تعداد فیلم ها: {movie_count}\n"
        f"📺 تعداد سریال ها: {series_count}\n"
        f"📁 تعداد فایل های فیلم: {movie_files_count}\n"
        f"📁 تعداد فایل های اپیزود: {episode_files_count}\n"
        f"👥 تعداد کاربران: {user_count}"
    )
    
    await message.answer(stats_text)

@dp.message(F.text == "✏️ ویرایش محتوا")
async def handle_edit_content(message: types.Message, state: FSMContext):
    """Handle edit content button (admin only)"""
    if not await is_admin(message.from_user.id):
        await message.answer("⛔️ شما دسترسی ادمین ندارید.")
        return
    
    await message.answer(
        "✏️ لطفا نام یا ID آیتمی که می‌خواهید ویرایش کنید را وارد کنید:",
        reply_markup=create_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_edit_item)

@dp.message(F.text == "📤 ارسال همگانی")
async def handle_bulk_message(message: types.Message, state: FSMContext):
    """Handle bulk message button (admin only)"""
    if not await is_admin(message.from_user.id):
        await message.answer("⛔️ شما دسترسی ادمین ندارید.")
        return
    
    await message.answer(
        "📤 لطفا پیامی که می‌خواهید برای همه کاربران ارسال کنید را وارد کنید:",
        reply_markup=create_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_bulk_message)

@dp.message(F.text == "🔗 لینک اشتراک")
async def handle_share_links(message: types.Message):
    """Handle share links button (admin only)"""
    if not await is_admin(message.from_user.id):
        await message.answer("⛔️ شما دسترسی ادمین ندارید.")
        return
    
    # Get all movies and series
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, year, share_uuid FROM movies ORDER BY title")
        movies = cursor.fetchall()
        
        cursor.execute("SELECT id, title, share_uuid FROM series ORDER BY title")
        series_list = cursor.fetchall()
    
    if not movies and not series_list:
        await message.answer("📭 هیچ محتوایی در سیستم وجود ندارد.")
        return
    
    # Create message with share links
    text = "🔗 لینک های اشتراک:\n\n"
    
    if movies:
        text += "🎬 فیلم ها:\n"
        for movie in movies:
            share_url = f"{BASE_SHARE_URL}share_{movie['share_uuid']}"
            text += f"{movie['title']} ({movie['year']}): {share_url}\n"
        text += "\n"
    
    if series_list:
        text += "📺 سریال ها:\n"
        for series in series_list:
            share_url = f"{BASE_SHARE_URL}share_{series['share_uuid']}"
            text += f"{series['title']}: {share_url}\n"
            
            # Get seasons for this series
            cursor.execute("SELECT id, season_number FROM seasons WHERE series_id = ? ORDER BY season_number", (series['id'],))
            seasons = cursor.fetchall()
            
            for season in seasons:
                # Get episodes for this season
                cursor.execute("SELECT id, episode_number, title, share_uuid FROM episodes WHERE season_id = ? ORDER BY episode_number", (season['id'],))
                episodes = cursor.fetchall()
                
                for episode in episodes:
                    episode_share_url = f"{BASE_SHARE_URL}share_{episode['share_uuid']}"
                    episode_title = f" - {episode['title']}" if episode['title'] else ""
                    text += f"  ├─ {series['title']} - فصل {season['season_number']} - قسمت {episode['episode_number']}{episode_title}: {episode_share_url}\n"
    
    # Split long messages
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            await message.answer(part)
    else:
        await message.answer(text)

# Movie addition flow
@dp.message(StateFilter(AdminStates.waiting_for_movie_title))
async def handle_movie_title(message: types.Message, state: FSMContext):
    """Handle movie title input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    await state.update_data(title=message.text)
    await message.answer("📅 لطفا سال تولید فیلم را وارد کنید:", reply_markup=create_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_movie_year)

@dp.message(StateFilter(AdminStates.waiting_for_movie_year))
async def handle_movie_year(message: types.Message, state: FSMContext):
    """Handle movie year input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    if not message.text.isdigit():
        await message.answer("⚠️ سال باید یک عدد باشد. لطفا دوباره وارد کنید:", reply_markup=create_cancel_keyboard())
        return
    
    await state.update_data(year=int(message.text))
    await message.answer("📝 لطفا توضیحات فیلم را وارد کنید:", reply_markup=create_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_movie_description)

@dp.message(StateFilter(AdminStates.waiting_for_movie_description))
async def handle_movie_description(message: types.Message, state: FSMContext):
    """Handle movie description input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    await state.update_data(description=message.text)
    await message.answer("🏷 لطفا تگ های فیلم را با کاما جدا کنید (مثلا: اکشن,ماجراجویی,علمی تخیلی):", reply_markup=create_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_movie_tags)

@dp.message(StateFilter(AdminStates.waiting_for_movie_tags))
async def handle_movie_tags(message: types.Message, state: FSMContext):
    """Handle movie tags input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    await state.update_data(tags=message.text)
    await message.answer("🎭 لطفا ژانرهای فیلم را انتخاب کنید:", reply_markup=create_genres_keyboard())
    await state.set_state(AdminStates.waiting_for_movie_genres)

@dp.callback_query(StateFilter(AdminStates.waiting_for_movie_genres), F.data.startswith("genre_"))
async def handle_movie_genres(callback: types.CallbackQuery, state: FSMContext):
    """Handle movie genres selection"""
    genre_id = int(callback.data.split("_")[1])
    
    data = await state.get_data()
    selected_genres = data.get('genres', [])
    selected_genres.append(genre_id)
    await state.update_data(genres=selected_genres)
    
    # Show confirmation button
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید انتخاب ژانرها", callback_data="confirm_genres")]
    ])
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM genres WHERE id = ?", (genre_id,))
        genre_name = cursor.fetchone()['name']
    
    await callback.message.answer(f"✅ ژانر «{genre_name}» اضافه شد. برای اضافه کردن ژانرهای دیگر ادامه دهید یا تایید کنید.")
    await callback.message.answer("ژانرهای انتخاب شده:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(StateFilter(AdminStates.waiting_for_movie_genres), F.data == "confirm_genres")
async def handle_confirm_genres(callback: types.CallbackQuery, state: FSMContext):
    """Handle genres confirmation"""
    await callback.message.answer("🔤 لطفا نام های جایگزین فیلم را با کاما جدا کنید (در صورت وجود):", reply_markup=create_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_alternative_names)
    await callback.answer()

@dp.message(StateFilter(AdminStates.waiting_for_alternative_names))
async def handle_movie_alternative_names(message: types.Message, state: FSMContext):
    """Handle movie alternative names input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    await state.update_data(alternative_names=message.text)
    
    data = await state.get_data()
    
    # Create movie in database
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO movies (title, year, description, tags, alternative_names, share_uuid)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (data['title'], data['year'], data['description'], data['tags'], 
             data.get('alternative_names', ''), generate_share_uuid())
        )
        movie_id = cursor.lastrowid
        
        # Add genres
        for genre_id in data.get('genres', []):
            cursor.execute(
                "INSERT INTO movie_genres (movie_id, genre_id) VALUES (?, ?)",
                (movie_id, genre_id)
            )
        
        conn.commit()
    
    await message.answer(
        f"✅ فیلم «{data['title']}» با موفقیت اضافه شد. لطفا فایل های ویدیویی با کیفیت های مختلف را ارسال کنید:",
        reply_markup=create_cancel_keyboard()
    )
    await state.update_data(movie_id=movie_id)
    await state.set_state(AdminStates.waiting_for_movie_files)

@dp.message(StateFilter(AdminStates.waiting_for_movie_files))
async def handle_movie_files(message: types.Message, state: FSMContext):
    """Handle movie files upload"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    if not message.video:
        await message.answer("⚠️ لطفا یک فایل ویدیویی ارسال کنید:", reply_markup=create_cancel_keyboard())
        return
    
    data = await state.get_data()
    movie_id = data['movie_id']
    
    # Ask for quality
    await message.answer("📺 لطفا کیفیت این فایل را وارد کنید (مثلا: 1080p, 720p, 480p):", reply_markup=create_cancel_keyboard())
    await state.update_data(file_id=message.video.file_id, file_size=message.video.file_size, duration=message.video.duration)
    await state.set_state(AdminStates.waiting_for_quality_selection)

@dp.message(StateFilter(AdminStates.waiting_for_quality_selection))
async def handle_quality_selection(message: types.Message, state: FSMContext):
    """Handle quality selection for movie files"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    quality = message.text.strip()
    data = await state.get_data()
    movie_id = data['movie_id']
    
    # Save file with quality
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO movie_files (movie_id, file_id, quality, file_size, duration)
            VALUES (?, ?, ?, ?, ?)
            """,
            (movie_id, data['file_id'], quality, data['file_size'], data['duration'])
        )
        conn.commit()
    
    await message.answer(
        f"✅ فایل با کیفیت {quality} اضافه شد. می‌توانید فایل دیگری با کیفیت متفاوت ارسال کنید یا برای اتمام از دکمه لغو استفاده کنید.",
        reply_markup=create_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_movie_files)

# Series addition flow
@dp.message(StateFilter(AdminStates.waiting_for_series_title))
async def handle_series_title(message: types.Message, state: FSMContext):
    """Handle series title input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    await state.update_data(title=message.text)
    await message.answer("📝 لطفا توضیحات سریال را وارد کنید:", reply_markup=create_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_series_description)

@dp.message(StateFilter(AdminStates.waiting_for_series_description))
async def handle_series_description(message: types.Message, state: FSMContext):
    """Handle series description input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    await state.update_data(description=message.text)
    await message.answer("🏷 لطفا تگ های سریال را با کاما جدا کنید (مثلا: اکشن,ماجراجویی,کمدی):", reply_markup=create_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_series_tags)

@dp.message(StateFilter(AdminStates.waiting_for_series_tags))
async def handle_series_tags(message: types.Message, state: FSMContext):
    """Handle series tags input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    await state.update_data(tags=message.text)
    await message.answer("🎭 لطفا ژانرهای سریال را انتخاب کنید:", reply_markup=create_genres_keyboard())
    await state.set_state(AdminStates.waiting_for_series_genres)

@dp.callback_query(StateFilter(AdminStates.waiting_for_series_genres), F.data.startswith("genre_"))
async def handle_series_genres(callback: types.CallbackQuery, state: FSMContext):
    """Handle series genres selection"""
    genre_id = int(callback.data.split("_")[1])
    
    data = await state.get_data()
    selected_genres = data.get('genres', [])
    selected_genres.append(genre_id)
    await state.update_data(genres=selected_genres)
    
    # Show confirmation button
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید انتخاب ژانرها", callback_data="confirm_series_genres")]
    ])
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM genres WHERE id = ?", (genre_id,))
        genre_name = cursor.fetchone()['name']
    
    await callback.message.answer(f"✅ ژانر «{genre_name}» اضافه شد. برای اضافه کردن ژانرهای دیگر ادامه دهید یا تایید کنید.")
    await callback.message.answer("ژانرهای انتخاب شده:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(StateFilter(AdminStates.waiting_for_series_genres), F.data == "confirm_series_genres")
async def handle_confirm_series_genres(callback: types.CallbackQuery, state: FSMContext):
    """Handle series genres confirmation"""
    await callback.message.answer("🔤 لطفا نام های جایگزین سریال را با کاما جدا کنید (در صورت وجود):", reply_markup=create_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_series_alternative_names)
    await callback.answer()

@dp.message(StateFilter(AdminStates.waiting_for_series_alternative_names))
async def handle_series_alternative_names(message: types.Message, state: FSMContext):
    """Handle series alternative names input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    await state.update_data(alternative_names=message.text)
    
    data = await state.get_data()
    
    # Create series in database
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO series (title, description, tags, alternative_names, share_uuid)
            VALUES (?, ?, ?, ?, ?)
            """,
            (data['title'], data['description'], data['tags'], 
             data.get('alternative_names', ''), generate_share_uuid())
        )
        series_id = cursor.lastrowid
        
        # Add genres
        for genre_id in data.get('genres', []):
            cursor.execute(
                "INSERT INTO series_genres (series_id, genre_id) VALUES (?, ?)",
                (series_id, genre_id)
            )
        
        conn.commit()
    
    await message.answer(
        f"✅ سریال «{data['title']}» با موفقیت اضافه شد. اکنون لطفا شماره فصل را وارد کنید:",
        reply_markup=create_cancel_keyboard()
    )
    await state.update_data(series_id=series_id)
    await state.set_state(AdminStates.waiting_for_season_number)

@dp.message(StateFilter(AdminStates.waiting_for_season_number))
async def handle_season_number(message: types.Message, state: FSMContext):
    """Handle season number input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    if not message.text.isdigit():
        await message.answer("⚠️ شماره فصل باید یک عدد باشد. لطفا دوباره وارد کنید:", reply_markup=create_cancel_keyboard())
        return
    
    await state.update_data(season_number=int(message.text))
    await message.answer("📝 لطفا عنوان فصل را وارد کنید (اختیاری):", reply_markup=create_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_season_title)

@dp.message(StateFilter(AdminStates.waiting_for_season_title))
async def handle_season_title(message: types.Message, state: FSMContext):
    """Handle season title input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    await state.update_data(season_title=message.text)
    await message.answer("📝 لطفا توضیحات فصل را وارد کنید (اختیاری):", reply_markup=create_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_season_description)

@dp.message(StateFilter(AdminStates.waiting_for_season_description))
async def handle_season_description(message: types.Message, state: FSMContext):
    """Handle season description input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    data = await state.get_data()
    series_id = data['series_id']
    
    # Create season in database
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO seasons (series_id, season_number, title, description)
            VALUES (?, ?, ?, ?)
            """,
            (series_id, data['season_number'], data.get('season_title', ''), message.text)
        )
        season_id = cursor.lastrowid
        conn.commit()
    
    await message.answer(
        f"✅ فصل {data['season_number']} با موفقیت اضافه شد. اکنون لطفا شماره قسمت را وارد کنید:",
        reply_markup=create_cancel_keyboard()
    )
    await state.update_data(season_id=season_id)
    await state.set_state(AdminStates.waiting_for_episode_number)

@dp.message(StateFilter(AdminStates.waiting_for_episode_number))
async def handle_episode_number(message: types.Message, state: FSMContext):
    """Handle episode number input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    if not message.text.isdigit():
        await message.answer("⚠️ شماره قسمت باید یک عدد باشد. لطفا دوباره وارد کنید:", reply_markup=create_cancel_keyboard())
        return
    
    await state.update_data(episode_number=int(message.text))
    await message.answer("📝 لطفا عنوان قسمت را وارد کنید (اختیاری):", reply_markup=create_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_episode_title)

@dp.message(StateFilter(AdminStates.waiting_for_episode_title))
async def handle_episode_title(message: types.Message, state: FSMContext):
    """Handle episode title input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    await state.update_data(episode_title=message.text)
    await message.answer("🔤 لطفا نام های جایگزین قسمت را با کاما جدا کنید (در صورت وجود):", reply_markup=create_cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_episode_alternative_names)

@dp.message(StateFilter(AdminStates.waiting_for_episode_alternative_names))
async def handle_episode_alternative_names(message: types.Message, state: FSMContext):
    """Handle episode alternative names input"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    data = await state.get_data()
    season_id = data['season_id']
    
    # Create episode in database
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO episodes (season_id, episode_number, title, alternative_names, share_uuid)
            VALUES (?, ?, ?, ?, ?)
            """,
            (season_id, data['episode_number'], data.get('episode_title', ''), message.text, generate_share_uuid())
        )
        episode_id = cursor.lastrowid
        conn.commit()
    
    await message.answer(
        f"✅ قسمت {data['episode_number']} با موفقیت اضافه شد. لطفا فایل های ویدیویی با کیفیت های مختلف را ارسال کنید:",
        reply_markup=create_cancel_keyboard()
    )
    await state.update_data(episode_id=episode_id)
    await state.set_state(AdminStates.waiting_for_episode_files)

@dp.message(StateFilter(AdminStates.waiting_for_episode_files))
async def handle_episode_files(message: types.Message, state: FSMContext):
    """Handle episode files upload"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    if not message.video:
        await message.answer("⚠️ لطفا یک فایل ویدیویی ارسال کنید:", reply_markup=create_cancel_keyboard())
        return
    
    data = await state.get_data()
    episode_id = data['episode_id']
    
    # Ask for quality
    await message.answer("📺 لطفا کیفیت این فایل را وارد کنید (مثلا: 1080p, 720p, 480p):", reply_markup=create_cancel_keyboard())
    await state.update_data(file_id=message.video.file_id, file_size=message.video.file_size, duration=message.video.duration)
    await state.set_state(AdminStates.waiting_for_quality_selection)

# Bulk message handling
@dp.message(StateFilter(AdminStates.waiting_for_bulk_message))
async def handle_bulk_message_text(message: types.Message, state: FSMContext):
    """Handle bulk message text"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    # Get all users
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users")
        users = cursor.fetchall()
    
    success_count = 0
    fail_count = 0
    
    for user in users:
        try:
            await bot.send_message(user['id'], f"📢 پیام همگانی:\n\n{message.text}")
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to send message to user {user['id']}: {e}")
            fail_count += 1
    
    await message.answer(
        f"✅ ارسال همگانی завер شد:\n\n"
        f"✅ موفق: {success_count}\n"
        f"❌ ناموفق: {fail_count}",
        reply_markup=create_admin_keyboard()
    )
    await state.clear()

# Edit content handling
@dp.message(StateFilter(AdminStates.waiting_for_edit_item))
async def handle_edit_item(message: types.Message, state: FSMContext):
    """Handle item name or ID input for editing"""
    if message.text == "❌ لغو":
        await state.clear()
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
        return
    
    search_term = message.text
    
    # Check if item exists in movies
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM movies WHERE title LIKE ? OR id = ?", 
            (f"%{search_term}%", search_term)
        )
        movie = cursor.fetchone()
        
        if movie:
            await state.update_data(item_type="movie", item_id=movie['id'], item_data=dict(movie))
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="عنوان"), KeyboardButton(text="سال")],
                    [KeyboardButton(text="توضیحات"), KeyboardButton(text="تگ ها")],
                    [KeyboardButton(text="نام های جایگزین"), KeyboardButton(text="ژانرها")],
                    [KeyboardButton(text="افزودن فایل"), KeyboardButton(text="❌ لغو")]
                ],
                resize_keyboard=True
            )
            await message.answer(
                f"🎬 فیلم: {movie['title']} ({movie['year']})\n\n"
                "لطفا فیلدی که می‌خواهید ویرایش کنید را انتخاب کنید:",
                reply_markup=keyboard
            )
            await state.set_state(AdminStates.waiting_for_edit_field)
            return
        
        # Check if item exists in series
        cursor.execute(
            "SELECT * FROM series WHERE title LIKE ? OR id = ?", 
            (f"%{search_term}%", search_term)
        )
        series = cursor.fetchone()
        
        if series:
            await state.update_data(item_type="series", item_id=series['id'], item_data=dict(series))
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="عنوان"), KeyboardButton(text="توضیحات")],
                    [KeyboardButton(text="تگ ها"), KeyboardButton(text="نام های جایگزین")],
                    [KeyboardButton(text="ژانرها"), KeyboardButton(text="افزودن فصل")],
                    [KeyboardButton(text="❌ لغو")]
                ],
                resize_keyboard=True
            )
            await message.answer(
                f"📺 سریال: {series['title']}\n\n"
                "لطفا فیلدی که می‌خواهید ویرایش کنید را انتخاب کنید:",
                reply_markup=keyboard
            )
            await state.set_state(AdminStates.waiting_for_edit_field)
            return
        
        # Check if item exists in episodes
        cursor.execute(
            "SELECT e.*, s.season_number, se.title as series_title FROM episodes e " +
            "JOIN seasons s ON e.season_id = s.id " +
            "JOIN series se ON s.series_id = se.id " +
            "WHERE e.title LIKE ? OR e.id = ?",
            (f"%{search_term}%", search_term)
        )
        episode = cursor.fetchone()
        
        if episode:
            await state.update_data(item_type="episode", item_id=episode['id'], item_data=dict(episode))
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="عنوان"), KeyboardButton(text="شماره قسمت")],
                    [KeyboardButton(text="نام های جایگزین"), KeyboardButton(text="افزودن فایل")],
                    [KeyboardButton(text="❌ لغو")]
                ],
                resize_keyboard=True
            )
            await message.answer(
                f"📺 اپیزود: {episode['series_title']} - فصل {episode['season_number']} - قسمت {episode['episode_number']}\n\n"
                "لطفا فیلدی که می‌خواهید ویرایش کنید را انتخاب کنید:",
                reply_markup=keyboard
            )
            await state.set_state(AdminStates.waiting_for_edit_field)
            return
    
    await message.answer("⚠️ آیتمی با این نام یا ID یافت نشد. لطفا دوباره تلاش کنید:")

@dp.message(StateFilter(AdminStates.waiting_for_edit_field))
async def handle_edit_field(message: types.Message, state: FSMContext):
    """Handle field selection for editing"""
    if message.text == "❌ لغو":
        await message.answer("✏️ لطفا نام یا ID آیتمی که می‌خواهید ویرایش کنید را وارد کنید:", reply_markup=create_cancel_keyboard())
        await state.set_state(AdminStates.waiting_for_edit_item)
        return
    
    data = await state.get_data()
    item_type = data['item_type']
    
    if message.text == "افزودن فایل":
        if item_type == "movie":
            await message.answer(
                "🎬 لطفا فایل ویدیویی جدید را ارسال کنید:",
                reply_markup=create_cancel_keyboard()
            )
            await state.set_state(AdminStates.waiting_for_movie_files)
        elif item_type == "episode":
            await message.answer(
                "📺 لطفا فایل ویدیویی جدید را ارسال کنید:",
                reply_markup=create_cancel_keyboard()
            )
            await state.set_state(AdminStates.waiting_for_episode_files)
        return
    
    if message.text == "افزودن فصل" and item_type == "series":
        await message.answer(
            "📺 لطفا شماره فصل جدید را وارد کنید:",
            reply_markup=create_cancel_keyboard()
            )
        await state.set_state(AdminStates.waiting_for_season_number)
        return
    
    if message.text == "ژانرها":
        await message.answer("🎭 لطفا ژانرهای جدید را انتخاب کنید:", reply_markup=create_genres_keyboard())
        return
    
    field_mapping = {
        "عنوان": "title",
        "سال": "year",
        "توضیحات": "description",
        "تگ ها": "tags",
        "نام های جایگزین": "alternative_names",
        "شماره قسمت": "episode_number"
    }
    
    if message.text not in field_mapping:
        await message.answer("⚠️ لطفا یکی از گزینه های موجود را انتخاب کنید:")
        return
    
    field = field_mapping[message.text]
    await state.update_data(edit_field=field)
    
    current_value = data['item_data'].get(field, "وجود ندارد")
    await message.answer(
        f"✏️ لطفا مقدار جدید را وارد کنید:\n\nمقدار فعلی: {current_value}",
        reply_markup=create_cancel_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_edit_value)

@dp.message(StateFilter(AdminStates.waiting_for_edit_value))
async def handle_edit_value(message: types.Message, state: FSMContext):
    """Handle new value input and update database"""
    if message.text == "❌ لغو":
        data = await state.get_data()
        if data['item_type'] == "movie":
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="عنوان"), KeyboardButton(text="سال")],
                    [KeyboardButton(text="توضیحات"), KeyboardButton(text="تگ ها")],
                    [KeyboardButton(text="نام های جایگزین"), KeyboardButton(text="ژانرها")],
                    [KeyboardButton(text="افزودن فایل"), KeyboardButton(text="❌ لغو")]
                ],
                resize_keyboard=True
            )
        elif data['item_type'] == "series":
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="عنوان"), KeyboardButton(text="توضیحات")],
                    [KeyboardButton(text="تگ ها"), KeyboardButton(text="نام های جایگزین")],
                    [KeyboardButton(text="ژانرها"), KeyboardButton(text="افزودن فصل")],
                    [KeyboardButton(text="❌ لغو")]
                ],
                resize_keyboard=True
            )
        else:  # episode
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="عنوان"), KeyboardButton(text="شماره قسمت")],
                    [KeyboardButton(text="نام های جایگزین"), KeyboardButton(text="افزودن فایل")],
                    [KeyboardButton(text="❌ لغو")]
                ],
                resize_keyboard=True
            )
        
        await message.answer("لطفا فیلدی که می‌خواهید ویرایش کنید را انتخاب کنید:", reply_markup=keyboard)
        await state.set_state(AdminStates.waiting_for_edit_field)
        return
    
    data = await state.get_data()
    item_type = data['item_type']
    item_id = data['item_id']
    field = data['edit_field']
    value = message.text
    
    # Update database
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if item_type == "movie":
            cursor.execute(f"UPDATE movies SET {field} = ? WHERE id = ?", (value, item_id))
        elif item_type == "series":
            cursor.execute(f"UPDATE series SET {field} = ? WHERE id = ?", (value, item_id))
        else:  # episode
            cursor.execute(f"UPDATE episodes SET {field} = ? WHERE id = ?", (value, item_id))
        conn.commit()
    
    await message.answer(
        f"✅ فیلد {field} با موفقیت به روز شد.",
        reply_markup=create_admin_keyboard()
    )
    await state.clear()

# Search functionality
@dp.message(F.text)
async def handle_search_query(message: types.Message, state: FSMContext):
    """Handle search queries"""
    query = message.text.strip()
    
    # If it's a command or button text, skip
    if query.startswith('/') or query in ["🎬 فیلم ها", "📺 سریال ها", "🔍 جستجو", "ℹ️ راهنما", "🔙 بازگشت", "❌ لغو"]:
        return
    
    # Search in movies and series
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Search in movies with case-insensitive matching
        cursor.execute(
            """
            SELECT id, title, year, 'movie' as type FROM movies 
            WHERE LOWER(title) LIKE LOWER(?) OR LOWER(alternative_names) LIKE LOWER(?) OR LOWER(tags) LIKE LOWER(?) OR LOWER(description) LIKE LOWER(?)
            UNION
            SELECT id, title, NULL as year, 'series' as type FROM series 
            WHERE LOWER(title) LIKE LOWER(?) OR LOWER(alternative_names) LIKE LOWER(?) OR LOWER(tags) LIKE LOWER(?) OR LOWER(description) LIKE LOWER(?)
            LIMIT 20
            """,
            (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", 
             f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%")
        )
        results = cursor.fetchall()
    
    if not results:
        await message.answer("🔍 هیچ نتیجه ای برای جستجوی شما یافت نشد.")
        return
    
    # Create inline keyboard with results
    keyboard = InlineKeyboardBuilder()
    for result in results:
        if result['type'] == 'movie':
            text = f"🎬 {result['title']} ({result['year']})"
        else:
            text = f"📺 {result['title']}"
        
        keyboard.add(InlineKeyboardButton(
            text=text,
            callback_data=f"{result['type']}_{result['id']}"
        ))
    
    keyboard.adjust(1)
    await message.answer(
        f"🔍 نتایج جستجو برای «{query}»:",
        reply_markup=keyboard.as_markup()
    )

# Callback query handlers for sorting
@dp.callback_query(F.data.startswith("sort_"))
async def handle_sorting_callback(callback: types.CallbackQuery):
    """Handle sorting callback"""
    data_parts = callback.data.split("_")
    content_type = data_parts[1]  # movie or series
    sort_type = data_parts[2]  # newest, oldest, asc, desc, genre
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        if content_type == "movie":
            if sort_type == "newest":
                cursor.execute("SELECT * FROM movies ORDER BY created_at DESC LIMIT 20")
            elif sort_type == "oldest":
                cursor.execute("SELECT * FROM movies ORDER BY created_at ASC LIMIT 20")
            elif sort_type == "asc":
                cursor.execute("SELECT * FROM movies ORDER BY title ASC LIMIT 20")
            elif sort_type == "desc":
                cursor.execute("SELECT * FROM movies ORDER BY title DESC LIMIT 20")
            elif sort_type == "genre":
                await callback.message.answer("🎭 لطفا یک ژانر برای فیلتر کردن انتخاب کنید:", reply_markup=create_genres_keyboard())
                await callback.answer()
                return
            
            items = cursor.fetchall()
            
            if not items:
                await callback.message.answer("📭 هیچ فیلمی در سیستم وجود ندارد.")
                await callback.answer()
                return
            
            keyboard = InlineKeyboardBuilder()
            for movie in items:
                keyboard.add(InlineKeyboardButton(
                    text=f"{movie['title']} ({movie['year']})", 
                    callback_data=f"movie_{movie['id']}"
                ))
            
            text = "🎬 لیست فیلم ها:"
        
        else:  # series
            if sort_type == "newest":
                cursor.execute("SELECT * FROM series ORDER BY created_at DESC LIMIT 20")
            elif sort_type == "oldest":
                cursor.execute("SELECT * FROM series ORDER BY created_at ASC LIMIT 20")
            elif sort_type == "asc":
                cursor.execute("SELECT * FROM series ORDER BY title ASC LIMIT 20")
            elif sort_type == "desc":
                cursor.execute("SELECT * FROM series ORDER BY title DESC LIMIT 20")
            elif sort_type == "genre":
                await callback.message.answer("🎭 لطفا یک ژانر برای فیلتر کردن انتخاب کنید:", reply_markup=create_genres_keyboard())
                await callback.answer()
                return
            
            items = cursor.fetchall()
            
            if not items:
                await callback.message.answer("📭 هیچ سریالی در سیستم وجود ندارد.")
                await callback.answer()
                return
            
            keyboard = InlineKeyboardBuilder()
            for series in items:
                keyboard.add(InlineKeyboardButton(
                    text=series['title'], 
                    callback_data=f"series_{series['id']}"
                ))
            
            text = "📺 لیست سریال ها:"
    
    keyboard.adjust(1)
    await callback.message.answer(text, reply_markup=keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("genre_"))
async def handle_genre_filter(callback: types.CallbackQuery):
    """Handle genre filter callback"""
    genre_id = int(callback.data.split("_")[1])
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Get genre name
        cursor.execute("SELECT name FROM genres WHERE id = ?", (genre_id,))
        genre = cursor.fetchone()
        
        if not genre:
            await callback.answer("⚠️ ژانر یافت نشد.")
            return
        
        # Check if we're filtering movies or series
        if "sort_movie" in callback.message.text:
            cursor.execute(
                """
                SELECT m.* FROM movies m
                JOIN movie_genres mg ON m.id = mg.movie_id
                WHERE mg.genre_id = ?
                ORDER BY m.title
                LIMIT 20
                """,
                (genre_id,)
            )
            items = cursor.fetchall()
            
            if not items:
                await callback.message.answer(f"📭 هیچ فیلمی در ژانر «{genre['name']}» وجود ندارد.")
                await callback.answer()
                return
            
            keyboard = InlineKeyboardBuilder()
            for movie in items:
                keyboard.add(InlineKeyboardButton(
                    text=f"{movie['title']} ({movie['year']})", 
                    callback_data=f"movie_{movie['id']}"
                ))
            
            text = f"🎬 فیلم های ژانر {genre['name']}:"
        
        else:  # series
            cursor.execute(
                """
                SELECT s.* FROM series s
                JOIN series_genres sg ON s.id = sg.series_id
                WHERE sg.genre_id = ?
                ORDER BY s.title
                LIMIT 20
                """,
                (genre_id,)
            )
            items = cursor.fetchall()
            
            if not items:
                await callback.message.answer(f"📭 هیچ سریالی در ژانر «{genre['name']}» وجود ندارد.")
                await callback.answer()
                return
            
            keyboard = InlineKeyboardBuilder()
            for series in items:
                keyboard.add(InlineKeyboardButton(
                    text=series['title'], 
                    callback_data=f"series_{series['id']}"
                ))
            
            text = f"📺 سریال های ژانر {genre['name']}:"
    
    keyboard.adjust(1)
    await callback.message.answer(text, reply_markup=keyboard.as_markup())
    await callback.answer()

# Callback query handlers for movies and series
@dp.callback_query(F.data.startswith("movie_"))
async def handle_movie_callback(callback: types.CallbackQuery):
    """Handle movie selection callback"""
    movie_id = callback.data.split("_")[1]
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM movies WHERE id = ?", (movie_id,))
        movie = cursor.fetchone()
        
        if not movie:
            await callback.answer("⚠️ فیلم یافت نشد.")
            return
        
        # Check if movie has multiple qualities
        cursor.execute("SELECT COUNT(DISTINCT quality) as quality_count FROM movie_files WHERE movie_id = ?", (movie_id,))
        quality_count = cursor.fetchone()['quality_count']
    
    # Create message text
    text = f"🎬 {movie['title']} ({movie['year']})\n\n"
    if movie['description']:
        text += f"📝 {movie['description']}\n\n"
    if movie['tags']:
        text += f"🏷 تگ ها: {movie['tags']}\n\n"
    
    # Get genres
    cursor.execute(
        """
        SELECT g.name FROM genres g
        JOIN movie_genres mg ON g.id = mg.genre_id
        WHERE mg.movie_id = ?
        """,
        (movie_id,)
    )
    genres = cursor.fetchall()
    if genres:
        genre_names = ", ".join([genre['name'] for genre in genres])
        text += f"🎭 ژانرها: {genre_names}\n\n"
    
    if quality_count > 1:
        text += "📺 لطفا کیفیت مورد نظر را انتخاب کنید:"
        keyboard = create_quality_keyboard("movie", movie_id)
    else:
        text += "👇 برای دریافت لینک دانلود از دکمه زیر استفاده کنید:"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬇️ دانلود فیلم", callback_data=f"download_movie_{movie_id}")]
        ])
    
    # Add share button
    if keyboard:
        share_url = f"{BASE_SHARE_URL}share_{movie['share_uuid']}"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔗 اشتراک گذاری", url=share_url)])
    
    # Send poster if available
    if movie['poster_file_id']:
        await callback.message.answer_photo(
            movie['poster_file_id'],
            caption=text,
            reply_markup=keyboard
        )
    else:
        await callback.message.answer(text, reply_markup=keyboard)
    
    await callback.answer()

@dp.callback_query(F.data.startswith("series_"))
async def handle_series_callback(callback: types.CallbackQuery):
    """Handle series selection callback"""
    series_id = callback.data.split("_")[1]
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM series WHERE id = ?", (series_id,))
        series = cursor.fetchone()
        
        if not series:
            await callback.answer("⚠️ سریال یافت نشد.")
            return
        
        # Get seasons for this series
        cursor.execute("SELECT * FROM seasons WHERE series_id = ? ORDER BY season_number", (series_id,))
        seasons = cursor.fetchall()
    
    # Create message text
    text = f"📺 {series['title']}\n\n"
    if series['description']:
        text += f"📝 {series['description']}\n\n"
    if series['tags']:
        text += f"🏷 تگ ها: {series['tags']}\n\n"
    
    # Get genres
    cursor.execute(
        """
        SELECT g.name FROM genres g
        JOIN series_genres sg ON g.id = sg.genre_id
        WHERE sg.series_id = ?
        """,
        (series_id,)
    )
    genres = cursor.fetchall()
    if genres:
        genre_names = ", ".join([genre['name'] for genre in genres])
        text += f"🎭 ژانرها: {genre_names}\n\n"
    
    if not seasons:
        text += "📭 هیچ فصلی برای این سریال وجود ندارد."
        await callback.message.answer(text)
        await callback.answer()
        return
    
    text += "👇 لطفا یک فصل را انتخاب کنید:"
    
    # Create inline keyboard with seasons
    keyboard = InlineKeyboardBuilder()
    for season in seasons:
        keyboard.add(InlineKeyboardButton(
            text=f"فصل {season['season_number']}" + (f" - {season['title']}" if season['title'] else ""),
            callback_data=f"season_{season['id']}"
        ))
    
    keyboard.adjust(1)
    
    # Add share button
    share_url = f"{BASE_SHARE_URL}share_{series['share_uuid']}"
    keyboard.row(InlineKeyboardButton(text="🔗 اشتراک گذاری", url=share_url))
    
    # Send poster if available
    if series['poster_file_id']:
        await callback.message.answer_photo(
            series['poster_file_id'],
            caption=text,
            reply_markup=keyboard.as_markup()
        )
    else:
        await callback.message.answer(text, reply_markup=keyboard.as_markup())
    
    await callback.answer()

@dp.callback_query(F.data.startswith("season_"))
async def handle_season_callback(callback: types.CallbackQuery):
    """Handle season selection callback"""
    season_id = callback.data.split("_")[1]
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM seasons WHERE id = ?", (season_id,))
        season = cursor.fetchone()
        
        if not season:
            await callback.answer("⚠️ فصل یافت نشد.")
            return
        
        cursor.execute("SELECT * FROM episodes WHERE season_id = ? ORDER BY episode_number", (season_id,))
        episodes = cursor.fetchall()
    
    text = f"📀 فصل {season['season_number']}"
    if season['title']:
        text += f" - {season['title']}"
    text += "\n\n"
    
    if season['description']:
        text += f"📝 {season['description']}\n\n"
    
    if not episodes:
        text += "📭 هیچ اپیزودی برای این فصل وجود ندارد."
        await callback.message.answer(text)
        await callback.answer()
        return
    
    text += "👇 لطفا یک اپیزود را انتخاب کنید:"
    
    # Create inline keyboard with episodes
    keyboard = InlineKeyboardBuilder()
    for episode in episodes:
        keyboard.add(InlineKeyboardButton(
            text=f"قسمت {episode['episode_number']}" + (f" - {episode['title']}" if episode['title'] else ""),
            callback_data=f"episode_{episode['id']}"
        ))
    
    keyboard.adjust(1)
    await callback.message.answer(text, reply_markup=keyboard.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("episode_"))
async def handle_episode_callback(callback: types.CallbackQuery):
    """Handle episode selection callback"""
    episode_id = callback.data.split("_")[1]
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,))
        episode = cursor.fetchone()
        
        if not episode:
            await callback.answer("⚠️ اپیزود یافت نشد.")
            return
        
        # Get season and series info
        cursor.execute("SELECT s.*, se.title as series_title FROM seasons s JOIN series se ON s.series_id = se.id WHERE s.id = ?", (episode['season_id'],))
        season = cursor.fetchone()
        
        # Check if episode has multiple qualities
        cursor.execute("SELECT COUNT(DISTINCT quality) as quality_count FROM episode_files WHERE episode_id = ?", (episode_id,))
        quality_count = cursor.fetchone()['quality_count']
    
    text = f"📺 {season['series_title']} - فصل {season['season_number']} - قسمت {episode['episode_number']}\n\n"
    if episode['title']:
        text += f"📝 {episode['title']}\n\n"
    
    if quality_count > 1:
        text += "📺 لطفا کیفیت مورد نظر را انتخاب کنید:"
        keyboard = create_quality_keyboard("episode", episode_id)
    else:
        text += "👇 برای دریافت لینک دانلود از دکمه زیر استفاده کنید:"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬇️ دانلود اپیزود", callback_data=f"download_episode_{episode_id}")]
        ])
    
    # Add share button
    if keyboard:
        share_url = f"{BASE_SHARE_URL}share_{episode['share_uuid']}"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text="🔗 اشتراک گذاری", url=share_url)])
    
    await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("quality_"))
async def handle_quality_callback(callback: types.CallbackQuery):
    """Handle quality selection callback"""
    data_parts = callback.data.split("_")
    item_type = data_parts[1]  # movie or episode
    item_id = data_parts[2]
    quality = data_parts[3]
    
    # Update callback data to proceed with download
    if item_type == "movie":
        callback.data = f"download_movie_{item_id}_{quality}"
    else:  # episode
        callback.data = f"download_episode_{item_id}_{quality}"
    
    # Handle the download
    await handle_download_callback(callback)

@dp.callback_query(F.data.startswith("download_"))
async def handle_download_callback(callback: types.CallbackQuery):
    """Handle download callback"""
    data_parts = callback.data.split("_")
    content_type = data_parts[1]  # movie or episode
    content_id = data_parts[2]
    quality = data_parts[3] if len(data_parts) > 3 else None
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        if content_type == "movie":
            cursor.execute("SELECT * FROM movies WHERE id = ?", (content_id,))
            content = cursor.fetchone()
            if not content:
                await callback.answer("⚠️ فیلم یافت نشد.")
                return
            
            # Get the file with specified quality or the first available
            if quality:
                cursor.execute("SELECT * FROM movie_files WHERE movie_id = ? AND quality = ?", (content_id, quality))
            else:
                cursor.execute("SELECT * FROM movie_files WHERE movie_id = ? ORDER BY \
                              CASE quality WHEN '4K' THEN 1 WHEN '1080p' THEN 2 WHEN '720p' THEN 3 WHEN '480p' THEN 4 ELSE 5 END LIMIT 1", 
                              (content_id,))
            
            file_data = cursor.fetchone()
            
            if not file_data:
                await callback.answer("⚠️ فایل فیلم یافت نشد.")
                return
            
            # Send the video file
            caption = f"🎬 {content['title']} ({content['year']})"
            if quality:
                caption += f" - {quality}"
            
            await callback.message.answer_video(
                file_data['file_id'],
                caption=caption
            )
            
        else:  # episode
            cursor.execute("SELECT * FROM episodes WHERE id = ?", (content_id,))
            episode = cursor.fetchone()
            if not episode:
                await callback.answer("⚠️ اپیزود یافت نشد.")
                return
            
            # Get the file with specified quality or the first available
            if quality:
                cursor.execute("SELECT * FROM episode_files WHERE episode_id = ? AND quality = ?", (content_id, quality))
            else:
                cursor.execute("SELECT * FROM episode_files WHERE episode_id = ? ORDER BY \
                              CASE quality WHEN '4K' THEN 1 WHEN '1080p' THEN 2 WHEN '720p' THEN 3 WHEN '480p' THEN 4 ELSE 5 END LIMIT 1", 
                              (content_id,))
            
            file_data = cursor.fetchone()
            
            if not file_data:
                await callback.answer("⚠️ فایل اپیزود یافت نشد.")
                return
            
            # Get season and series info
            cursor.execute("SELECT s.*, se.title as series_title FROM seasons s JOIN series se ON s.series_id = se.id WHERE s.id = ?", (episode['season_id'],))
            season = cursor.fetchone()
            
            # Send the video file
            caption = f"📺 {season['series_title']} - فصل {season['season_number']} - قسمت {episode['episode_number']}"
            if episode['title']:
                caption += f" - {episode['title']}"
            if quality:
                caption += f" - {quality}"
            
            await callback.message.answer_video(
                file_data['file_id'],
                caption=caption
            )
    
    await callback.answer()

# Error handler
@dp.errors()
async def error_handler(update: types.Update, exception: Exception):
    """Handle errors"""
    logger.error(f"Update {update} caused error {exception}")
    # Try to send a message to the user if possible
    try:
        if update.message:
            await update.message.answer("⚠️ خطایی رخ داده است. لطفا دوباره تلاش کنید.")
        elif update.callback_query:
            await update.callback_query.message.answer("⚠️ خطایی رخ داده است. لطفا دوباره تلاش کنید.")
            await update.callback_query.answer()
    except:
        pass
    return True

# Main function
async def main():
    """Main function to start the bot"""
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
