import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Telegram Config
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
if ADMIN_ID:
    ADMIN_ID = int(ADMIN_ID)
CHANNEL_ID = os.getenv("CHANNEL_ID")
if CHANNEL_ID:
    CHANNEL_ID = int(CHANNEL_ID)

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "insightor.db"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

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
