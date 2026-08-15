# main.py
"""
Adika Marketplace - Entry Point
Starts Flask (Mini App) + Telegram Bot (polling) + cleanup scheduler.
"""

import logging
import threading
import time

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)

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
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    start_cleanup_scheduler()

    app = Application.builder().token(BOT_TOKEN).build()

    cancel = MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), h.go_home)

    # Buyer conversation (full state machine from original)
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 ለመግዛት / ለመከራየት$"), h.buyer_start)],
        states={
            # … map all BUYER_* states to the corresponding handlers
        },
        fallbacks=[CommandHandler("start", h.start), cancel],
        allow_reentry=True,
    )

    # Seller conversation
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 ለመሸጥ / ለማከራየት$"), h.seller_start)],
        states={
            # … map all SELLER_* states
        },
        fallbacks=[CommandHandler("start", h.start), cancel],
        allow_reentry=True,
    )

    # Broker registration (zero-friction)
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✍️ የደላላ/አቅራቢ መመዝገቢያ$"), h.broker_reg_start)],
        states={
            h.BROKER_ROLE: [CallbackQueryHandler(h.broker_role_chosen, pattern="^role_"), cancel],
            h.BROKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, h.broker_reg_phone), cancel],
            h.BROKER_SUBCITY: [CallbackQueryHandler(h.broker_reg_subcity, pattern="^broker_sc_"), cancel],
            h.BROKER_NID_PHOTO: [MessageHandler(filters.PHOTO, h.broker_reg_nid_photo), cancel],
        },
        fallbacks=[CommandHandler("start", h.start), cancel],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", h.start))
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)

    app.add_handler(MessageHandler(filters.Regex("^🛒 የገበያ ቦታ$"), h.marketplace_choice))
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ጥያቄዎች$"), h.requests_choice))
    app.add_handler(MessageHandler(filters.Regex("^👥 የደላሎች መድረክ$"), h.view_brokers_directory))
    app.add_handler(MessageHandler(filters.Regex("^📞 እገዛ / Support$"), h.help_command))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ የማሳወቂያ ማስተካከያ$"), h.notification_prefs_start))
    app.add_handler(cancel)

    app.add_handler(CallbackQueryHandler(h.go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(h.text_mode_callback, pattern=r"^(text_mode_|tm_sold_|tm_call_)"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(h.admin_approval_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(h.filter_brokers_by_subcity_callback, pattern="^dir_sc_"))
    app.add_handler(CallbackQueryHandler(h.notification_prefs_callback, pattern="^notif_pref_"))

    app.add_error_handler(h.error_handler)

    logger.info("🚀 Adika Marketplace Bot started successfully")
    app.run_polling()


if __name__ == "__main__":
    main()
