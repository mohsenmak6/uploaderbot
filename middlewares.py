# middlewares.py
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
from database import add_user, update_user_channels_status, get_user
from utils import check_channels_membership

class ChannelCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        # Skip channel check for admins
        if event.from_user.id in data['config'].ADMINS:
            return await handler(event, data)
        
        # Check if user has joined required channels
        user_joined = await check_channels_membership(event.from_user.id, event.bot)
        
        # Update user status in database
        user_data = {
            'id': event.from_user.id,
            'username': event.from_user.username,
            'first_name': event.from_user.first_name,
            'last_name': event.from_user.last_name
        }
        add_user(user_data)
        update_user_channels_status(event.from_user.id, user_joined)
        
        # If user hasn't joined all channels, send message with channel links
        if not user_joined:
            channels_text = "\n".join([f"➡️ {channel}" for channel in data['config'].REQUIRED_CHANNELS])
            await event.answer(
                f"⚠️ برای استفاده از ربات، لطفا در کانال های زیر عضو شوید:\n\n{channels_text}\n\nسپس دوباره /start را بزنید.",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        
        return await handler(event, data)

class CallbackChannelCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: Dict[str, Any]
    ) -> Any:
        # Skip channel check for admins
        if event.from_user.id in data['config'].ADMINS:
            return await handler(event, data)
        
        # Check if user has joined required channels
        user_joined = await check_channels_membership(event.from_user.id, event.bot)
        
        # Update user status in database
        user_data = {
            'id': event.from_user.id,
            'username': event.from_user.username,
            'first_name': event.from_user.first_name,
            'last_name': event.from_user.last_name
        }
        add_user(user_data)
        update_user_channels_status(event.from_user.id, user_joined)
        
        # If user hasn't joined all channels, send message with channel links
        if not user_joined:
            channels_text = "\n".join([f"➡️ {channel}" for channel in data['config'].REQUIRED_CHANNELS])
            await event.message.edit_text(
                f"⚠️ برای استفاده از ربات، لطفا در کانال های زیر عضو شوید:\n\n{channels_text}\n\nسپس دوباره /start را بزنید."
            )
            return
        
        return await handler(event, data)