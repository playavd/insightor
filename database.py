import aiosqlite
import asyncio
from datetime import datetime
import logging
from config import DATABASE_PATH

logger = logging.getLogger(__name__)

# Global lock for DB writes
db_lock = asyncio.Lock()

async def init_db():
    """Initialize the database and create tables if they don't exist."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ads (
                ad_id TEXT PRIMARY KEY,
                ad_url TEXT,
                first_seen DATETIME,
                post_date DATETIME,
                initial_price INTEGER,
                current_price INTEGER,
                car_brand TEXT,
                car_model TEXT,
                car_year INTEGER,
                gearbox TEXT,
                body_type TEXT,
                fuel_type TEXT,
                engine_size TEXT,
                drive_type TEXT,
                mileage INTEGER,
                user_name TEXT,
                user_id TEXT,
                is_business BOOLEAN,
                ad_status TEXT,
                last_checked DATETIME
            )
        """)
        await db.commit()
    logger.info("Database initialized.")

async def add_ad(ad_data: dict):
    """Insert a new ad into the database."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                INSERT OR IGNORE INTO ads (
                    ad_id, ad_url, first_seen, post_date, initial_price, current_price,
                    car_brand, car_model, car_year, gearbox, body_type, fuel_type,
                    engine_size, drive_type, mileage, user_name, user_id, is_business,
                    ad_status, last_checked
                ) VALUES (
                    :ad_id, :ad_url, :first_seen, :post_date, :initial_price, :current_price,
                    :car_brand, :car_model, :car_year, :gearbox, :body_type, :fuel_type,
                    :engine_size, :drive_type, :mileage, :user_name, :user_id, :is_business,
                    :ad_status, :first_seen
                )
            """, ad_data)
            await db.commit()

async def get_ad(ad_id: str):
    """Retrieve an ad by its ID."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM ads WHERE ad_id = ?", (ad_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

async def update_ad_price(ad_id: str, new_price: int):
    """Update the current price of an ad."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                UPDATE ads 
                SET current_price = ?, last_checked = ? 
                WHERE ad_id = ?
            """, (new_price, datetime.now(), ad_id))
            await db.commit()

async def update_ad_post_date(ad_id: str, new_post_date: datetime):
    """Update the post date of an ad (repost)."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                UPDATE ads 
                SET post_date = ?, last_checked = ? 
                WHERE ad_id = ?
            """, (new_post_date, datetime.now(), ad_id))
            await db.commit()

async def touch_ad(ad_id: str):
    """Update last_checked timestamp for an ad."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE ads SET last_checked = ? WHERE ad_id = ?", (datetime.now(), ad_id))
            await db.commit()

async def update_ad_status(ad_id: str, new_status: str):
    """Update the status of an ad (e.g., Basic -> VIP)."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                UPDATE ads 
                SET ad_status = ?, last_checked = ? 
                WHERE ad_id = ?
            """, (new_status, datetime.now(), ad_id))
            await db.commit()
