import asyncio
import logging
import sys
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher, BaseMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from shared.config import BOT_TOKEN, USER_BOT_TOKEN, ADMIN_ID, CHANNEL_ID, LOG_DIR
from shared.database import init_db, get_active_alerts
from shared.utils import format_ad_message, is_match

from scraper_service.logic import BazarakiScraper
from client_bot.handlers import user_router
from admin_bot.handlers import admin_router

# Logging Setup
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            LOG_DIR / "insightor.log",
            maxBytes=100*1024, # 100KB
            backupCount=1
        )
    ]
)

# Services
scheduler = AsyncIOScheduler()
scraper = BazarakiScraper()

# Bot Setup
admin_bot = Bot(token=BOT_TOKEN)
user_bot = Bot(token=USER_BOT_TOKEN) if USER_BOT_TOKEN else None

# Dispatchers
dp_admin = Dispatcher()
dp_user = Dispatcher()

# Middleware for Access Control (Admin Only)
class AdminMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get('event_from_user')
        if not user:
             return await handler(event, data)
        if user.id != ADMIN_ID:
             return
        return await handler(event, data)

# Notification Callback (Scraper -> Telegram)
async def notify_user(notification_type: str, ad_data: dict):
    """Send notification to Telegram (Admin & Users)."""
    try:
        msg_text = format_ad_message(ad_data, notification_type)
        if not msg_text: return
        
        # 1. Notify Admin
        target_id = CHANNEL_ID if CHANNEL_ID else ADMIN_ID
        if target_id:
             try:
                 await admin_bot.send_message(target_id, msg_text, parse_mode="HTML")
             except Exception as e:
                 logger.error(f"Failed to notify admin: {e}")
        
        # 2. Notify Users
        if user_bot and notification_type in ['new', 'repost']:
            alerts = await get_active_alerts()
            logger.debug(f"Notify User: Loaded {len(alerts)} active alerts.")
            
            for alert in alerts:
                filters = dict()
                import json
                try: filters = json.loads(alert['filters'])
                except: continue
                
                if is_match(ad_data, filters):
                    logger.info(f"MATCH FOUND: Ad {ad_data.get('ad_id')} for User {alert['user_id']}")
                    try:
                        # Add timeout to prevent hanging the scraper cycle
                        await asyncio.wait_for(
                            user_bot.send_message(alert['user_id'], msg_text, parse_mode="HTML"),
                            timeout=10
                        )
                        logger.debug(f"Notification sent to {alert['user_id']}")
                    except asyncio.TimeoutError:
                        logger.error(f"Timeout notifying user {alert['user_id']}")
                    except Exception as u_e:
                        logger.warning(f"Failed to notify user {alert['user_id']}: {u_e}")

    except Exception as e:
        logger.error(f"Failed to send notification: {e}")

# Scraper Job Wrapper
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


async def on_startup():
    # Ensure job is added
    if not scheduler.get_job('scraper_job'):
        scheduler.add_job(scraper_job, 'interval', minutes=6, id='scraper_job')
    
    if not scheduler.running:
        scheduler.start()
        
    # Initial run immediately?
    # asyncio.create_task(scraper_job()) 

async def main():
    await init_db()
    
    # Setup Admin Bot
    dp_admin.message.middleware(AdminMiddleware())
    dp_admin.include_router(admin_router)
    # Inject services
    dp_admin.workflow_data.update(scraper=scraper, scheduler=scheduler)
    dp_admin.startup.register(on_startup)
    
    # Setup User Bot
    dp_user.include_router(user_router)
    
    tasks = []
    logger.info("Admin Bot polling starting...")
    tasks.append(start_polling_safe(dp_admin, admin_bot, "Admin Bot"))
    
    if user_bot:
        logger.info("User Bot polling starting...")
        tasks.append(start_polling_safe(dp_user, user_bot, "User Bot"))
    else:
        logger.warning("USER_BOT_TOKEN not found.")
        
    await asyncio.gather(*tasks)

async def start_polling_safe(dp: Dispatcher, bot: Bot, name: str):
    """Run polling with infinite retry logic for network issues."""
    from aiogram.exceptions import TelegramNetworkError
    from aiohttp.client_exceptions import ClientConnectorError, ClientOSError
    
    while True:
        try:
            await dp.start_polling(bot)
        except (TelegramNetworkError, ClientConnectorError, ClientOSError, ConnectionResetError) as e:
            logger.error(f"⚠️ {name} connection failed: {e}. Retrying in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.exception(f"❌ {name} crashed with unexpected error: {e}. Retrying in 10s...")
            await asyncio.sleep(10)
        finally:
            # Short sleep to prevent tight loops if start_polling returns immediately
            await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
