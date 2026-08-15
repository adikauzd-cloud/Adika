# ==============================================================================
# config.py — Environment & constants for Adika Marketplace
# ==============================================================================
import os
import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Set, Dict, Any

# ---------- Environment ----------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip().strip('"').strip("'")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "0")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "adika-vrkk.onrender.com")
PORT = int(os.getenv("PORT", "8080"))
DB_FILE = os.getenv("DB_FILE", "adika_marketplace.db")
USE_WEBHOOK = os.getenv("USE_WEBHOOK", "false").lower() == "true"
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")  # production, staging, development

# Fix PostgreSQL URL
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ---------- Admin Validation ----------
try:
    ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 0
except ValueError:
    ADMIN_CHAT_ID_INT = 0
    print(f"⚠️  Invalid ADMIN_CHAT_ID: {ADMIN_CHAT_ID}. Set to 0.")

ADMIN_IDS: Set[int] = {ADMIN_CHAT_ID_INT} if ADMIN_CHAT_ID_INT else set()

# ---------- Logging Configuration ----------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

# Configure root logger
logger = logging.getLogger("adika")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(console_handler)

# File handler with rotation
try:
    file_handler = RotatingFileHandler(
        "logs/adika.log",
        maxBytes=10_485_760,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(file_handler)
except Exception as e:
    logger.warning(f"Could not setup file logging: {e}")

# ---------- UI Constants ----------
TEXT_PAGE_SIZE = 4
VIEW_INCREMENT = 1
VIEW_BASELINE_MIN = 35
VIEW_BASELINE_MAX = 90
MAX_PHOTOS = 5
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_DESCRIPTION_LENGTH = 2000
CACHE_TTL = 300  # 5 minutes

MAIN_KEYBOARD = [
    ["🔍 ለመግዛት / ለመከራየት", "📢 ለመሸጥ / ለማከራየት"],
    ["🛒 የገበያ ቦታ", "📋 የፈላጊዎች ጥያቄዎች"],
    ["👥 የደላሎች መድረክ", "✍️ የደላላ/አቅራቢ መመዝገቢያ"],
    ["⚙️ የማሳወቂያ ማስተካከያ", "📞 እገዛ / Support"],
    ["🏠 ዋና ገጽ"],
]

SUB_CITIES = [
    "ቦሌ", "CMC", "አራዳ", "22/ካዛንችስ", "ጀሞ",
    "የካ", "ልደታ", "ቂርቆስ", "አዲስ ከተማ", "ንፋስ ስልክ ላፍቶ",
    "ኮልፌ ቀራኒዮ", "አቃቂ ቃሊቲ", "ጉሌሌ",
]

SPECIALTIES = ["🚗 መኪና", "🏠 ቤት/ቦታ", "🔄 ሁለቱም"]

CAR_SUB_CATEGORIES = ["🚗 የቤት መኪና", "🚚 የሥራ መኪና", "🚜 ከባድ ተሽከርካሪ/ማሽን"]
HOUSE_TYPES = ["🏡 ቪላ", "🏢 አፓርታማ", "🏢 ኮንዶሚኒየም", "🏢 ሪል እስቴት", "🏞️ መሬት/ቦታ"]
PROPERTY_TYPES = ["🏠 መኖሪያ ቤት", "🏢 የሥራ ቦታ / ንግድ"]
FUEL_TYPES = ["⛽ ቤንዚን", "🛢️ ናፍጣ", "⚡ ኤሌክትሪክ", "🔋 ሀይብሪድ"]
TRANSMISSION_TYPES = ["🕹️ ማንዋል", "🤖 ኦቶማቲክ"]
CONDITIONS = ["🆕 አዲስ", "✅ ያገለገለ", "🔧 ጥገና የሚፍልግ"]

SUPPORT_ADMIN_URL = "https://t.me/AdikaSupport"
SUPPORT_ADMIN_HANDLE = "@AdikaSupport"

# ---------- Validation Constants ----------
PHONE_PATTERNS = [
    r"^(09|07|01)\d{8}$",
    r"^(9|7)\d{8}$",
    r"^251(9|7)\d{8}$",
]
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

# ---------- Cache Settings ----------
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "")

# ---------- Validate Required Environment ----------
def validate_environment() -> None:
    """Validate that all required environment variables are set."""
    required = ['BOT_TOKEN']
    if ENVIRONMENT == "production":
        required.append('ADMIN_CHAT_ID')
    
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        raise RuntimeError(f"❌ Missing required env vars: {', '.join(missing)}")
    
    if not BOT_TOKEN:
        raise RuntimeError("❌ BOT_TOKEN environment variable is required")
    
    if DATABASE_URL:
        logger.info("✅ Using PostgreSQL database")
    else:
        logger.info(f"✅ Using SQLite database: {DB_FILE}")
    
    logger.info(f"✅ Environment: {ENVIRONMENT}")
    logger.info(f"✅ Admin ID: {ADMIN_CHAT_ID_INT}")

# Validate on import if not in test mode
if not os.getenv("TESTING"):
    try:
        validate_environment()
    except RuntimeError as e:
        logger.error(str(e))
        if ENVIRONMENT == "production":
            sys.exit(1)
