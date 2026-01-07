from pathlib import Path

# Alert Config
MAX_ALERTS_BASIC = 5

# URL Config
BASE_URL = "https://www.bazaraki.com"
SEARCH_URL = "https://www.bazaraki.com/car-motorbikes-boats-and-parts/cars-trucks-and-vans/"

# Scraper Config
REQUEST_DELAY_MIN = 2
REQUEST_DELAY_MAX = 5
MAX_CONSECUTIVE_UNCHANGED = 10  # Stop scraping after seeing this many unchanged basic ads
MAX_PAGES_LIMIT = 20 # Safety limit (20 pages * 60 ads = 1200 ads)
USER_AGENT_LIST = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

# Database Path (Used by database.py, but depends on BASE_DIR from config... 
# actually database.py imports DATABASE_PATH. 
# We should probably keep DATABASE_PATH in config.py if it depends on BASE_DIR 
# OR move BASE_DIR here. but BASE_DIR is env/setup related. 
# Let's keep paths in config.py for now as they are "setup" configuration.)
