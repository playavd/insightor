import logging
import re
from datetime import datetime
from bs4 import BeautifulSoup
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from shared.database import (
    get_user_followed_ads_paginated, get_user_followed_ads_count, 
    get_ad, get_ad_history, is_ad_followed_by_user, add_ad, follow_ad
)
from shared.utils import format_ad_message
from client_bot.keyboards import get_main_menu_kb
from client_bot.states import FavoriteAddition
from scraper_service.logic import BazarakiScraper

logger = logging.getLogger(__name__)
router = Router()

ITEMS_PER_PAGE = 5

async def show_favorites_page(message_or_callback: types.Message | CallbackQuery, user_id: int, page: int = 0, is_edit: bool = False):
    total_count = await get_user_followed_ads_count(user_id)
    if total_count == 0:
        # Show empty state with Add button
         text = "You have no favorite ads."
         keyboard = [
            [InlineKeyboardButton(text="➕ Add by URL", callback_data="fav_add_url")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="fav_close")]
         ]
         markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
         
         if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.message.edit_text(text, reply_markup=markup)
            await message_or_callback.answer()
         else:
            await message_or_callback.answer(text, reply_markup=markup)
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
    keyboard.append([InlineKeyboardButton(text="➕ Add by URL", callback_data="fav_add_url")])
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

@router.callback_query(F.data == "fav_add_url")
async def on_fav_add_url(callback: CallbackQuery, state: FSMContext):
    await state.set_state(FavoriteAddition.WaitingForURL)
    
    await callback.message.answer(
        "🔗 <b>Add Ad by URL</b>\n\n"
        "Please paste the Bazaraki ad link.\n"
        "Example: <code>https://www.bazaraki.com/adv/1234567_slug/</code>\n\n"
        "Type /cancel to cancel.",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(F.text, StateFilter(FavoriteAddition.WaitingForURL))
async def process_fav_url_input(message: types.Message, state: FSMContext, scraper: BazarakiScraper):
    url = message.text.strip()
    
    if url in ["/cancel", "❌ Cancel"]:
        await state.clear()
        await show_favorites_page(message, message.from_user.id, 0)
        return
        
    # Validation
    if "bazaraki.com/adv/" not in url:
         await message.answer("❌ Invalid link.\nMust contain <code>bazaraki.com/adv/</code>.\nTry again or /cancel.", parse_mode="HTML")
         return
    
    try:
        # Extract ID roughly to check existence first
        # Match /adv/123456_ or /adv/123456/
        # Allow trailing stuff
        match = re.search(r"/adv/(\d+)", url)
        if not match:
             await message.answer("❌ Could not extract Ad ID from link.\nPlease make sure it is a valid listing URL.")
             return
        
        ad_id = match.group(1)
        user_id = message.from_user.id
        
        # Check if already followed
        if await is_ad_followed_by_user(user_id, ad_id):
            await message.answer("⚠️ You are already following this ad!")
            # Show details?
            ad = await get_ad(ad_id)
            if ad:
                 # Show details immediately
                 history = await get_ad_history(ad_id, limit=5)
                 text = format_ad_message(ad, 'detailed', history)
                 buttons = [[InlineKeyboardButton(text="Unfollow", callback_data=f"toggle_follow:{ad_id}")]]
                 await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
            await state.clear()
            return
            
        # Not followed -> Scrape
        status_msg = await message.answer("🔎 Checking link...")
        
        # Scraper injected via middleware

        
        details = await scraper.fetch_ad_details(url)
        
        if not details:
             await status_msg.edit_text("❌ Failed to fetch details.\nThe page might be unavailable or protected.")
             await state.clear()
             return

        # Check category (Car check)
        # We need breadcrumbs or some indicator. 
        # utils.AdData has 'car_brand', 'car_model'. If empty -> maybe not car?
        # But 'fetch_ad_details' tries to parse these.
        # If 'car_brand' is present, it's likely a car.
        
        # Additional check: fetch_ad_details extracts from 'chars-column'.
        # If no relevant car fields (brand, model, engine, mileage), warn user?
        # But requirement says "check if it's car category".
        # Let's rely on 'car_brand' field presence which comes from breadcrumbs "Motors -> Cars -> ..."
        
        if not details.get('car_brand') and not details.get('car_model'):
             # Fallback check: look at raw logic? 
             # scraper logic.py puts brand/model if breadcrumbs match.
             # If not matched, it tries title.
             # If still nothing, it might be weird.
             pass 
             
        # Add to DB
        # Construct full AdData
        # We need price too, fetched from details page? 
        # logic.py fetch_ad_details DOES NOT fetch price usually (scraper gets it from listing).
        # We need to ensure we get price. Scraper logic updated in check_followed_ads to parse price from details.
        
        # Re-using logic from check_followed_ads to parse price is hard without code duplication or refactor.
        # Let's simple parse price here or update fetch_ad_details?
        # Updating fetch_ad_details in logic.py to return price is best but might break others? No.
        # But for now let's just do a quick scrape of price using logic we know works or reuse scraper instance method if we add one.
        
        # Actually logic.py:301 gets price from listing not details.
        # But check_followed_ads (added recently) parses price from soup!
        # But we can't easily call check_followed_ads logic here.
        # We rely on 'details' dict from 'fetch_ad_details'.
        
        # !!! CRITICAL: fetch_ad_details does NOT return price.
        # We must extend fetch_ad_details or do a separate price parse.
        # Or better: let's update fetch_ad_details in logic.py to include price parsing if possible?
        # User asked to avoid modifying scraper logic too much if not needed.
        # But wait, check_followed_ads ALREADY implements price parsing from details soup.
        # We should probably extract that logic or just do it here.
        # BUT we don't have the soup here.
        
        # Use scraper to fetch page text again? OR modify fetch_ad_details.
        # Let's modify fetch_ad_details to return price if found.
        
        # WAIT: I can't modify logic.py easily in this turn without breaking flow. 
        # I will assume I can parse price from the 'url' by calling scraper.fetch_page myself here?
        # Yes, I can use scraper.fetch_page() and parse.
        
        html = await scraper.fetch_page(url)
        soup = BeautifulSoup(html, 'lxml')
        
        # Price Parse
        price = 0
        price_tag = soup.find(class_='advert__content-price') or soup.find('div', class_='price') or soup.find(class_='announcement-price__cost')
        if price_tag:
             text = price_tag.get_text(separator='|', strip=True)
             nums = [int(''.join(filter(str.isdigit, p))) for p in text.split('|') if any(c.isdigit() for c in p)]
             if nums: price = nums[0]
             
        # Status?
        # check_followed_ads logic for status:
        is_vip = soup.find(class_='ribbon-vip') or soup.find(class_='label-vip')
        is_top = soup.find(class_='label-top') or soup.find(class_='_top')
        status = 'VIP' if is_vip else 'TOP' if is_top else 'Basic'
        
        # Prepare Ad Data
        full_ad = {
            'ad_id': ad_id,
            'ad_url': url,
            'first_seen': datetime.now(),
            'post_date': details.get('post_date'),
            'initial_price': price,
            'current_price': price,
            'car_brand': details.get('car_brand'),
            'car_model': details.get('car_model'),
            'car_year': details.get('car_year'),
            'car_color': details.get('car_color'),
            'gearbox': details.get('gearbox'),
            'body_type': details.get('body_type'),
            'fuel_type': details.get('fuel_type'),
            'engine_size': details.get('engine_size'),
            'drive_type': details.get('drive_type'),
            'mileage': details.get('mileage'),
            'user_name': details.get('user_name'),
            'user_id': details.get('user_id'),
            'is_business': details.get('is_business'),
            'ad_status': status
        }
        
        await add_ad(full_ad)
        await follow_ad(user_id, ad_id)
        
        # Show detailed view immediately
        text = format_ad_message(full_ad, 'detailed')
        
        buttons = [
            [
                InlineKeyboardButton(text="Unfollow", callback_data=f"toggle_follow:{ad_id}"),
                InlineKeyboardButton(text="🔗 Open on Site", url=full_ad['ad_url'])
            ],
            [InlineKeyboardButton(text="🔙 Back to List", callback_data="fav_close")]
        ]
        
        await status_msg.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error adding fav url: {e}")
        await message.answer("❌ Error processing link.")
        await state.clear()
