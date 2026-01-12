from typing import Any, Callable, Dict, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from shared.database import log_user_activity

class UserActivityMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        
        user_id = None
        action = None
        
        if isinstance(event, Message):
            user_id = event.from_user.id
            action = f"message: {event.text[:50] if event.text else 'content_type=' + event.content_type}"
            
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
            action = f"callback: {event.data}"
            
        if user_id:
            # Fire and forget logging to avoid blocking response
            # Note: In production we might want to use background task, 
            # but log_user_activity is async and fast, so awaiting it is fine for now.
            try:
                await log_user_activity(user_id, action)
            except Exception as e:
                # Don't fail the request if logging fails
                pass

        return await handler(event, data)
