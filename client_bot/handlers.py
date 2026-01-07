import logging
import json
import difflib
from datetime import datetime
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardRemove, KeyboardButton, ReplyKeyboardMarkup, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from shared.config import MAX_ALERTS_BASIC
from shared.database import (
    add_or_update_user, get_user, create_alert, get_user_alerts,
    delete_alert, toggle_alert, get_distinct_values, get_min_max_values,
    get_alert, get_latest_matching_ads, update_alert, rename_alert,
    get_active_alerts_count_by_user
)
from shared.utils import format_ad_message

from .states import AlertCreation, AlertEditor, AlertManagement
from .keyboards import get_main_menu_kb, get_nav_kb, get_dashboard_kb

logger = logging.getLogger(__name__)
user_router = Router()

# --- Helpers ---
async def get_current_alerts_map(state: FSMContext, alerts: list):
    # Map "Status Name" -> Alert Dict to handle button clicks
    mapping = {}
    for alert in alerts:
        status_icon = "🟢" if alert['is_active'] else "🔴"
        key = f"{status_icon} {alert['name']}"
        mapping[key] = alert
    await state.update_data(alerts_map=mapping)

async def return_to_dashboard(message: types.Message, state: FSMContext):
    data = await state.get_data()
    filters = data.get('filters', {})
    kb = get_dashboard_kb(filters)
    
    await state.set_state(AlertEditor.Menu)
    await message.answer("➕ <b>New Alert Wizard</b>", reply_markup=kb, parse_mode="HTML")

async def save_alert_early(message: types.Message, state: FSMContext):
    # Placeholder for saving mid-wizard if we supported it fully
    # Currently we just direct to dashboard Save
    await message.answer("Please use the 'Save & Finish' or 'Activate' button in the dashboard/menu.")

# --- Start & Menu Handlers ---

@user_router.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    await add_or_update_user(user.id, user.username, user.first_name)
    
    await message.answer(
        f"👋 Hello, {user.first_name}!\n\n"
        "I can help you monitor Bazaraki for new car ads.\n"
        "Select an option to get started:",
        reply_markup=get_main_menu_kb()
    )

@user_router.message(F.text == "🔔 New Alert", StateFilter("*"))
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
             "Deactivate one in '🗂️ My Alerts', or upgrade to <b>⭐ Pro</b>.",
             parse_mode="HTML"
        )
        return

    # Initialize new alert state
    await state.clear()
    
    # We default to Cars category implicitly.
    await state.update_data(category="Cars", filters={})
    
    # OPTION 2: Dashboard First (Skipping Linear Wizard)
    await state.set_state(AlertEditor.Menu)
    
    kb = get_dashboard_kb({})
    # Remove existing Reply Keyboard to prevent confusion
    loading_msg = await message.answer("🔄 Loading...", reply_markup=ReplyKeyboardRemove())
    await loading_msg.delete()
    await message.answer("➕ <b>New Alert Wizard</b>\n\nSelect a filter to edit:", reply_markup=kb, parse_mode="HTML")

@user_router.message(F.text == "🗂️ My Alerts", StateFilter("*"))
async def show_alert_list(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    alerts = await get_user_alerts(user_id)
    
    if not alerts:
        await message.answer("You have no alerts.", reply_markup=get_main_menu_kb())
        return

    builder = ReplyKeyboardBuilder()
    for alert in alerts:
        status_icon = "🟢" if alert['is_active'] else "🔴"
        builder.button(text=f"{status_icon} {alert['name']}")
    
    builder.button(text="🔔 New Alert")
    builder.button(text="⬅️ Back")
    builder.adjust(1)
    
    await state.set_state(AlertManagement.ViewingList)
    await get_current_alerts_map(state, alerts)
    await message.answer("Select an alert to view details:", reply_markup=builder.as_markup(resize_keyboard=True))

@user_router.message(F.text == "❌ Cancel", StateFilter(AlertCreation))
async def cancel_wizard(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Alert creation cancelled.", reply_markup=get_main_menu_kb())

# --- Wizard Flow (Brand -> Model -> Year -> ...) ---

# Note: We removed Category handler.

@user_router.message(AlertCreation.Brand)
async def process_brand(message: types.Message, state: FSMContext):
    text = message.text.strip()
    
    if text == "⬅️ Back":
        # Back from Brand goes to Main Menu (Cancelled)
        await state.clear()
        await message.answer("Back to Main Menu", reply_markup=get_main_menu_kb())
        return

    if text == "💾 Save & Finish":
        # Redirect to generic save? Or just assume Brand Only alert?
        # We'll treat it as Brand Only and go to dashboard/save.
        # Ideally we should construct filters and show dashboard.
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
        await state.update_data(model=None) # Explicitly clear model in state data if needed
        # filters already has no model
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

@user_router.message(AlertCreation.Model)
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

@user_router.message(AlertCreation.YearFrom)
async def process_year_from(message: types.Message, state: FSMContext):
    # Missing from previous snippet? Assuming logic similar to others.
    # Logic: Read text, validate int, update filters['year_min']
    text = message.text.strip()
    
    if text == "⬅️ Back":
        # Back logic depends on if we came from Brand or Model
        data = await state.get_data()
        if data.get('filters', {}).get('brand'):
             # If brand was selected, we probably went through Model
             # But if Brand was ANY, we skipped Model.
             # We need to know previous step.
             # Simple heuristic:
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

@user_router.message(AlertCreation.YearTo)
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

    # Move to Dashboard/Editor directly? Or Price?
    # Original flow had PriceMax.
    await state.set_state(AlertCreation.PriceMax)
    _, max_p = await get_min_max_values('current_price')
    await message.answer(f"Step 5: Max Price (max ~{max_p}€)", reply_markup=get_nav_kb(include_any=True))

@user_router.message(AlertCreation.PriceMax)
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
    
    # Transition to AlertEditor state
    await state.set_state(AlertEditor.Menu)
    
    msg_load = await message.answer("🔄 Finalizing Wizard...", reply_markup=ReplyKeyboardRemove())
    await msg_load.delete()
    await message.answer(
        "✅ <b>Basic Setup Complete!</b>\n\n"
        "Review your settings below. You can refine them (e.g. Fuel, Gearbox) or click Activate.", 
        reply_markup=kb, 
        parse_mode="HTML"
    )


# --- Dashboard / Editor Handlers ---

@user_router.callback_query(F.data == "dash_cancel", StateFilter(AlertEditor))
async def dash_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("❌ Alert creation cancelled.", reply_markup=get_main_menu_kb())

@user_router.callback_query(F.data == "dash_save", StateFilter(AlertEditor))
async def dash_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    filters = data.get('filters', {})
    editing_id = data.get('editing_alert_id')
    
    if editing_id:
        await update_alert(editing_id, callback.from_user.id, filters)
        msg_title = "✅ <b>Alert Updated!</b>"
    else:
        name = f"Alert {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        await create_alert(callback.from_user.id, name, filters)
        msg_title = f"✅ <b>Alert Saved!</b>\nName: {name}"

    await state.clear()
    await callback.message.delete()
    await callback.message.answer(
        f"{msg_title}\n(You can manage it in 'My Alerts')",
        reply_markup=get_main_menu_kb(),
        parse_mode="HTML"
    )
    
    wait_msg = await callback.message.answer("🔎 Searching recent matches...")
    matches = await get_latest_matching_ads(filters, limit=5)
    await wait_msg.delete()
    
    if matches:
        await callback.message.answer(f"🔎 Found {len(matches)} recent matches:")
        for ad in matches:
            text = format_ad_message(ad, 'new')
            if text: await callback.message.answer(text, parse_mode="HTML")
    else:
        await callback.message.answer("ℹ️ No recent matches found.")

@user_router.callback_query(F.data.startswith("edit_"), StateFilter(AlertEditor.Menu))
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

@user_router.callback_query(F.data.startswith("set_any:"))
async def process_any_button(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[1]
    data = await state.get_data()
    filters = data.get('filters', {})
    filters[field] = None 
    if field == "year_min": filters['year_max'] = None # Clear max if min cleared? Optional.
    
    await state.update_data(filters=filters)
    # Return to dashboard
    await return_to_dashboard(callback.message, state) # Use message from callback
    # Note: return_to_dashboard uses message.answer (new message). 
    # But for callback in editor we usually edit.
    # We should adapt return_to_dashboard to edit if possible.
    # For now, let's just do it inline here to be clean.
    kb = get_dashboard_kb(filters)
    await state.set_state(AlertEditor.Menu)
    await callback.message.edit_text("➕ <b>New Alert Wizard</b>", reply_markup=kb, parse_mode="HTML")

@user_router.callback_query(F.data == "dash_back")
async def process_dash_back(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    filters = data.get('filters', {})
    kb = get_dashboard_kb(filters)
    await state.set_state(AlertEditor.Menu)
    await callback.message.edit_text("➕ <b>New Alert Wizard</b>", reply_markup=kb, parse_mode="HTML")

@user_router.message(AlertEditor.InputText)
async def process_dashboard_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data.get('editing_field')
    text = message.text.strip()
    
    if text == "/cancel":
        await return_to_dashboard(message, state)
        return

    val = None
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
    # Dynamic options...
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

@user_router.callback_query(F.data.startswith("pg:"))
async def process_pagination(callback: CallbackQuery, state: FSMContext):
    _, field, page_str = callback.data.split(":")
    await start_selection(callback, state, field, int(page_str))

@user_router.callback_query(F.data.startswith("sel:"))
async def process_selection(callback: CallbackQuery, state: FSMContext):
    _, field, value = callback.data.split(":", 2)
    
    data = await state.get_data()
    filters = data.get('filters', {})
    
    if value == "Any": 
        filters[field] = None
    else:
        # Handle types
        if field == "is_business":
             filters[field] = (value == "Business")
        else:
             filters[field] = value

    await state.update_data(filters=filters)
    
    kb = get_dashboard_kb(filters)
    await state.set_state(AlertEditor.Menu)
    await callback.message.edit_text("➕ <b>New Alert Wizard</b>", reply_markup=kb, parse_mode="HTML")

# --- Alert Management (Viewing / Deleting) ---

@user_router.message(AlertManagement.ViewingList)
async def process_alert_selection(message: types.Message, state: FSMContext):
    text = message.text
    if text == "⬅️ Back":
        await state.clear()
        await message.answer("Main Menu", reply_markup=get_main_menu_kb())
        return

    data = await state.get_data()
    mapping = data.get('alerts_map', {})
    alert = mapping.get(text)
    
    if not alert:
        await message.answer("Alert not found. Please select from the list.")
        return
    
    filters = json.loads(alert['filters'])
    
    # Simple summary (can be expanded)
    details = []
    for k, v in filters.items():
        if k == 'is_business':
             val = "Business" if v else "Private"
             details.append(f"Seller Type: {val}")
        elif v: 
             details.append(f"{k}: {v}")
    details_str = "\n".join(details)
    
    await state.update_data(current_alert_id=alert['alert_id'])
    await state.set_state(AlertManagement.ViewingDetail)
    
    action_btn = "Deactivate" if alert['is_active'] else "Activate"
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=action_btn), KeyboardButton(text="⚙️ Edit Filters")],
        [KeyboardButton(text="✏️ Rename"), KeyboardButton(text="🗑 Delete")],
        [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="🏠 Main Menu")]
    ], resize_keyboard=True)
    
    await message.answer(f"📋 <b>Alert: {alert['name']}</b>\n{details_str}", reply_markup=kb, parse_mode="HTML")

@user_router.message(AlertManagement.ViewingDetail)
async def process_alert_action(message: types.Message, state: FSMContext):
    text = message.text
    user_id = message.from_user.id
    data = await state.get_data()
    alert_id = data.get('current_alert_id')
    
    if text == "⬅️ Back":
        await show_alert_list(message, state) # Go back to list
        return

    if text == "🏠 Main Menu":
        await state.clear()
        await message.answer("🏠 Main Menu", reply_markup=get_main_menu_kb())
        return
    
    if text in ["Activate", "Deactivate"]:
        new_status = (text == "Activate")
        await toggle_alert(alert_id, user_id, new_status)
        await message.answer(f"Alert {text}d.")
        if new_status:
             alert = await get_alert(alert_id)
             if alert:
                 msg = await message.answer("🔎 Searching recent matches...")
                 fs = json.loads(alert['filters'])
                 matches = await get_latest_matching_ads(fs, limit=5)
                 await msg.delete()
                 for ad in matches:
                     t = format_ad_message(ad, 'new')
                     if t: await message.answer(t, parse_mode="HTML")
        await show_alert_list(message, state)
        return

    if text == "🗑 Delete":
        await delete_alert(alert_id, user_id)
        await message.answer("Alert deleted.")
        await show_alert_list(message, state)
        return
        
    if text == "⚙️ Edit Filters":
        alert = await get_alert(alert_id)
        if alert:
             filters = json.loads(alert['filters'])
             await state.set_state(AlertEditor.Menu)
             await state.update_data(filters=filters, editing_alert_id=alert_id)
             kb = get_dashboard_kb(filters)
             await message.answer("🛠 <b>Editing Alert</b>", reply_markup=kb, parse_mode="HTML")
        return

    if text == "✏️ Rename":
        await state.set_state(AlertEditor.Rename)
        await message.answer("Enter new name for the alert (max 25 chars):")
        return

    await message.answer("Unknown action.")

@user_router.message(AlertEditor.Rename)
async def process_rename(message: types.Message, state: FSMContext):
    name = message.text.strip()[:25]
    data = await state.get_data()
    alert_id = data.get('current_alert_id')
    user_id = message.from_user.id
    
    if name == "/cancel":
         await show_alert_list(message, state)
         return

    await rename_alert(alert_id, user_id, name)
    await message.answer(f"✅ Renamed to '{name}'.")
    
    await show_alert_list(message, state)
