import logging
import difflib
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove

from shared.constants import MAX_ALERTS_BASIC
from shared.database import (
    get_user, add_or_update_user, get_active_alerts_count_by_user,
    get_distinct_values, get_min_max_values
)
from client_bot.states import AlertCreation, AlertEditor
from client_bot.keyboards import get_dashboard_kb, get_nav_kb
# Note: Cyclic import avoidance - we import common parts or just needed keyboards

logger = logging.getLogger(__name__)
router = Router()

@router.message(F.text == "🔔 New Alert", StateFilter("*"))
async def start_new_alert(message: types.Message, state: FSMContext):
    # Check if user exists
    user = await get_user(message.from_user.id)
    if not user:
        await add_or_update_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    
    # Check active alerts
    active_count = await get_active_alerts_count_by_user(message.from_user.id)
    
    if active_count >= MAX_ALERTS_BASIC:
        await message.answer(
             f"🚫 <b>Alerts limit reached ({active_count}/{MAX_ALERTS_BASIC} active).</b>\n\n"
             "Deactivate one in '🗂️ My Alerts', or upgrade to <b>🎖️ Pro</b>.",
             parse_mode="HTML"
        )
        return

    # Initialize new alert state
    await state.clear()
    
    # We default to Cars category implicitly.
    await state.update_data(category="Cars", filters={})
    
    # Dashboard First approach
    await state.set_state(AlertEditor.Menu)
    
    kb = get_dashboard_kb({})
    # Remove existing Reply Keyboard to prevent confusion
    loading_msg = await message.answer("🔄 Loading...", reply_markup=ReplyKeyboardRemove())
    await loading_msg.delete()
    await message.answer("➕ <b>New Alert Wizard</b>\n\nSelect a filter to edit:", reply_markup=kb, parse_mode="HTML")

# --- Wizard Steps (optional flow if accessed otherwise, or fallback) ---
# Keeping existing logic for linear wizard just in case we re-enable it or user hits back to it
# Note: The original handlers had full wizard flow (Brand -> Model...). 
# I will preserve it here.

@router.message(AlertCreation.Brand)
async def process_brand(message: types.Message, state: FSMContext):
    text = message.text.strip()
    
    if text == "⬅️ Back":
        # Back from Brand goes to Main Menu (Cancelled) in original logic
        # We need get_main_menu_kb. Import here to avoid cycle at top if needed, 
        # but utils should be fine.
        from client_bot.keyboards import get_main_menu_kb
        from shared.database import get_user_alerts_count, get_user_followed_ads_count
        user_id = message.from_user.id
        alerts_cnt = await get_user_alerts_count(user_id)
        fav_cnt = await get_user_followed_ads_count(user_id)
        
        await state.clear()
        await message.answer("Back to Main Menu", reply_markup=get_main_menu_kb(alerts_cnt, fav_cnt))
        return

    if text == "💾 Save & Finish":
        await message.answer("Please finish the basic setup first or select ANY for remaining fields.")
        return

    # Validate Brand against DB
    brands = await get_distinct_values('car_brand')
    
    final_brand = text
    if text != "ANY":
        # Check exact (case insensitive)
        match = next((b for b in brands if b.lower() == text.lower()), None)
        
        if not match:
             # Fuzzy search
             possibilities = difflib.get_close_matches(text, brands, n=3, cutoff=0.4)
             msg = f"❌ Brand '{text}' not found."
             if possibilities:
                 msg += f"\nDid you mean: {', '.join(possibilities)}?"
             else:
                 msg += "\nPlease type the full brand name or select ANY."
             await message.answer(msg)
             return
             
        final_brand = match

    data = await state.get_data()
    filters = data.get('filters', {})
    filters['brand'] = final_brand if final_brand != "ANY" else None
    await state.update_data(filters=filters)
    
    if final_brand == "ANY":
        await state.update_data(model=None) 
        await state.set_state(AlertCreation.YearFrom)
        min_y, _ = await get_min_max_values('car_year')
        await message.answer(
            f"Step 3: Year From (Min: {min_y})\nType year (YYYY) or ANY.",
            reply_markup=get_nav_kb(include_any=True)
        )
    else:
        await state.set_state(AlertCreation.Model)
        models = await get_distinct_values('car_model', 'car_brand', final_brand)
        chunked_models = models[:30]
        await message.answer(
            f"Step 2: Model for {final_brand}\nSelect or type model.",
            reply_markup=get_nav_kb(options=chunked_models, include_any=True)
        )

@router.message(AlertCreation.Model)
async def process_model(message: types.Message, state: FSMContext):
    text = message.text.strip()
    
    if text == "⬅️ Back":
        await state.set_state(AlertCreation.Brand)
        await message.answer("Step 1: Brand", reply_markup=get_nav_kb(include_any=True))
        return

    data = await state.get_data()
    filters = data.get('filters', {})

    models_val = [m.strip() for m in text.split(',')] if text != "ANY" else None
    filters['model'] = models_val
    await state.update_data(filters=filters)

    await state.set_state(AlertCreation.YearFrom)
    min_y, _ = await get_min_max_values('car_year')
    await message.answer(
        f"Step 3: Year From (Min: {min_y})\nEnter the year YYYY.",
        reply_markup=get_nav_kb(include_any=True)
    )

@router.message(AlertCreation.YearFrom)
async def process_year_from(message: types.Message, state: FSMContext):
    text = message.text.strip()
    
    if text == "⬅️ Back":
        data = await state.get_data()
        if data.get('filters', {}).get('brand'):
             if 'model' in data.get('filters', {}) and data.get('filters')['brand']:
                 await state.set_state(AlertCreation.Model)
                 brand = data['filters']['brand']
                 models = await get_distinct_values('car_model', 'car_brand', brand)
                 await message.answer(f"Step 2: Model for {brand}", reply_markup=get_nav_kb(options=models[:30], include_any=True))
             else:
                 await state.set_state(AlertCreation.Brand)
                 await message.answer("Step 1: Brand", reply_markup=get_nav_kb(include_any=True))
        else:
             await state.set_state(AlertCreation.Brand)
             await message.answer("Step 1: Brand", reply_markup=get_nav_kb(include_any=True))
        return

    val = None
    if text != "ANY":
        if not text.isdigit():
            await message.answer("Please enter a valid year (YYYY).")
            return
        val = int(text)

    data = await state.get_data()
    filters = data.get('filters', {})
    filters['year_min'] = val
    await state.update_data(filters=filters)

    await state.set_state(AlertCreation.YearTo)
    await message.answer("Step 4: Year To", reply_markup=get_nav_kb(include_any=True))

@router.message(AlertCreation.YearTo)
async def process_year_to(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if text == "⬅️ Back":
        await state.set_state(AlertCreation.YearFrom)
        min_y, _ = await get_min_max_values('car_year')
        await message.answer(f"Step 3: Year From", reply_markup=get_nav_kb(include_any=True))
        return

    val = None
    if text != "ANY":
        if not text.isdigit():
            await message.answer("Please enter a valid year.")
            return
        val = int(text)
        
    data = await state.get_data()
    filters = data.get('filters', {})
    filters['year_max'] = val
    await state.update_data(filters=filters)

    await state.set_state(AlertCreation.PriceMax)
    _, max_p = await get_min_max_values('current_price')
    await message.answer(f"Step 5: Max Price (max ~{max_p}€)", reply_markup=get_nav_kb(include_any=True))

@router.message(AlertCreation.PriceMax)
async def process_price_max(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if text == "⬅️ Back":
        await state.set_state(AlertCreation.YearTo)
        await message.answer("Step 4: Year To", reply_markup=get_nav_kb(include_any=True))
        return

    val = None
    if text != "ANY":
        if not text.isdigit():
             await message.answer("Please enter a valid price.")
             return
        val = int(text)

    data = await state.get_data()
    filters = data.get('filters', {})
    filters['price_max'] = val
    await state.update_data(filters=filters)

    # End of basic wizard -> Show Dashboard
    kb = get_dashboard_kb(filters)
    
    await state.set_state(AlertEditor.Menu)
    
    msg_load = await message.answer("🔄 Finalizing Wizard...", reply_markup=ReplyKeyboardRemove())
    await msg_load.delete()
    await message.answer(
        "✅ <b>Basic Setup Complete!</b>\n\n"
        "Review your settings below. You can refine them (e.g. Fuel, Gearbox) or click Activate.", 
        reply_markup=kb, 
        parse_mode="HTML"
    )
