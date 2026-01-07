import logging
import json
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from shared.database import (
    get_user_alerts, get_alert, toggle_alert, delete_alert, rename_alert, get_latest_matching_ads
)
from shared.utils import format_ad_message
from client_bot.states import AlertManagement, AlertEditor
from client_bot.keyboards import get_main_menu_kb, get_dashboard_kb

logger = logging.getLogger(__name__)
router = Router()

async def get_current_alerts_map(state: FSMContext, alerts: list):
    mapping = {}
    for alert in alerts:
        status_icon = "🟢" if alert['is_active'] else "🔴"
        key = f"{status_icon} {alert['name']}"
        mapping[key] = alert
    await state.update_data(alerts_map=mapping)

@router.message(F.text == "🗂️ My Alerts", StateFilter("*"))
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

@router.message(AlertManagement.ViewingList)
async def process_alert_selection(message: types.Message, state: FSMContext):
    text = message.text
    if text == "⬅️ Back":
        await state.clear()
        await message.answer("Main Menu", reply_markup=get_main_menu_kb())
        return
    
    if text == "🔔 New Alert":
        # Redirect to wizard entry
        # Ideally we should just clear state and call the handler, but we can't easily call handler function across modules
        # unless we imported it.
        # Cleanest: Just tell user to click New Alert again or simulate it?
        # Better: Import start_new_alert from wizard. But wizard imports us? Circular?
        # Wizard doesn't import management. So we CAN import wizard.
        from client_bot.handlers.wizard import start_new_alert
        await start_new_alert(message, state)
        return

    data = await state.get_data()
    mapping = data.get('alerts_map', {})
    alert = mapping.get(text)
    
    if not alert:
        await message.answer("Alert not found. Please select from the list.")
        return
    
    filters = json.loads(alert['filters'])
    
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

@router.message(AlertManagement.ViewingDetail)
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
                     if t:
                         # Prepend Alert Name (NO buttons)
                         final_t = f"🔔 <b>{alert['name']}</b>\n\n{t}"
                         await message.answer(final_t, parse_mode="HTML")
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
             # We need to tell the state which alert we are editing
             await state.update_data(filters=filters, editing_alert_id=alert_id)
             kb = get_dashboard_kb(filters)
             await message.answer("🛠 <b>Editing Alert</b>", reply_markup=kb, parse_mode="HTML")
        return

    if text == "✏️ Rename":
        await state.set_state(AlertEditor.Rename)
        await message.answer("Enter new name for the alert (max 25 chars):")
        return

    await message.answer("Unknown action.")

@router.message(AlertEditor.Rename)
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

from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

@router.callback_query(F.data.startswith("toggle_alert:"))
async def process_toggle_alert_callback(callback: CallbackQuery):
    try:
        _, alert_id_str, action = callback.data.split(":")
        alert_id = int(alert_id_str)
        user_id = callback.from_user.id
        
        is_active = (action == "on")
        
        # Toggle within database
        await toggle_alert(alert_id, user_id, is_active)
        
        # We need to update the message markup to flip the button
        new_action = "off" if is_active else "on"
        btn_text = "🔕 Deactivate Alert" if is_active else "🔔 Activate Alert"
        
        new_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=btn_text, callback_data=f"toggle_alert:{alert_id}:{new_action}")]
        ])
        
        await callback.message.edit_reply_markup(reply_markup=new_kb)
        
        status_text = "activated" if is_active else "deactivated"
        await callback.answer(f"Alert {status_text}.")
        
    except Exception as e:
        logger.error(f"Callback toggle error: {e}")
        await callback.answer("Error updating alert.", show_alert=True)
