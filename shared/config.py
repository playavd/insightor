import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Telegram Config
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
if not ADMIN_ID:
    raise ValueError("ADMIN_ID not found in .env file")
ADMIN_ID = int(ADMIN_ID)
CHANNEL_ID = os.getenv("CHANNEL_ID")
if CHANNEL_ID:
    CHANNEL_ID = int(CHANNEL_ID)

USER_BOT_TOKEN = os.getenv("USER_BOT_TOKEN")

# Paths
# Base dir is the project root (parent of 'shared')
BASE_DIR = Path(__file__).resolve().parent.parent
# Database and logs stay in root or logs/
DATABASE_PATH = BASE_DIR / "insightor.db"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
