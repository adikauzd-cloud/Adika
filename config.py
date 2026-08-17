# ==============================================================================
# config.py — Adika Marketplace configuration
# ==============================================================================
import os
import logging

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("adika")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "0")

# ---------------------------------------------------------------------------
# Persistent DB: PostgreSQL connection string ONLY
# Supabase: Project Settings → Database → Connection string → URI
#   Example: postgresql://postgres.xxx:PASSWORD@aws-0-...pooler.supabase.com:6543/postgres
# NOTE: SUPABASE_URL (https://xxx.supabase.co) and SUPABASE_ANON_KEY are REST API
#       keys — they are NOT used for psycopg2. Use the Postgres URI as DATABASE_URL.
# ---------------------------------------------------------------------------
DATABASE_URL = (
    os.environ.get("DATABASE_URL")
    or os.environ.get("SUPABASE_DB_URL")
    or os.environ.get("POSTGRES_URL")
    or os.environ.get("POSTGRES_CONNECTION_STRING")
    or ""
)
DATABASE_URL = str(DATABASE_URL).strip().strip('"').strip("'")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Reject accidental REST URL pasted as DATABASE_URL
if DATABASE_URL.startswith("http://") or DATABASE_URL.startswith("https://"):
    logger.error(
        "DATABASE_URL looks like an HTTP URL (SUPABASE_URL). "
        "Use the PostgreSQL URI from Supabase → Settings → Database instead."
    )
    DATABASE_URL = ""

if not DATABASE_URL:
    logger.error(
        "DATABASE_URL is not set. Set DATABASE_URL to your Supabase/Render "
        "PostgreSQL URI. SQLite is permanently disabled."
    )
else:
    # Redact password in logs
    _safe = DATABASE_URL
    try:
        if "@" in _safe and "://" in _safe:
            _pre, _post = _safe.split("@", 1)
            _scheme = _pre.split("://", 1)[0]
            _safe = f"{_scheme}://***@{_post}"
    except Exception:
        _safe = "postgresql://***"
    logger.info("Database: PostgreSQL persistent (%s)", _safe)

RENDER_EXTERNAL_HOSTNAME = (os.environ.get("RENDER_EXTERNAL_HOSTNAME", "") or "").strip()
PORT = int(os.environ.get("PORT", "8080"))
# Legacy name only — SQLite is disabled; kept so old imports do not crash
DB_FILE = os.environ.get("DB_FILE", "adika_marketplace.db")

if RENDER_EXTERNAL_HOSTNAME:
    WEBAPP_URL = f"https://{RENDER_EXTERNAL_HOSTNAME}"
else:
    WEBAPP_URL = os.environ.get("WEBAPP_URL", "http://127.0.0.1:8080")

try:
    ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 0
except ValueError:
    ADMIN_CHAT_ID_INT = 0

ADMIN_IDS = {ADMIN_CHAT_ID_INT} if ADMIN_CHAT_ID_INT else set()

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

BROKER_CATEGORIES = ["🚗 መኪና", "🏠 ቤትና ቦታ", "📦 አጠቃላይ ደላላ"]
BROKER_REG_SUBCITIES = [
    "ቦሌ", "አራዳ", "ቂርቆስ", "ልደታ", "አዲስ ከተማ",
    "ጉሌሌ", "የካ", "ንፋስ ስልክ", "አቃቂ ቃሊቲ", "ኮልፌ ቀራኒዮ",
    "አዲስ አበባ (ሙሉ)",
]
