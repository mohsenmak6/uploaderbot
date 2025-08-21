import os
import re
import logging
import asyncio
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
                file_id TEXT NOT NULL,
                alternative_names TEXT,
                poster_file_id TEXT,
                quality TEXT DEFAULT 'HD',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                file_id TEXT NOT NULL,
                alternative_names TEXT,
                quality TEXT DEFAULT 'HD',
                FOREIGN KEY (season_id) REFERENCES seasons (id) ON DELETE CASCADE
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
        
        conn.commit()

# Initialize database
init_db()

# States for FSM
class AdminStates(StatesGroup):
    waiting_for_movie_title = State()
    waiting_for_movie_year = State()
    waiting_for_movie_description = State()
    waiting_for_movie_tags = State()
    waiting_for_alternative_names = State()
    
    waiting_for_series_title = State()
    waiting_for_series_description = State()
    waiting_for_series_tags = State()
    
    waiting_for_season_number = State()
    waiting_for_season_title = State()
    waiting_for_season_description = State()
    
    waiting_for_episode_title = State()
    waiting_for_episode_number = State()
    
    waiting_for_edit_item = State()
    waiting_for_edit_field = State()
    waiting_for_edit_value = State()

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

# Middleware for checking channel membership
@dp.message.middleware
async def channel_membership_middleware(handler, event: types.Message, data: dict):
    # Skip check for admins
    if await is_admin(event.from_user.id):
        return await handler(event, data)
    
    # Skip check for certain commands
    if event.text in ["/start", "/help"]:
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

# Command handlers
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Handle /start command"""
    await update_user_info(message.from_user)
    
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
async def handle_back(message: types.Message):
    """Handle back button"""
    if await is_admin(message.from_user.id):
        await message.answer("🛠 پنل مدیریت", reply_markup=create_admin_keyboard())
    else:
        await message.answer("منوی اصلی", reply_markup=create_main_keyboard())

@dp.message(F.text == "🔙 بازگشت به منوی اصلی")
async def handle_back_to_main(message: types.Message):
    """Handle back to main menu button"""
    await message.answer("منوی اصلی", reply_markup=create_main_keyboard())

@dp.message(F.text == "🎬 فیلم ها")
async def handle_movies(message: types.Message):
    """Handle movies button"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM movies ORDER BY title LIMIT 10")
        movies = cursor.fetchall()
    
    if not movies:
        await message.answer("📭 هیچ فیلمی در سیستم وجود ندارد.")
        return
    
    keyboard = InlineKeyboardBuilder()
    for movie in movies:
        keyboard.add(InlineKeyboardButton(
            text=f"{movie['title']} ({movie['year']})", 
            callback_data=f"movie_{movie['id']}"
        ))
    
    keyboard.adjust(1)
    await message.answer("🎬 لیست فیلم ها:", reply_markup=keyboard.as_markup())

@dp.message(F.text == "📺 سریال ها")
async def handle_series(message: types.Message):
    """Handle series button"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM series ORDER BY title LIMIT 10")
        series_list = cursor.fetchall()
    
    if not series_list:
        await message.answer("📭 هیچ سریالی در سیستم وجود ندارد.")
        return
    
    keyboard = InlineKeyboardBuilder()
    for series in series_list:
        keyboard.add(InlineKeyboardButton(
            text=series['title'], 
            callback_data=f"series_{series['id']}"
        ))
    
    keyboard.adjust(1)
    await message.answer("📺 لیست سریال ها:", reply_markup=keyboard.as_markup())

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
        "🎬 لطفا فیلم را ارسال کنید یا فوروارد نمایید:",
        reply_markup=create_back_keyboard()
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
        reply_markup=create_back_keyboard()
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
    
    stats_text = (
        "📊 آمار ربات:\n\n"
        f"🎬 تعداد فیلم ها: {movie_count}\n"
        f"📺 تعداد سریال ها: {series_count}\n"
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
        "✏️ لطفا ID آیتمی که می‌خواهید ویرایش کنید را وارد کنید:",
        reply_markup=create_back_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_edit_item)

# Handle video files from admins
@dp.message(F.video, StateFilter(AdminStates.waiting_for_movie_title))
async def handle_video_upload(message: types.Message, state: FSMContext):
    """Handle video file upload from admin"""
    if not await is_admin(message.from_user.id):
        await message.answer("⛔️ شما دسترسی ادمین ندارید.")
        return
    
    file_id = message.video.file_id
    await state.update_data(file_id=file_id)
    
    await message.answer(
        "✅ فیلم دریافت شد. لطفا عنوان فیلم را وارد کنید:",
        reply_markup=create_back_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_movie_title)

@dp.message(StateFilter(AdminStates.waiting_for_movie_title))
async def handle_movie_title(message: types.Message, state: FSMContext):
    """Handle movie title input"""
    await state.update_data(title=message.text)
    await message.answer("📅 لطفا سال تولید فیلم را وارد کنید:")
    await state.set_state(AdminStates.waiting_for_movie_year)

@dp.message(StateFilter(AdminStates.waiting_for_movie_year))
async def handle_movie_year(message: types.Message, state: FSMContext):
    """Handle movie year input"""
    if not message.text.isdigit():
        await message.answer("⚠️ سال باید یک عدد باشد. لطفا دوباره وارد کنید:")
        return
    
    await state.update_data(year=int(message.text))
    await message.answer("📝 لطفا توضیحات فیلم را وارد کنید:")
    await state.set_state(AdminStates.waiting_for_movie_description)

@dp.message(StateFilter(AdminStates.waiting_for_movie_description))
async def handle_movie_description(message: types.Message, state: FSMContext):
    """Handle movie description input"""
    await state.update_data(description=message.text)
    await message.answer("🏷 لطفا تگ های فیلم را با کاما جدا کنید (مثلا: اکشن,ماجراجویی,علمی تخیلی):")
    await state.set_state(AdminStates.waiting_for_movie_tags)

@dp.message(StateFilter(AdminStates.waiting_for_movie_tags))
async def handle_movie_tags(message: types.Message, state: FSMContext):
    """Handle movie tags input"""
    await state.update_data(tags=message.text)
    await message.answer("🔤 لطفا نام های替代 فیلم را با کاما جدا کنید (در صورت وجود):")
    await state.set_state(AdminStates.waiting_for_alternative_names)

@dp.message(StateFilter(AdminStates.waiting_for_alternative_names))
async def handle_movie_alternative_names(message: types.Message, state: FSMContext):
    """Handle movie alternative names input and save movie to database"""
    data = await state.get_data()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO movies (title, year, description, tags, file_id, alternative_names)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (data['title'], data['year'], data['description'], data['tags'], 
             data['file_id'], message.text)
        )
        conn.commit()
    
    await message.answer(
        f"✅ فیلم «{data['title']}» با موفقیت اضافه شد.",
        reply_markup=create_admin_keyboard()
    )
    await state.clear()

# Series handling
@dp.message(StateFilter(AdminStates.waiting_for_series_title))
async def handle_series_title(message: types.Message, state: FSMContext):
    """Handle series title input"""
    await state.update_data(title=message.text)
    await message.answer("📝 لطفا توضیحات سریال را وارد کنید:")
    await state.set_state(AdminStates.waiting_for_series_description)

@dp.message(StateFilter(AdminStates.waiting_for_series_description))
async def handle_series_description(message: types.Message, state: FSMContext):
    """Handle series description input"""
    await state.update_data(description=message.text)
    await message.answer("🏷 لطفا تگ های سریال را با کاما جدا کنید (مثلا: اکشن,ماجراجویی,کمدی):")
    await state.set_state(AdminStates.waiting_for_series_tags)

@dp.message(StateFilter(AdminStates.waiting_for_series_tags))
async def handle_series_tags(message: types.Message, state: FSMContext):
    """Handle series tags input and save series to database"""
    data = await state.get_data()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO series (title, description, tags)
            VALUES (?, ?, ?)
            """,
            (data['title'], data['description'], message.text)
        )
        conn.commit()
    
    await message.answer(
        f"✅ سریال «{data['title']}» با موفقیت اضافه شد.",
        reply_markup=create_admin_keyboard()
    )
    await state.clear()

# Edit content handling
@dp.message(StateFilter(AdminStates.waiting_for_edit_item))
async def handle_edit_item(message: types.Message, state: FSMContext):
    """Handle item ID input for editing"""
    item_id = message.text
    
    # Check if item exists in movies
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM movies WHERE id = ?", (item_id,))
        movie = cursor.fetchone()
        
        if movie:
            await state.update_data(item_type="movie", item_id=item_id, item_data=movie)
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="عنوان"), KeyboardButton(text="سال")],
                    [KeyboardButton(text="توضیحات"), KeyboardButton(text="تگ ها")],
                    [KeyboardButton(text="نام های替代"), KeyboardButton(text="🔙 بازگشت")]
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
        cursor.execute("SELECT * FROM series WHERE id = ?", (item_id,))
        series = cursor.fetchone()
        
        if series:
            await state.update_data(item_type="series", item_id=item_id, item_data=series)
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="عنوان"), KeyboardButton(text="توضیحات")],
                    [KeyboardButton(text="تگ ها"), KeyboardButton(text="نام های替代")],
                    [KeyboardButton(text="🔙 بازگشت")]
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
    
    await message.answer("⚠️ آیتمی با این ID یافت نشد. لطفا دوباره尝试 کنید:")

@dp.message(StateFilter(AdminStates.waiting_for_edit_field))
async def handle_edit_field(message: types.Message, state: FSMContext):
    """Handle field selection for editing"""
    if message.text == "🔙 بازگشت":
        await message.answer("✏️ لطفا ID آیتمی که می‌خواهید ویرایش کنید را وارد کنید:", reply_markup=create_back_keyboard())
        await state.set_state(AdminStates.waiting_for_edit_item)
        return
    
    data = await state.get_data()
    field_mapping = {
        "عنوان": "title",
        "سال": "year",
        "توضیحات": "description",
        "تگ ها": "tags",
        "نام های替代": "alternative_names"
    }
    
    if message.text not in field_mapping:
        await message.answer("⚠️ لطفا یکی از گزینه های موجود را انتخاب کنید:")
        return
    
    field = field_mapping[message.text]
    await state.update_data(edit_field=field)
    
    current_value = data['item_data'].get(field, "وجود ندارد")
    await message.answer(
        f"✏️ لطفا مقدار جدید را وارد کنید:\n\nمقدار فعلی: {current_value}",
        reply_markup=create_back_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_edit_value)

@dp.message(StateFilter(AdminStates.waiting_for_edit_value))
async def handle_edit_value(message: types.Message, state: FSMContext):
    """Handle new value input and update database"""
    if message.text == "🔙 بازگشت":
        data = await state.get_data()
        if data['item_type'] == "movie":
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="عنوان"), KeyboardButton(text="سال")],
                    [KeyboardButton(text="توضیحات"), KeyboardButton(text="تگ ها")],
                    [KeyboardButton(text="نام های替代"), KeyboardButton(text="🔙 بازگشت")]
                ],
                resize_keyboard=True
            )
        else:
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="عنوان"), KeyboardButton(text="توضیحات")],
                    [KeyboardButton(text="تگ ها"), KeyboardButton(text="نام های替代")],
                    [KeyboardButton(text="🔙 بازگشت")]
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
        else:  # series
            cursor.execute(f"UPDATE series SET {field} = ? WHERE id = ?", (value, item_id))
        conn.commit()
    
    await message.answer(
        f"✅ فیلد {field} با موفقیت به روز شد.",
        reply_markup=create_admin_keyboard()
    )
    await state.clear()

# Search functionality
@dp.message(F.text)
async def handle_search_query(message: types.Message):
    """Handle search queries"""
    query = message.text.strip()
    
    # If it's a command or button text, skip
    if query.startswith('/') or query in ["🎬 فیلم ها", "📺 سریال ها", "🔍 جستجو", "ℹ️ راهنما"]:
        return
    
    # Search in movies and series
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Search in movies
        cursor.execute(
            """
            SELECT id, title, year, 'movie' as type FROM movies 
            WHERE title LIKE ? OR alternative_names LIKE ? OR tags LIKE ?
            UNION
            SELECT id, title, NULL as year, 'series' as type FROM series 
            WHERE title LIKE ? OR alternative_names LIKE ? OR tags LIKE ?
            LIMIT 20
            """,
            (f"%{query}%", f"%{query}%", f"%{query}%", 
             f"%{query}%", f"%{query}%", f"%{query}%")
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
    
    # Create message text
    text = f"🎬 {movie['title']} ({movie['year']})\n\n"
    if movie['description']:
        text += f"📝 {movie['description']}\n\n"
    if movie['tags']:
        text += f"🏷 تگ ها: {movie['tags']}\n\n"
    
    text += "👇 برای دریافت لینک دانلود از دکمه زیر استفاده کنید:"
    
    # Create inline keyboard with download button
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬇️ دانلود فیلم", callback_data=f"download_movie_{movie_id}")]
    ])
    
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
        
        # Get seasons for this series
        cursor.execute("SELECT * FROM seasons WHERE series_id = ? ORDER BY season_number", (series_id,))
        seasons = cursor.fetchall()
    
    if not series:
        await callback.answer("⚠️ سریال یافت نشد.")
        return
    
    # Create message text
    text = f"📺 {series['title']}\n\n"
    if series['description']:
        text += f"📝 {series['description']}\n\n"
    if series['tags']:
        text += f"🏷 تگ ها: {series['tags']}\n\n"
    
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
    
    text = f"📺 {season['series_title']} - فصل {season['season_number']} - قسمت {episode['episode_number']}\n\n"
    if episode['title']:
        text += f"📝 {episode['title']}\n\n"
    
    text += "👇 برای دریافت لینک دانلود از دکمه زیر استفاده کنید:"
    
    # Create inline keyboard with download button
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬇️ دانلود اپیزود", callback_data=f"download_episode_{episode_id}")]
    ])
    
    await callback.message.answer(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("download_"))
async def handle_download_callback(callback: types.CallbackQuery):
    """Handle download callback"""
    data_parts = callback.data.split("_")
    content_type = data_parts[1]  # movie or episode
    content_id = data_parts[2]
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        if content_type == "movie":
            cursor.execute("SELECT * FROM movies WHERE id = ?", (content_id,))
            content = cursor.fetchone()
            if not content:
                await callback.answer("⚠️ فیلم یافت نشد.")
                return
            
            # Send the video file
            await callback.message.answer_video(
                content['file_id'],
                caption=f"🎬 {content['title']} ({content['year']})"
            )
            
        else:  # episode
            cursor.execute("SELECT * FROM episodes WHERE id = ?", (content_id,))
            episode = cursor.fetchone()
            if not episode:
                await callback.answer("⚠️ اپیزود یافت نشد.")
                return
            
            # Get season and series info
            cursor.execute("SELECT s.*, se.title as series_title FROM seasons s JOIN series se ON s.series_id = se.id WHERE s.id = ?", (episode['season_id'],))
            season = cursor.fetchone()
            
            # Send the video file
            caption = f"📺 {season['series_title']} - فصل {season['season_number']} - قسمت {episode['episode_number']}"
            if episode['title']:
                caption += f" - {episode['title']}"
            
            await callback.message.answer_video(
                episode['file_id'],
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
            await update.message.answer("⚠️ خطایی رخ داده است. لطفا دوباره尝试 کنید.")
        elif update.callback_query:
            await update.callback_query.message.answer("⚠️ خطایی رخ داده است. لطفا دوباره尝试 کنید.")
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
