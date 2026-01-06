import logging
import json
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

from config import MAX_ALERTS_BASIC
from database import (
    add_or_update_user, get_user, create_alert, get_user_alerts,
    delete_alert, toggle_alert, get_distinct_values, get_min_max_values,
    get_alert, get_latest_matching_ads, format_ad_message, update_alert, rename_alert,
    get_active_alerts_count_by_user
)

logger = logging.getLogger(__name__)
user_router = Router()

# --- Keyboards ---
def get_main_menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔔 New Alert"), KeyboardButton(text="🗂️ My Alerts")],
            [KeyboardButton(text="🔍 Archive Search"), KeyboardButton(text="⭐ Pro")]
        ],
        resize_keyboard=True
    )

def get_nav_kb(options: list[str] | None = None, include_any: bool = True):
    """
    Helper to create keyboards dynamically.
    options: List of main option buttons (e.g. ["Automatic", "Manual"])
    """
    kb = []
    if options:
        # Group options into rows of 2 or 3
        row = []
        for opt in options:
            row.append(KeyboardButton(text=opt))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
    
    if include_any:
        kb.insert(0, [KeyboardButton(text="ANY")])

    # Control Row
    control_row = [
        KeyboardButton(text="⬅️ Back"),
        KeyboardButton(text="💾 Save & Finish"),
        KeyboardButton(text="❌ Cancel")
    ]
    kb.append(control_row)
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- FSM States ---
class AlertCreation(StatesGroup):
    Category = State()
    Brand = State()
    Model = State()
    YearFrom = State()
    YearTo = State()
    PriceMax = State()
    PriceMin = State()
    MileageMax = State()
    MileageMin = State()
    Gearbox = State()
    Fuel = State()
    EngineFrom = State()
    EngineTo = State()
    Drive = State()
    Body = State()
    Color = State()
    AdType = State()
    AdStatus = State()
    UserId = State()
    AlertName = State()

class AlertEditor(StatesGroup):
    Menu = State()
    SelectBrand = State()
    SelectModel = State()
    SelectOption = State() # Generic option selector (Fuel, Body, etc.)
    InputText = State() # Generic text input (Year, Price, etc.)
    Rename = State() # Special state for renaming
    # Specific fields use metadata in state data, not unique states for each

class AlertManagement(StatesGroup):
    ViewingList = State()
    ViewingDetail = State()

# --- Helpers ---
# --- Helpers ---
def get_dashboard_kb(filters: dict) -> InlineKeyboardMarkup:
    """
    Generates the Main Dashboard Inline Keyboard based on current filters.
    """
    builder = InlineKeyboardBuilder()

    # Helper to format button text
    def fmt(label, key, suffix="", prefix=""):
        val = filters.get(key)
        if val is None: return f"{label}: Any"
        return f"{label}: {prefix}{val}{suffix}"

    # Row 1: Brand & Model
    builder.button(text=fmt("Brand", "brand"), callback_data="edit_brand")
    # Show Model ONLY if Brand is selected
    if filters.get("brand"):
        builder.button(text=fmt("Model", "model"), callback_data="edit_model")
    
    # Row 2: Year (Min & Max)
    # Year Max only visible if Year Min is set
    builder.button(text=fmt("Year min", "year_min", prefix=">"), callback_data="edit_year_min")
    if filters.get("year_min"):
        builder.button(text=fmt("Year max", "year_max", prefix="<"), callback_data="edit_year_max")
    
    # Row 3: Price (Max & Min)
    # Price Min visible regardless
    builder.button(text=fmt("Price max", "price_max", "€", prefix="<"), callback_data="edit_price_max")
    builder.button(text=fmt("Price min", "price_min", "€", prefix=">"), callback_data="edit_price_min")

    # Row 4: Mileage
    builder.button(text=fmt("Mileage", "mileage_max", " km", prefix="<"), callback_data="edit_mileage_max")
    
    # Row 5: Engine (Min & Max visible regardless)
    builder.button(text=fmt("Engine min", "engine_min", " cc", prefix=">"), callback_data="edit_engine_min")
    builder.button(text=fmt("Engine max", "engine_max", " cc", prefix="<"), callback_data="edit_engine_max")
    
    # Row 6: Gearbox & Fuel
    builder.button(text=fmt("Gearbox", "gearbox"), callback_data="edit_gearbox")
    builder.button(text=fmt("Fuel", "fuel_type"), callback_data="edit_fuel_type")

    # Row 7: Drivetrain & Body
    builder.button(text=fmt("Drivetrain", "drive_type"), callback_data="edit_drive_type")
    builder.button(text=fmt("Body", "body_type"), callback_data="edit_body_type")
    
    # Row 8: Color
    builder.button(text=fmt("Color", "color"), callback_data="edit_color")
    
    # Row 9: Promo (Ad Status)
    builder.button(text=fmt("Promo", "ad_status"), callback_data="edit_ad_status")

    # Row 10: Seller Type & ID
    u_type = filters.get('is_business')
    u_label = "Any"
    if u_type is True: u_label = "Business"
    elif u_type is False: u_label = "Private"
    builder.button(text=f"Seller Type: {u_label}", callback_data="edit_is_business")
    
    builder.button(text=fmt("Seller ID", "target_user_id"), callback_data="edit_target_user_id")

    # Adjust layout
    # Row 1: 1 or 2 btns
    # Row 2: 1 or 2 btns
    # Row 3: 2 btns
    # Row 4: 1 btn
    # Row 5: 2 btns
    # Row 6: 2 btns
    # Row 7: 2 btns
    # Row 8: 1 btn
    # Row 9: 1 btn
    # Row 10: 2 btns
    
    # Simple strategy: let builder adjust? No, need precise rows.
    # We can just set width=2 for all, it fills rows.
    # But YearMax logic makes it variable.
    # Let's use individual rows or a calculated width list.
    
    sizes = []
    # R1
    sizes.append(2 if filters.get("brand") else 1)
    # R2
    sizes.append(2 if filters.get("year_min") else 1)
    # R3 (Price)
    sizes.append(2)
    # R4 (Mileage)
    sizes.append(1)
    # R5 (Engine)
    sizes.append(2)
    # R6 (Gear/Fuel)
    sizes.append(2)
    # R7 (Drive/Body)
    sizes.append(2)
    # R8 (Color)
    sizes.append(1)
    # R9 (Promo)
    sizes.append(1)
    # R10 (Seller)
    sizes.append(2)
    
    builder.adjust(*sizes)
    
    builder.row(
        InlineKeyboardButton(text="🔙 Back", callback_data="dash_cancel"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="dash_cancel"),
        InlineKeyboardButton(text="✅ Activate", callback_data="dash_save")
    )
    
    return builder.as_markup()

# moved to top

async def get_current_alerts_map(state: FSMContext, alerts: list):
    # Map "Status Name" -> Alert Dict to handle button clicks
    mapping = {}
    for alert in alerts:
        status_icon = "🟢" if alert['is_active'] else "🔴"
        key = f"{status_icon} {alert['name']}"
        mapping[key] = alert
    await state.update_data(alerts_map=mapping)

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
    
    # Show Details
    filters = json.loads(alert['filters'])
    
    # Format details nicely
    details = []
    if filters.get('brand'): details.append(f"• Brand: {filters['brand']}")
    if filters.get('model'): 
        m = filters['model']
        if isinstance(m, list): m = ", ".join(m)
        details.append(f"• Model: {m}")
    if filters.get('year_min') or filters.get('year_max'):
        details.append(f"• Year: {filters.get('year_min', 'Any')} - {filters.get('year_max', 'Any')}")
    if filters.get('price_max') or filters.get('price_min'): 
        details.append(f"• Price: {filters.get('price_min', 0)} - {filters.get('price_max', 'Any')}€")
    if filters.get('mileage_max') or filters.get('mileage_min'): 
        details.append(f"• Mileage: {filters.get('mileage_min', 0)} - {filters.get('mileage_max', 'Any')} km")
    if filters.get('gearbox'): details.append(f"• Gearbox: {filters['gearbox']}")
    if filters.get('fuel_type'): details.append(f"• Fuel: {filters['fuel_type']}")
    if filters.get('engine_min') or filters.get('engine_max'):
        details.append(f"• Engine: {filters.get('engine_min', 0)} - {filters.get('engine_max', 'Any')} cc")
    if filters.get('drive_type'): details.append(f"• Drive: {filters['drive_type']}")
    if filters.get('body_type'): details.append(f"• Body: {filters['body_type']}")
    if filters.get('color'): details.append(f"• Color: {filters['color']}")
    
    if filters.get('is_business') is not None:
        u_type = "Business" if filters['is_business'] else "Private"
        details.append(f"• Seller: {u_type}")
        
    if filters.get('ad_status'): details.append(f"• Ad Status: {filters['ad_status']}")
    if filters.get('target_user_id'): details.append(f"• User ID: {filters['target_user_id']}")
    
    # ... Add more fields as needed for summary ...
    
    details_str = "\n".join(details)
    status_str = "Active" if alert['is_active'] else "Inactive"
    
    await state.update_data(current_alert_id=alert['alert_id'])
    await state.set_state(AlertManagement.ViewingDetail)
    
    # Action Buttons
    action_btn = "Deactivate" if alert['is_active'] else "Activate"
    action_btn = "Deactivate" if alert['is_active'] else "Activate"
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=action_btn), KeyboardButton(text="⚙️ Edit Filters")],
        [KeyboardButton(text="✏️ Rename"), KeyboardButton(text="🗑 Delete")],
        [KeyboardButton(text="⬅️ Back")]
    ], resize_keyboard=True)
    
    await message.answer(
        f"📋 <b>Alert: {alert['name']}</b>\n"
        f"Status: {status_str}\n\n"
        f"<b>Settings:</b>\n{details_str}", 
        reply_markup=kb,
        parse_mode="HTML"
    )

@user_router.message(AlertManagement.ViewingDetail)
async def process_alert_action(message: types.Message, state: FSMContext):
    text = message.text
    user_id = message.from_user.id
    data = await state.get_data()
    alert_id = data.get('current_alert_id')
    
    if text == "⬅️ Back":
        # Return to list
        await show_alert_list(message, state)
        return
        
    if text in ["Activate", "Deactivate"]:
        new_status = (text == "Activate")
        await toggle_alert(alert_id, user_id, new_status)
        await message.answer(f"Alert {text}d.")
        
        # If activating, send initial matches
        if new_status:
            alert = await get_alert(alert_id)
            if alert and alert.get('filters'):
                filters = json.loads(alert['filters'])
                matches = await get_latest_matching_ads(filters, limit=5)
                if matches:
                    await message.answer("🔎 Searching for recent matches...")
                    for ad in matches:
                        t = format_ad_message(ad, 'new')
                        if t: await message.answer(t, parse_mode="HTML")
                    await message.answer(f"✅ Found {len(matches)} recent ads.")
                else:
                    await message.answer("ℹ️ No recent matches found.")
        
        await show_alert_list(message, state)
        return

    if text == "⚙️ Edit Filters":
        alert = await get_alert(alert_id)
        if not alert:
             await message.answer("Alert not found.")
             return await show_alert_list(message, state)
        
        filters = json.loads(alert['filters'])
        await state.set_state(AlertEditor.Menu)
        await state.update_data(filters=filters, editing_alert_id=alert_id)
        
        kb = get_dashboard_kb(filters)
        # Remove existing Reply Keyboard (Alert Detail Actions)
        # Remove existing Reply Keyboard (Alert Detail Actions)
        msg_load = await message.answer("🔄 Switching to Editor...", reply_markup=ReplyKeyboardRemove())
        await msg_load.delete()
        await message.answer(f"🛠 <b>Editing Alert: {alert['name']}</b>", reply_markup=kb, parse_mode="HTML")
        return

    if text == "✏️ Rename":
        await state.set_state(AlertEditor.Rename)
        await message.answer("Enter new name for the alert (max 25 chars):")
        return

    if text == "🗑 Delete":
        await delete_alert(alert_id, user_id)
        await message.answer("Alert deleted.")
        await show_alert_list(message, state)
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
    
    # Reload detail view
    # We need to refresh alert data in state map, but simpler to just go back to list or detail 
    await show_alert_list(message, state)

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

# --- Handlers ---
@user_router.message(F.text == "🔔 New Alert", StateFilter("*"))
async def start_new_alert(message: types.Message, state: FSMContext):
    # Check if user exists
    user = await get_user(message.from_user.id)
    if not user:
        await add_or_update_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        user = await get_user(message.from_user.id)
    
    # Check active alerts - use reliable count
    active_count = await get_active_alerts_count_by_user(message.from_user.id)
    
    if active_count >= MAX_ALERTS_BASIC:
        # Limit Reached
        await message.answer(
             f"🚫 <b>Alerts limit reached ({active_count}/{MAX_ALERTS_BASIC} active).</b>\n\n"
             "Deactivate one in '🗂️ My Alerts', or upgrade to <b>⭐ Pro</b> to unlock up to 100 alerts.",
             parse_mode="HTML"
        )
        return

    # Initialize new alert state
    await state.clear()
    await state.set_state(AlertEditor.Menu)
    
    # Empty filters
    await state.update_data(filters={})
    
    kb = get_dashboard_kb({})
    # Remove existing Reply Keyboard to prevent confusion
    loading_msg = await message.answer("🔄 Loading...", reply_markup=ReplyKeyboardRemove())
    await loading_msg.delete()
    await message.answer("➕ <b>New Alert Wizard</b>\n\nSelect a filter to edit:", reply_markup=kb, parse_mode="HTML")

@user_router.message(F.text == "🗂️ My Alerts", StateFilter("*"))
async def show_alert_list(message: types.Message, state: FSMContext):
    await state.clear() # Clear any previous state
    user_id = message.from_user.id
    alerts = await get_user_alerts(user_id)
    
    if not alerts:
        await message.answer("You have no alerts.", reply_markup=get_main_menu_kb())
        return

    builder = ReplyKeyboardBuilder()
    for alert in alerts:
        status_icon = "🟢" if alert['is_active'] else "🔴"
        builder.button(text=f"{status_icon} {alert['name']}")
    
    builder.button(text="⬅️ Back")
    builder.adjust(1)
    
    await state.set_state(AlertManagement.ViewingList)
    await get_current_alerts_map(state, alerts) # Cache for lookup
    await message.answer("Select an alert to view details:", reply_markup=builder.as_markup(resize_keyboard=True))



@user_router.callback_query(F.data == "dash_cancel", StateFilter(AlertEditor))
async def dash_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("❌ Alert creation cancelled.", reply_markup=get_main_menu_kb())

@user_router.callback_query(F.data == "ignore")
async def dash_ignore(callback: CallbackQuery):
    await callback.answer()

@user_router.callback_query(F.data == "dash_save", StateFilter(AlertEditor))
async def dash_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    filters = data.get('filters', {})
    
    # Logic: New or Edit?
    editing_id = data.get('editing_alert_id')
    
    if editing_id:
        await update_alert(editing_id, callback.from_user.id, filters)
        msg_title = "✅ <b>Alert Updated!</b>"
        # Keep name same, mostly
    else:
        from datetime import datetime
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
    
    # Send matches
    matches = await get_latest_matching_ads(filters, limit=5)
    if matches:
        await callback.message.answer(f"🔎 Found {len(matches)} recent matches:")
        for ad in matches:
            text = format_ad_message(ad, 'new')
            if text: await callback.message.answer(text, parse_mode="HTML")
    else:
        await callback.message.answer("ℹ️ No recent matches found.")

@user_router.message(F.text == "❌ Cancel", StateFilter(AlertCreation))
async def cancel_wizard(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Alert creation cancelled.", reply_markup=get_main_menu_kb())

@user_router.message(AlertCreation.Category)
async def process_category(message: types.Message, state: FSMContext):
    if message.text != "Cars":
        await message.answer("Only 'Cars' category is currently supported.")
        return
    
    await state.update_data(category="Cars")
    await state.set_state(AlertCreation.Brand)
    await message.answer(
        "Step 2: Brand\n"
        "Type a brand name or select 'ANY'.",
        reply_markup=get_nav_kb(include_any=True)
    )

@user_router.message(AlertCreation.Brand)
async def process_brand(message: types.Message, state: FSMContext):
    text = message.text.strip()
    
    if text == "⬅️ Back":
        await state.set_state(AlertCreation.Category)
        await message.answer("Step 1: Select Category", reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Cars")], [KeyboardButton(text="❌ Cancel")]], resize_keyboard=True
        ))
        return

    if text == "💾 Save & Finish":
        # TODO: Implement early save
        await message.answer("Early save not yet fully implemented, but let's assume valid.")
        return

    # Validate Brand against DB
    brands = await get_distinct_values('car_brand')
    
    if text != "ANY":
        # Check exact (case insensitive)
        match = next((b for b in brands if b.lower() == text.lower()), None)
        
        if not match:
             # Fuzzy search for hints
             import difflib
             possibilities = difflib.get_close_matches(text, brands, n=3, cutoff=0.4)
             
             msg = f"❌ Brand '{text}' not found."
             if possibilities:
                 msg += f"\nDid you mean: {', '.join(possibilities)}?"
             else:
                 msg += "\nPlease type the full brand name (e.g. Mercedes-Benz) or select ANY."
                 
             await message.answer(msg)
             return
             
        text = match # Use correct casing from DB

    await state.update_data(brand=text if text != "ANY" else None)
    
    if text == "ANY":
        # Skip Model step if Brand is ANY (as per requirements filter is inactive)
        await state.update_data(model=None)
        await state.set_state(AlertCreation.YearFrom)
        # Fetch min year for hint
        min_y, _ = await get_min_max_values('car_year')
        await message.answer(
            f"Step 4: Year From (Min: {min_y})\nType year (YYYY) or ANY.",
            reply_markup=get_nav_kb(include_any=True)
        )
    else:
        await state.set_state(AlertCreation.Model)
        # Fetch models for this brand
        models = await get_distinct_values('car_model', 'car_brand', text)
        
        # We will create a simplified keyboard with some top models or just text input expectation
        # But for compliance, we should try to show buttons.
        chunked_models = models[:30] # Limit to 30 buttons to avoid overflow
        
        await message.answer(
            f"Step 3: Model for {text}\nSelect or type model.",
            reply_markup=get_nav_kb(options=chunked_models, include_any=True)
        )

@user_router.message(AlertCreation.Model)
async def process_model(message: types.Message, state: FSMContext):
    text = message.text.strip()
    data = await state.get_data()
    
    if text == "⬅️ Back":
        await state.set_state(AlertCreation.Brand)
        await message.answer("Step 2: Brand", reply_markup=get_nav_kb(include_any=True))
        return
        
    if text == "💾 Save & Finish":
        return await save_alert_early(message, state)

    # If user selected multiple models (comma sep), handle it
    # For now, just store as is or list
    models = [m.strip() for m in text.split(',')] if text != "ANY" else None
    
    await state.update_data(model=models)
    await state.set_state(AlertCreation.YearFrom)
    
    min_y, _ = await get_min_max_values('car_year')
    await message.answer(
        f"Step 4: Year From (Min: {min_y})\nenter the year YYYY.",
        reply_markup=get_nav_kb(include_any=True)
    )



@user_router.callback_query(F.data.startswith("edit_"), StateFilter(AlertEditor.Menu))
async def edit_field_start(callback: CallbackQuery, state: FSMContext):
    field = callback.data.replace("edit_", "")
    
    # Check if this is a text field or selection field
    text_fields = [
        "year_min", "year_max", "price_min", "price_max", 
        "mileage_max", "engine_min", "engine_max", "target_user_id"
    ]
    
    selection_fields = [
        "brand", "model", "gearbox", "fuel_type", 
        "drive_type", "body_type", "color", "ad_status", "is_business"
    ]

    if field in text_fields:
        await state.update_data(editing_field=field)
        await state.set_state(AlertEditor.InputText)
        
        # Determine prompt
        prompt = f"Enter value for <b>{field.replace('_', ' ').title()}</b>:"
        if "year" in field: prompt += "\n(Format: YYYY, e.g. 2020)"
        elif "price" in field: prompt += "\n(Format: Number, e.g. 15000)"
        elif "mileage" in field: prompt += "\n(Format: Number, e.g. 100000)"
        elif "engine" in field: prompt += "\n(Format: cc, e.g. 1500)"
        
        # Add Inline Keyboard for Input State (Any, Back)
        builder = InlineKeyboardBuilder()
        builder.button(text="Any (Clear)", callback_data=f"set_any:{field}")
        builder.button(text="🔙 Back", callback_data="dash_back")
        builder.adjust(1)
        
        await callback.message.edit_text(prompt + "\n\n<i>Type value or select option below:</i>", reply_markup=builder.as_markup(), parse_mode="HTML")
    
    elif field in selection_fields:
        # Pass to selection handler (impl next)
        await start_selection(callback, state, field)
        
    else:
        await callback.answer("Not implemented yet.")

@user_router.callback_query(F.data.startswith("set_any:"))
async def process_any_button(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[1]
    data = await state.get_data()
    filters = data.get('filters', {})
    filters[field] = None # Set to Any
    
    # Special logic: if resetting Year Min, clear Year Max?
    if field == "year_min": filters['year_max'] = None
    
    await state.update_data(filters=filters)
    # Return to dashboard
    kb = get_dashboard_kb(filters)
    await state.set_state(AlertEditor.Menu)
    await callback.message.edit_text("➕ <b>New Alert Wizard</b>", reply_markup=kb, parse_mode="HTML")

@user_router.message(AlertEditor.InputText)
async def process_dashboard_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data.get('editing_field')
    text = message.text.strip()
    
    # /cancel to return
    if text == "/cancel":
        # Should mostly handle by button, but keep for robustness (or remove?)
        # Let's keep /cancel as alias to Back
        await return_to_dashboard(message, state)
        return

    # Validation
    val = None
    if not text.isdigit():
        await message.answer("❌ Invalid format. Please enter a number.\nTry again or /cancel.")
        return
    
    val = int(text)
    
    # Specific Checks
    if "year" in field and (val < 1900 or val > 2030):
        await message.answer("❌ Year must be between 1900 and 2030.")
        return
        
    # Validation passed
    filters = data.get('filters', {})
    filters[field] = val
    await state.update_data(filters=filters)
    
    await return_to_dashboard(message, state)

async def return_to_dashboard(message: types.Message, state: FSMContext):
    data = await state.get_data()
    filters = data.get('filters', {})
    kb = get_dashboard_kb(filters)
    
    await state.set_state(AlertEditor.Menu)
    await message.answer("➕ <b>New Alert Wizard</b>", reply_markup=kb, parse_mode="HTML")


@user_router.message(AlertCreation.YearTo)
async def process_year_to(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if text == "⬅️ Back":
        await state.set_state(AlertCreation.YearFrom)
        min_y, _ = await get_min_max_values('car_year')
        await message.answer(f"Step 4: Year From", reply_markup=get_nav_kb(include_any=True))
        return
    if text == "💾 Save & Finish": return await save_alert_early(message, state)

    if not text.isdigit(): # If strict
        await message.answer("Please enter a valid year.")
        return
        
    await state.update_data(year_to=int(text))
    await state.set_state(AlertCreation.PriceMax)
    
    _, max_p = await get_min_max_values('current_price')
    await message.answer(f"Step 6: Max Price (Max stored: {max_p}€)", reply_markup=get_nav_kb(include_any=True))


# --- Selector Handlers ---
async def start_selection(callback: CallbackQuery, state: FSMContext, field: str, page: int = 0):
    await state.set_state(AlertEditor.SelectOption)
    
    # Get Options
    options = []
    if field == "brand":
        options = await get_distinct_values('car_brand')
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
    
    # Validation for empty options
    if not options and field != "is_business": # business fixed list
        await callback.answer("No options available.")
        return

    # Filter None/Empty
    options = [str(o) for o in options if o]
    options.sort()
    
    if field != "is_business" and field != "ad_status": 
         options.insert(0, "Any")

    # Pagination
    ITEMS_PER_PAGE = 30
    total_pages = (len(options) - 1) // ITEMS_PER_PAGE + 1
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    chunk = options[start:end]
    
    builder = InlineKeyboardBuilder()
    for opt in chunk:
        # Use simple hashing or truncation if value too long? 
        # Callback data max 64 bytes. "sel:brand:Mercedes-Benz" is fine.
        # But "sel:body_type:Convertible (Open Top)" might be long.
        # Let's hope it fits.
        val_safe = opt[:40] 
        builder.button(text=opt, callback_data=f"sel:{field}:{val_safe}")
    
    builder.adjust(2)
    
    # Nav Buttons
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"pg:{field}:{page-1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"pg:{field}:{page+1}"))
    
    if nav_row: builder.row(*nav_row)
    builder.row(InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="dash_back"))
    
    heading = f"Select <b>{field.replace('_', ' ').title()}</b> (Page {page+1}/{total_pages}):"
    await callback.message.edit_text(heading, reply_markup=builder.as_markup(), parse_mode="HTML")

@user_router.callback_query(F.data.startswith("pg:"))
async def process_pagination(callback: CallbackQuery, state: FSMContext):
    _, field, page_str = callback.data.split(":")
    await start_selection(callback, state, field, int(page_str))

@user_router.callback_query(F.data.startswith("sel:"))
async def process_selection(callback: CallbackQuery, state: FSMContext):
    _, field, value = callback.data.split(":", 2) # split only twice
    
    data = await state.get_data()
    filters = data.get('filters', {})
    
    # Handle Special Logic
    if value == "Any": 
        filters[field] = None
    elif field == "is_business":
        if value == "Business": filters[field] = True
        elif value == "Private": filters[field] = False
        else: filters[field] = None
    else:
        filters[field] = value
        
    # Reset dependent fields
    if field == "brand":
        filters['model'] = None # Reset model on brand change
        
    await state.update_data(filters=filters)
    
    # Return to Menu
    kb = get_dashboard_kb(filters)
    await state.set_state(AlertEditor.Menu)
    await callback.message.edit_text("➕ <b>New Alert Wizard</b>", reply_markup=kb, parse_mode="HTML")

@user_router.callback_query(F.data == "dash_back")
async def back_to_dashboard_cb(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    filters = data.get('filters', {})
    kb = get_dashboard_kb(filters)
    await state.set_state(AlertEditor.Menu)
    # Use callback.message here!
    await callback.message.edit_text("➕ <b>New Alert Wizard</b>", reply_markup=kb, parse_mode="HTML")

# Clean up old unused handlers (optional, but good practice to avoid file bloat)
# Truncating old wizard code...



async def save_alert_early(message: types.Message, state: FSMContext):
    data = await state.get_data()
    # Fill defaults for remaining
    # Use generic name
    from datetime import datetime
    name = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # Extract known data, others are None by default in get()
    filters = {
        'brand': data.get('brand'),
        'model': data.get('model'),
        'year_min': data.get('year_from'),
        'year_max': data.get('year_to'),
        'price_min': data.get('price_min'),
        'price_max': data.get('price_max'),
        'mileage_min': data.get('mileage_min'),
        'mileage_max': data.get('mileage_max'),
        'gearbox': data.get('gearbox'),
        'fuel_type': data.get('fuel'),
        'engine_min': data.get('engine_from'),
        'engine_max': data.get('engine_to'),
        'drive_type': data.get('drive'),
        'body_type': data.get('body'),
        'color': data.get('color'),
        'is_business': data.get('is_business'),
        'ad_status': data.get('ad_status'),
        'target_user_id': data.get('target_user_id')
    }
    
    await create_alert(message.from_user.id, name, filters)
    await state.clear()
    await message.answer(f"💾 Alert '{name}' saved!", reply_markup=get_main_menu_kb())

