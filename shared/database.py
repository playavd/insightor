import aiosqlite
import asyncio
import logging
import json
from datetime import datetime
from typing import TypedDict, Any, List, Optional, Dict

# Local imports
from .config import DATABASE_PATH
from .utils import is_match, AdData

logger = logging.getLogger(__name__)

# Global lock for DB writes to prevent race conditions
db_lock = asyncio.Lock()

class Stats(TypedDict):
    total_ads: int
    new_today: int

async def init_db() -> None:
    """Initialize the database and create tables if they don't exist."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.commit()
        
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

        await db.execute("""
            CREATE TABLE IF NOT EXISTS followed_ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                ad_id TEXT,
                created_at DATETIME,
                failed_checks_count INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                UNIQUE(user_id, ad_id)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS ad_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ad_id TEXT,
                change_type TEXT,
                old_value TEXT,
                new_value TEXT,
                timestamp DATETIME,
                FOREIGN KEY(ad_id) REFERENCES ads(ad_id)
            )
        """)
        
        # Migrations
        try:
            await db.execute("ALTER TABLE ads ADD COLUMN car_color TEXT")
        except aiosqlite.OperationalError:
            pass # Column already exists
            
        await db.commit()
    logger.info("Database initialized.")

# --- ADS CRUD ---

# --- ADS CRUD ---

async def add_ad(ad_data: AdData) -> None:
    """Insert a new ad into the database."""
    params: Dict[str, Any] = dict(ad_data)
    params['last_checked'] = params['first_seen']
    params.setdefault('car_color', None)

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

async def get_ad(ad_id: str) -> Optional[dict[str, Any]]:
    """Retrieve an ad by its ID."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM ads WHERE ad_id = ?", (ad_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def update_ad_price(ad_id: str, new_price: int) -> None:
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                UPDATE ads 
                SET current_price = ?, last_checked = ? 
                WHERE ad_id = ?
            """, (new_price, datetime.now(), ad_id))
            await db.commit()

async def update_ad_color(ad_id: str, color: str) -> None:
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE ads SET car_color = ? WHERE ad_id = ?", (color, ad_id))
            await db.commit()

async def update_ad_post_date(ad_id: str, new_post_date: datetime) -> None:
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                UPDATE ads 
                SET post_date = ?, last_checked = ? 
                WHERE ad_id = ?
            """, (new_post_date, datetime.now(), ad_id))
            await db.commit()

async def update_ad_status(ad_id: str, new_status: str) -> None:
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("""
                UPDATE ads 
                SET ad_status = ?, last_checked = ? 
                WHERE ad_id = ?
            """, (new_status, datetime.now(), ad_id))
            await db.commit()

async def touch_ad(ad_id: str) -> None:
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE ads SET last_checked = ? WHERE ad_id = ?", (datetime.now(), ad_id))
            await db.commit()

async def update_ad_business(ad_id: str, is_business: bool) -> None:
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE ads SET is_business = ? WHERE ad_id = ?", (is_business, ad_id))
            await db.commit()

async def get_all_ads() -> List[dict[str, Any]]:
    """Retrieve all ads usage for export."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM ads") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_statistics() -> Stats:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM ads") as cursor:
            row_total = await cursor.fetchone()
            total = row_total[0] if row_total else 0
        
        async with db.execute("SELECT COUNT(*) FROM ads WHERE first_seen > date('now', '-1 day')") as cursor:
            row_new = await cursor.fetchone()
            new_today = row_new[0] if row_new else 0
            
    return {"total_ads": total, "new_today": new_today}

# --- SEARCH & MATCHING ---

async def get_latest_matching_ads(filters: dict, limit: int = 10) -> List[dict[str, Any]]:
    """
    Fetch recent ads and filter them in memory using helper logic.
    Optimized to fetch only last checked ads.
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Fetching strictly by recency (last_checked) might miss older ads that just matched?
        # But use case is "New Alert" or "Activate", usually we want recent market status.
        cursor = await db.execute("SELECT * FROM ads ORDER BY last_checked DESC LIMIT 2000")
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
        col_expr = f"CAST({column} AS INTEGER)" if column == "engine_size" else column
        # Ensure we don't pick up garbage
        query = f"SELECT MIN({col_expr}), MAX({col_expr}) FROM ads WHERE {col_expr} IS NOT NULL AND {col_expr} > 0"
        async with db.execute(query) as cursor:
            row = await cursor.fetchone()
            return (row[0] or 0, row[1] or 0) if row else (0, 0)

async def get_distinct_values(column: str, filter_col: Optional[str] = None, filter_val: Optional[str] = None) -> List[str]:
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

# --- USER & ALERTS ---

async def add_or_update_user(user_id: int, username: Optional[str], first_name: Optional[str]) -> None:
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

async def get_user(user_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def create_alert(user_id: int, name: str, filters: dict) -> int:
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("INSERT INTO alerts (user_id, name, created_at, filters) VALUES (?, ?, ?, ?)",
                           (user_id, name, datetime.now(), json.dumps(filters)))
            alert_id = cursor.lastrowid
            await db.execute("UPDATE users SET active_alerts_count = active_alerts_count + 1 WHERE user_id = ?", (user_id,))
            await db.commit()
            return alert_id

async def get_user_alerts(user_id: int) -> List[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM alerts WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_alert(alert_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def delete_alert(alert_id: int, user_id: int) -> None:
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("DELETE FROM alerts WHERE alert_id = ? AND user_id = ?", (alert_id, user_id))
            # Recalculate count to be safe
            await db.execute("""
                UPDATE users 
                SET active_alerts_count = (SELECT COUNT(*) FROM alerts WHERE user_id = ? AND is_active = 1)
                WHERE user_id = ?
            """, (user_id, user_id))
            await db.commit()

async def toggle_alert(alert_id: int, user_id: int, is_active: bool) -> None:
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE alerts SET is_active = ? WHERE alert_id = ? AND user_id = ?", (is_active, alert_id, user_id))
            # Update count
            await db.execute("""
                UPDATE users 
                SET active_alerts_count = (SELECT COUNT(*) FROM alerts WHERE user_id = ? AND is_active = 1)
                WHERE user_id = ?
            """, (user_id, user_id))
            await db.commit()

async def update_alert(alert_id: int, user_id: int, filters: dict) -> None:
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE alerts SET filters = ? WHERE alert_id = ? AND user_id = ?", 
                             (json.dumps(filters), alert_id, user_id))
            await db.commit()

async def rename_alert(alert_id: int, user_id: int, new_name: str) -> None:
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute("UPDATE alerts SET name = ? WHERE alert_id = ? AND user_id = ?", 
                             (new_name, alert_id, user_id))
            await db.commit()

async def get_active_alerts() -> List[dict[str, Any]]:
    """Get all active alerts for the scraper loop."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM alerts WHERE is_active = 1") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_active_alerts_count_by_user(user_id: int) -> int:
    """Get precise count of active alerts for a user."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM alerts WHERE user_id = ? AND is_active = 1", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

# --- FOLLOWED ADS & HISTORY ---

async def follow_ad(user_id: int, ad_id: str) -> bool:
    """
    Toggle follow status for an ad.
    Returns: True if now following, False if unfollowed.
    """
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Check if already following
            async with db.execute("SELECT 1 FROM followed_ads WHERE user_id = ? AND ad_id = ?", (user_id, ad_id)) as cursor:
                exists = await cursor.fetchone()
            
            if exists:
                await db.execute("DELETE FROM followed_ads WHERE user_id = ? AND ad_id = ?", (user_id, ad_id))
                await db.commit()
                logger.info(f"User {user_id} unfollowed ad {ad_id}")
                return False
            else:
                await db.execute(
                    "INSERT INTO followed_ads (user_id, ad_id, created_at) VALUES (?, ?, ?)",
                    (user_id, ad_id, datetime.now())
                )
                await db.commit()
                return True

async def is_ad_followed_by_user(user_id: int, ad_id: str) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT 1 FROM followed_ads WHERE user_id = ? AND ad_id = ?", (user_id, ad_id)) as cursor:
            return bool(await cursor.fetchone())

async def get_followed_ads() -> List[str]:
    """Get list of unique ad_ids that are being followed by at least one user."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT DISTINCT ad_id FROM followed_ads") as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_ad_followers(ad_id: str) -> List[int]:
    """Get list of user_ids following a specific ad."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT user_id FROM followed_ads WHERE ad_id = ?", (ad_id,)) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_all_followed_ads_by_user(user_id: int) -> set[str]:
    """Get a set of all ad_ids followed by a specific user."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT ad_id FROM followed_ads WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return {row[0] for row in rows}

async def update_follow_check_status(ad_id: str, increment_fail: bool = False, reset_fail: bool = False):
    """Update failed checks count for a followed ad."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            if reset_fail:
                await db.execute("UPDATE followed_ads SET failed_checks_count = 0 WHERE ad_id = ?", (ad_id,))
            elif increment_fail:
                await db.execute("UPDATE followed_ads SET failed_checks_count = failed_checks_count + 1 WHERE ad_id = ?", (ad_id,))
            await db.commit()

async def get_user_alerts_count(user_id: int) -> int:
    """Get total count of alerts (active or not) for a user."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM alerts WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_user_followed_ads_count(user_id: int) -> int:
    """Get count of ads followed by user."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM followed_ads WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_user_followed_ads_paginated(user_id: int, offset: int = 0, limit: int = 5) -> List[dict[str, Any]]:
    """Get followed ads for a user with pagination, joined with ad details."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = """
            SELECT a.*, f.created_at as followed_at 
            FROM followed_ads f
            JOIN ads a ON f.ad_id = a.ad_id
            WHERE f.user_id = ?
            ORDER BY f.created_at DESC
            LIMIT ? OFFSET ?
        """
        async with db.execute(query, (user_id, limit, offset)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_ad_failed_checks(ad_id: str) -> int:
    """Get the max failed checks count for an ad (from any follower entry)."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        async with db.execute("SELECT MAX(failed_checks_count) FROM followed_ads WHERE ad_id = ?", (ad_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] is not None else 0

# --- AD HISTORY ---

async def add_history_entry(ad_id: str, change_type: str, old_val: Any, new_val: Any):
    """Log a change to the ad history."""
    async with db_lock:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "INSERT INTO ad_history (ad_id, change_type, old_value, new_value, timestamp) VALUES (?, ?, ?, ?, ?)",
                (ad_id, change_type, str(old_val), str(new_val), datetime.now())
            )
            await db.commit()

async def get_ad_history(ad_id: str, limit: int = 50) -> List[dict[str, Any]]:
    """Retrieve history for an ad."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM ad_history WHERE ad_id = ? ORDER BY timestamp DESC LIMIT ?", 
            (ad_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

