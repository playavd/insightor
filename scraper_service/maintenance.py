import logging
import asyncio
import random
from datetime import datetime
from typing import Any

from shared.constants import REQUEST_DELAY_MIN, REQUEST_DELAY_MAX, SEARCH_URL
from shared.database import get_ad, update_ad_color, add_ad
from shared.utils import AdData
from .logic import BazarakiScraper # Import the scraper class to use its fetch methods

logger = logging.getLogger(__name__)

async def rescan_colors(scraper: BazarakiScraper, max_pages_limit: int = 100):
    """
    Scanning specifically to fill missing colors.
    This is a maintenance task, separate from the main cycle.
    """
    scraper.is_running = True
    scraper.stop_signal = False
    page = 1
    updated_count = 0
    
    logger.info(f"Starting COLOR RESCAN for {max_pages_limit} pages...")
    
    try:
        while not scraper.stop_signal and page <= max_pages_limit:
            url = f"{SEARCH_URL}?page={page}"
            logger.info(f"Rescan: Fetching {url}")
            
            html = await scraper.fetch_page(url)
            if not html:
                break
                
            ads = scraper.parse_listing_page(html)
            if not ads:
                break
            
            logger.info(f"Rescan Page {page}: Found {len(ads)} ads. checking for missing colors...")
                
            for ad in ads:
                if scraper.stop_signal:
                    break
                    
                ad_id = ad['ad_id']
                existing_ad = await get_ad(ad_id)
                
                if existing_ad:
                    # Check if color is missing
                    if not existing_ad.get('car_color'):
                        logger.info(f"Ad {ad_id} missing color. Fetching details...")
                        details = await scraper.fetch_ad_details(ad['ad_url'])
                        if details and details.get('car_color'):
                            await update_ad_color(ad_id, details['car_color'])
                            updated_count += 1
                            logger.info(f"Updated Ad {ad_id} with color: {details['car_color']}")
                        
                        # Delay after fetching details
                        await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
                else:
                    # New ad found during rescan - we can add it completely
                    logger.info(f"Ad {ad_id} is NEW (found during rescan). Adding...")
                    details = await scraper.fetch_ad_details(ad['ad_url'])
                    if details:
                        # Construct AdData manually or helper
                        full_ad_data: AdData = {
                            'ad_id': ad_id,
                            'ad_url': ad['ad_url'],
                            'first_seen': datetime.now(),
                            'post_date': details.get('post_date'),
                            'initial_price': ad['price'],
                            'current_price': ad['price'],
                            'car_brand': details.get('car_brand'),
                            'car_model': details.get('car_model'),
                            'car_year': details.get('car_year'),
                            'car_color': details.get('car_color'),
                            'gearbox': details.get('gearbox'),
                            'body_type': details.get('body_type'),
                            'fuel_type': details.get('fuel_type'),
                            'engine_size': details.get('engine_size'),
                            'drive_type': details.get('drive_type'),
                            'mileage': details.get('mileage'),
                            'user_name': details.get('user_name'),
                            'user_id': details.get('user_id'),
                            'is_business': details.get('is_business'),
                            'ad_status': ad['status']
                        }
                        await add_ad(full_ad_data)
                        updated_count += 1
                        
                    await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

            page += 1
            await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
            
    finally:
        scraper.is_running = False
        logger.info(f"Rescan complete. Updated/Added {updated_count} ads.")
