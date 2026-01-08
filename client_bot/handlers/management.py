import logging
import json
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from shared.database import (
    get_user_alerts, get_alert, toggle_alert, delete_alert, rename_alert, get_latest_matching_ads,
    follow_ad, get_ad, get_ad_history
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
        # Fetch counts (fav might be > 0 even if alerts is 0)
        from shared.database import get_user_alerts_count, get_user_followed_ads_count
        alerts_cnt = await get_user_alerts_count(user_id)
        fav_cnt = await get_user_followed_ads_count(user_id)
        
        await message.answer("You have no alerts.", reply_markup=get_main_menu_kb(alerts_cnt, fav_cnt))
        return

    builder = ReplyKeyboardBuilder()
    
    # New Alert at Top
    builder.button(text="🔔 New Alert")
    
    for alert in alerts:
        status_icon = "🟢" if alert['is_active'] else "🔴"
        builder.button(text=f"{status_icon} {alert['name']}")
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
        
        # Fetch counts for proper menu
        from shared.database import get_user_alerts_count, get_user_followed_ads_count
        user_id = message.from_user.id
        alerts_cnt = await get_user_alerts_count(user_id)
        fav_cnt = await get_user_followed_ads_count(user_id)
        
        await message.answer("Main Menu", reply_markup=get_main_menu_kb(alerts_cnt, fav_cnt))
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
        
        # Fetch counts for proper menu
        from shared.database import get_user_alerts_count, get_user_followed_ads_count
        alerts_cnt = await get_user_alerts_count(user_id)
        fav_cnt = await get_user_followed_ads_count(user_id)
        
        await message.answer("🏠 Main Menu", reply_markup=get_main_menu_kb(alerts_cnt, fav_cnt))
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
                         # Prepend Alert Name
                         final_t = f"🔔 <b>{alert['name']}</b>\n\n{t}"
                         
                         # Add standard buttons
                         buttons = [
                            [
                                InlineKeyboardButton(text="Follow", callback_data=f"toggle_follow:{ad['ad_id']}"),
                                InlineKeyboardButton(text="Details", callback_data=f"more_details:{ad['ad_id']}"),
                                InlineKeyboardButton(text="Deactivate", callback_data=f"toggle_alert:{alert_id}:off")
                            ]
                         ]
                         kb = InlineKeyboardMarkup(inline_keyboard=buttons)
                         
                         await message.answer(final_t, parse_mode="HTML", reply_markup=kb)
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
        btn_text = "Deactivate" if is_active else "Activate"
        
        # Reconstruct keyboard to preserve other buttons (Follow, Details)
        current_markup = callback.message.reply_markup
        new_rows = []
        if current_markup and current_markup.inline_keyboard:
            for row in current_markup.inline_keyboard:
                new_row = []
                for btn in row:
                    if btn.callback_data == callback.data:
                         # This is the button we clicked
                         new_row.append(InlineKeyboardButton(text=btn_text, callback_data=f"toggle_alert:{alert_id}:{new_action}"))
                    else:
                         new_row.append(btn)
                new_rows.append(new_row)
        else:
            new_rows = [[InlineKeyboardButton(text=btn_text, callback_data=f"toggle_alert:{alert_id}:{new_action}")]]
        
        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_rows))
        
        status_text = "activated" if is_active else "deactivated"
        await callback.answer(f"Alert {status_text}.")
        

        
    except Exception as e:
        logger.error(f"Callback toggle error: {e}")
        await callback.answer("Error updating alert.", show_alert=True)

@router.callback_query(F.data.startswith("toggle_follow:"))
async def process_toggle_follow_callback(callback: CallbackQuery):
    try:
        _, ad_id = callback.data.split(":")
        user_id = callback.from_user.id
        
        # Toggle follow status
        is_following = await follow_ad(user_id, ad_id)
        
        # Update button text
        # We need to reconstruct the keyboard. 
        # Since we don't know the exact previous keyboard state (it might have "Deactivate Alert" or not),
        # we can inspect the current markup
        current_markup = callback.message.reply_markup
        new_rows = []
        if current_markup and current_markup.inline_keyboard:
            for row in current_markup.inline_keyboard:
                new_row = []
                for btn in row:
                    if btn.callback_data == callback.data:
                         # This is the button we clicked
                         new_text = "Unfollow" if is_following else "Follow"
                         new_row.append(InlineKeyboardButton(text=new_text, callback_data=callback.data))
                    else:
                         new_row.append(btn)
                new_rows.append(new_row)
        else:
            # Fallback if no markup found? Should not happen.
            new_text = "Unfollow" if is_following else "Follow"
            new_rows = [[InlineKeyboardButton(text=new_text, callback_data=callback.data)]]

        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_rows))
        
        status_text = "followed" if is_following else "unfollowed"
        await callback.answer(f"Ad {status_text}.")
        
    except Exception as e:
        logger.error(f"Callback follow error: {e}")
        await callback.answer("Error updating follow status.", show_alert=True)

@router.callback_query(F.data.startswith("more_details:"))
async def process_more_details(callback: CallbackQuery):
    try:
        _, ad_id = callback.data.split(":")
        
        ad = await get_ad(ad_id)
        if not ad:
            await callback.answer("Ad not found.", show_alert=True)
            return

        history = await get_ad_history(ad_id, limit=5)
        
        text = format_ad_message(ad, 'detailed', history)
        
        try:
            # Try to edit the existing message
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=callback.message.reply_markup)
        except Exception:
            # Fallback: send as new message if edit fails (e.g. too old)
            await callback.message.answer(text, parse_mode="HTML")
            
        await callback.answer()
        
    except Exception as e:
        logger.error(f"More details error: {e}")
        await callback.answer("Error fetching details.", show_alert=True)
