import asyncio
import aiosqlite
import logging
import random
from scraper_service.logic import BazarakiScraper
from shared.config import DATABASE_PATH

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fix_unknowns():
    scraper = BazarakiScraper()
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Find all target ads
        query = "SELECT ad_id, ad_url FROM ads WHERE car_brand IS NULL OR car_brand = 'Unknown' OR car_brand = ''"
        async with db.execute(query) as cursor:
            rows = await cursor.fetchall()
            
        logger.info(f"Found {len(rows)} ads with Unknown/Missing Brand. Starting rescan...")
        
        updated_count = 0
        
        for i, (ad_id, url) in enumerate(rows):
            logger.info(f"[{i+1}/{len(rows)}] Rescanning {url}...")
            
            # Fetch details
            details = await scraper.fetch_ad_details(url)
            
            if details and details.get('car_brand'):
                brand = details['car_brand']
                model = details.get('car_model')
                
                # Update DB
                await db.execute(
                    "UPDATE ads SET car_brand = ?, car_model = ? WHERE ad_id = ?",
                    (brand, model, ad_id)
                )
                await db.commit()
                updated_count += 1
                logger.info(f"  ✅ Fixed: {brand} {model}")
            else:
                logger.warning(f"  ❌ Still failed to extract brand for {url}")
            
            # Sleep specifically to be nice
            await asyncio.sleep(random.uniform(1.5, 3.0))
            
        logger.info(f"Remediation Complete. Fixed {updated_count}/{len(rows)} ads.")

if __name__ == "__main__":
    asyncio.run(fix_unknowns())
