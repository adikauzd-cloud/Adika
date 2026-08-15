# ==============================================================================
# main.py — Entry point: Flask (thread) + Telegram bot (polling)
# ==============================================================================
import sys
import os
import threading
import time

# Ensure package dir is on path when run as script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram.ext import Application

from config import BOT_TOKEN, logger
from models import init_db, expire_old_listings
from handlers import register_handlers
from webapp import run_flask


def start_cleanup_scheduler():
    """Daily job: expire listings older than 30 days."""
    def _loop():
        time.sleep(90)
        while True:
            try:
                expire_old_listings(30)
            except Exception as e:
                logger.error(f"cleanup: {e}")
            time.sleep(24 * 3600)

    t = threading.Thread(target=_loop, daemon=True, name="adika-cleanup")
    t.start()
    logger.info("🧹 Cleanup scheduler started")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("❌ BOT_TOKEN environment variable is required")

    init_db()
    threading.Thread(target=run_flask, daemon=True, name="flask").start()
    start_cleanup_scheduler()

    app = Application.builder().token(BOT_TOKEN).build()
    register_handlers(app)

    logger.info("🚀 Adika Marketplace Bot started (polling + Flask)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
