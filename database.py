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
                fuel_type TEXT,
                engine_size INTEGER,
                drive_type TEXT,
                mileage INTEGER,
                user_name TEXT,
                user_id TEXT,
                is_business BOOLEAN,
                ad_status TEXT,
                last_checked DATETIME
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_date DATETIME,
                is_premium BOOLEAN DEFAULT FALSE,
                active_alerts_count INTEGER DEFAULT 0
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                created_at DATETIME,
                is_active BOOLEAN DEFAULT TRUE,
                filters JSON,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
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

# --- Shared Logic ---

def is_match(ad: AdData, filters: dict) -> bool:
    """Check if ad matches alert filters."""
    try:
        # Brand
        if filters.get('brand') and filters['brand'] != ad.get('car_brand'): return False
        
        # Model
        if filters.get('model'):
             ad_model = ad.get('car_model', '')
             target_models = filters['model']
             if isinstance(target_models, list):
                 if ad_model not in target_models: return False
             elif ad_model != target_models: return False

        # Years
        if filters.get('year_min') and (not ad.get('car_year') or ad['car_year'] < filters['year_min']): return False
        if filters.get('year_max') and (not ad.get('car_year') or ad['car_year'] > filters['year_max']): return False
        
        # Prices
        if filters.get('price_min') and (not ad.get('current_price') or ad['current_price'] < filters['price_min']): return False
        if filters.get('price_max') and (not ad.get('current_price') or ad['current_price'] > filters['price_max']): return False

        # Mileage
        if filters.get('mileage_min') and (not ad.get('mileage') or ad['mileage'] < filters['mileage_min']): return False
        if filters.get('mileage_max') and (not ad.get('mileage') or ad['mileage'] > filters['mileage_max']): return False

        # Engine
        if filters.get('engine_min'):
             if not ad.get('engine_size'): return False
             if ad['engine_size'] < filters['engine_min']: return False
        if filters.get('engine_max'):
             if not ad.get('engine_size'): return False
             if ad['engine_size'] > filters['engine_max']: return False

        # Others
        for field in ['gearbox', 'fuel_type', 'drive_type', 'body_type', 'car_color', 'ad_status']:
            filter_key = field if field != 'car_color' else 'color'
            if filters.get(filter_key) and filters[filter_key] != ad.get(field): return False

        # Business
        if filters.get('is_business') is not None and filters['is_business'] != ad.get('is_business'): return False

        return True
    except Exception as e:
        logger.error(f"Error matching ad: {e}")
        return False

def format_ad_message(ad_data: AdData, notification_type: str = 'new') -> str | None:
    """Format ad data into a message string."""
    try:
        brand = ad_data.get('car_brand', 'Unknown') or 'Unknown'
        model = ad_data.get('car_model', '') or ''
        year = ad_data.get('car_year', '') or ''
        title = f"{brand} {model} {year}".strip()
        
        mileage = ad_data.get('mileage', 0)
        mileage_str = f"{mileage:,} km" if mileage else "N/A"
            
        fuel = ad_data.get('fuel_type', 'N/A')
        gear = ad_data.get('gearbox', 'N/A')
        engine = ad_data.get('engine_size', 'N/A')
        if isinstance(engine, int): engine = f"{engine} cc"

        seller = ad_data.get('user_name', 'Unknown')
        status = ad_data.get('ad_status', 'Basic')
        
        status_prefix = "🚗"
        if status == 'VIP': status_prefix = "🌟 VIP"
        elif status == 'TOP': status_prefix = "🔥 TOP"
        
        seller_id = ad_data.get('user_id', '')
        seller_info = seller
        if seller_id:
            seller_info += f" (#id_{seller_id})"

        msg_text = ""
        if notification_type == 'new':
            msg_text = (
                f"{status_prefix} <a href=\"{ad_data['ad_url']}\">{title}</a>\n"
                f"💰 <b>{ad_data['current_price']} €</b>  📏 {mileage_str}\n"
                f"⛽ {fuel}  ⚙️ {gear}  🔧 {engine}\n"
                f"👤 {seller_info}"
            )
        elif notification_type == 'repost':
            msg_text = (
                f"🔄 <b>Ad Reposted!</b>\n"
                f"The ad was bumped to the top.\n"
                f"🔗 <a href=\"{ad_data['ad_url']}\">{brand} {model}</a>"
            )
        return msg_text
    except Exception as e:
        logger.error(f"Error formatting match msg: {e}")
        return None

async def get_latest_matching_ads(filters: dict, limit: int = 10) -> list[AdData]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Fetch a reasonable batch of recent ads to check
        cursor = await db.execute("SELECT * FROM ads ORDER BY last_checked DESC LIMIT 2000") # Changed to last_checked for recency
        rows = await cursor.fetchall()
        
        matches = []
        for row in rows:
            ad = dict(row)
            if is_match(ad, filters):
                matches.append(ad)
                if len(matches) >= limit:
                    break
        return matches

async def get_min_max_values(column: str) -> tuple[int, int]:
    """Get min and max values for a numeric column."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Cast to integer for engine_size if it's stored as text, though we updated schema.
        # But for safety with existing data, we cast.
        col_expr = f"CAST({column} AS INTEGER)" if column == "engine_size" else column
        query = f"SELECT MIN({col_expr}), MAX({col_expr}) FROM ads WHERE {col_expr} IS NOT NULL AND {col_expr} > 0"
        async with db.execute(query) as cursor:
            row = await cursor.fetchone()
            return (row[0] or 0, row[1] or 0) if row else (0, 0)

async def get_distinct_values(column: str, filter_col: str | None = None, filter_val: str | None = None) -> list[str]:
    """Get sorted distinct values for a text column."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        query = f"SELECT DISTINCT {column} FROM ads WHERE {column} IS NOT NULL AND {column} != ''"
        args = []
        if filter_col and filter_val:
            query += f" AND {filter_col} = ?"
            args.append(filter_val)
        query += f" ORDER BY {column} ASC"
        
        async with db.execute(query, tuple(args)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def add_or_update_user(user_id: int, username: str, first_name: str) -> None:
    """Add or update a Telegram user."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                INSERT INTO users (user_id, username, first_name, joined_date)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name
            """, (user_id, username, first_name, datetime.now()))
            await db.commit()

async def get_user(user_id: int) -> dict[str, Any] | None:
    """Get user details."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def create_alert(user_id: int, name: str, filters: dict) -> bool:
    """Create a new alert for user."""
    import json
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("INSERT INTO alerts (user_id, name, created_at, filters) VALUES (?, ?, ?, ?)",
                           (user_id, name, datetime.now(), json.dumps(filters)))
            await db.execute("UPDATE users SET active_alerts_count = active_alerts_count + 1 WHERE user_id = ?", (user_id,))
            await db.commit()
    return True

async def get_user_alerts(user_id: int) -> list[dict[str, Any]]:
    """Get all alerts for a user."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM alerts WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_alert(alert_id: int) -> dict[str, Any] | None:
    """Retrieve a single alert by ID."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def delete_alert(alert_id: int, user_id: int) -> None:
    """Delete an alert."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("DELETE FROM alerts WHERE alert_id = ? AND user_id = ?", (alert_id, user_id))
            await db.execute("UPDATE users SET active_alerts_count = MAX(0, active_alerts_count - 1) WHERE user_id = ?", (user_id,))
            await db.commit()

async def toggle_alert(alert_id: int, user_id: int, is_active: bool) -> None:
    """Activate or deactivate an alert."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE alerts SET is_active = ? WHERE alert_id = ? AND user_id = ?", (is_active, alert_id, user_id))
            await db.commit()

async def get_active_alerts() -> list[dict[str, Any]]:
    """Get all active alerts for matching."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM alerts WHERE is_active = 1") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
