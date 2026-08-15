# ==============================================================================
# config.py — Adika Marketplace configuration
# ==============================================================================
import os
import logging
import re
import logging.handlers

# ==============================================================================
# 1. ENVIRONMENT VARIABLES WITH VALIDATION
# ==============================================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "0")
DATABASE_URL = (os.environ.get("DATABASE_URL", "") or "").strip()
RENDER_EXTERNAL_HOSTNAME = (os.environ.get("RENDER_EXTERNAL_HOSTNAME", "") or "").strip()
PORT = int(os.environ.get("PORT", "8080"))
DB_FILE = os.environ.get("DB_FILE", "adika_marketplace.db")
LOG_FILE = os.environ.get("LOG_FILE", "adika.log")

# Clean DATABASE_URL - handle quotes properly
if DATABASE_URL:
    if DATABASE_URL.startswith('"') and DATABASE_URL.endswith('"'):
        DATABASE_URL = DATABASE_URL[1:-1]
    elif DATABASE_URL.startswith("'") and DATABASE_URL.endswith("'"):
        DATABASE_URL = DATABASE_URL[1:-1]

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if RENDER_EXTERNAL_HOSTNAME:
    WEBAPP_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}"
else:
    WEBAPP_URL = os.environ.get("WEBAPP_URL", "http://127.0.0.1:8080")

try:
    ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 0
except ValueError:
    ADMIN_CHAT_ID_INT = 0

ADMIN_IDS = {ADMIN_CHAT_ID_INT} if ADMIN_CHAT_ID_INT else set()

# ==============================================================================
# 2. LOGGING SETUP
# ==============================================================================

def setup_logging():
    """Setup logging with file rotation."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    logger = logging.getLogger("adika")
    
    # Add file handler with rotation
    try:
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=10*1024*1024, backupCount=5
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))
        logger.addHandler(handler)
    except Exception:
        pass  # File logging is optional
    
    return logger

logger = setup_logging()

# ==============================================================================
# 3. CONFIGURATION VALIDATION
# ==============================================================================

def validate_config():
    """Validate required configuration."""
    errors = []
    
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN is required")
    
    if not DATABASE_URL and not DB_FILE:
        errors.append("DATABASE_URL or DB_FILE is required")
    
    if ADMIN_CHAT_ID_INT == 0:
        logger.warning("⚠️ ADMIN_CHAT_ID not set - admin features will be limited")
    
    if errors:
        raise ValueError(f"Configuration errors: {', '.join(errors)}")
    
    logger.info("✅ Configuration validated successfully")

# ==============================================================================
# 4. CONSTANTS
# ==============================================================================

TEXT_PAGE_SIZE = 4
VIEW_INCREMENT = 1
VIEW_BASELINE_MIN = 35
VIEW_BASELINE_MAX = 90
MAX_IMAGE_BYTES = 5 * 1024 * 1024

SUPPORT_ADMIN_URL = "https://t.me/AdikaSupport"
SUPPORT_ADMIN_HANDLE = "@AdikaSupport"

MAIN_KEYBOARD = [
   ["🔍 ለመግዛት / ለመከራየት", "📢 ለመሸጥ / ለማከራየት"],
   ["🛒 የገበያ ቦታ", "📋 የፈላጊዎች ጥያቄዎች"],
   ["👥 የደላሎች መድረክ", "✍️ የደላላ/አቅራቢ መመዝገቢያ"],
   ["⚙️ የማሳወቂያ ማስተካከያ", "📞 እገዛ / Support"],
   ["🏠 ዋና ገጽ"]
]

SUB_CITIES = [
   "ቦሌ", "የካ", "አራዳ", "ልደታ",
   "ቂርቆስ", "አዲስ ከተማ", "ንፋስ ስልክ ላፍቶ",
   "ኮልፌ ቀራኒዮ", "አቃቂ ቃሊቲ", "ጉሌሌ", "ላምበርት/የካ"
]

CAR_SUB_CATEGORIES = ["🚗 የቤት መኪና", "🚚 የሥራ መኪና", "🚜 ከባድ ተሽከርካሪ/ማሽን"]
HOUSE_TYPES = ["🏡 ቪላ", "🏢 አፓርታማ", "🏢 ኮንዶሚኒየም", "🏢 ሪል እስቴት", "🏞️ መሬት/ቦታ"]
PROPERTY_TYPES = ["🏠 መኖሪያ ቤት", "🏢 የሥራ ቦታ / ንግድ"]
FUEL_TYPES = ["⛽ ቤንዚን", "🛢️ ናፍጣ", "⚡ ኤሌክትሪክ", "🔋 ሀይብሪድ"]
TRANSMISSION_TYPES = ["🕹️ ማንዋል", "🤖 ኦቶማቲክ"]
CONDITIONS = ["🆕 አዲስ", "✅ ያገለገለ", "🔧 ጥገና የሚፍልግ"]

BROKER_CATEGORIES = ["🚗 መኪና", "🏠 ቤትና ቦታ", "📦 አጠቃላይ ደላላ"]
BROKER_REG_SUBCITIES = [
    "ቦሌ", "አራዳ", "ቂርቆስ", "ልደታ", "አዲስ ከተማ",
    "ጉሌሌ", "የካ", "ንፋስ ስልክ", "አቃቂ ቃሊቲ", "ኮልፌ ቀራኒዮ",
    "አዲስ አበባ (ሙሉ)",
]

# ==============================================================================
# 5. HELPER FUNCTIONS
# ==============================================================================

def sanitize_input(text: str, max_len: int = 1000) -> str:
    """Sanitize user input to prevent XSS and injection."""
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r'<[^>]*>', '', text)
    # Remove potentially dangerous characters
    text = re.sub(r'[;\'"\\]', '', text)
    return text[:max_len].strip()

def validate_column_name(name: str) -> bool:
    """Ensure column name is safe for SQL queries."""
    return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name))
