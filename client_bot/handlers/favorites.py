import logging
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from shared.database import get_user_followed_ads_paginated, get_user_followed_ads_count, get_ad, get_ad_history
from shared.utils import format_ad_message
from client_bot.keyboards import get_main_menu_kb

logger = logging.getLogger(__name__)
router = Router()

ITEMS_PER_PAGE = 5

async def show_favorites_page(message_or_callback: types.Message | CallbackQuery, user_id: int, page: int = 0, is_edit: bool = False):
    total_count = await get_user_followed_ads_count(user_id)
    if total_count == 0:
        text = "You have no favorite ads."
        # Fetch counts logic for menu? 
        # Actually this is usually triggered from menu, so we are here.
        # But if we just unfollowed last one?
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.answer("No favorites found.")
            await message_or_callback.message.edit_text(text)
        else:
            await message_or_callback.answer(text)
        return

    offset = page * ITEMS_PER_PAGE
    ads = await get_user_followed_ads_paginated(user_id, offset, ITEMS_PER_PAGE)
    
    total_pages = (total_count - 1) // ITEMS_PER_PAGE + 1
    
    # Build List
    keyboard = []
    
    for ad in ads:
        # Title: #ID Brand Model Year
        # Limit length?
        title = f"#{ad['ad_id']} {ad.get('car_brand', '')} {ad.get('car_model', '')} {ad.get('car_year', '')}"
        keyboard.append([InlineKeyboardButton(text=title, callback_data=f"fav_detail:{ad['ad_id']}:{page}")])
    
    # Navigation
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"fav_page:{page-1}"))
        
        # "Page X of Y" - purely visual or just count?
        nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
        
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"fav_page:{page+1}"))
        
        keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton(text="🔙 Back", callback_data="fav_close")])
    
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    text = f"⭐ <b>Favorites ({total_count})</b>\nSelect an ad to view details:"
    
    if is_edit and isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    elif isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(text, reply_markup=markup, parse_mode="HTML")
    elif isinstance(message_or_callback, CallbackQuery):
        # Should be is_edit=True usually
        await message_or_callback.message.answer(text, reply_markup=markup, parse_mode="HTML")

@router.message(F.text == "⭐ Favorites")
async def cmd_favorites(message: types.Message):
    await show_favorites_page(message, message.from_user.id, page=0, is_edit=False)

@router.callback_query(F.data.startswith("fav_page:"))
async def on_fav_page(callback: CallbackQuery):
    _, page_str = callback.data.split(":")
    await show_favorites_page(callback, callback.from_user.id, page=int(page_str), is_edit=True)
    await callback.answer()

@router.callback_query(F.data == "fav_close")
async def on_fav_close(callback: CallbackQuery):
    await callback.message.delete()
    # We don't send main menu because it's already there behind the inline message usually?
    # No, usually inline message is separate. User sent "Favorites" text message, bot replied with inline.
    # So deleting it cleans up.
    await callback.answer()

@router.callback_query(F.data.startswith("fav_detail:"))
async def on_fav_detail(callback: CallbackQuery):
    _, ad_id, page_str = callback.data.split(":")
    page = int(page_str)
    
    ad = await get_ad(ad_id)
    if not ad:
        await callback.answer("Ad not found.")
        return

    history = await get_ad_history(ad_id, limit=5)
    text = format_ad_message(ad, 'detailed', history)
    
    # Custom buttons for Favorite Detail View
    # Needs: Unfollow (toggle?), Back (to list)
    # If we use standard toggle_follow logic, it expects specific callback data to update itself.
    # But here we want custom layout.
    
    # If we reuse 'toggle_follow:{ad_id}', `management.py` will intercept it and update the button.
    # That works.
    
    buttons = [
        [
            InlineKeyboardButton(text="Unfollow", callback_data=f"toggle_follow:{ad_id}"),
            # Standard 'Details' doesn't make sense here as we ARE in details.
            # Maybe 'Open URL'?
            InlineKeyboardButton(text="🔗 Open on Site", url=ad['ad_url'])
        ],
        [InlineKeyboardButton(text="🔙 Back to List", callback_data=f"fav_page:{page}")]
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    await callback.answer()
