# ==============================================================================
# main.py — Entry point: Flask (thread) + Telegram bot (polling/webhook)
# ==============================================================================
import sys
import os
import threading
import time
import signal
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram.ext import Application

from config import BOT_TOKEN, logger, PORT, USE_WEBHOOK, BASE_URL, ENVIRONMENT
from models import init_db, expire_old_listings
from handlers import register_handlers
from webapp import run_flask

app_instance = None
shutdown_event = threading.Event()

def start_cleanup_scheduler():
    """Daily job to expire old listings."""
    def _loop():
        time.sleep(90)
        while not shutdown_event.is_set():
            try:
                expired_count = expire_old_listings()
                if expired_count > 0:
                    logger.info(f"🧹 Cleaned up {expired_count} expired listings")
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
            for _ in range(1440):
                if shutdown_event.is_set():
                    break
                time.sleep(60)

    t = threading.Thread(target=_loop, daemon=True, name="adika-cleanup")
    t.start()
    logger.info("🧹 Cleanup scheduler started")

def signal_handler(sig, frame):
    """Handle shutdown signals."""
    logger.info(f"Received signal {sig}, shutting down gracefully...")
    shutdown_event.set()
    if app_instance:
        try:
            app_instance.stop()
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
    sys.exit(0)

def main():
    """Main entry point."""
    try:
        if not BOT_TOKEN:
            raise RuntimeError("❌ BOT_TOKEN environment variable is required")
        
        logger.info("Initializing database...")
        init_db()
        
        logger.info("Starting Flask server...")
        flask_thread = threading.Thread(target=run_flask, daemon=True, name="flask")
        flask_thread.start()
        
        start_cleanup_scheduler()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        global app_instance
        app_instance = Application.builder().token(BOT_TOKEN).build()
        register_handlers(app_instance)
        
        logger.info(f"🚀 Adika Marketplace Bot starting (ENV: {ENVIRONMENT})")
        
        if USE_WEBHOOK:
            webhook_url = f"{BASE_URL}/webhook"
            logger.info(f"Using webhook mode: {webhook_url}")
            app_instance.bot.set_webhook(
                url=webhook_url,
                allowed_updates=["message", "callback_query", "chat_member"]
            )
            app_instance.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                webhook_url=webhook_url,
                allowed_updates=["message", "callback_query", "chat_member"],
                drop_pending_updates=True,
            )
        else:
            logger.info("Using polling mode")
            app_instance.run_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query", "chat_member"]
            )
    
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        shutdown_event.set()

if __name__ == "__main__":
    main()
