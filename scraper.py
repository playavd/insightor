import asyncio
import cloudscraper
import logging
import random
from bs4 import BeautifulSoup
from datetime import datetime
from config import BASE_URL, SEARCH_URL, REQUEST_DELAY_MIN, REQUEST_DELAY_MAX, MAX_CONSECUTIVE_UNCHANGED, MAX_PAGES_LIMIT, USER_AGENT_LIST
from database import add_ad, get_ad, update_ad_price, update_ad_post_date, touch_ad
from dateparser import parse as parse_date

logger = logging.getLogger(__name__)

class BazarakiScraper:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'darwin',
                'desktop': True
            }
        )
        self.stop_signal = False
        self.is_running = False

    def get_random_user_agent(self):
        return random.choice(USER_AGENT_LIST)

    async def fetch_page(self, url: str):
        """Fetch a page using cloudscraper in a thread."""
        # Randomize UA slightly more or usage specific one
        ua = self.get_random_user_agent()
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.google.com/",
            "Upgrade-Insecure-Requests": "1",
        }
        
        loop = asyncio.get_event_loop()
        try:
            # Tweak scraper instance if needed
            # self.scraper.headers.update(headers) 
            
            response = await loop.run_in_executor(None, lambda: self.scraper.get(url, headers=headers))
            
            if response.status_code == 403 or (response.status_code != 200 and ("challenge" in response.text.lower() or "cloudflare" in response.text.lower())):
                logger.error(f"CRITICAL: Cloudflare Block or 403 Forbidden. Status: {response.status_code}")
                # Dump for debugging
                with open("debug_cf.html", "w", encoding="utf-8") as f:
                    f.write(response.text)
                return None
            
            # Additional check: If 200 but title indicates block
            if "<title>Just a moment...</title>" in response.text:
                 logger.error(f"CRITICAL: Cloudflare Challenge Page Detected (Status 200)")
                 return None

            return response.text
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    def parse_listing_page(self, html: str):
        """Parse the listing page and extract ad cards."""
        soup = BeautifulSoup(html, 'lxml')
        
        # There might be multiple list containers or one main one
        # We look for all, but prioritize the main one if valid
        containers = soup.find_all(class_='list-simple__output')
        if not containers:
            logger.warning("No list-simple__output container found.")
            return []
        
        ads = []
        for listing_container in containers:
             # Items might be li or div
             items = listing_container.find_all('li', recursive=False)
             if not items:
                 items = listing_container.find_all('div', recursive=False)
             
             for item in items:
                # Exclusion rules
                classes = item.get('class', [])
                if 'banner' in classes or 'ads-google' in classes:
                    continue
                    
                # Find Link: usually .advert__content-title or just the first anchor
                link_tag = item.find('a', class_='advert__content-title')
                if not link_tag:
                     link_tag = item.find('a', href=True)
                
                if not link_tag:
                   continue
                
                href = link_tag['href']
                if not href.startswith('/'):
                    # External link or unexpected format
                    # Check if it is a relative path starting with /adv/
                    if '/adv/' not in href:
                        continue
                
                full_url = f"{BASE_URL}{href}"
                # /adv/12345/ -> 12345
                parts = href.strip('/').split('/')
                if len(parts) >= 2 and parts[0] == 'adv':
                     # href is like /adv/12345_slug/
                     raw_id = parts[1]
                     # Extract just the number if it contains underscores
                     if '_' in raw_id:
                         ad_id = raw_id.split('_')[0]
                     else:
                         ad_id = raw_id
                else:
                     continue # Not an ad link
                
                # Extract basic info
                price = 0
                # Price is often in .advert__content-price
                price_tag = item.find(class_='advert__content-price')
                if not price_tag:
                    price_tag = item.find('p', class_='price') # Fallback
                
                if price_tag:
                     try:
                        # Use separator to prevent joining of multiple prices (e.g. old and new)
                        # "10 000 12 000" -> "10000|12000"
                        text = price_tag.get_text(separator='|', strip=True)
                        parts = text.split('|')
                        
                        found_prices = []
                        for part in parts:
                             # Clean: remove € and whitespace, keep digits
                             digits = ''.join(filter(str.isdigit, part))
                             if digits:
                                 found_prices.append(int(digits))
                        
                        if found_prices:
                            # If multiple prices found (e.g. discounted), current price is usually the lower one
                            # or simply the last one? 
                            # Safe bet: min price if discount, but sometimes maybe price range?
                            # Bazaraki usually shows Old (High) -> New (Low).
                            price = min(found_prices)
                            
                     except ValueError:
                        price = 0

                # Status Update
                # Attribute might be on the item itself OR on a child
                is_vip = item.has_attr('data-t-vip') or item.find(attrs={"data-t-vip": True})
                
                # For TOP, check classes on children
                is_top = item.find(class_='label-top') or item.find(class_='ribbon-top') or item.find(class_='_top')
                
                if is_vip:
                    status = 'VIP'
                elif is_top:
                    status = 'TOP'
                else:
                    status = 'Basic'
                
                ads.append({
                    'ad_id': ad_id,
                    'ad_url': full_url,
                    'price': price,
                    'status': status
                })
            
        return ads

    async def fetch_ad_details(self, url: str):
        """Scrape details from the single ad page."""
        html = await self.fetch_page(url)
        if not html:
            return None
            
        soup = BeautifulSoup(html, 'lxml')
        
        details = {}
        
        # Post date
        date_span = soup.find('span', class_='date-meta')
        if date_span:
            date_text = date_span.get_text(strip=True) # e.g. "Today 14:00"
            dt = parse_date(date_text)
            details['post_date'] = dt if dt else datetime.now()
        else:
            details['post_date'] = datetime.now()

        # 1. Try to get Brand/Model from Breadcrumbs (more reliable)
        # Format often: "Motors - Cars ... - Brand - Model"
        # Found in debug: data-breadcrumbs='Motors - Cars - Mercedes-Benz - GLA-Class'
        breadcrumb_tag = soup.find(attrs={"data-breadcrumbs": True})
        if breadcrumb_tag:
            bc_text = breadcrumb_tag['data-breadcrumbs']
            parts = [p.strip() for p in bc_text.split('-')]
            # Usually: [Category, SubCategory, Brand, Model]
            # Cars path: "Motors", "Cars", Brand, Model
            
            # Filter out empty strings if any
            parts = [p for p in parts if p]
            
            if len(parts) >= 3:
                # Heuristic: If we know it's cars category (starts with Motors)
                # Motors - Cars - Brand - Model
                if 'Motors' in parts[0]:
                    try:
                         # Brand is usually index 2 (0=Motors, 1=Cars)
                         if len(parts) > 2: details['car_brand'] = parts[2]
                         # Model is usually index 3
                         if len(parts) > 3: details['car_model'] = parts[3]
                    except:
                        pass

        # 2. Specs extraction logic (Fallback + Extra Fields)
        chars_list = soup.find('ul', class_='chars-column')
        if chars_list:
            for li in chars_list.find_all('li'):
                key_tag = li.find('span', class_='key-chars')
                val_tag = li.find(class_='value-chars')
                
                if key_tag and val_tag:
                    key = key_tag.get_text(strip=True).lower().replace(':', '')
                    val = val_tag.get_text(strip=True)
                    
                    # Only overwrite if not set by breadcrumbs (or if breadcrumbs failed)
                    if 'brand' in key and not details.get('car_brand'): details['car_brand'] = val
                    elif 'model' in key and not details.get('car_model'): details['car_model'] = val
                    elif 'year' in key: 
                        try: details['car_year'] = int(val)
                        except: details['car_year'] = 0
                    elif 'gearbox' in key: details['gearbox'] = val
                    elif 'body type' in key: details['body_type'] = val
                    elif 'fuel type' in key: details['fuel_type'] = val
                    elif 'engine size' in key: details['engine_size'] = val
                    elif 'drive type' in key or 'drive' in key: details['drive_type'] = val
                    elif 'mileage' in key:
                         try: details['mileage'] = int(val.lower().replace('km', '').replace(' ', ''))
                         except: details['mileage'] = 0
                         
        # Determine seller info
        author_div = soup.find('div', class_='author-name')
        if author_div:
             # Check for image alt first (business)
             img = author_div.find('img')
             if img and img.get('alt'):
                 details['user_name'] = img.get('alt')
                 details['is_business'] = True
             else:
                 details['user_name'] = author_div.get_text(strip=True)
                 details['is_business'] = False 
             
             # Extract User ID from data-user attribute (Most Reliable)
             if author_div.get('data-user'):
                 details['user_id'] = author_div.get('data-user')
             else:
                 # Fallback to link parsing if data-user missing
                 link = author_div.find('a', href=True) or author_div.parent.find('a', href=True)
                 if link:
                     href = link['href'].strip('/') # c/carsdeals
                     parts = href.split('/')
                     if parts:
                         details['user_id'] = parts[-1]
        else:
             details['user_name'] = "Unknown" 
             details['is_business'] = False
             
        # Check for VIP/TOP in details (fallback for list parser)
        # Sometimes list parser misses it. 
        # Look for badges in the header or title area
        if soup.find(class_='ribbon-vip') or soup.find(class_='label-vip'):
             details['ad_status_update'] = 'VIP'
        elif soup.find(class_='label-top'):
             details['ad_status_update'] = 'TOP'
        
        return details

    async def run_cycle(self, notify_callback):
        """The main scraping loop."""
        self.is_running = True
        self.stop_signal = False
        page = 1
        consecutive_basic_unchanged = 0
        
        logger.info("Starting scraper cycle...")
        
        while not self.stop_signal:
            url = f"{SEARCH_URL}?page={page}"
            logger.info(f"Fetching {url}")
            
            html = await self.fetch_page(url)
            if not html:
                logger.warning("Failed to fetch listing page, stopping cycle.")
                break
                
            ads = self.parse_listing_page(html)
            if not ads:
                logger.info("No ads found on page, end of pagination.")
                break
            
            logger.info(f"Page {page}: Found {len(ads)} ads. Processing...")
                
            for i, ad in enumerate(ads):
                if self.stop_signal:
                    break
                    
                ad_id = ad['ad_id']
                logger.info(f"Processing Ad {i+1}/{len(ads)}: ID {ad_id} | Status {ad['status']}")
                current_price = ad['price']
                ad_status = ad['status']
                
                existing_ad = await get_ad(ad_id)
                
                should_fetch_details = False
                notification_type = None # 'new', 'price', 'repost'
                
                if not existing_ad:
                    # NEW AD: Must fetch details
                    should_fetch_details = True
                    notification_type = 'new'
                    if ad_status == 'Basic':
                        consecutive_basic_unchanged = 0 
                else:
                    # EXISTING AD
                    db_price = existing_ad['current_price']
                    
                    if current_price != db_price:
                         # PRICE CHANGE
                         # Optimization based on user feedback:
                         # "you don't have to open ad page to update the price"
                         # Update directly from list data + Notify
                         await update_ad_price(ad_id, current_price)
                         
                         # Get updated object to send notification
                         updated_ad = await get_ad(ad_id)
                         updated_ad['old_price'] = db_price
                         
                         # Notify immediately (no detailed fetch)
                         if notify_callback:
                             await notify_callback('price', updated_ad)
                             
                         if ad_status == 'Basic':
                            consecutive_basic_unchanged = 0
                    else:
                        # UNCHANGED
                        await touch_ad(ad_id)
                        if ad_status == 'Basic':
                            consecutive_basic_unchanged += 1
                
                if should_fetch_details:
                    # Fetch full details (Only for NEW ads now)
                    details = await self.fetch_ad_details(ad['ad_url'])
                    if details:
                        # If status update found in details
                        if details.get('ad_status_update'):
                            ad_status = details['ad_status_update']

                        # If New
                        if notification_type == 'new':
                            full_ad_data = {
                                'ad_id': ad_id,
                                'ad_url': ad['ad_url'],
                                'first_seen': datetime.now(),
                                'post_date': details['post_date'],
                                'initial_price': current_price,
                                'current_price': current_price,
                                'car_brand': details.get('car_brand'),
                                'car_model': details.get('car_model'),
                                'car_year': details.get('car_year'),
                                'gearbox': details.get('gearbox'),
                                'body_type': details.get('body_type'),
                                'fuel_type': details.get('fuel_type'),
                                'engine_size': details.get('engine_size'),
                                'drive_type': details.get('drive_type'),
                                'mileage': details.get('mileage'),
                                'user_name': details.get('user_name'),
                                'user_id': details.get('user_id'),
                                'is_business': details.get('is_business'),
                                'ad_status': ad_status
                            }
                            await add_ad(full_ad_data)
                            if notify_callback:
                                await notify_callback('new', full_ad_data)

                    # Anti-ban delay ONLY if we fetched a page
                    await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
            
            # Check stop condition
            if consecutive_basic_unchanged >= MAX_CONSECUTIVE_UNCHANGED:
                logger.info(f"Stopping condition met: {consecutive_basic_unchanged} consecutive basic ads unchanged.")
                break
            
            # Delay before fetching the next page
            await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
            
            page += 1
            # Safety limit for pages (optional)
            if page > MAX_PAGES_LIMIT:
                break
        
        self.is_running = False
        logger.info("Cycle finished.")
