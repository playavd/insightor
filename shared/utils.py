import logging
import json
import html
from datetime import datetime, date
from typing import TypedDict, Any, Dict, List, Optional, Union

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

def is_match(ad: Union[AdData, Dict[str, Any]], filters: dict) -> bool:
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

def get_status_display(status: str) -> str:
    """Helper to get formatted status string."""
    status = status or 'Basic'
    if status == 'VIP': return " 🌟 VIP"
    elif status == 'TOP': return " 🔥 TOP"
    elif status == 'VIP+TOP': return " 🌟 VIP 🔥 TOP"
    return ""

def format_ad_message(ad_data: Union[AdData, Dict[str, Any]], notification_type: str = 'new', history: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
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
        ad_id_tag = f"#ad{ad_data.get('ad_id', '')}"
        
        if notification_type == 'new':
            safe_title = html.escape(title)
            safe_fuel = html.escape(fuel)
            safe_gear = html.escape(gear)
            safe_seller = html.escape(seller_info)
            msg_text = (
                f"{status_prefix} <a href=\"{ad_data['ad_url']}\">{safe_title}</a> {ad_id_tag}\n"
                f"💰 <b>{ad_data['current_price']} €</b>  ⏱️ {mileage_str}\n"
                f"⛽ {safe_fuel}  ⚙️ {safe_gear}  🧩 {engine}\n"
                f"👤 {safe_seller}"
            )
        elif notification_type == 'status':
            safe_title = html.escape(title)
            old = ad_data.get('old_status', 'Basic')
            msg_text = (
                f"🆙 <b>Status Update</b> ({old} ➜ {status}) {ad_id_tag}\n"
                f"<a href=\"{ad_data['ad_url']}\">{safe_title}</a>\n"
                f"💰 {ad_data['current_price']} €"
            )
        elif notification_type == 'repost':
            safe_brand = html.escape(brand)
            safe_model = html.escape(model)
            msg_text = (
                f"🔄 <b>Ad Reposted!</b> {ad_id_tag}\n"
                f"The ad was bumped to the top.\n"
                f"🔗 <a href=\"{ad_data['ad_url']}\">{safe_brand} {safe_model}</a>"
            )

        elif notification_type == 'detailed':
            safe_title = html.escape(title)
            safe_fuel = html.escape(fuel)
            safe_gear = html.escape(gear)
            safe_seller = html.escape(seller)
            
            # Status visualization
            status_display = get_status_display(status)

            # Init Price
            init_price = ad_data.get('initial_price', ad_data.get('current_price'))
            
            # First Seen
            first_seen = ad_data.get('first_seen', 'N/A')
            if isinstance(first_seen, datetime):
                first_seen_str = first_seen.strftime("%Y-%m-%d %H:%M")
            elif isinstance(first_seen, str):
                try: 
                    dt = datetime.fromisoformat(first_seen)
                    first_seen_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    first_seen_str = str(first_seen)
            else:
                first_seen_str = str(first_seen)

            # Seller info
            seller_str = f"👤 {safe_seller}"
            if seller_id:
                seller_str += f" #{seller_id}"
            
            if ad_data.get('is_business'):
                seller_str += " (Business)"
            else:
                seller_str += " (Private)"

            msg_text = (
                f"ℹ️ <b>Details for Ad #ad{ad_data['ad_id']}</b>\n"
                f"👀 First seen: {first_seen_str}\n\n"
                f"🚗 <a href=\"{ad_data['ad_url']}\">{safe_title}</a>{status_display}\n"
                f"💰 First seen price {init_price} €  ⏱️ {mileage_str}\n"
                f"⛽ {safe_fuel}  ⚙️ {safe_gear}  🧩 {engine}\n"
                f"{seller_str}\n\n"
            )
            
            if not history:
                 msg_text += "No tracked changes yet."
            else:
                 msg_text += "\n<b>History:</b>\n"
                 # Format History: DD MMM HH:MM Event
                 for entry in history[:50]:
                     ts = entry['timestamp']
                     if isinstance(ts, str):
                         try:
                             if '.' in ts: ts = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S.%f')
                             else: ts = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
                         except:
                             pass
                     if not isinstance(ts, datetime):
                         ts_str = "?? ???"
                     else:
                         ts_str = ts.strftime("%d %b %H:%M")
 
                     ctype = entry['change_type']
                     old = entry['old_value']
                     new = entry['new_value']
                     
                     line = ""
                     if ctype == 'first_seen':
                         line = "First seen"
                     elif ctype == 'price_change' or ctype == 'price':
                         line = f"Price {old} > {new}"
                     elif ctype == 'status_change' or ctype == 'status':
                         line = f"{old} > {new}"
                     elif ctype == 'repost':
                         line = "Ad was reposted"
                     elif ctype == 'active':
                         if str(new).lower() == 'false': line = "⛔ Deactivated"
                         else: line = "✅ Activated"
                     else:
                         line = f"{ctype} changed"
                     
                     msg_text += f"{ts_str} {line}\n"

        return msg_text
    except Exception as e:
        logger.error(f"Error formatting match msg: {e}")
        return None
