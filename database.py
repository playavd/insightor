import aiosqlite
import asyncio
import logging
from datetime import datetime, date
from typing import TypedDict, Optional, Any
from pathlib import Path

from config import DATABASE_PATH

logger = logging.getLogger(__name__)

# Global lock for DB writes to prevent race conditions during concurrent heavy loads
db_lock = asyncio.Lock()

class AdData(TypedDict):
    ad_id: str
    ad_url: str
    first_seen: datetime
    post_date: datetime | None
    initial_price: int
    current_price: int
    car_brand: str | None
    car_model: str | None
    car_year: int | None
    car_color: str | None
    gearbox: str | None
    body_type: str | None
    fuel_type: str | None
    engine_size: int | None
    drive_type: str | None
    mileage: int | None
    user_name: str | None
    user_id: str | None
    is_business: bool | None
    ad_status: str

class Stats(TypedDict):
    total_ads: int
    new_today: int

async def init_db() -> None:
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
                car_color TEXT,
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
        # Migration: Add car_color column if it doesn't exist
        try:
            await db.execute("ALTER TABLE ads ADD COLUMN car_color TEXT")
        except aiosqlite.OperationalError:
            # Column likely already exists
            pass
            
        await db.commit()
    logger.info("Database initialized.")

async def add_ad(ad_data: AdData) -> None:
    """Insert a new ad into the database."""
    # Ensure datetimes are valid or None
    params = ad_data.copy()
    # Add last_checked as first_seen for new ads
    params['last_checked'] = params['first_seen']
    if 'car_color' not in params:
        params['car_color'] = None

    query = """
        INSERT OR IGNORE INTO ads (
            ad_id, ad_url, first_seen, post_date, initial_price, current_price,
            car_brand, car_model, car_year, car_color, gearbox, body_type, fuel_type,
            engine_size, drive_type, mileage, user_name, user_id, is_business,
            ad_status, last_checked
        ) VALUES (
            :ad_id, :ad_url, :first_seen, :post_date, :initial_price, :current_price,
            :car_brand, :car_model, :car_year, :car_color, :gearbox, :body_type, :fuel_type,
            :engine_size, :drive_type, :mileage, :user_name, :user_id, :is_business,
            :ad_status, :last_checked
        )
    """
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(query, params)
            await db.commit()

async def get_ad(ad_id: str) -> dict[str, Any] | None:
    """Retrieve an ad by its ID."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM ads WHERE ad_id = ?", (ad_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def update_ad_price(ad_id: str, new_price: int) -> None:
    """Update the current price of an ad."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                UPDATE ads 
                SET current_price = ?, last_checked = ? 
                WHERE ad_id = ?
            """, (new_price, datetime.now(), ad_id))
            await db.commit()

async def update_ad_color(ad_id: str, color: str) -> None:
    """Update the car color of an ad."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                UPDATE ads 
                SET car_color = ?
                WHERE ad_id = ?
            """, (color, ad_id))
            await db.commit()

async def update_ad_post_date(ad_id: str, new_post_date: datetime) -> None:
    """Update the post date of an ad (repost)."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                UPDATE ads 
                SET post_date = ?, last_checked = ? 
                WHERE ad_id = ?
            """, (new_post_date, datetime.now(), ad_id))
            await db.commit()

async def update_ad_status(ad_id: str, new_status: str) -> None:
    """Update the status of an ad (e.g., Basic -> VIP)."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                UPDATE ads 
                SET ad_status = ?, last_checked = ? 
                WHERE ad_id = ?
            """, (new_status, datetime.now(), ad_id))
            await db.commit()

async def touch_ad(ad_id: str) -> None:
    """Update last_checked timestamp for an ad."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE ads SET last_checked = ? WHERE ad_id = ?", (datetime.now(), ad_id))
            await db.commit()

async def get_all_ads() -> list[dict[str, Any]]:
    """Retrieve all ads for export."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM ads") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_statistics() -> Stats:
    """Get total ads count and new ads in the last 24 hours."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM ads") as cursor:
            row = await cursor.fetchone()
            total = row[0] if row else 0
        
        async with db.execute("SELECT COUNT(*) FROM ads WHERE first_seen > date('now', '-1 day')") as cursor:
            row = await cursor.fetchone()
            new_today = row[0] if row else 0
            
    return {"total_ads": total, "new_today": new_today}
