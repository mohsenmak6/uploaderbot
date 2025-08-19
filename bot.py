#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import asyncio
from typing import List, Dict, Optional, Union, Any, Tuple
from dataclasses import dataclass, field

from aiogram import Bot, Dispatcher, F, Router, html
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove, ContentType
)
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import aiosqlite

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration - PUT YOUR ACTUAL BOT TOKEN HERE
BOT_TOKEN = "8417638218:AAGfO3ubY0ruAVsoF9-stdUM9U7nLDvTXg4"  # Replace with your actual bot token from @BotFather
ADMINS = [123661460]  # Replace with your Telegram user ID
DB_PATH = "media_bot.db"
PAGE_SIZE = 10

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# States
class UploadStates(StatesGroup):
    waiting_for_type = State()
    waiting_for_movie_metadata = State()
    waiting_for_series_metadata = State()
    waiting_for_season_metadata = State()
    waiting_for_episode_metadata = State()
    waiting_for_alternative_names = State()

class EditStates(StatesGroup):
    waiting_for_edit_choice = State()
    waiting_for_edit_value = State()

# Database initialization
async def init_database():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                year INTEGER,
                description TEXT,
                tags TEXT,
                file_id TEXT NOT NULL,
                poster_file_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await db.execute('''
            CREATE TABLE IF NOT EXISTS series (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                tags TEXT,
                poster_file_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
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
        
        await db.commit()

# Database operations
class Database:
    @staticmethod
    async def add_movie(title: str, year: int, description: str, tags: str, file_id: str, poster_file_id: str = None):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO movies (title, year, description, tags, file_id, poster_file_id) VALUES (?, ?, ?, ?, ?, ?)",
                (title, year, description, tags, file_id, poster_file_id)
            )
            await db.commit()

    @staticmethod
    async def add_series(title: str, description: str, tags: str, poster_file_id: str = None) -> int:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "INSERT INTO series (title, description, tags, poster_file_id) VALUES (?, ?, ?, ?)",
                (title, description, tags, poster_file_id)
            )
            await db.commit()
            return cursor.lastrowid

    @staticmethod
    async def add_season(series_id: int, season_number: int) -> int:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "INSERT INTO seasons (series_id, season_number) VALUES (?, ?)",
                (series_id, season_number)
            )
            await db.commit()
            return cursor.lastrowid

    @staticmethod
    async def add_episode(season_id: int, episode_number: int, title: str, file_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO episodes (season_id, episode_number, title, file_id) VALUES (?, ?, ?, ?)",
                (season_id, episode_number, title, file_id)
            )
            await db.commit()

    @staticmethod
    async def add_alternative_name(content_type: str, content_id: int, name: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO alternative_names (content_type, content_id, name) VALUES (?, ?, ?)",
                (content_type, content_id, name)
            )
            await db.commit()

    @staticmethod
    async def search_content(query: str) -> List[Tuple]:
        async with aiosqlite.connect(DB_PATH) as db:
            # Search movies
            movie_cursor = await db.execute(
                "SELECT 'movie' as type, id, title, year, description FROM movies WHERE title LIKE ? OR description LIKE ? OR tags LIKE ?",
                (f"%{query}%", f"%{query}%", f"%{query}%")
            )
            movies = await movie_cursor.fetchall()
            
            # Search series
            series_cursor = await db.execute(
                "SELECT 'series' as type, id, title, NULL as year, description FROM series WHERE title LIKE ? OR description LIKE ? OR tags LIKE ?",
                (f"%{query}%", f"%{query}%", f"%{query}%")
            )
            series = await series_cursor.fetchall()
            
            # Search alternative names
            alt_cursor = await db.execute(
                '''SELECT 'movie' as type, m.id, m.title, m.year, m.description 
                   FROM movies m 
                   JOIN alternative_names a ON m.id = a.content_id AND a.content_type = 'movie'
                   WHERE a.name LIKE ?
                   UNION
                   SELECT 'series' as type, s.id, s.title, NULL as year, s.description 
                   FROM series s 
                   JOIN alternative_names a ON s.id = a.content_id AND a.content_type = 'series'
                   WHERE a.name LIKE ?''',
                (f"%{query}%", f"%{query}%")
            )
            alt_results = await alt_cursor.fetchall()
            
            return movies + series + alt_results

    @staticmethod
    async def get_movies(page: int = 0) -> List[Tuple]:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT * FROM movies ORDER BY title LIMIT ? OFFSET ?",
                (PAGE_SIZE, page * PAGE_SIZE)
            )
            return await cursor.fetchall()

    @staticmethod
    async def get_series(page: int = 0) -> List[Tuple]:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT * FROM series ORDER BY title LIMIT ? OFFSET ?",
                (PAGE_SIZE, page * PAGE_SIZE)
            )
            return await cursor.fetchall()

    @staticmethod
    async def get_seasons(series_id: int) -> List[Tuple]:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT * FROM seasons WHERE series_id = ? ORDER BY season_number",
                (series_id,)
            )
            return await cursor.fetchall()

    @staticmethod
    async def get_episodes(season_id: int) -> List[Tuple]:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT * FROM episodes WHERE season_id = ? ORDER BY episode_number",
                (season_id,)
            )
            return await cursor.fetchall()

# Keyboard helpers
def get_main_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="🎬 جستجوی فیلم", callback_data="search_movies"),
         InlineKeyboardButton(text="📺 جستجوی سریال", callback_data="search_series")],
        [InlineKeyboardButton(text="🔍 جستجو", callback_data="global_search")]
    ]
    if is_admin:
        keyboard.append([InlineKeyboardButton(text="⚙️ پنل ادمین", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(text="📊 آمار", callback_data="admin_stats"),
         InlineKeyboardButton(text="✏️ ویرایش محتوا", callback_data="admin_edit")],
        [InlineKeyboardButton(text="🗑️ حذف محتوا", callback_data="admin_delete"),
         InlineKeyboardButton(text="📤 مدیریت آپلودها", callback_data="admin_uploads")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_pagination_keyboard(current_page: int, total_pages: int, action_prefix: str) -> Optional[InlineKeyboardMarkup]:
    keyboard = []
    if current_page > 0:
        keyboard.append(InlineKeyboardButton(text="⏪ قبلی", callback_data=f"{action_prefix}_page_{current_page - 1}"))
    if current_page < total_pages - 1:
        keyboard.append(InlineKeyboardButton(text="⏩ بعدی", callback_data=f"{action_prefix}_page_{current_page + 1}"))
    return InlineKeyboardMarkup(inline_keyboard=[keyboard]) if keyboard else None

# Handlers
@dp.message(CommandStart())
async def cmd_start(message: Message):
    is_admin = message.from_user.id in ADMINS
    welcome_text = """
    🤖 به ربات مدیا خوش آمدید!

    🔍 می‌توانید فیلم و سریال جستجو کنید
    🎬 محتوای مورد نظر خود را پیدا کنید
    📺 از تماشای محتوا لذت ببرید

    برای شروع از دکمه‌های زیر استفاده کنید:
    """
    await message.answer(welcome_text, reply_markup=get_main_keyboard(is_admin))

@dp.message(Command("help"))
async def cmd_help(message: Message):
    help_text = """
    📖 راهنمای ربات:

    🔍 جستجو: برای پیدا کردن فیلم و سریال
    🎬 فیلم‌ها: مشاهده لیست فیلم‌ها
    📺 سریال‌ها: مشاهده لیست سریال‌ها

    👨‍💼 ادمین‌ها می‌توانند:
    • آپلود محتوا
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

@dp.message(F.content_type.in_({ContentType.VIDEO, ContentType.DOCUMENT}))
async def handle_media_upload(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await message.answer("❌ فقط ادمین‌ها می‌توانند محتوا آپلود کنند.")
        return

    # Get file_id from video or document
    if message.video:
        file_id = message.video.file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith('video/'):
        file_id = message.document.file_id
    else:
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

@dp.callback_query(F.data == "upload_movie")
async def upload_movie_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🎬 لطفا اطلاعات فیلم را به این فرمت وارد کنید:\n"
        "عنوان | سال | توضیحات | تگ‌ها (با کاما جدا شوند)\n\n"
        "مثال:\n"
        "اینترلستلر | 2014 | فیلمی درباره سفر در فضا | علمی تخیلی,فضا,کریستوفر نولان"
    )
    await state.set_state(UploadStates.waiting_for_movie_metadata)

@dp.callback_query(F.data == "upload_series")
async def upload_series_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📺 لطفا اطلاعات سریال را به این فرمت وارد کنید:\n"
        "عنوان | توضیحات | تگ‌ها (با کاما جدا شوند)\n\n"
        "مثال:\n"
        "بریکینگ بد | سریال درباره یک معلم شیمی که متافی می‌سازد | درام,جنایی,متافی"
    )
    await state.set_state(UploadStates.waiting_for_series_metadata)

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
        
        await Database.add_movie(title, year, description, tags, data['file_id'])
        await message.answer("✅ فیلم با موفقیت اضافه شد!")
        
    except ValueError as e:
        await message.answer(f"❌ خطا در فرمت داده‌ها: {e}")
    except Exception as e:
        await message.answer(f"❌ خطا در پردازش اطلاعات: {e}")
    
    await state.clear()

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
        
        series_id = await Database.add_series(title, description, tags)
        await state.update_data(series_id=series_id)
        
        await message.answer(
            "✅ سریال اضافه شد! حالا شماره فصل را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(UploadStates.waiting_for_season_metadata)
        
    except Exception as e:
        await message.answer(f"❌ خطا در پردازش اطلاعات: {e}")
        await state.clear()

@dp.message(UploadStates.waiting_for_season_metadata)
async def process_season_metadata(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        season_number = int(message.text.strip())
        
        season_id = await Database.add_season(data['series_id'], season_number)
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

@dp.message(UploadStates.waiting_for_episode_metadata)
async def process_episode_metadata(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        parts = message.text.split('|')
        episode_number = int(parts[0].strip())
        title = parts[1].strip() if len(parts) > 1 else f"قسمت {episode_number}"
        
        await Database.add_episode(data['season_id'], episode_number, title, data['file_id'])
        await message.answer("✅ اپیزود با موفقیت اضافه شد!")
        
        await message.answer(
            "📝 آیا نام جایگزین برای این سریال دارید؟ (اگر ندارید 'خیر' ارسال کنید):"
        )
        await state.set_state(UploadStates.waiting_for_alternative_names)
        
    except Exception as e:
        await message.answer(f"❌ خطا: {e}")
        await state.clear()

@dp.message(UploadStates.waiting_for_alternative_names)
async def process_alternative_names(message: Message, state: FSMContext):
    if message.text.lower() == 'خیر':
        await message.answer("✅ فرآیند آپلود کامل شد!")
        await state.clear()
        return
    
    try:
        data = await state.get_data()
        await Database.add_alternative_name('series', data['series_id'], message.text)
        await message.answer("✅ نام جایگزین اضافه شد! نام دیگر وارد کنید یا 'خیر' بفرستید.")
        
    except Exception as e:
        await message.answer(f"❌ خطا: {e}")
        await state.clear()

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
            content_type, content_id, title, year, description = result
            year_text = f" ({year})" if year else ""
            emoji = "🎬" if content_type == "movie" else "📺"
            response += f"{i}. {emoji} {title}{year_text}\n"
        
        await message.answer(response)
    except Exception as e:
        await message.answer("❌ خطایی در جستجو رخ داد.")
        logger.error(f"Search error: {e}")

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ دسترسی denied")
        return
    
    await callback.message.edit_text(
        "⚙️ پنل مدیریت ادمین",
        reply_markup=get_admin_keyboard()
    )

@dp.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    is_admin = callback.from_user.id in ADMINS
    await callback.message.edit_text(
        "🤖 به ربات مدیا خوش آمدید!",
        reply_markup=get_main_keyboard(is_admin)
    )

# Error handler
@dp.errors()
async def error_handler(event, exception):
    logger.error(f"Error occurred: {exception}")

# Main function
async def main():
    # Initialize database
    await init_database()
    
    # Start polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    print("🤖 Starting Persian Media Bot...")
    print("📝 Initialize database...")
    asyncio.run(init_database())
    print("🚀 Bot is running...")
    
    # Check if token is set
    if BOT_TOKEN == "YOUR_ACTUAL_BOT_TOKEN_HERE":
        print("❌ ERROR: Please replace BOT_TOKEN with your actual bot token from @BotFather")
        print("❌ ERROR: Please replace ADMINS with your Telegram user ID")
    else:
        asyncio.run(main())
