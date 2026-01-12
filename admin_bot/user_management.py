import logging
import asyncio
import json
from datetime import datetime
from aiogram import Router, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter

from shared.database import (
    get_all_users_paginated, 
    get_total_users_count, 
    search_users, 
    get_user_stats,
    get_user,
    get_user_alerts,
    get_user_followed_ads_paginated,
    get_user_activities,
    delete_alert,
    delete_all_user_data,
    toggle_alert,
    get_alert,
    get_ad_history
)
from admin_bot.states import AdminStates
from admin_bot.handlers import admin_keyboard  # To return to main menu

user_management_router = Router()
logger = logging.getLogger(__name__)

# --- USERS LIST ---

@user_management_router.message(F.text == "👥 Users")
async def cmd_users_list(message: types.Message):
    await show_users_list(message, page=0)

async def show_users_list(message: types.Message, page: int):
    limit = 10
    offset = page * limit
    users = await get_all_users_paginated(limit, offset)
    total_users = await get_total_users_count()
    
    if not users and page > 0:
        await message.answer("No more users.")
        return

    text = f"👥 <b>Users List</b> (Total: {total_users})\nPage {page + 1}\n\n"
    
    kb_rows = []
    
    # "Search User" button at the top
    kb_rows.append([InlineKeyboardButton(text="🔎 Search User", callback_data="admin_search_user")])

    for u in users:
        # User row button
        status = "🔒" if False else "" # We don't track block status yet
        username = f"@{u['username']}" if u['username'] else f"ID: {u['user_id']}"
        display_name = f"{u['first_name']} {username} {status}"
        kb_rows.append([InlineKeyboardButton(text=display_name, callback_data=f"admin_user:{u['user_id']}")])

    # Pagination
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"admin_users_page:{page-1}"))
    if (offset + limit) < total_users:
        nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"admin_users_page:{page+1}"))
    if nav_buttons:
        kb_rows.append(nav_buttons)

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    
    if isinstance(message, types.CallbackQuery):
        await message.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

@user_management_router.callback_query(F.data.startswith("admin_users_page:"))
async def cb_users_page(callback: types.CallbackQuery):
    page = int(callback.data.split(":")[1])
    await show_users_list(callback, page)
    await callback.answer()

# --- SEARCH USER ---

@user_management_router.callback_query(F.data == "admin_search_user")
async def cb_search_user(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🔎 Send me the <b>User ID</b> or <b>@Username</b>:", parse_mode="HTML")
    await state.set_state(AdminStates.waiting_for_user_search)
    await callback.answer()

@user_management_router.message(StateFilter(AdminStates.waiting_for_user_search))
async def process_search_user(message: types.Message, state: FSMContext):
    query = message.text.strip().replace("@", "")
    results = await search_users(query)
    
    if not results:
        await message.answer("❌ No user found. Try again or use menu.", reply_markup=admin_keyboard)
        await state.clear()
        return

    if len(results) == 1:
        # Direct open
        await show_user_profile(message, results[0]['user_id'])
        await state.clear()
    else:
        # Show list
        text = "🔎 <b>Found Users:</b>\n"
        kb_rows = []
        for u in results:
            username = f"@{u['username']}" if u['username'] else f"ID: {u['user_id']}"
            kb_rows.append([InlineKeyboardButton(text=f"{u['first_name']} {username}", callback_data=f"admin_user:{u['user_id']}")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
        await state.clear()

# --- USER PROFILE ---

@user_management_router.callback_query(F.data.startswith("admin_user:"))
async def cb_user_profile(callback: types.CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    await show_user_profile(callback.message, user_id, is_edit=True)
    await callback.answer()

async def show_user_profile(message: types.Message, user_id: int, is_edit: bool = False):
    user = await get_user(user_id)
    if not user:
        await message.answer("User not found.")
        return

    stats = await get_user_stats(user_id)
    
    username = f"@{user['username']}" if user['username'] else "No Username"
    joined_date = user['joined_date'].split()[0] if user['joined_date'] else "Unknown"
    
    text = (
        f"👤 <b>User Profile</b>\n"
        f"ID: <code>{user_id}</code>\n"
        f"Name: {user['first_name']}\n"
        f"Username: {username}\n"
        f"Joined: {joined_date}\n\n"
        f"🔔 Alerts: {stats['alerts_active']} active ({stats['alerts_inactive']} inactive)\n"
        f"⭐ Favorites: {stats['favorites']}\n"
        f"📅 Last Active: {stats['last_active'] or 'Never'}\n"
        f"🔄 Total Activities: {stats['total_activities']}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔔 Alerts", callback_data=f"admin_u_alerts:{user_id}"),
            InlineKeyboardButton(text="⭐ Favorites", callback_data=f"admin_u_favs:{user_id}")
        ],
        [
            InlineKeyboardButton(text="🗑 Clear Data", callback_data=f"admin_u_clear_ask:{user_id}"),
            InlineKeyboardButton(text="📜 Activities", callback_data=f"admin_u_logs:{user_id}")
        ],
        [InlineKeyboardButton(text="⬅️ Back to List", callback_data="admin_users_page:0")]
    ])

    if is_edit:
        await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

# --- ALERTS MANAGEMENT ---

@user_management_router.callback_query(F.data.startswith("admin_u_alerts:"))
async def cb_user_alerts(callback: types.CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    alerts = await get_user_alerts(user_id)
    
    text = f"🔔 <b>User Alerts ({len(alerts)})</b>"
    kb_rows = []
    
    for alert in alerts:
        status = "✅" if alert['is_active'] else "zzz"
        btn_text = f"{status} {alert['name']}"
        kb_rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"admin_alert_view:{alert['alert_id']}:{user_id}")])
    
    kb_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"admin_user:{user_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@user_management_router.callback_query(F.data.startswith("admin_alert_view:"))
async def cb_admin_alert_view(callback: types.CallbackQuery):
    _, alert_id, user_id = callback.data.split(":")
    
    alert = await get_alert(int(alert_id))
    if not alert:
        await callback.answer("Alert not found.")
        return

    # Parse filters
    try:
        filters = json.loads(alert['filters'])
    except:
        filters = {}

    # Format filters for display
    filter_lines = []
    if filters.get('brand'): filter_lines.append(f"🚗 Brand: {filters['brand']}")
    if filters.get('model'): 
        models = filters['model']
        if isinstance(models, list): models = ", ".join(models)
        filter_lines.append(f"🚙 Model: {models}")
    
    # Year
    y_min = filters.get('year_min')
    y_max = filters.get('year_max')
    if y_min or y_max:
        r = f"{y_min or 'Any'} - {y_max or 'Any'}"
        filter_lines.append(f"📅 Year: {r}")

    # Price
    p_min = filters.get('price_min')
    p_max = filters.get('price_max')
    if p_min or p_max:
        r = f"€{p_min or 0} - €{p_max or 'Any'}"
        filter_lines.append(f"💰 Price: {r}")
        
    # Other common filters
    if filters.get('fuel_type'): filter_lines.append(f"⛽ Fuel: {filters['fuel_type']}")
    if filters.get('gearbox'): filter_lines.append(f"⚙️ Gear: {filters['gearbox']}")
    
    filter_text = "\n".join(filter_lines) if filter_lines else "No specific filters."
    
    import html
    safe_name = html.escape(alert['name'])
    status_icon = "✅" if alert['is_active'] else "zzz"
    text = (
        f"🔔 <b>Alert Details</b>\n"
        f"Name: {safe_name}\n"
        f"Status: {status_icon} {'Active' if alert['is_active'] else 'Inactive'}\n"
        f"Created: {alert['created_at']}\n\n"
        f"<b>Filters:</b>\n{filter_text}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Delete Alert", callback_data=f"admin_alert_del:{alert_id}:{user_id}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data=f"admin_u_alerts:{user_id}")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@user_management_router.callback_query(F.data.startswith("admin_alert_del:"))
async def cb_admin_alert_delete(callback: types.CallbackQuery):
    _, alert_id, user_id = callback.data.split(":")
    await delete_alert(int(alert_id), int(user_id))
    await callback.answer("Alert deleted.")
    # Refresh alerts list
    await cb_user_alerts(callback) # This expects callback.data formatted for it, but we can call logic directly...
    # Re-call cb_user_alerts requires correct data in callback. It's user_id.
    # Hacky but works: update data and call
    callback.data = f"admin_u_alerts:{user_id}"
    await cb_user_alerts(callback)

# --- FAVORITES MANAGEMENT ---

@user_management_router.callback_query(F.data.startswith("admin_u_favs:"))
async def cb_user_favs(callback: types.CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    # Show first 5 favorites for now or simple list
    favs = await get_user_followed_ads_paginated(user_id, limit=50) # Just get up to 50
    
    text = f"⭐ <b>User Favorites ({len(favs)})</b>"
    kb_rows = []
    
    for ad in favs:
        btn_text = f"{ad['car_brand']} {ad['car_model']} (#{ad['ad_id']})"
        kb_rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"admin_fav_view:{ad['ad_id']}:{user_id}")])
        
    kb_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data=f"admin_user:{user_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@user_management_router.callback_query(F.data.startswith("admin_fav_view:"))
async def cb_admin_fav_view(callback: types.CallbackQuery):
    _, ad_id, user_id = callback.data.split(":")
    
    from shared.utils import format_ad_message
    from shared.database import get_ad
    
    ad = await get_ad(ad_id)
    history = await get_ad_history(ad_id)
    
    if ad:
        # notification_type="detailed" fixes the empty message bug
        text = format_ad_message(ad, notification_type="detailed", history=history)
    else:
        text = "Ad details not found."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
             InlineKeyboardButton(text="🔗 Open Link", url=ad['ad_url']) if ad else None
        ],
        [InlineKeyboardButton(text="🗑 Remove Favorite", callback_data=f"admin_fav_del:{ad_id}:{user_id}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data=f"admin_u_favs:{user_id}")]
    ])
    
    # Filter out None buttons
    kb.inline_keyboard = [row for row in kb.inline_keyboard if any(row)]
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@user_management_router.callback_query(F.data.startswith("admin_fav_del:"))
async def cb_admin_fav_del(callback: types.CallbackQuery):
    _, ad_id, user_id = callback.data.split(":")
    from shared.database import follow_ad, is_ad_followed_by_user
    
    # Check if followed
    if await is_ad_followed_by_user(int(user_id), ad_id):
        await follow_ad(int(user_id), ad_id) # Untoggles
        await callback.answer("Removed from favorites.")
    else:
        await callback.answer("Already removed.")
        
    callback.data = f"admin_u_favs:{user_id}"
    await cb_user_favs(callback)

# --- CLEAR DATA ---

@user_management_router.callback_query(F.data.startswith("admin_u_clear_ask:"))
async def cb_clear_ask(callback: types.CallbackQuery):
    user_id = callback.data.split(":")[1]
    text = "⚠️ <b>Are you sure?</b>\nThis will delete ALL alerts and favorites for this user."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Yes, Delete All", callback_data=f"admin_u_clear_confirm:{user_id}")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data=f"admin_user:{user_id}")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@user_management_router.callback_query(F.data.startswith("admin_u_clear_confirm:"))
async def cb_clear_confirm(callback: types.CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    await delete_all_user_data(user_id)
    await callback.answer("All user data cleared.")
    await show_user_profile(callback.message, user_id, is_edit=True)

# --- ACTIVITIES ---

@user_management_router.callback_query(F.data.startswith("admin_u_logs:"))
async def cb_user_logs(callback: types.CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    logs = await get_user_activities(user_id, limit=50)
    
    log_text = ""
    for log in logs:
        ts = log['timestamp'].split('.')[0] # Rm ms
        log_text += f"[{ts}] {log['action'][:30]}\n"
    
    if not log_text:
        log_text = "No activities found."
        
    text = f"📜 <b>Recent Activities</b>\n<pre>{log_text}</pre>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back", callback_data=f"admin_user:{user_id}")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()
