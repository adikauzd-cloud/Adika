import logging

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
Adika Marketplace - Configuration
Safely loads environment variables with sensible defaults.
"""

import os
from typing import Optional

# Required
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable is missing.")

# Optional / with defaults
ADMIN_CHAT_ID: str = os.getenv("ADMIN_CHAT_ID", "0")
ADMIN_CHAT_ID_INT: int = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID.isdigit() else 0

DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip().strip('"').strip("'")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

RENDER_EXTERNAL_HOSTNAME: str = os.getenv(
    "RENDER_EXTERNAL_HOSTNAME", "adika-vrkk.onrender.com"
)

# Derived
WEBAPP_BASE_URL: str = f"https://{RENDER_EXTERNAL_HOSTNAME}"
DB_FILE: str = "adika_marketplace.db"
PORT: int = int(os.getenv("PORT", "8080"))

# Feature flags / limits
MAX_PHOTOS_PER_LISTING: int = 5
MAX_IMAGE_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB
TEXT_PAGE_SIZE: int = 4
AUTO_EXPIRE_DAYS: int = 30
