import asyncio
import logging
from shared.database import init_db, add_ad, get_ad
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_database():
    logger.info("Testing Database...")
    await init_db()
    
    test_ad = {
        'ad_id': 'test_123',
        'ad_url': 'http://example.com/test',
        'first_seen': datetime.now(),
        'post_date': datetime.now(),
        'initial_price': 1000,
        'current_price': 1000,
        'car_brand': 'TestBrand',
        'car_model': 'TestModel',
        'car_year': 2020,
        'gearbox': 'Manual',
        'body_type': 'Sedan',
        'fuel_type': 'Petrol',
        'engine_size': '2.0L',
        'drive_type': 'FWD',
        'mileage': 50000,
        'user_name': 'Tester',
        'user_id': 'user_1',
        'is_business': False,
        'ad_status': 'Basic'
    }
    
    await add_ad(test_ad)
    fetched = await get_ad('test_123')
    
    if fetched and fetched['car_brand'] == 'TestBrand':
        logger.info("✅ Database Test Passed: Ad inserted and retrieved.")
    else:
        logger.error("❌ Database Test Failed.")

if __name__ == "__main__":
    asyncio.run(test_database())
