
import asyncio
import logging
from shared.database import init_db, update_ad_business
from shared.config import LOG_DIR
import sys

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fix_script")

ADS_TO_FIX = [
    "5557374",
    "5901457",
    "5930579",
    "6020220",
    "6130920",
    "5760591"
]

async def main():
    logger.info("Starting fix_business_status script...")
    await init_db()
    
    for ad_id in ADS_TO_FIX:
        logger.info(f"Setting is_business=True for Ad {ad_id}")
        await update_ad_business(ad_id, True)
    
    logger.info("Done.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
