# keyboards.py
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton, 
                          InlineKeyboardMarkup, InlineKeyboardButton)
from database import get_all_movies, get_all_series, get_series_seasons, get_season_episodes
from config import BOT_USERNAME

def main_menu_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("فیلم ها 🎬"), KeyboardButton("سریال ها 📺"))
    keyboard.add(KeyboardButton("جستجو 🔍"), KeyboardButton("راهنما ❓"))
    return keyboard

def admin_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("آپلود محتوا 📤"), KeyboardButton("مدیریت محتوا 🛠"))
    keyboard.add(KeyboardButton("ارسال پیام به کاربران ✉️"), KeyboardButton("بازگشت به منوی اصلی 🔙"))
    return keyboard

def cancel_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("لغو ❌"))
    return keyboard

def upload_options_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("آپلود فیلم 🎬"), KeyboardButton("آپلود سریال 📺"))
    keyboard.add(KeyboardButton("آپلود فصل جدید ➕"), KeyboardButton("آپلود قسمت جدید 🎞"))
    keyboard.add(KeyboardButton("لغو ❌"))
    return keyboard

def manage_options_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("ویرایش فیلم ✏️"), KeyboardButton("ویرایش سریال ✏️"))
    keyboard.add(KeyboardButton("ویرایش قسمت ✏️"), KeyboardButton("حذف محتوا 🗑"))
    keyboard.add(KeyboardButton("لغو ❌"))
    return keyboard

def quality_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("480p", callback_data="quality_480"),
        InlineKeyboardButton("720p", callback_data="quality_720"),
        InlineKeyboardButton("1080p", callback_data="quality_1080"),
        InlineKeyboardButton("4K", callback_data="quality_4k")
    )
    return keyboard

def movie_list_keyboard(page=0, limit=10):
    movies = get_all_movies(limit, page * limit)
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    for movie in movies:
        keyboard.add(InlineKeyboardButton(
            f"{movie['title']} ({movie['year']})" if movie['year'] else movie['title'],
            callback_data=f"movie_{movie['id']}"
        ))
    
    # Pagination
    total_movies = count_movies()
    total_pages = (total_movies + limit - 1) // limit
    
    pagination_buttons = []
    if page > 0:
        pagination_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"movies_page_{page-1}"))
    if page < total_pages - 1:
        pagination_buttons.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"movies_page_{page+1}"))
    
    if pagination_buttons:
        keyboard.row(*pagination_buttons)
    
    keyboard.add(InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu"))
    return keyboard

def series_list_keyboard(page=0, limit=10):
    series = get_all_series(limit, page * limit)
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    for s in series:
        keyboard.add(InlineKeyboardButton(
            s['title'],
            callback_data=f"series_{s['id']}"
        ))
    
    # Pagination
    total_series = count_series()
    total_pages = (total_series + limit - 1) // limit
    
    pagination_buttons = []
    if page > 0:
        pagination_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"series_page_{page-1}"))
    if page < total_pages - 1:
        pagination_buttons.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"series_page_{page+1}"))
    
    if pagination_buttons:
        keyboard.row(*pagination_buttons)
    
    keyboard.add(InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu"))
    return keyboard

def seasons_keyboard(series_id):
    seasons = get_series_seasons(series_id)
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    for season in seasons:
        keyboard.add(InlineKeyboardButton(
            f"فصل {season['season_number']} - {season['title']}" if season['title'] else f"فصل {season['season_number']}",
            callback_data=f"season_{season['id']}"
        ))
    
    keyboard.add(InlineKeyboardButton("بازگشت به لیست سریال ها", callback_data="back_to_series"))
    return keyboard

def episodes_keyboard(season_id):
    episodes = get_season_episodes(season_id)
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    for episode in episodes:
        keyboard.add(InlineKeyboardButton(
            f"قسمت {episode['episode_number']} - {episode['title']}" if episode['title'] else f"قسمت {episode['episode_number']}",
            callback_data=f"episode_{episode['id']}"
        ))
    
    keyboard.add(InlineKeyboardButton("بازگشت به لیست فصل ها", callback_data=f"back_to_seasons"))
    return keyboard

def media_action_keyboard(media_type, media_id, file_id=None):
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    if file_id:
        keyboard.add(InlineKeyboardButton("دانلود 📥", callback_data=f"download_{media_type}_{media_id}"))
    
    if media_type == "series":
        keyboard.add(InlineKeyboardButton("مشاهده فصل ها", callback_data=f"view_seasons_{media_id}"))
    elif media_type == "season":
        keyboard.add(InlineKeyboardButton("مشاهده قسمت ها", callback_data=f"view_episodes_{media_id}"))
    
    keyboard.add(InlineKeyboardButton("اشتراک گذاری 🔗", 
                                     url=f"https://t.me/{BOT_USERNAME}?start=share_{media_type}_{media_id}"))
    keyboard.add(InlineKeyboardButton("بازگشت", callback_data=f"back_{media_type}"))
    
    return keyboard

def edit_options_keyboard(media_type, media_id):
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    keyboard.add(InlineKeyboardButton("ویرایش عنوان", callback_data=f"edit_title_{media_type}_{media_id}"))
    keyboard.add(InlineKeyboardButton("ویرایش توضیحات", callback_data=f"edit_desc_{media_type}_{media_id}"))
    keyboard.add(InlineKeyboardButton("ویرایش تگ ها", callback_data=f"edit_tags_{media_type}_{media_id}"))
    keyboard.add(InlineKeyboardButton("ویرایش نام های جایگزین", callback_data=f"edit_alt_{media_type}_{media_id}"))
    
    if media_type == "movie":
        keyboard.add(InlineKeyboardButton("ویرایش سال", callback_data=f"edit_year_{media_type}_{media_id}"))
        keyboard.add(InlineKeyboardButton("ویرایش کیفیت", callback_data=f"edit_quality_{media_type}_{media_id}"))
    
    keyboard.add(InlineKeyboardButton("اضافه کردن کیفیت جدید", callback_data=f"add_quality_{media_type}_{media_id}"))
    keyboard.add(InlineKeyboardButton("اضافه کردن پوستر", callback_data=f"add_poster_{media_type}_{media_id}"))
    keyboard.add(InlineKeyboardButton("حذف", callback_data=f"delete_{media_type}_{media_id}"))
    keyboard.add(InlineKeyboardButton("بازگشت", callback_data=f"back_to_{media_type}_{media_id}"))
    
    return keyboard

def confirmation_keyboard(action, id):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("بله ✅", callback_data=f"confirm_{action}_{id}"),
        InlineKeyboardButton("خیر ❌", callback_data=f"cancel_{action}_{id}")
    )
    return keyboard

def broadcast_confirmation_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("ارسال به همه کاربران", callback_data="broadcast_all"),
        InlineKeyboardButton("ارسال به کاربران خاص", callback_data="broadcast_specific"),
        InlineKeyboardButton("لغو", callback_data="cancel_broadcast")
    )
    return keyboard