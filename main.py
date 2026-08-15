# main.py  (updated entry point)

import asyncio
import logging
import threading
import time

from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters

from config import BOT_TOKEN, AUTO_EXPIRE_DAYS
from models import init_db, expire_old_listings
from webapp import run_flask
import handlers as h

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def start_cleanup_scheduler():
    def _loop():
        time.sleep(60)
        while True:
            try:
                expire_old_listings(AUTO_EXPIRE_DAYS)
            except Exception as e:
                logger.error(f"cleanup error: {e}")
            time.sleep(24 * 3600)

    t = threading.Thread(target=_loop, daemon=True, name="adika-cleanup")
    t.start()
    logger.info("🧹 Cleanup scheduler started")


def main():
    # 1. Database
    init_db()

    # 2. Ensure an event loop exists on the MainThread (critical fix)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # 3. Start Flask in a background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True, name="flask-webapp")
    flask_thread.start()
    logger.info("🌐 Flask Mini App started in background thread")

    # 4. Daily cleanup
    start_cleanup_scheduler()

    # 5. Build Telegram Application
    application = Application.builder().token(BOT_TOKEN).build()

    # Make the bot instance available globally for the notification helper
    import webapp
    webapp.bot_app = application          # ← important

    cancel = MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), h.go_home)

    # --- Conversations (keep your existing ones) ---
    # buyer_conv = ...
    # seller_conv = ...
    # broker_conv = ...

    application.add_handler(CommandHandler("start", h.start))
    # application.add_handler(buyer_conv)
    # application.add_handler(seller_conv)
    # application.add_handler(broker_conv)

    application.add_handler(MessageHandler(filters.Regex("^🛒 የገበያ ቦታ$"), h.marketplace_choice))
    application.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ጥያቄዎች$"), h.requests_choice))
    application.add_handler(MessageHandler(filters.Regex("^👥 የደላሎች መድረክ$"), h.view_brokers_directory))
    application.add_handler(MessageHandler(filters.Regex("^📞 እገዛ / Support$"), h.help_command))
    application.add_handler(MessageHandler(filters.Regex("^⚙️ የማሳወቂያ ማስተካከያ$"), h.notification_prefs_start))
    application.add_handler(cancel)

    application.add_handler(CallbackQueryHandler(h.go_home, pattern="^flow_home$"))
    application.add_handler(CallbackQueryHandler(h.text_mode_callback, pattern=r"^(text_mode_|tm_sold_|tm_call_)"))
    application.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"))
    application.add_handler(CallbackQueryHandler(h.admin_approval_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(h.filter_brokers_by_subcity_callback, pattern="^dir_sc_"))
    application.add_handler(CallbackQueryHandler(h.notification_prefs_callback, pattern="^notif_pref_"))

    application.add_error_handler(h.error_handler)

    logger.info("🚀 Adika Marketplace Bot starting (polling)...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
