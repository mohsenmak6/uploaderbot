# main.py
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from config import BOT_TOKEN
from database import init_db
from handlers import router
from middlewares import ChannelCheckMiddleware, CallbackChannelCheckMiddleware

async def main():
    # Initialize database
    init_db()
    
    # Initialize bot and dispatcher
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    
    # Register middlewares
    dp.message.middleware(ChannelCheckMiddleware())
    dp.callback_query.middleware(CallbackChannelCheckMiddleware())
    
    # Include router
    dp.include_router(router)
    
    # Start polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())