# main.py
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from config import BOT_TOKEN
from database import init_db
from handlers import router
from middlewares import ChannelCheckMiddleware, CallbackChannelCheckMiddleware

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    try:
        # Initialize database
        init_db()
        logger.info("Database initialized successfully")
        
        # Initialize bot and dispatcher
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher()
        
        # Register middlewares
        dp.message.middleware(ChannelCheckMiddleware())
        dp.callback_query.middleware(CallbackChannelCheckMiddleware())
        
        # Include router
        dp.include_router(router)
        
        logger.info("Bot starting...")
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
