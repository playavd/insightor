import asyncio
import csv
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from shared.config import LOG_DIR
from shared.database import get_all_ads, get_statistics
from scraper_service.logic import BazarakiScraper

admin_router = Router()

admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="▶️ Start Scraper"), KeyboardButton(text="⏸ Pause Scraper")],
        [KeyboardButton(text="📊 Statistics"), KeyboardButton(text="📜 View Logs")],
        [KeyboardButton(text="📥 Download Data"), KeyboardButton(text="👥 Users")]
    ],
    resize_keyboard=True
)

from datetime import datetime

@admin_router.message(Command("start"))
@admin_router.message(F.text == "▶️ Start Scraper")
async def cmd_start_admin(message: types.Message, scraper: BazarakiScraper, scheduler: AsyncIOScheduler):
    scraper.stop_signal = False
    
    job = scheduler.get_job('scraper_job')
    if job:
        job.resume()
        try:
            # Force immediate execution
            job.modify(next_run_time=datetime.now())
            await message.answer("✅ Scraper enabled. Cycle starting immediately...", reply_markup=admin_keyboard)
        except Exception as e:
             # Fallback if modification fails
             await message.answer(f"✅ Scraper enabled (Scheduled).", reply_markup=admin_keyboard)
    else:
        # If job is missing, we can't easily add it back without the function reference.
        # But it should exist from startup.
        if not scheduler.running: scheduler.start()
        await message.answer("⚠️ Scraper enabled, but job was missing. Restart bot if it doesn't run.", reply_markup=admin_keyboard)

@admin_router.message(Command("stop"))
@admin_router.message(F.text == "⏸ Pause Scraper")
async def cmd_stop_admin(message: types.Message, scraper: BazarakiScraper, scheduler: AsyncIOScheduler):
    scraper.stop_signal = True
    # We can pause the job
    job = scheduler.get_job('scraper_job')
    if job:
        job.pause()
        await message.answer("🛑 Scraper job paused.", reply_markup=admin_keyboard)
    else:
        await message.answer("🛑 Scraper signaled to stop.", reply_markup=admin_keyboard)

@admin_router.message(Command("logs"))
@admin_router.message(F.text == "📜 View Logs")
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

@admin_router.message(Command("database"))
@admin_router.message(F.text == "📥 Download Data")
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
        await message.answer(f"Error exporting database: {e}")

@admin_router.message(F.text == "📊 Statistics")
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
