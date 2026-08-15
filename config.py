# ==============================================================================
# config.py — Adika Marketplace configuration
# ==============================================================================
import os
import logging

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "0")
DATABASE_URL = (os.environ.get("DATABASE_URL", "") or "").strip().strip('"').strip("'")
RENDER_EXTERNAL_HOSTNAME = (os.environ.get("RENDER_EXTERNAL_HOSTNAME", "") or "").strip()
PORT = int(os.environ.get("PORT", "8080"))
DB_FILE = os.environ.get("DB_FILE", "adika_marketplace.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if RENDER_EXTERNAL_HOSTNAME:
    WEBAPP_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}"
else:
    WEBAPP_URL = os.environ.get("WEBAPP_URL", "http://127.0.0.1:8080")

if not BOT_TOKEN:
    # Allow import for tooling; main() will re-check
    pass

try:
    ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 0
except ValueError:
    ADMIN_CHAT_ID_INT = 0

ADMIN_IDS = {ADMIN_CHAT_ID_INT} if ADMIN_CHAT_ID_INT else set()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("adika")

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
CONDITIONS = ["🆕 አዲስ", "✅ ያገለገለ", "🔧 ጥገና የሚፈልግ"]


# ==============================================================================
# 6. HELPER FUNCTIONS (SINGLE DEFINITIONS ONLY)
# ==============================================================================


# Broker registration options
BROKER_CATEGORIES = ["🚗 መኪና", "🏠 ቤትና ቦታ", "📦 አጠቃላይ ደላላ"]
BROKER_REG_SUBCITIES = ["ቦሌ", "አራዳ", "ቂርቆስ", "አዳማ", "አዲስ አበባ (ሙሉ)"]
