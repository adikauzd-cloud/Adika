# ==============================================================================
# config.py — Environment & constants for Adika Marketplace
# ==============================================================================
import os
import logging

# ---------- Environment ----------
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip().strip('"').strip("'")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "0")
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
PORT = int(os.getenv("PORT", "8080"))
DB_FILE = os.getenv("DB_FILE", "adika_marketplace.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Dynamic Web App base URL (Render) with local fallback
if RENDER_EXTERNAL_HOSTNAME:
    WEBAPP_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}"
else:
    WEBAPP_URL = os.getenv("WEBAPP_URL", "http://127.0.0.1:8080")

try:
    ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 0
except ValueError:
    ADMIN_CHAT_ID_INT = 0

ADMIN_IDS = {ADMIN_CHAT_ID_INT} if ADMIN_CHAT_ID_INT else set()

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("adika")

# ---------- UI constants ----------
TEXT_PAGE_SIZE = 4
VIEW_INCREMENT = 1
VIEW_BASELINE_MIN = 35
VIEW_BASELINE_MAX = 90

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
CONDITIONS = ["🆕 አዲስ", "✅ ያገለገለ", "🔧 ጥገና የሚፈልግ"]

SUPPORT_ADMIN_URL = "https://t.me/AdikaSupport"
SUPPORT_ADMIN_HANDLE = "@AdikaSupport"

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB
