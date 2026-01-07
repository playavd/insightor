import asyncio
import cloudscraper
import logging
import random
from bs4 import BeautifulSoup
from datetime import datetime, date
from typing import Callable, Any

from shared.constants import (
    BASE_URL, SEARCH_URL, REQUEST_DELAY_MIN, REQUEST_DELAY_MAX, 
    MAX_CONSECUTIVE_UNCHANGED, MAX_PAGES_LIMIT, USER_AGENT_LIST
)
from shared.database import (
    add_ad, get_ad, update_ad_price, update_ad_post_date, touch_ad, 
    update_ad_status, update_ad_color
)
from shared.utils import AdData
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

    def get_random_user_agent(self) -> str:
        return random.choice(USER_AGENT_LIST)

    async def fetch_page(self, url: str) -> str | None:
        """Fetch a page using cloudscraper in a thread."""
        headers = {
            "User-Agent": self.get_random_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
        }
        
        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(None, lambda: self.scraper.get(url, headers=headers))
            
            if response.status_code == 403 or (response.status_code != 200 and ("challenge" in response.text.lower() or "cloudflare" in response.text.lower())):
                logger.error(f"CRITICAL: Cloudflare Block or 403 Forbidden. Status: {response.status_code}")
                return None
            
            if "<title>Just a moment...</title>" in response.text:
                 logger.error(f"CRITICAL: Cloudflare Challenge Page Detected (Status 200)")
                 return None

            return response.text
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    def parse_listing_page(self, html: str) -> list[dict[str, Any]]:
        """Parse the listing page and extract ad cards."""
        soup = BeautifulSoup(html, 'lxml')
        containers = soup.find_all(class_='list-simple__output')
        
        if not containers:
            return []
        
        ads = []
        for container in containers:
             items = container.find_all('li', recursive=False) or container.find_all('div', recursive=False)
             
             for item in items:
                classes = item.get('class', [])
                if 'banner' in classes or 'ads-google' in classes:
                    continue
                    
                link_tag = item.find('a', class_='advert__content-title') or item.find('a', href=True)
                if not link_tag:
                   continue
                
                href = link_tag['href']
                if not href.startswith('/') or '/adv/' not in href:
                    continue
                
                # Extract ID
                try:
                    # /adv/123456_slug/ -> 123456
                    ad_id = href.strip('/').split('/')[1].split('_')[0]
                except IndexError:
                    continue

                full_url = f"{BASE_URL}{href}"
                
                # Extract Price
                price = 0
                price_tag = item.find(class_='advert__content-price') or item.find('p', class_='price')
                if price_tag:
                     try:
                        text = price_tag.get_text(separator='|', strip=True)
                        # Extract all numbers from "10 000 | 12 000"
                        found_prices = [int(''.join(filter(str.isdigit, p))) for p in text.split('|') if any(c.isdigit() for c in p)]
                        if found_prices:
                            price = min(found_prices)
                     except ValueError:
                        pass

                # Status
                is_vip = item.has_attr('data-t-vip') or item.find(attrs={"data-t-vip": True}) or item.find(class_='ribbon-vip')
                is_top = item.find(class_='label-top') or item.find(class_='ribbon-top') or item.find(class_='_top')
                
                status = 'VIP' if is_vip else 'TOP' if is_top else 'Basic'
                
                # Date
                date_tag = item.find(class_='list-simple__time')
                post_date = parse_date(date_tag.get_text(strip=True)) if date_tag else None
                
                if not post_date:
                    # Date missing on listing page, will handle in run_cycle
                    pass

                ads.append({
                    'ad_id': ad_id,
                    'ad_url': full_url,
                    'price': price,
                    'status': status,
                    'post_date': post_date
                })
            
        return ads

    async def fetch_ad_details(self, url: str) -> dict[str, Any] | None:
        """Scrape details from the single ad page."""
        html = await self.fetch_page(url)
        if not html:
            return None
            
        soup = BeautifulSoup(html, 'lxml')
        details: dict[str, Any] = {}
        
        # Post date
        date_span = soup.find('span', class_='date-meta')
        if date_span:
            details['post_date'] = parse_date(date_span.get_text(strip=True))
        
        if 'post_date' not in details or not details['post_date']:
             # DO NOT use datetime.now() as it triggers false repost detection
             details['post_date'] = None

        # Breadcrumbs for Brand/Model
        breadcrumb_tag = soup.find(attrs={"data-breadcrumbs": True})
        if breadcrumb_tag:
            # "Motors - Cars - Brand - Model"
            parts = [p.strip() for p in breadcrumb_tag['data-breadcrumbs'].split(' - ') if p.strip()]
            if len(parts) >= 3 and 'Motors' in parts[0]:
                 if len(parts) > 2: details['car_brand'] = parts[2]
                 if len(parts) > 3: details['car_model'] = parts[3]
        
        # Fallback: Extract from Title or H1 if breadcrumbs fail or are incomplete
        if not details.get('car_brand'):
             # Title format often: "Toyota Yaris Cross 1.5L 2024 for sale in ..."
             page_title = soup.title.get_text(strip=True) if soup.title else ""
             h1_text = soup.find('h1', class_='page-title').get_text(strip=True) if soup.find('h1', class_='page-title') else ""
             
             # Combined check
             check_text = h1_text or page_title
             if check_text:
                 # We can't easily guess the brand without a list of known brands, 
                 # but we can try to grab the first word if it looks like a brand.
                 # Better approach: Check if known brands are in the title.
                 # However, we don't have the full DB of brands here easily without query.
                 # Let's try to parse the first word of the H1 if it's not "Car" or "For Sale".
                 words = check_text.split()
                 if words and words[0].isalpha():
                      details['car_brand'] = words[0] # Aggressive fallback, but better than Unknown
                      if len(words) > 1:
                          details['car_model'] = words[1]


        # Specs
        chars_list = soup.find('ul', class_='chars-column')
        if chars_list:
            for li in chars_list.find_all('li'):
                key_tag = li.find('span', class_='key-chars')
                val_tag = li.find(class_='value-chars')
                
                if key_tag and val_tag:
                    key = key_tag.get_text(strip=True).lower().replace(':', '')
                    val = val_tag.get_text(strip=True)
                    
                    if 'brand' in key and not details.get('car_brand'): details['car_brand'] = val
                    elif 'model' in key and not details.get('car_model'): details['car_model'] = val
                    elif 'year' in key: 
                        try: details['car_year'] = int(val)
                        except: details['car_year'] = 0
                    elif 'gearbox' in key: details['gearbox'] = val
                    elif 'body type' in key: details['body_type'] = val
                    elif 'fuel type' in key: details['fuel_type'] = val
                    elif 'engine size' in key: 
                        # Parse Engine Size: "2.0L" -> 2000, "600cc" -> 600
                        try:
                            clean_val = val.lower().replace('l', '').replace('cc', '').replace(',', '.').strip()
                            if 'electric' in clean_val:
                                details['engine_size'] = 0
                            else:
                                size = float(clean_val)
                                if size < 10: # Assumed to be Liters (e.g. 2.0)
                                    details['engine_size'] = int(size * 1000)
                                else: # Assumed to be cc (e.g. 600, 1500)
                                    details['engine_size'] = int(size)
                        except (ValueError, TypeError):
                            details['engine_size'] = 0
                    elif 'drive' in key: details['drive_type'] = val
                    elif 'color' in key or 'colour' in key: details['car_color'] = val
                    elif 'mileage' in key:
                         try: details['mileage'] = int(val.lower().replace('km', '').replace(' ', ''))
                         except: details['mileage'] = 0
                         
        # Seller Info
        author_div = soup.find('div', class_='author-name')
        if author_div:
             img = author_div.find('img')
             if img and img.get('alt'):
                 details['user_name'] = img.get('alt')
                 details['is_business'] = False # Default assumption, specific scraping might refine
             else:
                 details['user_name'] = author_div.get_text(strip=True)
                 details['is_business'] = False 
             
             if author_div.get('data-user'):
                 details['user_id'] = author_div.get('data-user')
             else:
                 link = author_div.find('a', href=True) or author_div.parent.find('a', href=True)
                 if link:
                     details['user_id'] = link['href'].strip('/').split('/')[-1]
        
        # IMPROVED Business Check
        # 1. Check for "distinctions" badge (often used for Pro/Business sellers)
        if soup.find(class_='author-distinctions__item') or soup.find(class_='verification-badge'):
             details['is_business'] = True
             logger.info(f"Detected Business via Badge for {url}")
        
        # 2. (REMOVED) Check for "Show all ads" link 
        # Reason: Private sellers with multiple items also have this link.
        # if soup.find('a', string=lambda t: t and "ads" in t.lower() and "seller" in t.lower()):
        #      details['is_business'] = True
        #      logger.info(f"Detected Business via 'Show all ads' link for {url}")

        # 3. Check for dedicated "Shop" link
        if soup.find('a', href=lambda h: h and '/shop/' in h):
             details['is_business'] = True
             logger.info(f"Detected Business via Shop Link for {url}")
             
        # 4. Reliable Check: "js-show-popup-contact-business"
        # This class appears on the contact button for business accounts
        if soup.find(class_='js-show-popup-contact-business'):
             details['is_business'] = True
             logger.info(f"Detected Business via Contact Popup Class for {url}")
        
        # Check Status in details
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
        new_ads_count = 0
        
        logger.info("Starting scraper cycle...")
        
        try:
            while not self.stop_signal:
                url = f"{SEARCH_URL}?page={page}"
                logger.debug(f"Fetching {url}")
                
                html = await self.fetch_page(url)
                if not html:
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
                    current_price = ad['price']
                    ad_status = ad['status']
                    
                    existing_ad = await get_ad(ad_id)
                    should_fetch_details = False
                    notification_type = None
                    
                    if not existing_ad:
                        # NEW AD: Must fetch details
                        should_fetch_details = True
                        notification_type = 'new'
                        if ad_status == 'Basic':
                            consecutive_basic_unchanged = 0 
                    else:
                        # EXISTING AD
                        db_price = existing_ad['current_price']
                        db_status = existing_ad['ad_status']
                        db_post_date = existing_ad['post_date']
                        if isinstance(db_post_date, str):
                             try: db_post_date = parse_date(db_post_date)
                             except: pass

                        # 1. PRICE CHECK
                        if current_price != db_price:
                             await update_ad_price(ad_id, current_price)
                             consecutive_basic_unchanged = 0
                              
                        # 2. STATUS CHECK
                        if ad_status != db_status:
                             await update_ad_status(ad_id, ad_status)
                             updated_ad = await get_ad(ad_id)
                             updated_ad['old_status'] = db_status
                             if notify_callback:
                                 await notify_callback('status', updated_ad)
                             consecutive_basic_unchanged = 0

                        # 3. REPOST CHECK (Only if date is visible)
                        is_repost = False
                        current_post_date = ad.get('post_date')
                        
                        if current_post_date and db_post_date:
                            # Ensure we have datetime objects
                            # (Already parsed in parse_listing_page and get_ad parsing)
                            try:
                                if current_post_date > db_post_date:
                                    is_repost = True
                            except TypeError: pass
                        
                        if is_repost:
                             await update_ad_post_date(ad_id, current_post_date)
                             updated_ad = await get_ad(ad_id)
                             if notify_callback:
                                 await notify_callback('repost', updated_ad)
                             consecutive_basic_unchanged = 0
                        
                        # 4. UNCHANGED
                        if current_price == db_price and ad_status == db_status and not is_repost:
                            await touch_ad(ad_id)
                            if ad_status == 'Basic':
                                consecutive_basic_unchanged += 1
                    
                    
                    if should_fetch_details:
                        details = await self.fetch_ad_details(ad['ad_url'])
                        if details:
                            if details.get('ad_status_update'):
                                ad_status = details['ad_status_update']

                            if notification_type == 'new':
                                full_ad_data: AdData = {
                                    'ad_id': ad_id,
                                    'ad_url': ad['ad_url'],
                                    'first_seen': datetime.now(),
                                    'post_date': details.get('post_date'),
                                    'initial_price': current_price,
                                    'current_price': current_price,
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
                                    'ad_status': ad_status
                                }
                                await add_ad(full_ad_data)
                                new_ads_count += 1
                                if notify_callback:
                                    await notify_callback('new', full_ad_data)

                        # Anti-ban delay ONLY if we fetched a page
                        await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
                
                # Check stop condition
                if consecutive_basic_unchanged >= MAX_CONSECUTIVE_UNCHANGED:
                    logger.info(f"Stopping condition met: {consecutive_basic_unchanged} consecutive basic ads unchanged.")
                    break
                
                await asyncio.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))
                page += 1
                if page > MAX_PAGES_LIMIT:
                    break
        finally:
            self.is_running = False
        
        return new_ads_count

    # rescan_colors moved to maintenance.py
