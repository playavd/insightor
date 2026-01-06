import asyncio
import logging
import sys
import csv
import json
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher, types, F, BaseMiddleware, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, USER_BOT_TOKEN, ADMIN_ID, CHANNEL_ID, LOG_DIR
from database import (
    init_db, AdData, get_statistics, get_all_ads, 
    get_active_alerts, is_match, format_ad_message
)
from scraper import BazarakiScraper
from user_handlers import user_router

# Logging Setup
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            LOG_DIR / "insightor.log",
            maxBytes=100*1024, # ~100KB
            backupCount=1
        )
    ]
)

# Bot Setup
admin_bot = Bot(token=BOT_TOKEN)
user_bot = Bot(token=USER_BOT_TOKEN) if USER_BOT_TOKEN else None

# Dispatchers
dp_admin = Dispatcher()
dp_user = Dispatcher()

scheduler = AsyncIOScheduler()
scraper = BazarakiScraper()

# Middleware for Access Control (Admin Only)
class AdminMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get('event_from_user')
        if not user:
             return await handler(event, data)
        if user.id != ADMIN_ID:
             return
        return await handler(event, data)

dp_admin.message.middleware(AdminMiddleware())

# --- Matching Logic ---
# (Keep is_match and notify_user as is, they are independent functions usually)
# However, notify_user uses 'admin_bot' and 'user_bot' global vars which is fine.


async def notify_user(notification_type: str, ad_data: dict):
    """Send notification to Telegram (Admin & Users)."""
    try:
        msg_text = format_ad_message(ad_data, notification_type)
        if not msg_text: return

        # Verify bot sessions before sending? Usually fine if token is valid.
        
        # 2. Notify Admin
        target_id = CHANNEL_ID if CHANNEL_ID else ADMIN_ID
        if target_id:
             try:
                 await admin_bot.send_message(target_id, msg_text, parse_mode="HTML")
             except Exception as e:
                 logger.error(f"Failed to notify admin: {e}")
        
        # 3. Notify Users
        if user_bot and notification_type in ['new', 'repost']:
            alerts = await get_active_alerts()
            for alert in alerts:
                filters = json.loads(alert['filters'])
                if is_match(ad_data, filters):
                    try:
                        await user_bot.send_message(alert['user_id'], msg_text, parse_mode="HTML")
                    except Exception as u_e:
                        logger.warning(f"Failed to notify user {alert['user_id']}: {u_e}")

    except Exception as e:
        logger.error(f"Failed to send notification: {e}")

async def scraper_job():
    if scraper.is_running:
        logger.warning("Scraper cycle already running. Skipping.")
        return

    logger.info("Scheduler Trigger: Starting scraper cycle.")
    
    # Notify Start
    try:
         target_id = CHANNEL_ID if CHANNEL_ID else ADMIN_ID
         if target_id:
             await admin_bot.send_message(target_id, "🏁 <b>Scraper cycle started...</b>", parse_mode="HTML")
    except Exception: pass

    # Run Cycle
    new_ads_count = await scraper.run_cycle(notify_callback=notify_user)
    
    next_run = datetime.now() + timedelta(minutes=6)
    next_run_str = next_run.strftime('%H:%M:%S')
    logger.info(f"Cycle finished. Next run approx: {next_run_str}")
    
    # Notify Finish
    try:
        if target_id:
            text = (
                f"🏁 <b>Cycle Finished</b>\n"
                f"✅ New Ads: {new_ads_count}\n"
                f"⏰ Next Run: {next_run_str} (approx)"
            )
            await admin_bot.send_message(target_id, text, parse_mode="HTML")
    except Exception: pass

# --- Admin Handlers (Attached to dp_admin directly) ---
admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="▶️ Start Scraper"), KeyboardButton(text="⏸ Pause Scraper")],
        [KeyboardButton(text="📊 Statistics"), KeyboardButton(text="📜 View Logs")],
        [KeyboardButton(text="📥 Download Data")]
    ],
    resize_keyboard=True
)

@dp_admin.message(Command("start"))
@dp_admin.message(F.text == "▶️ Start Scraper")
async def cmd_start_admin(message: types.Message):
    scraper.stop_signal = False
    if not scheduler.get_job('scraper_job'):
        scheduler.add_job(scraper_job, 'interval', minutes=6, id='scraper_job')
    if not scheduler.running: scheduler.start()
    if not scraper.is_running: asyncio.create_task(scraper_job()) 
    await message.answer("✅ Bot started.", reply_markup=admin_keyboard)

@dp_admin.message(Command("stop"))
@dp_admin.message(F.text == "⏸ Pause Scraper")
async def cmd_stop_admin(message: types.Message):
    scraper.stop_signal = True
    if scheduler.get_job('scraper_job'): scheduler.remove_job('scraper_job')
    await message.answer("🛑 Bot stopped.", reply_markup=admin_keyboard)

@dp_admin.message(Command("logs"))
@dp_admin.message(F.text == "📜 View Logs")
async def cmd_logs(message: types.Message):
    log_file = LOG_DIR / "insightor.log"
    if log_file.exists():
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
                last_5 = "".join(lines[-5:])
                await message.answer(f"Last 5 log lines:\n<pre>{last_5}</pre>", parse_mode="HTML")
            await message.answer_document(FSInputFile(log_file))
        except Exception as e:
            await message.answer(f"Error reading logs: {e}")
    else:
        await message.answer("No logs found.")

@dp_admin.message(Command("database"))
@dp_admin.message(F.text == "📥 Download Data")
async def cmd_database(message: types.Message):
    try:
        data = await get_all_ads()
        if data:
            csv_path = LOG_DIR / "ads_export.csv"
            keys = data[0].keys()
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(data)
            await message.answer_document(FSInputFile(csv_path))
        else:
            await message.answer("Database is empty.")
    except Exception as e:
        logger.error(f"Export error: {e}", exc_info=True)
        await message.answer(f"Error exporting database: {e}")

@dp_admin.message(F.text == "📊 Statistics")
async def btn_stats(message: types.Message):
    try:
        stats = await get_statistics()
        text = (
            f"📊 <b>Statistics</b>\n"
            f"Total Ads: {stats['total_ads']}\n"
            f"New in 24h: {stats['new_today']}"
        )
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"Error fetching stats: {e}")


async def on_startup():
    if not scheduler.running:
        scheduler.start()

async def main():
    await init_db()
    
    # Configure User Bot Dispatcher
    dp_user.include_router(user_router)
    
    tasks = []
    
    # Admin Bot Polling
    dp_admin.startup.register(on_startup)
    tasks.append(dp_admin.start_polling(admin_bot))
    
    # User Bot Polling
    if user_bot:
        logger.info("User Bot polling starting...")
        tasks.append(dp_user.start_polling(user_bot))
    else:
        logger.warning("USER_BOT_TOKEN not found.")
        
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
