import logging
import json
from typing import TypedDict, Any

logger = logging.getLogger(__name__)

class AdData(TypedDict):
    """Type definition for Ad Data, mirroring the DB schema structure."""
    ad_id: str
    ad_url: str
    first_seen: Any # datetime
    post_date: Any | None # datetime
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

def is_match(ad: AdData | dict[str, Any], filters: dict) -> bool:
    """
    Check if ad matches alert filters.
    Centralized matching logic used by both Scraper notifications and User Alerts.
    """
    try:
        # Brand (Case Insensitive)
        if filters.get('brand'):
            f_brand = filters['brand'].lower()
            a_brand = (ad.get('car_brand') or '').lower()
            if f_brand != a_brand: return False
        
        # Model (Case Insensitive, supports list)
        if filters.get('model'):
             ad_model = (ad.get('car_model') or '').lower()
             target_models = filters['model']
             
             if isinstance(target_models, list):
                 # Check against lowercased list
                 targets_lower = [str(x).lower() for x in target_models]
                 if ad_model not in targets_lower: return False
             else:
                 if ad_model != str(target_models).lower(): return False

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
             try: val = float(ad['engine_size'])
             except: return False
             if val < filters['engine_min']: return False
        if filters.get('engine_max'):
             if not ad.get('engine_size'): return False
             try: val = float(ad['engine_size'])
             except: return False
             if val > filters['engine_max']: return False

        # Others (Exact match, Case Insensitive for safety)
        # Note: 'car_color' filter key is sometimes stored as 'color'
        for field in ['gearbox', 'fuel_type', 'drive_type', 'body_type', 'car_color', 'ad_status']:
            filter_key = field if field != 'car_color' else 'color'
            f_val = filters.get(filter_key)
            if f_val:
                a_val = ad.get(field)
                if not a_val: return False # Filter exists but ad property matches nothing
                
                # Special logic for ad_status = VIP+TOP
                if field == 'ad_status' and str(f_val).upper() == "VIP+TOP":
                    if str(a_val).upper() not in ["VIP", "TOP"]: return False
                else:
                    if str(f_val).lower() != str(a_val).lower(): return False

        # Business
        if filters.get('is_business') is not None and filters['is_business'] != ad.get('is_business'): return False
        
        # User ID
        if filters.get('target_user_id'):
            target = str(filters['target_user_id']).strip().lower()
            ad_user = str(ad.get('user_id', '')).strip().lower()
            if target != ad_user: return False

        return True
    except Exception as e:
        logger.error(f"Error matching ad: {e}")
        return False

def format_ad_message(ad_data: AdData | dict[str, Any], notification_type: str = 'new') -> str | None:
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
        if isinstance(engine, int) or (isinstance(engine, str) and engine.isdigit()): 
            engine = f"{engine} cc"

        seller = ad_data.get('user_name', 'Unknown')
        status = ad_data.get('ad_status', 'Basic')
        
        status_prefix = "🚗"
        if status == 'VIP': status_prefix = "🌟 VIP"
        elif status == 'TOP': status_prefix = "🔥 TOP"
        
        seller_id = ad_data.get('user_id', '')
        seller_info = seller
        if seller_id:
            # Hash tag for clickable ID
            seller_info += f" (#id{seller_id})"

        msg_text = ""
        if notification_type == 'new':
            import html
            safe_title = html.escape(title)
            safe_fuel = html.escape(fuel)
            safe_gear = html.escape(gear)
            safe_seller = html.escape(seller_info)
            msg_text = (
                f"{status_prefix} <a href=\"{ad_data['ad_url']}\">{safe_title}</a>\n"
                f"💰 <b>{ad_data['current_price']} €</b>  ⏱️ {mileage_str}\n"
                f"⛽ {safe_fuel}  ⚙️ {safe_gear}  🧩 {engine}\n"
                f"👤 {safe_seller}"
            )
        elif notification_type == 'status':
            import html
            safe_title = html.escape(title)
            old = ad_data.get('old_status', 'Basic')
            msg_text = (
                f"🆙 <b>Status Update</b> ({old} ➜ {status})\n"
                f"<a href=\"{ad_data['ad_url']}\">{safe_title}</a>\n"
                f"💰 {ad_data['current_price']} €"
            )
        elif notification_type == 'repost':
            import html
            safe_brand = html.escape(brand)
            safe_model = html.escape(model)
            msg_text = (
                f"🔄 <b>Ad Reposted!</b>\n"
                f"The ad was bumped to the top.\n"
                f"🔗 <a href=\"{ad_data['ad_url']}\">{safe_brand} {safe_model}</a>"
            )
        return msg_text
    except Exception as e:
        logger.error(f"Error formatting match msg: {e}")
        return None
