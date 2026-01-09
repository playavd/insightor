import logging
from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


from shared.database import (
    update_alert, create_alert, get_latest_matching_ads, get_distinct_values, get_alert
)
from shared.utils import format_ad_message
from client_bot.states import AlertEditor
from client_bot.keyboards import get_dashboard_kb, get_main_menu_kb

logger = logging.getLogger(__name__)
router = Router()

async def return_to_dashboard(message: types.Message, state: FSMContext):
    data = await state.get_data()
    filters = data.get('filters', {})
    kb = get_dashboard_kb(filters)
    
    await state.set_state(AlertEditor.Menu)
    await message.answer("➕ <b>New Alert Wizard</b>", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "dash_cancel", StateFilter(AlertEditor))
async def dash_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    
    from shared.database import get_user_alerts_count, get_user_followed_ads_count
    user_id = callback.from_user.id
    alerts_cnt = await get_user_alerts_count(user_id)
    fav_cnt = await get_user_followed_ads_count(user_id)
    
    await callback.message.answer("❌ Alert creation cancelled.", reply_markup=get_main_menu_kb(alerts_cnt, fav_cnt))

@router.callback_query(F.data == "dash_save", StateFilter(AlertEditor))
async def dash_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    filters = data.get('filters', {})
    editing_id = data.get('editing_alert_id')
    
    if editing_id:
        await update_alert(editing_id, callback.from_user.id, filters)
        # Fetch name for notification
        alert = await get_alert(editing_id)
        name = alert['name'] if alert else "Alert"
        msg_title = "✅ <b>Alert Updated!</b>"
    else:
        name = f"Alert {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        alert_id = await create_alert(callback.from_user.id, name, filters)
        msg_title = f"✅ <b>Alert Saved!</b>\nName: {name}"

    await state.clear()
    await callback.message.delete()
    
    from shared.database import get_user_alerts_count, get_user_followed_ads_count
    user_id = callback.from_user.id
    alerts_cnt = await get_user_alerts_count(user_id)
    fav_cnt = await get_user_followed_ads_count(user_id)

    await callback.message.answer(
        f"{msg_title}\n(You can manage it in 'My Alerts')",
        reply_markup=get_main_menu_kb(alerts_cnt, fav_cnt),
        parse_mode="HTML"
    )
    
    wait_msg = await callback.message.answer("🔎 Searching recent matches...")
    matches = await get_latest_matching_ads(filters, limit=5)
    await wait_msg.delete()
    
    if matches:
        await callback.message.answer(f"🔎 Found {len(matches)} recent matches:")
        
        # Determine alert_id
        current_alert_id = editing_id if editing_id else alert_id
        
        # Pre-fetch followed status for efficiency
        from shared.database import get_all_followed_ads_by_user
        followed_ads = await get_all_followed_ads_by_user(callback.from_user.id)
        
        for ad in matches:
            try:
                text = format_ad_message(ad, 'new')
                if text: 
                    # Prepend Alert Name
                    final_text = f"🔔 <b>{name}</b>\n\n{text}"
                    
                    # Determine button text
                    is_following = ad['ad_id'] in followed_ads
                    follow_btn_text = "Unfollow" if is_following else "Follow"
                    
                    # Add standard buttons
                    buttons = [
                       [
                           InlineKeyboardButton(text=follow_btn_text, callback_data=f"toggle_follow:{ad['ad_id']}"),
                           InlineKeyboardButton(text="Details", callback_data=f"more_details:{ad['ad_id']}"),
                           InlineKeyboardButton(text="Deactivate", callback_data=f"toggle_alert:{current_alert_id}:off")
                       ]
                    ]
                    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
                    
                    await callback.message.answer(final_text, parse_mode="HTML", reply_markup=kb)
            except Exception as e:
                logger.error(f"Failed to send match {ad.get('ad_id')}: {e}")
    else:
        await callback.message.answer("ℹ️ No recent matches found.")

@router.callback_query(F.data.startswith("edit_"), StateFilter(AlertEditor.Menu))
async def edit_field_start(callback: CallbackQuery, state: FSMContext):
    field = callback.data.replace("edit_", "")
    text_fields = ["year_min", "year_max", "price_min", "price_max", "mileage_max", "engine_min", "engine_max", "target_user_id"]
    selection_fields = ["brand", "model", "gearbox", "fuel_type", "drive_type", "body_type", "color", "ad_status", "is_business"]

    if field in text_fields:
        await state.update_data(editing_field=field)
        await state.set_state(AlertEditor.InputText)
        prompt = f"Enter value for <b>{field.replace('_', ' ').title()}</b>:"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="Any (Clear)", callback_data=f"set_any:{field}")
        builder.button(text="🔙 Back", callback_data="dash_back")
        builder.adjust(1)
        
        await callback.message.edit_text(prompt, reply_markup=builder.as_markup(), parse_mode="HTML")
    
    elif field in selection_fields:
        await start_selection(callback, state, field)

@router.callback_query(F.data.startswith("set_any:"))
async def process_any_button(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[1]
    data = await state.get_data()
    filters = data.get('filters', {})
    filters[field] = None 
    if field == "year_min": filters['year_max'] = None
    
    await state.update_data(filters=filters)
    # Return to dashboard
    # Since we are in callback, better to edit usage
    kb = get_dashboard_kb(filters)
    await state.set_state(AlertEditor.Menu)
    await callback.message.edit_text("➕ <b>New Alert Wizard</b>", reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "dash_back")
async def process_dash_back(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    filters = data.get('filters', {})
    kb = get_dashboard_kb(filters)
    await state.set_state(AlertEditor.Menu)
    await callback.message.edit_text("➕ <b>New Alert Wizard</b>", reply_markup=kb, parse_mode="HTML")

@router.message(AlertEditor.InputText)
async def process_dashboard_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data.get('editing_field')
    text = message.text.strip()
    
    if text == "/cancel":
        await return_to_dashboard(message, state)
        return

    val = None
    
    # Special handling for target_user_id which is string
    if field == "target_user_id":
        val = text
        # Basic validation could be added
    else:
        # Numeric fields
        if not text.isdigit():
            await message.answer("❌ Invalid format. Please enter a number.\nTry again or /cancel.")
            return
        val = int(text)
    
    filters = data.get('filters', {})
    filters[field] = val
    await state.update_data(filters=filters)
    await return_to_dashboard(message, state)

# --- Selection Logic ---

async def start_selection(callback: CallbackQuery, state: FSMContext, field: str, page: int = 0):
    await state.set_state(AlertEditor.SelectOption)
    
    options = []
    if field == "brand": options = await get_distinct_values('car_brand')
    elif field == "model":
        data = await state.get_data()
        brand = data.get('filters', {}).get('brand')
        if not brand:
            await callback.answer("Please select Brand first.")
            return
        options = await get_distinct_values('car_model', 'car_brand', brand)
    elif field == "gearbox": options = await get_distinct_values('gearbox')
    elif field == "fuel_type": options = await get_distinct_values('fuel_type')
    elif field == "drive_type": options = await get_distinct_values('drive_type')
    elif field == "body_type": options = await get_distinct_values('body_type')
    elif field == "color": options = await get_distinct_values('car_color')
    elif field == "ad_status": options = ["Basic", "VIP", "TOP", "VIP+TOP"]
    elif field == "is_business": options = ["Private", "Business", "Any"]
    
    options = [str(o) for o in options if o]
    options.sort()
    if field not in ["is_business"]: options.insert(0, "Any")

    # Pagination
    ITEMS_PER_PAGE = 30
    total_pages = (len(options) - 1) // ITEMS_PER_PAGE + 1
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    chunk = options[start:end]
    
    builder = InlineKeyboardBuilder()
    for opt in chunk:
        val_safe = opt[:40] 
        builder.button(text=opt, callback_data=f"sel:{field}:{val_safe}")
    
    builder.adjust(2)
    
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"pg:{field}:{page-1}"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"pg:{field}:{page+1}"))
    
    if nav_row: builder.row(*nav_row)
    builder.row(InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="dash_back"))
    
    await callback.message.edit_text(f"Select <b>{field.title()}</b>:", reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("pg:"))
async def process_pagination(callback: CallbackQuery, state: FSMContext):
    _, field, page_str = callback.data.split(":")
    await start_selection(callback, state, field, int(page_str))

@router.callback_query(F.data.startswith("sel:"))
async def process_selection(callback: CallbackQuery, state: FSMContext):
    _, field, value = callback.data.split(":", 2)
    
    data = await state.get_data()
    filters = data.get('filters', {})
    
    if value == "Any": 
        filters[field] = None
    else:
        if field == "is_business":
             filters[field] = (value == "Business")
        else:
             filters[field] = value

    await state.update_data(filters=filters)
    
    kb = get_dashboard_kb(filters)
    await state.set_state(AlertEditor.Menu)
    await callback.message.edit_text("➕ <b>New Alert Wizard</b>", reply_markup=kb, parse_mode="HTML")
