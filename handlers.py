
# handlers.py
from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardRemove
from database import *
from keyboards import *
from utils import *
from states import AdminStates
from config import ADMINS
import re

router = Router()

# Start command handler
@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    
    # Check if deep linking
    if len(message.text.split()) > 1:
        deep_link = message.text.split()[1]
        if deep_link.startswith("share_"):
            # Handle deep linking for sharing media
            parts = deep_link.split("_")
            if len(parts) >= 3:
                media_type = parts[1]
                media_id = parts[2]
                
                if media_type == "movie":
                    movie = get_movie(media_id)
                    if movie:
                        caption = format_movie_info(movie)
                        await message.answer_photo(
                            movie['poster_file_id'] if movie['poster_file_id'] else types.FSInputFile("default_poster.jpg"),
                            caption=caption,
                            reply_markup=media_action_keyboard("movie", media_id, movie['file_id'])
                        )
                        return
                elif media_type == "series":
                    series = get_series(media_id)
                    if series:
                        caption = format_series_info(series)
                        await message.answer_photo(
                            series['poster_file_id'] if series['poster_file_id'] else types.FSInputFile("default_poster.jpg"),
                            caption=caption,
                            reply_markup=media_action_keyboard("series", media_id)
                        )
                        return
                elif media_type == "episode":
                    episode = get_episode(media_id)
                    if episode:
                        season = get_season(episode['season_id'])
                        series = get_series(season['series_id']) if season else None
                        caption = format_episode_info(episode, season, series)
                        await message.answer_video(
                            episode['file_id'],
                            caption=caption,
                            reply_markup=media_action_keyboard("episode", media_id, episode['file_id'])
                        )
                        return
    
    # Regular start command
    user_id = message.from_user.id
    user_data = {
        'id': user_id,
        'username': message.from_user.username,
        'first_name': message.from_user.first_name,
        'last_name': message.from_user.last_name
    }
    add_user(user_data)
    
    if user_id in ADMINS:
        await message.answer("سلام ادمین گرامی! 👋", reply_markup=admin_keyboard())
    else:
        await message.answer("خوش آمدید! 👋", reply_markup=main_menu_keyboard())

# Admin commands
@router.message(F.text == "آپلود محتوا 📤")
async def admin_upload(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await message.answer("شما دسترسی لازم را ندارید.")
        return
    
    await message.answer("لطفا نوع محتوایی که میخواهید آپلود کنید را انتخاب کنید:", reply_markup=upload_options_keyboard())
    await state.set_state(AdminStates.waiting_for_movie)

@router.message(F.text == "مدیریت محتوا 🛠")
async def admin_manage(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await message.answer("شما دسترسی لازم را ندارید.")
        return
    
    await message.answer("لطفا نوع عملیاتی که میخواهید انجام دهید را انتخاب کنید:", reply_markup=manage_options_keyboard())
    await state.set_state(AdminStates.waiting_for_edit)

@router.message(F.text == "ارسال پیام به کاربران ✉️")
async def admin_broadcast(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        await message.answer("شما دسترسی لازم را ندارید.")
        return
    
    await message.answer("لطفا پیامی که میخواهید برای کاربران ارسال کنید را وارد کنید:", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_broadcast)

@router.message(F.text == "بازگشت به منوی اصلی 🔙")
async def back_to_main(message: types.Message, state: FSMContext):
    await state.clear()
    if message.from_user.id in ADMINS:
        await message.answer("منوی اصلی ادمین", reply_markup=admin_keyboard())
    else:
        await message.answer("منوی اصلی", reply_markup=main_menu_keyboard())

# Upload handlers
@router.message(AdminStates.waiting_for_movie, F.text == "آپلود فیلم 🎬")
async def upload_movie_step1(message: types.Message, state: FSMContext):
    await message.answer("لطفا فیلم را ارسال کنید:", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_movie_info)

@router.message(AdminStates.waiting_for_movie_info, F.video)
async def upload_movie_step2(message: types.Message, state: FSMContext):
    file_id = message.video.file_id
    await state.update_data(file_id=file_id)
    await message.answer("لطفا اطلاعات فیلم را به فرمت زیر ارسال کنید:\nعنوان|سال|توضیحات|تگ ها (با کاما جدا شوند)", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_movie_info)

@router.message(AdminStates.waiting_for_movie_info, F.text)
async def upload_movie_step3(message: types.Message, state: FSMContext):
    if message.text == "لغو ❌":
        await state.clear()
        await message.answer("عملیات لغو شد.", reply_markup=admin_keyboard())
        return
    
    data = await state.get_data()
    movie_info = parse_movie_info(message.text)
    movie_info['file_id'] = data['file_id']
    
    # Add movie to database
    movie_id = add_movie(movie_info)
    
    await message.answer("فیلم با موفقیت اضافه شد. آیا میخواهید کیفیت دیگری اضافه کنید؟", reply_markup=quality_keyboard())
    await state.update_data(movie_id=movie_id, media_type="movie")
    await state.set_state(AdminStates.waiting_for_quality)

@router.message(AdminStates.waiting_for_movie, F.text == "آپلود سریال 📺")
async def upload_series_step1(message: types.Message, state: FSMContext):
    await message.answer("لطفا اطلاعات سریال را به فرمت زیر ارسال کنید:\nعنوان|توضیحات|تگ ها (با کاما جدا شوند)", reply_markup=cancel_keyboard())
    await state.set_state(AdminStates.waiting_for_series_info)

@router.message(AdminStates.waiting_for_series_info, F.text)
async def upload_series_step2(message: types.Message, state: FSMContext):
    if message.text == "لغو ❌":
        await state.clear()
        await message.answer("عملیات لغو شد.", reply_markup=admin_keyboard())
        return
    
    series_info = parse_series_info(message.text)
    series_id = add_series(series_info)
    
    await message.answer("سریال با موفقیت اضافه شد. آیا میخواهید پوستر اضافه کنید؟", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="بله ✅", callback_data="add_poster_series"),
        InlineKeyboardButton(text="خیر ❌", callback_data="skip_poster")]
    ]))
    await state.update_data(series_id=series_id)
    await state.set_state(AdminStates.waiting_for_poster)

# Add more handlers for seasons, episodes, etc.

# Callback query handlers
@router.callback_query(F.data.startswith("movie_"))
async def show_movie_details(callback: types.CallbackQuery):
    movie_id = callback.data.split("_")[1]
    movie = get_movie(movie_id)
    
    if movie:
        caption = format_movie_info(movie)
        if movie['poster_file_id']:
            await callback.message.answer_photo(
                movie['poster_file_id'],
                caption=caption,
                reply_markup=media_action_keyboard("movie", movie_id, movie['file_id'])
            )
        else:
            await callback.message.answer(
                caption,
                reply_markup=media_action_keyboard("movie", movie_id, movie['file_id'])
            )
    else:
        await callback.answer("فیلم یافت نشد.")
    
    await callback.answer()

@router.callback_query(F.data.startswith("download_"))
async def download_media(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    media_type = parts[1]
    media_id = parts[2]
    
    if media_type == "movie":
        movie = get_movie(media_id)
        if movie:
            await callback.message.answer_video(movie['file_id'])
    elif media_type == "episode":
        episode = get_episode(media_id)
        if episode:
            await callback.message.answer_video(episode['file_id'])
    
    await callback.answer()

@router.callback_query(F.data.startswith("view_seasons_"))
async def view_series_seasons(callback: types.CallbackQuery):
    series_id = callback.data.split("_")[2]
    keyboard = seasons_keyboard(series_id)
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()

# Add more callback handlers for pagination, editing, etc.

# Inline query handler
@router.inline_query()
async def inline_query_handler(inline_query: types.InlineQuery):
    query = inline_query.query
    if not query:
        return
    
    results = []
    media_results = search_media(query)
    
    for i, item in enumerate(media_results[:50]):  # Limit to 50 results
        if 'type' not in item or item['type'] == 'movie':
            caption = format_movie_info(item)
            input_content = types.InputTextMessageContent(
                message_text=caption,
                parse_mode="HTML"
            )
            
            result = types.InlineQueryResultArticle(
                id=str(i),
                title=item['title'],
                description=item.get('description', '')[:100],
                input_message_content=input_content,
                reply_markup=media_action_keyboard("movie", item['id'], item['file_id'])
            )
            results.append(result)
        else:
            caption = format_series_info(item)
            input_content = types.InputTextMessageContent(
                message_text=caption,
                parse_mode="HTML"
            )
            
            result = types.InlineQueryResultArticle(
                id=str(i),
                title=item['title'],
                description=item.get('description', '')[:100],
                input_message_content=input_content,
                reply_markup=media_action_keyboard("series", item['id'])
            )
            results.append(result)
    
    await inline_query.answer(results, cache_time=300, is_personal=True)

# Main menu handlers
@router.message(F.text == "فیلم ها 🎬")
async def show_movies(message: types.Message):
    await message.answer("لیست فیلم ها:", reply_markup=movie_list_keyboard())

@router.message(F.text == "سریال ها 📺")
async def show_series(message: types.Message):
    await message.answer("لیست سریال ها:", reply_markup=series_list_keyboard())

@router.message(F.text == "جستجو 🔍")
async def search_media_handler(message: types.Message, state: FSMContext):
    await message.answer("لطفا عبارت جستجو را وارد کنید:", reply_markup=cancel_keyboard())
    await state.set_state("waiting_for_search")

@router.message(F.text == "راهنما ❓")
async def show_help(message: types.Message):
    help_text = """
🤖 راهنمای ربات فیلم و سریال

📥 برای دریافت فیلم یا سریال:
- از منوی اصلی گزینه «فیلم ها» یا «سریال ها» را انتخاب کنید
- یا از گزینه «جستجو» برای یافتن محتوای خاص استفاده کنید

🔍 برای جستجو:
- می توانید با عنوان، تگ ها یا نام های جایگزین جستجو کنید

🎬 برای دریافت لینک مستقیم:
- روی دکمه «دانلود» در زیر هر محتوا کلیک کنید

📤 برای اشتراک گذاری:
- از دکمه «اشتراک گذاری» استفاده کنید

👨‍💼 بخش ادمین:
- فقط ادمین ها می توانند محتوا آپلود و مدیریت کنند
    """
    await message.answer(help_text)

# Add more handlers as needed
