import asyncio
import logging
import sys
import csv
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_ID, CHANNEL_ID, LOG_DIR
from database import init_db, get_all_ads, get_statistics
from scraper import BazarakiScraper

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
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()
scraper = BazarakiScraper()

# Middleware for Access Control
class AdminMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get('event_from_user')
        if not user:
            return await handler(event, data)
            
        if user.id != ADMIN_ID:
            if isinstance(event, types.Message):
                await event.answer("⛔ Access Denied. You are not authorized to use this bot.")
            return
            
        return await handler(event, data)

dp.message.middleware(AdminMiddleware())

async def notify_user(notification_type: str, ad_data: dict):
    """Send notification to Telegram."""
    try:
        if notification_type == 'new':
            brand = ad_data.get('car_brand', 'Unknown') or 'Unknown'
            model = ad_data.get('car_model', '') or ''
            year = ad_data.get('car_year', '') or ''
            title = f"{brand} {model} {year}".strip()
            
            mileage = ad_data.get('mileage', 0)
            mileage_str = f"{mileage:,} km" if mileage else "N/A"
                
            fuel = ad_data.get('fuel_type', 'N/A')
            gear = ad_data.get('gearbox', 'N/A')
            engine = ad_data.get('engine_size', 'N/A')
            seller = ad_data.get('user_name', 'Unknown')
            status = ad_data.get('ad_status', 'Basic')
            
            status_prefix = "🚗"
            if status == 'VIP': status_prefix = "🌟 VIP"
            elif status == 'TOP': status_prefix = "🔥 TOP"
            
            seller_id = ad_data.get('user_id', '')
            seller_info = seller
            if seller_id:
                seller_info += f" (#id_{seller_id})"

            text = (
                f"{status_prefix} <a href=\"{ad_data['ad_url']}\">{title}</a>\n"
                f"💰 <b>{ad_data['current_price']} €</b>  📏 {mileage_str}\n"
                f"⛽ {fuel}  ⚙️ {gear}  🔧 {engine}\n"
                f"👤 {seller_info}"
            )
        elif notification_type == 'repost':
            text = (
                f"🔄 <b>Ad Reposted!</b>\n"
                f"The ad was bumped to the top.\n"
                f"🔗 <a href=\"{ad_data['ad_url']}\">{ad_data.get('car_brand', '')} {ad_data.get('car_model', '')}</a>"
            )
        elif notification_type == 'status':
            old_status = ad_data.get('old_status', 'Unknown')
            new_status = ad_data.get('ad_status', 'Unknown')
            text = (
                f"🚀 <b>Status Changed</b>\n"
                f"{old_status} ➡️ <b>{new_status}</b>\n"
                f"🔗 <a href=\"{ad_data['ad_url']}\">View Ad</a>"
            )
        else:
             return

        target_id = CHANNEL_ID if CHANNEL_ID else ADMIN_ID
        if target_id and text:
             await bot.send_message(target_id, text, parse_mode="HTML")
             
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")

async def scraper_job():
    if scraper.is_running:
        logger.warning("Scraper cycle already running. Skipping.")
        return

    logger.info("Scheduler Trigger: Starting scraper cycle.")
    
    target_id = CHANNEL_ID if CHANNEL_ID else ADMIN_ID
    if target_id:
        try:
             await bot.send_message(target_id, "🏁 <b>Scraper cycle started...</b>", parse_mode="HTML")
        except Exception as e:
             logger.error(f"Failed to send start msg: {e}")

    # Run Cycle
    new_ads_count = await scraper.run_cycle(notify_callback=notify_user)
    
    next_run = datetime.now() + timedelta(minutes=6)
    next_run_str = next_run.strftime('%H:%M:%S')
    logger.info(f"Cycle finished. Next run approx: {next_run_str}")
    
    if target_id:
        text = (
            f"🏁 <b>Cycle Finished</b>\n"
            f"✅ New Ads: {new_ads_count}\n"
            f"⏰ Next Run: {next_run_str} (approx)"
        )
        try:
            await bot.send_message(target_id, text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send finish msg: {e}")

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
@dp.message(F.text == "▶️ Start Scraper")
async def cmd_start(message: types.Message):
    # Reset stop signal just in case
    scraper.stop_signal = False
    
    if not scheduler.get_job('scraper_job'):
        scheduler.add_job(scraper_job, 'interval', minutes=6, id='scraper_job')
    
    if not scheduler.running:
        scheduler.start()
        
    if not scraper.is_running:
        asyncio.create_task(scraper_job())
        
    await message.answer("✅ Bot started. Parsing initiated (Every 6 mins).", reply_markup=main_keyboard)

@dp.message(Command("stop"))
@dp.message(F.text == "⏸ Pause Scraper")
async def cmd_stop(message: types.Message):
    scraper.stop_signal = True
    
    if scheduler.get_job('scraper_job'):
        scheduler.remove_job('scraper_job')
        
    await message.answer("🛑 Bot stopped. Parsing will abort.", reply_markup=main_keyboard)

@dp.message(Command("logs"))
@dp.message(F.text == "📜 View Logs")
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

@dp.message(Command("database"))
@dp.message(F.text == "📥 Download Data")
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

@dp.message(F.text == "📊 Statistics")
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

async def on_startup(bot: Bot):
    if not scheduler.running:
        scheduler.start()

async def main():
    await init_db()
    dp.startup.register(on_startup)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
