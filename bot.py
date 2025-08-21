#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import asyncio
from typing import List, Union

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, Filter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

import aiosqlite

# --- Configuration ---
BOT_TOKEN = "8417638218:AAGfO3ubY0ruAVsoF9-stdUM9U7nLDvTXg4" # Replace with your bot token
ADMINS = [123661460]  # Replace with admin user IDs
DB_PATH = "media_bot.db"
PAGE_SIZE = 5  # Number of items per page
BOT_USERNAME = "bdgfilm_bot" # Replace with your bot's username
REQUIRED_CHANNELS = ["@booodgeh"]  # List of channels users must join

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Bot and Dispatcher Initialization ---
try:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
except Exception as e:
    logger.error(f"Failed to initialize bot: {e}")
    exit(1)

# --- FSM States ---
class UploadStates(StatesGroup):
    # Movie Upload States
    waiting_for_movie_title = State()
    waiting_for_movie_year = State()
    waiting_for_movie_description = State()
    waiting_for_movie_tags = State()
    waiting_for_movie_category = State()
    waiting_for_movie_poster = State()
    waiting_for_movie_quality_file = State()
    waiting_for_movie_quality_name = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast_message = State()
    waiting_for_user_id_for_message = State()
    waiting_for_message_to_user = State()

class SearchStates(StatesGroup):
    waiting_for_search_query = State()


# --- Custom Filters ---
class IsAdmin(Filter):
    """Custom filter to check if a user is an admin."""
    def __init__(self, admin_ids: List[int]) -> None:
        self.admin_ids = admin_ids

    async def __call__(self, message: Union[types.Message, types.CallbackQuery]) -> bool:
        return message.from_user.id in self.admin_ids

# --- Database Initialization ---
async def init_database():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            # Users table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    joined_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_active DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Movies table
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
            # Series table
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
            # Seasons table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS seasons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_id INTEGER NOT NULL,
                    season_number INTEGER NOT NULL,
                    FOREIGN KEY (series_id) REFERENCES series (id) ON DELETE CASCADE
                )
            ''')
            # Episodes table
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
            # Quality Options table (for movies and episodes)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS quality_options (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_type TEXT NOT NULL, -- 'movie' or 'episode'
                    content_id INTEGER NOT NULL,
                    quality TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    file_size INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await db.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

# --- Database Operations ---
class Database:
    @staticmethod
    async def add_or_update_user(user_id: int, username: str, first_name: str, last_name: str):
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "username=excluded.username, first_name=excluded.first_name, last_name=excluded.last_name, last_active=CURRENT_TIMESTAMP",
                    (user_id, username, first_name, last_name)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Error updating user: {e}")

    @staticmethod
    async def get_all_user_ids() -> List[int]:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("SELECT user_id FROM users")
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Error getting all user IDs: {e}")
            return []

    @staticmethod
    async def add_movie(title: str, year: int, description: str, tags: str, category: str, poster_file_id: str = None) -> int:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    "INSERT INTO movies (title, year, description, tags, category, poster_file_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (title, year, description, tags, category, poster_file_id)
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
    async def get_movie_by_id(movie_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM movies WHERE id = ?", (movie_id,))
            return await cursor.fetchone()

    @staticmethod
    async def get_quality_options(content_type: str, content_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM quality_options WHERE content_type = ? AND content_id = ? ORDER BY quality",
                (content_type, content_id)
            )
            return await cursor.fetchall()

    @staticmethod
    async def search_content(query: str):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, title, year, 'movie' as type FROM movies WHERE title LIKE ? "
                "UNION ALL "
                "SELECT id, title, NULL as year, 'series' as type FROM series WHERE title LIKE ?",
                (f"%{query}%", f"%{query}%")
            )
            return await cursor.fetchall()

    @staticmethod
    async def get_all_content(content_type: str, sort_by: str, page: int, category: str = None):
        order_map = {
            "movie": {"newest": "created_at DESC", "year": "year DESC"},
            "series": {"newest": "created_at DESC"}
        }
        order_by = order_map.get(content_type, {}).get(sort_by, "created_at DESC")
        table = "movies" if content_type == "movie" else "series"

        query = f"SELECT * FROM {table}"
        params = []
        if category:
            query += " WHERE category = ?"
            params.append(category)

        query += f" ORDER BY {order_by} LIMIT ? OFFSET ?"
        params.extend([PAGE_SIZE, page * PAGE_SIZE])

        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, tuple(params))
            return await cursor.fetchall()

    @staticmethod
    async def get_content_categories(content_type: str):
        table = "movies" if content_type == "movie" else "series"
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(f"SELECT DISTINCT category FROM {table} WHERE category IS NOT NULL AND category != ''")
            return [row[0] for row in await cursor.fetchall()]

    @staticmethod
    async def get_stats():
        stats = {}
        async with aiosqlite.connect(DB_PATH) as db:
            stats['total_users'] = (await (await db.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
            stats['total_movies'] = (await (await db.execute("SELECT COUNT(*) FROM movies")).fetchone())[0]
            stats['total_series'] = (await (await db.execute("SELECT COUNT(*) FROM series")).fetchone())[0]
            stats['total_episodes'] = (await (await db.execute("SELECT COUNT(*) FROM episodes")).fetchone())[0]
            return stats

# --- Keyboard Helpers ---
def get_main_reply_keyboard(is_admin: bool = False) -> types.ReplyKeyboardMarkup:
    """FIX: Use ReplyKeyboardMarkup for persistent menu."""
    keyboard = [
        [types.KeyboardButton(text="🎬 فیلم‌ها"), types.KeyboardButton(text="📺 سریال‌ها")],
        [types.KeyboardButton(text="🔍 جستجو")]
    ]
    if is_admin:
        keyboard.append([types.KeyboardButton(text="⚙️ پنل ادمین")])
    return types.ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_channel_join_keyboard() -> types.InlineKeyboardMarkup:
    keyboard = []
    for channel in REQUIRED_CHANNELS:
        keyboard.append([types.InlineKeyboardButton(text=f"🔗 عضویت در {channel}", url=f"https://t.me/{channel[1:]}")])
    keyboard.append([types.InlineKeyboardButton(text="✅ عضو شدم، بررسی کن", callback_data="check_membership")])
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admin_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ افزودن فیلم", callback_data="add_movie_cb")],
        [types.InlineKeyboardButton(text="📊 آمار", callback_data="admin_stats")],
        [types.InlineKeyboardButton(text="📤 ارسال همگانی", callback_data="admin_broadcast")],
        [types.InlineKeyboardButton(text="✉️ ارسال به کاربر", callback_data="admin_message_user")]
    ])

def get_movies_main_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🆕 جدیدترین‌ها", callback_data="browse_movie_newest_0")],
        [types.InlineKeyboardButton(text="📅 بر اساس سال", callback_data="browse_movie_year_0")],
        [types.InlineKeyboardButton(text="🏷️ دسته‌بندی‌ها", callback_data="movies_categories")]
    ])

def get_series_main_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🆕 جدیدترین‌ها", callback_data="browse_series_newest_0")],
        [types.InlineKeyboardButton(text="🏷️ دسته‌بندی‌ها", callback_data="series_categories")]
    ])

def get_content_list_keyboard(content_list: list, content_type: str, sort_by: str, page: int, category: str = None) -> types.InlineKeyboardMarkup:
    keyboard = []
    for item in content_list:
        text = f"🎬 {item['title']} ({item['year']})" if content_type == 'movie' and item['year'] else f"📺 {item['title']}"
        keyboard.append([types.InlineKeyboardButton(text=text, callback_data=f"view_{content_type}_{item['id']}")])

    nav_row = []
    cat_str = f"_{category}" if category else ""
    if page > 0:
        nav_row.append(types.InlineKeyboardButton(text="⏪ قبلی", callback_data=f"browse_{content_type}_{sort_by}_{page-1}{cat_str}"))
    # A bit of a guess, but if we got PAGE_SIZE items, there might be more
    if len(content_list) == PAGE_SIZE:
        nav_row.append(types.InlineKeyboardButton(text="⏩ بعدی", callback_data=f"browse_{content_type}_{sort_by}_{page+1}{cat_str}"))

    if nav_row:
        keyboard.append(nav_row)

    # Back button depends on context
    back_cb = "movies_categories" if category and content_type == 'movie' else "show_movies"
    if content_type == 'series':
        back_cb = "series_categories" if category else "show_series"
    keyboard.append([types.InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_cb)])

    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_categories_keyboard(categories: list, content_type: str) -> types.InlineKeyboardMarkup:
    keyboard = [[types.InlineKeyboardButton(text=cat, callback_data=f"browse_{content_type}_newest_0_{cat}")] for cat in categories]
    keyboard.append([types.InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"show_{content_type}")])
    return types.InlineKeyboardMarkup(inline_keyboard=keyboard)

# --- Helper Functions ---
async def check_user_membership(user_id: int) -> bool:
    """FIX: Performs a real check of the user's membership in required channels."""
    if not REQUIRED_CHANNELS:
        return True
    try:
        for channel in REQUIRED_CHANNELS:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ["creator", "administrator", "member"]:
                return False
        return True
    except TelegramAPIError as e:
        logger.error(f"Error checking membership for user {user_id}: {e}")
        # If bot is not admin or channel is wrong, deny access as we can't verify
        return False
    except Exception as e:
        logger.error(f"Unexpected error checking membership for user {user_id}: {e}")
        return False

async def format_movie_caption(movie_data: aiosqlite.Row) -> str:
    caption = f"🎬 <b>{movie_data['title']} ({movie_data['year']})</b>\n\n"
    if movie_data['description']:
        caption += f"📝 <b>خلاصه:</b> {movie_data['description']}\n"
    if movie_data['category']:
        caption += f"🏷️ <b>دسته بندی:</b> #{movie_data['category']}\n"
    if movie_data['tags']:
        caption += f"🔎 <b>برچسب ها:</b> {movie_data['tags']}\n"
    caption += f"\n@{BOT_USERNAME}"
    return caption

async def send_movie_details(chat_id: int, movie_id: int, edit_message_id: int = None):
    movie = await Database.get_movie_by_id(movie_id)
    if not movie:
        if edit_message_id:
            await bot.edit_message_text("فیلم پیدا نشد!", chat_id, edit_message_id)
        else:
            await bot.send_message(chat_id, "فیلم پیدا نشد!")
        return

    caption = await format_movie_caption(movie)
    qualities = await Database.get_quality_options('movie', movie_id)

    buttons = []
    for q in qualities:
        size_mb = f"({q['file_size'] / (1024*1024):.1f} MB)" if q['file_size'] else ""
        buttons.append([types.InlineKeyboardButton(text=f"📥 {q['quality']} {size_mb}", callback_data=f"download_movie_{movie_id}_{q['id']}")])

    buttons.append([types.InlineKeyboardButton(text="🔗 اشتراک گذاری", switch_inline_query=f"movie_{movie_id}")])
    buttons.append([types.InlineKeyboardButton(text="🔙 بازگشت به فیلم ها", callback_data="show_movies")])
    markup = types.InlineKeyboardMarkup(inline_keyboard=buttons)

    if edit_message_id:
        if movie['poster_file_id']:
            # Can't edit a text message to become a photo message, so delete and send new
            await bot.delete_message(chat_id, edit_message_id)
            await bot.send_photo(chat_id, photo=movie['poster_file_id'], caption=caption, reply_markup=markup)
        else:
            await bot.edit_message_text(caption, chat_id, edit_message_id, reply_markup=markup)
    else:
        if movie['poster_file_id']:
            await bot.send_photo(chat_id, photo=movie['poster_file_id'], caption=caption, reply_markup=markup)
        else:
            await bot.send_message(chat_id, caption, reply_markup=markup)

# --- Command Handlers ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    """Handles the /start command, checks membership, and shows the main menu."""
    await state.clear() # FIX: Cancel any previous command/state
    user = message.from_user
    await Database.add_or_update_user(user.id, user.username, user.first_name, user.last_name)

    # FIX: Check membership before proceeding
    if not await check_user_membership(user.id):
        await message.answer(
            "👋 برای استفاده از ربات، ابتدا باید در کانال ما عضو شوید. پس از عضویت، دکمه زیر را فشار دهید.",
            reply_markup=get_channel_join_keyboard()
        )
        return

    welcome_text = "🤖 به ربات فیلم و سریال خوش آمدید! لطفا از منوی زیر استفاده کنید."
    await message.answer(welcome_text, reply_markup=get_main_reply_keyboard(user.id in ADMINS))


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """FIX: Allows user to cancel any ongoing FSM operation."""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("هیچ عملیات فعالی برای لغو وجود ندارد.")
        return

    await state.clear()
    await message.answer(
        "عملیات لغو شد.",
        reply_markup=get_main_reply_keyboard(message.from_user.id in ADMINS)
    )

# --- Main Menu (Reply Keyboard) Handlers ---
@dp.message(F.text == "🎬 فیلم‌ها")
async def handle_show_movies(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("منوی فیلم‌ها:", reply_markup=get_movies_main_keyboard())

@dp.message(F.text == "📺 سریال‌ها")
async def handle_show_series(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("منوی سریال‌ها:", reply_markup=get_series_main_keyboard())

@dp.message(F.text == "🔍 جستجو")
async def handle_search(message: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(SearchStates.waiting_for_search_query)
    await message.answer("لطفا نام فیلم یا سریال مورد نظر خود را برای جستجو وارد کنید:")

@dp.message(F.text == "⚙️ پنل ادمین", IsAdmin(ADMINS))
async def handle_admin_panel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("⚙️ پنل مدیریت ادمین:", reply_markup=get_admin_keyboard())


# --- Callback Query Handlers ---
@dp.callback_query(F.data == "check_membership")
async def cb_check_membership(callback: types.CallbackQuery):
    """Handles the 'I've joined' button click."""
    user_id = callback.from_user.id
    if await check_user_membership(user_id):
        await callback.message.edit_text("✅ عضویت شما تایید شد! از ربات لذت ببرید.")
        # Send a new message with the reply keyboard
        await callback.message.answer(
            "حالا می توانید از منوی اصلی استفاده کنید.",
            reply_markup=get_main_reply_keyboard(user_id in ADMINS)
        )
    else:
        await callback.answer("❌ شما هنوز در کانال عضو نشده اید. لطفا ابتدا عضو شوید.", show_alert=True)
    await callback.answer()

@dp.callback_query(F.data.in_({"show_movies", "show_series"}))
async def cb_show_content_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    content_type = callback.data.split('_')[1]
    markup = get_movies_main_keyboard() if content_type == 'movies' else get_series_main_keyboard()
    text = "منوی فیلم‌ها:" if content_type == 'movies' else "منوی سریال‌ها:"
    await callback.message.edit_text(text, reply_markup=markup)

# Browsing Callbacks
@dp.callback_query(F.data.startswith("browse_"))
async def cb_browse_content(callback: types.CallbackQuery):
    parts = callback.data.split('_')
    # browse_{type}_{sort}_{page}_{category/optional}
    content_type, sort_by, page = parts[1], parts[2], int(parts[3])
    category = parts[4] if len(parts) > 4 else None

    content_list = await Database.get_all_content(content_type, sort_by, page, category)

    if not content_list:
        await callback.answer("محتوایی یافت نشد!", show_alert=True)
        return

    markup = get_content_list_keyboard(content_list, content_type, sort_by, page, category)
    await callback.message.edit_text(f"لیست {'فیلم ها' if content_type == 'movie' else 'سریال ها'}:", reply_markup=markup)
    await callback.answer()

# Categories Callbacks
@dp.callback_query(F.data.in_({"movies_categories", "series_categories"}))
async def cb_show_categories(callback: types.CallbackQuery):
    content_type = "movie" if callback.data == "movies_categories" else "series"
    categories = await Database.get_content_categories(content_type)
    if not categories:
        await callback.answer("هیچ دسته بندی وجود ندارد.", show_alert=True)
        return
    markup = get_categories_keyboard(categories, content_type)
    await callback.message.edit_text("یک دسته بندی را انتخاب کنید:", reply_markup=markup)

# View Content Callback
@dp.callback_query(F.data.startswith("view_"))
async def cb_view_content(callback: types.CallbackQuery):
    _, content_type, content_id_str = callback.data.split("_")
    content_id = int(content_id_str)

    if content_type == 'movie':
        await send_movie_details(callback.message.chat.id, content_id, edit_message_id=callback.message.message_id)
    # Add logic for series here if needed
    await callback.answer()

# Download Callback
@dp.callback_query(F.data.startswith("download_"))
async def cb_download_content(callback: types.CallbackQuery):
    await callback.answer("در حال ارسال فایل...")
    parts = callback.data.split('_')
    content_type, content_id, quality_id = parts[1], int(parts[2]), int(parts[3])

    qualities = await Database.get_quality_options(content_type, content_id)
    file_to_send = next((q for q in qualities if q['id'] == quality_id), None)

    if file_to_send:
        try:
            await bot.send_video(
                chat_id=callback.from_user.id,
                video=file_to_send['file_id'],
                caption=f"فایل شما - @{BOT_USERNAME}"
            )
        except Exception as e:
            await callback.message.answer(f"خطا در ارسال فایل: {e}")
    else:
        await callback.message.answer("فایل مورد نظر یافت نشد.")

# --- Search Handler ---
@dp.message(SearchStates.waiting_for_search_query)
async def process_search_query(message: types.Message, state: FSMContext):
    query = message.text
    await state.clear()
    results = await Database.search_content(query)
    if not results:
        await message.answer("نتیجه ای برای جستجوی شما یافت نشد.")
        return

    keyboard = []
    for item in results[:20]: # Limit results
        text = f"🎬 {item['title']} ({item['year']})" if item['type'] == 'movie' and item['year'] else f"📺 {item['title']}"
        keyboard.append([types.InlineKeyboardButton(text=text, callback_data=f"view_{item['type']}_{item['id']}")])
    await message.answer("نتایج جستجو:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard))

# --- Admin Handlers (/addmovie FSM) ---
@dp.message(Command("addmovie"), IsAdmin(ADMINS))
async def cmd_addmovie_start(message: types.Message, state: FSMContext):
    """FIX: /addmovie command to start the FSM process."""
    await state.clear()
    await state.set_state(UploadStates.waiting_for_movie_title)
    await message.answer("شروع فرآیند افزودن فیلم.\nلطفا <b>عنوان فیلم</b> را وارد کنید.\n\nبرای لغو از /cancel استفاده کنید.", parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "add_movie_cb", IsAdmin(ADMINS))
async def cb_addmovie_start(callback: types.CallbackQuery, state: FSMContext):
    await cmd_addmovie_start(callback.message, state)
    await callback.answer()


@dp.message(UploadStates.waiting_for_movie_title, F.text)
async def process_movie_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(UploadStates.waiting_for_movie_year)
    await message.answer("✅ عنوان ثبت شد. حالا <b>سال تولید</b> فیلم را وارد کنید.")

@dp.message(UploadStates.waiting_for_movie_year, F.text)
async def process_movie_year(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (1880 < int(message.text) < 2050):
        await message.answer("⛔️ سال نامعتبر است. لطفا یک سال صحیح وارد کنید (مثلا: 2023).")
        return
    await state.update_data(year=int(message.text))
    await state.set_state(UploadStates.waiting_for_movie_description)
    await message.answer("✅ سال ثبت شد. حالا <b>توضیحات/خلاصه</b> فیلم را وارد کنید.")

@dp.message(UploadStates.waiting_for_movie_description, F.text)
async def process_movie_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(UploadStates.waiting_for_movie_tags)
    await message.answer("✅ توضیحات ثبت شد. حالا <b>برچسب ها</b> را وارد کنید (با کاما جدا کنید).")

@dp.message(UploadStates.waiting_for_movie_tags, F.text)
async def process_movie_tags(message: types.Message, state: FSMContext):
    await state.update_data(tags=message.text)
    await state.set_state(UploadStates.waiting_for_movie_category)
    await message.answer("✅ برچسب ها ثبت شد. حالا <b>دسته بندی</b> را وارد کنید (مثلا: اکشن, درام).")

@dp.message(UploadStates.waiting_for_movie_category, F.text)
async def process_movie_category(message: types.Message, state: FSMContext):
    await state.update_data(category=message.text)
    await state.set_state(UploadStates.waiting_for_movie_poster)
    await message.answer("✅ دسته بندی ثبت شد. حالا <b>پوستر</b> فیلم را ارسال کنید (یا /skip برای رد شدن).")

@dp.message(UploadStates.waiting_for_movie_poster, Command("skip"))
async def process_movie_poster_skip(message: types.Message, state: FSMContext):
    await state.update_data(poster_file_id=None)
    await state.set_state(UploadStates.waiting_for_movie_quality_file)
    await message.answer("✅ از پوستر صرف نظر شد. حالا <b>اولین فایل ویدئویی</b> فیلم را ارسال کنید.")

@dp.message(UploadStates.waiting_for_movie_poster, F.photo)
async def process_movie_poster(message: types.Message, state: FSMContext):
    await state.update_data(poster_file_id=message.photo[-1].file_id)
    await state.set_state(UploadStates.waiting_for_movie_quality_file)
    await message.answer("✅ پوستر ثبت شد. حالا <b>اولین فایل ویدئویی</b> فیلم را ارسال کنید.")

@dp.message(UploadStates.waiting_for_movie_quality_file, F.video)
async def process_movie_file(message: types.Message, state: FSMContext):
    data = await state.get_data()
    qualities = data.get('qualities', [])
    qualities.append({
        'file_id': message.video.file_id,
        'file_size': message.video.file_size
    })
    await state.update_data(qualities=qualities)
    await state.set_state(UploadStates.waiting_for_movie_quality_name)
    await message.answer("✅ فایل ویدئو دریافت شد. حالا <b>نام کیفیت</b> این فایل را وارد کنید (مثلا: 720p WEB-DL).")

@dp.message(UploadStates.waiting_for_movie_quality_name, F.text)
async def process_movie_quality_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    qualities = data['qualities']
    # Add name to the last added file
    qualities[-1]['name'] = message.text

    await state.update_data(qualities=qualities)
    await state.set_state(UploadStates.waiting_for_movie_quality_file)

    markup = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✅ بله، فایل بعدی را ارسال میکنم", callback_data="add_another_quality")],
        [types.InlineKeyboardButton(text=" خیر، تمام شد", callback_data="finish_add_movie")]
    ])
    await message.answer("✅ کیفیت ثبت شد. آیا میخواهید کیفیت دیگری اضافه کنید؟", reply_markup=markup)

@dp.callback_query(F.data == "add_another_quality", UploadStates.waiting_for_movie_quality_file)
async def cb_add_another_quality(callback: types.CallbackQuery):
    await callback.message.edit_text("لطفا فایل ویدئویی بعدی را ارسال کنید.")
    await callback.answer()

@dp.callback_query(F.data == "finish_add_movie", UploadStates.waiting_for_movie_quality_file)
async def cb_finish_add_movie(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    movie_id = await Database.add_movie(
        title=data['title'],
        year=data['year'],
        description=data['description'],
        tags=data['tags'],
        category=data['category'],
        poster_file_id=data.get('poster_file_id')
    )
    if movie_id == -1:
        await callback.message.edit_text("⛔️ خطا در ذخیره فیلم در دیتابیس.")
        await state.clear()
        return

    for q in data['qualities']:
        await Database.add_quality_option(
            content_type='movie',
            content_id=movie_id,
            quality=q['name'],
            file_id=q['file_id'],
            file_size=q['file_size']
        )

    await state.clear()
    await callback.message.edit_text(f"✅ فیلم '{data['title']}' با موفقیت به دیتابیس اضافه شد!")
    await callback.answer()

# --- Other Admin Callbacks & Handlers ---
@dp.callback_query(F.data == "admin_stats", IsAdmin(ADMINS))
async def cb_admin_stats(callback: types.CallbackQuery):
    stats = await Database.get_stats()
    stats_text = (
        "📊 <b>آمار ربات</b>\n\n"
        f"👤 <b>کل کاربران:</b> {stats.get('total_users', 0)}\n"
        f"🎬 <b>تعداد فیلم‌ها:</b> {stats.get('total_movies', 0)}\n"
        f"📺 <b>تعداد سریال‌ها:</b> {stats.get('total_series', 0)}\n"
        f"🎞 <b>تعداد اپیزودها:</b> {stats.get('total_episodes', 0)}"
    )
    await callback.message.edit_text(stats_text, reply_markup=get_admin_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "admin_broadcast", IsAdmin(ADMINS))
async def cb_admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_broadcast_message)
    await callback.message.edit_text("لطفا پیامی که میخواهید برای همه کاربران ارسال شود را بفرستید.")
    await callback.answer()

@dp.message(AdminStates.waiting_for_broadcast_message, IsAdmin(ADMINS))
async def process_broadcast_message(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("در حال ارسال پیام به کاربران...")
    user_ids = await Database.get_all_user_ids()
    sent_count = 0
    failed_count = 0
    for user_id in user_ids:
        try:
            await bot.copy_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
            sent_count += 1
            await asyncio.sleep(0.1) # Avoid rate limits
        except Exception:
            failed_count += 1
    await message.answer(f"✅ پیام همگانی با موفقیت به {sent_count} کاربر ارسال شد.\n"
                         f"⛔️ ارسال به {failed_count} کاربر ناموفق بود.")


# --- Inline Query Handler ---
@dp.inline_query()
async def inline_query_handler(inline_query: types.InlineQuery):
    query = inline_query.query
    results = []

    if query.startswith("movie_"):
        try:
            movie_id = int(query.split('_')[1])
            movie = await Database.get_movie_by_id(movie_id)
            if movie:
                caption = await format_movie_caption(movie)
                results.append(types.InlineQueryResultArticle(
                    id=f"movie_{movie_id}",
                    title=f"🎬 {movie['title']} ({movie['year']})",
                    input_message_content=types.InputTextMessageContent(message_text=caption),
                    description=movie['description'][:50] + "...",
                    thumb_url= "https://i.imgur.com/gfg2p8f.png" # Placeholder
                ))
        except (ValueError, IndexError):
            pass # Ignore malformed queries
    else:
        # General search
        content_results = await Database.search_content(query)
        for item in content_results[:20]: # Limit results
            if item['type'] == 'movie':
                results.append(types.InlineQueryResultArticle(
                    id=f"share_movie_{item['id']}",
                    title=f"🎬 {item['title']} ({item['year']})",
                    input_message_content=types.InputTextMessageContent(
                        message_text=f"برای مشاهده و دانلود فیلم '{item['title']}' از ربات زیر استفاده کنید:\n@{BOT_USERNAME}"
                    )
                ))

    await inline_query.answer(results, cache_time=10)


# --- Main Execution ---
async def main():
    await init_database()
    logger.info("Bot is starting...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
