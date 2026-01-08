import logging
from aiogram import Router, types, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext

from client_bot.keyboards import get_main_menu_kb
from client_bot.states import AlertCreation
from shared.database import add_or_update_user

logger = logging.getLogger(__name__)
router = Router()

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    await add_or_update_user(user.id, user.username, user.first_name)
    
    from shared.database import get_user_alerts_count, get_user_followed_ads_count

    alerts_cnt = await get_user_alerts_count(user.id)
    fav_cnt = await get_user_followed_ads_count(user.id)
    
    await message.answer(
        f"👋 Hello, {user.first_name}!\n"
        "Select an option to get started.",
        reply_markup=get_main_menu_kb(alerts_cnt, fav_cnt)
    )

@router.message(F.text == "❌ Cancel", StateFilter(AlertCreation))
async def cancel_wizard(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Alert creation cancelled.", reply_markup=get_main_menu_kb())
