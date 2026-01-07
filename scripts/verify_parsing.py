import asyncio
import logging
import sys
from scraper_service.logic import BazarakiScraper
from shared.config import SEARCH_URL

# Configure logging to stdout
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

async def verify():
    scraper = BazarakiScraper()
    print(f"Fetching from: {SEARCH_URL}")
    
    # 1. Fetch Listing Page
    html = await scraper.fetch_page(SEARCH_URL)
    if not html:
        print("❌ Failed to fetch listing page.")
        return

    ads = scraper.parse_listing_page(html)
    print(f"✅ Found {len(ads)} ads on the first page.")
    
    if not ads:
        return

    # 2. Inspect First Ad (Basic Info)
    first_ad = ads[0]
    print("\n--- [First Ad Summary] ---")
    print(f"ID: {first_ad.get('ad_id')}")
    print(f"Price: {first_ad.get('price')}")
    print(f"Status: {first_ad.get('status')}")
    print(f"URL: {first_ad.get('ad_url')}")
    
    # 3. Fetch Details
    print(f"\nFetching details for {first_ad['ad_url']}...")
    details = await scraper.fetch_ad_details(first_ad['ad_url'])
    
    if details:
        print("\n--- [Parsed Details] ---")
        for k, v in details.items():
            print(f"{k}: {v}")
            
        print("\n✅ Parsing seems successful if the fields above look correct.")
    else:
        print("❌ Failed to fetch details.")

if __name__ == "__main__":
    asyncio.run(verify())
