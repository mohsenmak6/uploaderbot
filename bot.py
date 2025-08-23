import logging, json, random, string, re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode

# === Config ===
BOT_TOKEN = "8417638218:AAGfO3ubY0ruAVsoF9-stdUM9U7nLDvTXg4"
ADMIN_ID = 123661460  # آیدی عددی ادمین
REQUIRED_CHANNELS = ["@booodgeh"]  # کانال‌هایی که عضویت اجباری است
FILES_DB_PATH = "files_db.json"
KEYS_DB_PATH = "keys_db.json"
USERS_DB_PATH = "users_db.json"

# === Data ===
FILES_DB = {}     # {file_id: {"name": ..., "caption": ..., "downloads": int, "date": ...}}
FILE_KEYS = {}    # {short_key: file_id}
USERS_DB = {}     # {user_id: {"downloads": [file_id, ...], "first_seen": ..., "last_seen": ...}}

# === Logging ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === Helpers ===
def generate_key(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def save_db():
    with open(FILES_DB_PATH, "w") as f: json.dump(FILES_DB, f)
    with open(KEYS_DB_PATH, "w") as f: json.dump(FILE_KEYS, f)
    with open(USERS_DB_PATH, "w") as f: json.dump(USERS_DB, f)

def load_db():
    global FILES_DB, FILE_KEYS, USERS_DB
    try: FILES_DB = json.load(open(FILES_DB_PATH))
    except: FILES_DB = {}
    try: FILE_KEYS = json.load(open(KEYS_DB_PATH))
    except: FILE_KEYS = {}
    try: USERS_DB = json.load(open(USERS_DB_PATH))
    except: USERS_DB = {}

async def is_member(user_id, context):
    for ch in REQUIRED_CHANNELS:
        try:
            member = await context.bot.get_chat_member(ch, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except:
            return False
    return True

def record_download(user_id, file_id):
    user_id_str = str(user_id)
    USERS_DB.setdefault(user_id_str, {"downloads": [], "first_seen": datetime.now().isoformat(), "last_seen": datetime.now().isoformat()})
    USERS_DB[user_id_str]["downloads"].append(file_id)
    USERS_DB[user_id_str]["last_seen"] = datetime.now().isoformat()
    
    if file_id in FILES_DB:
        FILES_DB[file_id]["downloads"] = FILES_DB[file_id].get("downloads", 0) + 1
    save_db()

def get_admin_keyboard():
    return ReplyKeyboardMarkup([
        ["📊 آمار ربات", "📂 مدیریت فایل‌ها"],
        ["📢 ارسال پیام به همه", "🔄 به روزرسانی دیتابیس"]
    ], resize_keyboard=True)

def format_file_info(file_id, file_data, bot_username):
    # Find the key for this file
    key = None
    for k, v in FILE_KEYS.items():
        if v == file_id:
            key = k
            break
    
    if key and bot_username:
        bot_link = f"https://t.me/{bot_username}?start={key}"
        return (
            f"📁 نام فایل: {file_data.get('name', 'نامشخص')}\n"
            f"📝 کپشن: {file_data.get('caption', 'بدون کپشن')}\n"
            f"📥 تعداد دانلود: {file_data.get('downloads', 0)}\n"
            f"📅 تاریخ آپلود: {file_data.get('date', 'نامشخص')}\n"
            f"🔗 لینک مستقیم: {bot_link}"
        )
    return f"📁 نام فایل: {file_data.get('name', 'نامشخص')}\n📝 کپشن: {file_data.get('caption', 'بدون کپشن')}\n📥 تعداد دانلود: {file_data.get('downloads', 0)}\n📅 تاریخ آپلود: {file_data.get('date', 'نامشخص')}"

# === Handlers ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    now = datetime.now().isoformat()

    # ثبت کاربر در دیتابیس
    if str(user.id) not in USERS_DB:
        USERS_DB[str(user.id)] = {"downloads": [], "first_seen": now, "last_seen": now}
    else:
        USERS_DB[str(user.id)]["last_seen"] = now
    save_db()

    if not await is_member(user.id, context):
        await update.message.reply_text("⚠️ لطفاً ابتدا در کانال‌های زیر عضو شوید:\n" + "\n".join(REQUIRED_CHANNELS))
        return

    payload = update.message.text.replace("/start", "").strip()
    if payload:
        file_id = FILE_KEYS.get(payload)
        if file_id and file_id in FILES_DB:
            caption = FILES_DB[file_id].get("caption") or f"📂 {FILES_DB[file_id]['name']}"
            await context.bot.send_document(chat_id=user.id, document=file_id, caption=caption)
            record_download(user.id, file_id)
        else:
            await update.message.reply_text("❌ فایل یافت نشد یا لینک نامعتبر است.")
        return

    if user.id == ADMIN_ID:
        await update.message.reply_text("سلام ادمین 👑", reply_markup=get_admin_keyboard())
    else:
        await update.message.reply_text("سلام 👋 برای دریافت فایل روی دکمه یا لینک کلیک کنید.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: 
        return

    file = None
    file_name = "file"
    if update.message.document:
        file = update.message.document
        file_name = file.file_name or "document"
    elif update.message.video:
        file = update.message.video
        file_name = "video.mp4"
    elif update.message.audio:
        file = update.message.audio
        file_name = getattr(file, "file_name", "audio.mp3")
    elif update.message.photo:
        file = update.message.photo[-1]
        file_name = "photo.jpg"

    if file:
        file_id = file.file_id
        context.user_data["awaiting_name_for"] = file_id
        await update.message.reply_text("📝 لطفاً یک نام برای فایل ارسال کنید:")

async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: 
        return
        
    file_id = context.user_data.get("awaiting_name_for")
    if not file_id:
        return
        
    file_name = update.message.text
    FILES_DB[file_id] = {
        "name": file_name, 
        "caption": None, 
        "downloads": 0,
        "date": datetime.now().isoformat()
    }
    
    context.user_data["awaiting_caption_for"] = file_id
    context.user_data.pop("awaiting_name_for", None)
    
    await update.message.reply_text("📝 لطفاً متن یا توضیح فایل را ارسال کنید (یا /skip برای رد کردن):")

async def handle_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: 
        return
        
    file_id = context.user_data.get("awaiting_caption_for")
    if not file_id or file_id not in FILES_DB: 
        return

    caption = update.message.text
    FILES_DB[file_id]["caption"] = caption
    short_key = generate_key()
    FILE_KEYS[short_key] = file_id
    save_db()
    context.user_data.pop("awaiting_caption_for", None)

    bot_username = context.bot.username
    deep_link = f"https://t.me/{bot_username}?start={short_key}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 دریافت فایل", callback_data=f"get_{short_key}")],
        [InlineKeyboardButton("🔗 لینک اشتراک‌گذاری", url=deep_link)],
        [InlineKeyboardButton("✏️ ویرایش", callback_data=f"edit_{short_key}")]
    ])
    await update.message.reply_text("✅ فایل و متن ذخیره شدند!", reply_markup=keyboard)

async def skip_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: 
        return
        
    file_id = context.user_data.get("awaiting_caption_for")
    if not file_id or file_id not in FILES_DB: 
        return

    FILES_DB[file_id]["caption"] = None
    short_key = generate_key()
    FILE_KEYS[short_key] = file_id
    save_db()
    context.user_data.pop("awaiting_caption_for", None)

    bot_username = context.bot.username
    deep_link = f"https://t.me/{bot_username}?start={short_key}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 دریافت فایل", callback_data=f"get_{short_key}")],
        [InlineKeyboardButton("🔗 لینک اشتراک‌گذاری", url=deep_link)],
        [InlineKeyboardButton("✏️ ویرایش", callback_data=f"edit_{short_key}")]
    ])
    await update.message.reply_text("✅ فایل ذخیره شد!", reply_markup=keyboard)

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if not await is_member(user_id, context):
        await query.message.reply_text("⚠️ لطفاً ابتدا در کانال‌های زیر عضو شوید:\n" + "\n".join(REQUIRED_CHANNELS))
        return

    if data.startswith("get_"):
        short_key = data.replace("get_", "")
        file_id = FILE_KEYS.get(short_key)
        if file_id and file_id in FILES_DB:
            caption = FILES_DB[file_id].get("caption") or f"📂 {FILES_DB[file_id]['name']}"
            await context.bot.send_document(chat_id=user_id, document=file_id, caption=caption)
            record_download(user_id, file_id)
        else:
            await query.message.reply_text("❌ فایل یافت نشد یا لینک نامعتبر است.")
    
    elif data.startswith("edit_"):
        if user_id != ADMIN_ID:
            await query.answer("❌ فقط ادمین می‌تواند ویرایش کند!", show_alert=True)
            return
            
        short_key = data.replace("edit_", "")
        file_id = FILE_KEYS.get(short_key)
        
        if file_id and file_id in FILES_DB:
            context.user_data["editing_file"] = file_id
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"editname_{short_key}")],
                [InlineKeyboardButton("✏️ ویرایش کپشن", callback_data=f"editcaption_{short_key}")],
                [InlineKeyboardButton("🗑️ حذف فایل", callback_data=f"delete_{short_key}")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_files")]
            ])
            await query.edit_message_text(
                f"ویرایش فایل:\n{format_file_info(file_id, FILES_DB[file_id], context.bot.username)}",
                reply_markup=keyboard
            )
    
    elif data.startswith("editname_"):
        short_key = data.replace("editname_", "")
        file_id = FILE_KEYS.get(short_key)
        
        if file_id and file_id in FILES_DB:
            context.user_data["editing_file_name"] = file_id
            await query.message.reply_text("لطفاً نام جدید را وارد کنید:")
    
    elif data.startswith("editcaption_"):
        short_key = data.replace("editcaption_", "")
        file_id = FILE_KEYS.get(short_key)
        
        if file_id and file_id in FILES_DB:
            context.user_data["editing_file_caption"] = file_id
            await query.message.reply_text("لطفاً کپشن جدید را وارد کنید:")
    
    elif data.startswith("delete_"):
        short_key = data.replace("delete_", "")
        file_id = FILE_KEYS.get(short_key)
        
        if file_id and file_id in FILES_DB:
            # حذف فایل از دیتابیس
            del FILES_DB[file_id]
            del FILE_KEYS[short_key]
            save_db()
            
            await query.edit_message_text("✅ فایل با موفقیت حذف شد!")
    
    elif data == "stats":
        if user_id != ADMIN_ID:
            await query.answer("❌ فقط ادمین می‌تواند آمار را ببیند!", show_alert=True)
            return
            
        total_users = len(USERS_DB)
        total_files = len(FILES_DB)
        total_downloads = sum(f.get("downloads", 0) for f in FILES_DB.values())
        
        stats_text = (
            f"📊 آمار ربات:\n\n"
            f"👥 کاربران کل: {total_users}\n"
            f"📁 فایل‌های کل: {total_files}\n"
            f"📥 دانلودهای کل: {total_downloads}\n"
        )
        
        await query.edit_message_text(stats_text)
    
    elif data == "file_list":
        if user_id != ADMIN_ID:
            await query.answer("❌ فقط ادمین می‌تواند لیست فایل‌ها را ببیند!", show_alert=True)
            return
            
        if not FILES_DB:
            await query.edit_message_text("📭 هنوز فایلی آپلود نشده است.")
            return
            
        # ایجاد صفحه‌بندی برای لیست فایل‌ها
        files_list = list(FILES_DB.items())
        page = context.user_data.get("file_list_page", 0)
        max_page = max(0, (len(files_list) - 1) // 5)
        
        # محدود کردن صفحه به محدوده معتبر
        page = max(0, min(page, max_page))
        context.user_data["file_list_page"] = page
        
        # ایجاد دکمه‌های صفحه‌بندی
        keyboard_buttons = []
        start_idx = page * 5
        end_idx = min(start_idx + 5, len(files_list))
        
        for i in range(start_idx, end_idx):
            file_id, file_data = files_list[i]
            # پیدا کردن کلید برای این فایل
            key = None
            for k, v in FILE_KEYS.items():
                if v == file_id:
                    key = k
                    break
            
            if key:
                keyboard_buttons.append([InlineKeyboardButton(
                    f"📁 {file_data.get('name', 'نامشخص')} - 📥 {file_data.get('downloads', 0)}",
                    callback_data=f"edit_{key}"
                )])
        
        # دکمه‌های صفحه‌بندی
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"page_{page-1}"))
        if page < max_page:
            nav_buttons.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"page_{page+1}"))
        
        if nav_buttons:
            keyboard_buttons.append(nav_buttons)
        
        keyboard_buttons.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_admin")])
        
        keyboard = InlineKeyboardMarkup(keyboard_buttons)
        await query.edit_message_text(
            f"📂 لیست فایل‌ها (صفحه {page+1} dari {max_page+1}):",
            reply_markup=keyboard
        )
    
    elif data.startswith("page_"):
        page = int(data.replace("page_", ""))
        context.user_data["file_list_page"] = page
        # ایجاد دکمه شبیه سازی برای بازگشت به لیست فایل‌ها
        fake_query = type('', (), {'data': 'file_list', 'edit_message_text': query.edit_message_text})()
        await handle_button(update, context)
    
    elif data == "back_to_admin":
        if user_id == ADMIN_ID:
            await query.edit_message_text("به پنل ادمین خوش آمدید 👑", reply_markup=get_admin_keyboard())
    
    elif data == "back_to_files":
        if user_id == ADMIN_ID:
            # ایجاد دکمه شبیه سازی برای بازگشت به لیست فایل‌ها
            fake_query = type('', (), {'data': 'file_list', 'edit_message_text': query.edit_message_text})()
            await handle_button(update, context)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    if user_id == ADMIN_ID:
        # حالت‌های مختلف برای ادمین
        if "awaiting_name_for" in context.user_data:
            await handle_name(update, context)
        elif "awaiting_caption_for" in context.user_data:
            await handle_caption(update, context)
        elif "editing_file_name" in context.user_data:
            file_id = context.user_data["editing_file_name"]
            if file_id in FILES_DB:
                FILES_DB[file_id]["name"] = text
                save_db()
                await update.message.reply_text("✅ نام فایل با موفقیت به روز شد!")
                context.user_data.pop("editing_file_name", None)
        elif "editing_file_caption" in context.user_data:
            file_id = context.user_data["editing_file_caption"]
            if file_id in FILES_DB:
                FILES_DB[file_id]["caption"] = text
                save_db()
                await update.message.reply_text("✅ کپشن فایل با موفقیت به روز شد!")
                context.user_data.pop("editing_file_caption", None)
        elif text == "📊 آمار ربات":
            total_users = len(USERS_DB)
            total_files = len(FILES_DB)
            total_downloads = sum(f.get("downloads", 0) for f in FILES_DB.values())
            
            # محاسبه کاربران فعال (اخیراً دیده شده)
            active_users = 0
            for user_data in USERS_DB.values():
                last_seen_str = user_data.get("last_seen")
                if last_seen_str:
                    try:
                        last_seen = datetime.fromisoformat(last_seen_str)
                        if (datetime.now() - last_seen).days < 7:  # کاربرانی که در ۷ روز گذشته فعال بودند
                            active_users += 1
                    except:
                        pass
            
            stats_text = (
                f"📊 آمار کامل ربات:\n\n"
                f"👥 کاربران کل: {total_users}\n"
                f"🔥 کاربران فعال (۷ روز گذشته): {active_users}\n"
                f"📁 فایل‌های کل: {total_files}\n"
                f"📥 دانلودهای کل: {total_downloads}\n\n"
                f"📈 پرطرفدارترین فایل‌ها:\n"
            )
            
            # پیدا کردن ۵ فایل پرطرفدار
            popular_files = sorted(FILES_DB.items(), key=lambda x: x[1].get("downloads", 0), reverse=True)[:5]
            for i, (file_id, file_data) in enumerate(popular_files, 1):
                stats_text += f"{i}. {file_data.get('name', 'نامشخص')} - {file_data.get('downloads', 0)} دانلود\n"
            
            await update.message.reply_text(stats_text)
        
        elif text == "📂 مدیریت فایل‌ها":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 لیست فایل‌ها", callback_data="file_list")],
                [InlineKeyboardButton("📊 آمار فایل‌ها", callback_data="stats")]
            ])
            await update.message.reply_text("مدیریت فایل‌ها:", reply_markup=keyboard)
        
        elif text == "🔄 به روزرسانی دیتابیس":
            load_db()
            await update.message.reply_text("✅ دیتابیس با موفقیت به روز شد!")
        
        elif text == "📢 ارسال پیام به همه":
            await update.message.reply_text("لطفاً متن پیام را ارسال کنید:")
            context.user_data["broadcast"] = True
        
        elif context.user_data.get("broadcast"):
            count = 0
            failed = 0
            for user_id_str in USERS_DB.keys():
                try:
                    await context.bot.send_message(int(user_id_str), text)
                    count += 1
                except:
                    failed += 1
            await update.message.reply_text(f"📢 پیام برای {count} نفر ارسال شد. ({failed} ناموفق)")
            context.user_data["broadcast"] = False

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("به پنل ادمین خوش آمدید 👑", reply_markup=get_admin_keyboard())

# === Main ===
def main():
    load_db()
    app = Application.builder().token(BOT_TOKEN).build()
    
    # handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("skip", skip_caption))
    
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO, 
        handle_file
    ))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_button))
    
    print("✅ Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
