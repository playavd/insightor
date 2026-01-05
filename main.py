import asyncio
import logging
import sys
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import FSInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import BOT_TOKEN, ADMIN_ID, CHANNEL_ID, LOG_DIR
from database import init_db
from scraper import BazarakiScraper
import pandas as pd
from database import DATABASE_PATH
import aiosqlite

from logging.handlers import RotatingFileHandler

# Logging Setup
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            LOG_DIR / "insightor.log",
            maxBytes=100*1024, # ~100KB (approx 500 lines)
            backupCount=1
        )
    ]
)

# Bot Setup
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()
scraper = BazarakiScraper()

# Middleware for Access Control
class AdminMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # We only care about ensuring the user is the Admin
        user = data.get('event_from_user')
        if not user:
            return await handler(event, data)
            
        if user.id != ADMIN_ID:
            # If event is a message, we can reply
            if isinstance(event, types.Message):
                await event.answer("⛔ Access Denied. You are not authorized to use this bot.")
            return # Stop processing
            
        return await handler(event, data)

dp.message.middleware(AdminMiddleware())

STOP_PARSING = False

async def notify_user(notification_type: str, ad_data: dict):
    """Send notification to Telegram."""
    try:
        if notification_type == 'new':
            # Format details
            brand = ad_data.get('car_brand', 'Unknown')
            model = ad_data.get('car_model', '')
            year = ad_data.get('car_year', '')
            title = f"{brand} {model} {year}".strip()
            
            mileage = ad_data.get('mileage', 0)
            if mileage: 
                mileage = f"{mileage:,} km"
            else:
                mileage = "N/A"
                
            fuel = ad_data.get('fuel_type', 'N/A')
            gear = ad_data.get('gearbox', 'N/A')
            engine = ad_data.get('engine_size', 'N/A')
            seller = ad_data.get('user_name', 'Unknown')
            status = ad_data.get('ad_status', 'Basic')
            
            # Add emoji for status
            status_prefix = "🚗"
            if status == 'VIP': status_prefix = "🌟 VIP"
            elif status == 'TOP': status_prefix = "🔥 TOP"
            
            # Format: PREFIX Title (link)
            # 💰 Price  📏 Mileage
            # ⛽ Fuel  ⚙️ Gear  🔧 Engine
            # 👤 Seller (ID #123)
            
            seller_id = ad_data.get('user_id', '')
            seller_info = seller
            if seller_id:
                # Clickable hashtag format: #id_12345
                seller_info += f" (#id_{seller_id})"

            text = (
                f"{status_prefix} <a href=\"{ad_data['ad_url']}\">{title}</a>\n"
                f"💰 <b>{ad_data['current_price']} €</b>  📏 {mileage}\n"
                f"⛽ {fuel}  ⚙️ {gear}  🔧 {engine}\n"
                f"👤 {seller_info}"
            )
        elif notification_type == 'repost':
            # REPOST Notification
            text = (
                f"🔄 <b>Ad Reposted!</b>\n"
                f"The ad was bumped to the top.\n"
                f"🔗 <a href=\"{ad_data['ad_url']}\">{ad_data['car_brand']} {ad_data['car_model']}</a>"
            )
        elif notification_type == 'status':
            # STATUS Change Notification
            old_status = ad_data.get('old_status', 'Unknown')
            new_status = ad_data.get('ad_status', 'Unknown')
            text = (
                f"🚀 <b>Status Changed</b>\n"
                f"{old_status} ➡️ <b>{new_status}</b>\n"
                f"🔗 <a href=\"{ad_data['ad_url']}\">View Ad</a>"
            )
        elif notification_type == 'price':
             # Disabled as per request
             return

        target_id = CHANNEL_ID if CHANNEL_ID else ADMIN_ID
        if target_id and text:
             await bot.send_message(target_id, text, parse_mode="HTML")
             
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")

async def scraper_job():
    global STOP_PARSING
    if STOP_PARSING:
        return
        
    logger.info("Scheduler Trigger: Starting scraper cycle.")
    
    # Notify Start
    target_id = CHANNEL_ID if CHANNEL_ID else ADMIN_ID
    if target_id:
        try:
             await bot.send_message(target_id, "🏁 <b>Scraper cycle started...</b>", parse_mode="HTML")
        except Exception as e:
             logger.error(f"Failed to send start msg: {e}")

    # Run Cycle
    new_ads_count = await scraper.run_cycle(notify_callback=notify_user)
    
    # Log Next Run
    next_run = datetime.now() + timedelta(minutes=2)
    next_run_str = next_run.strftime('%H:%M:%S')
    logger.info(f"Cycle finished. Next run scheduled at: {next_run_str}")
    
    # Notify Finish
    if target_id:
        text = (
            f"🏁 <b>Cycle Finished</b>\n"
            f"✅ New Ads: {new_ads_count}\n"
            f"⏰ Next Run: {next_run_str}"
        )
        try:
            await bot.send_message(target_id, text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send finish msg: {e}")

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram import F

# Keyboard Setup
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="▶️ Start Scraper"), KeyboardButton(text="⏸ Pause Scraper")],
        [KeyboardButton(text="📊 Statistics"), KeyboardButton(text="📜 View Logs")],
        [KeyboardButton(text="📥 Download Data")]
    ],
    resize_keyboard=True
)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    global STOP_PARSING
    STOP_PARSING = False
    
    # Check if job exists, if not add it
    if not scheduler.get_job('scraper_job'):
        scheduler.add_job(scraper_job, 'interval', minutes=6, id='scraper_job')
    if not scheduler.running:
        scheduler.start()
        
    # Trigger immediate run if not running
    if not scraper.is_running:
        asyncio.create_task(scraper_job())
        
    await message.answer("✅ Bot started. Parsing initiated (Every 6 mins).", reply_markup=main_keyboard)

@dp.message(F.text == "▶️ Start Scraper")
async def btn_start(message: types.Message):
    await cmd_start(message)

@dp.message(Command("stop"))
async def cmd_stop(message: types.Message):
    global STOP_PARSING
    STOP_PARSING = True
    scraper.stop_signal = True
    
    if scheduler.get_job('scraper_job'):
        scheduler.remove_job('scraper_job')
        
    await message.answer("🛑 Bot stopped. Parsing will abort.", reply_markup=main_keyboard)

@dp.message(F.text == "⏸ Pause Scraper")
async def btn_stop(message: types.Message):
    await cmd_stop(message)

@dp.message(Command("logs"))
async def cmd_logs(message: types.Message):
    log_file = LOG_DIR / "insightor.log"
    if log_file.exists():
        with open(log_file, 'r') as f:
            lines = f.readlines()
            last_5 = "".join(lines[-5:])
            await message.answer(f"Last 5 log lines:\n<pre>{last_5}</pre>", parse_mode="HTML")
        await message.answer_document(FSInputFile(log_file))
    else:
        await message.answer("No logs found.")

@dp.message(F.text == "📜 View Logs")
async def btn_logs(message: types.Message):
    await cmd_logs(message)

@dp.message(Command("database"))
async def cmd_database(message: types.Message):
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM ads") as cursor:
                 rows = await cursor.fetchall()
                 data = [dict(row) for row in rows]
                 
        if data:
            df = pd.DataFrame(data)
            csv_path = LOG_DIR / "ads_export.csv"
            df.to_csv(csv_path, index=False)
            await message.answer_document(FSInputFile(csv_path))
        else:
            await message.answer("Database is empty.")
    except Exception as e:
        await message.answer(f"Error exporting database: {e}")

@dp.message(F.text == "📥 Download Data")
async def btn_database(message: types.Message):
    await cmd_database(message)

@dp.message(F.text == "📊 Statistics")
async def btn_stats(message: types.Message):
    try:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM ads") as cursor:
                row = await cursor.fetchone()
                total_ads = row[0]
            
            async with db.execute("SELECT COUNT(*) FROM ads WHERE first_seen > date('now', '-1 day')") as cursor:
                row = await cursor.fetchone()
                new_today = row[0]

        text = (
            f"📊 <b>Statistics</b>\n"
            f"Total Ads: {total_ads}\n"
            f"New in 24h: {new_today}"
        )
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"Error fetching stats: {e}")

async def on_startup(bot: Bot):
    # Just ensure scheduler is ready but don't add job or start scraping yet
    if not scheduler.running:
        scheduler.start()

async def main():
    await init_db()
    dp.startup.register(on_startup)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
