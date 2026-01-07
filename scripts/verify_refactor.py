import asyncio
import logging
import sys
from pathlib import Path

# Fix path to ensure current dir is in sys.path
sys.path.append(str(Path(__file__).parent))

async def verify():
    print("--- Starting Verification ---")
    
    print("1. Importing shared modules...")
    try:
        from shared.config import DATABASE_PATH
        from shared.database import init_db
        from shared.utils import is_match
        print(f"   Success. DB Path: {DATABASE_PATH}")
    except ImportError as e:
        print(f"   FAILED: {e}")
        return

    print("2. Importing Scraper Service...")
    try:
        from scraper_service.logic import BazarakiScraper
        s = BazarakiScraper()
        print("   Success. Scraper instance created.")
    except ImportError as e:
        print(f"   FAILED: {e}")
        return

    print("3. Importing Client Bot Handlers...")
    try:
        from client_bot.handlers import user_router
        print("   Success. User Router imported.")
    except ImportError as e:
        print(f"   FAILED: {e}")
        return

    print("4. Importing Admin Bot Handlers...")
    try:
        from admin_bot.handlers import admin_router
        print("   Success. Admin Router imported.")
    except ImportError as e:
        print(f"   FAILED: {e}")
        return

    print("5. Initializing Database...")
    try:
        await init_db()
        print("   Success. DB Initialized.")
    except Exception as e:
        print(f"   FAILED: {e}")
        return
        
    print("--- VERIFICATION COMPLETE: ALL PASS ---")

if __name__ == "__main__":
    asyncio.run(verify())
