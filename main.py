# main.py
"""
Adika Marketplace - Main Entry Point (Fully Fixed)
"""

import asyncio
import logging
import threading
import time
import re

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

    # Ensure event loop exists on MainThread
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # Start Flask
    flask_thread = threading.Thread(target=run_flask, daemon=True, name="flask-webapp")
    flask_thread.start()
    logger.info("🌐 Flask Mini App started")

    start_cleanup_scheduler()

    application = Application.builder().token(BOT_TOKEN).build()

    # Make bot available for notifications from Flask
    import webapp
    webapp.bot_app = application

    # ---------------------------------------------------------------
    # Robust button filters (fixes the freezing buttons)
    # ---------------------------------------------------------------
    BUY_FILTER = filters.Regex(r"^\s*🔍\s*ለመግዛት\s*/\s*ለመከራየት\s*$")
    SELL_FILTER = filters.Regex(r"^\s*📢\s*ለመሸጥ\s*/\s*ለማከራየት\s*$")
    BROKER_REG_FILTER = filters.Regex(r"^\s*✍️\s*የደላላ/አቅራቢ መመዝገቢያ\s*$")
    HOME_FILTER = filters.Regex(r"^\s*🏠\s*ዋና ገጽ\s*$")

    cancel = MessageHandler(HOME_FILTER, h.go_home)

    # ---------------------------------------------------------------
    # BUYER Conversation
    # ---------------------------------------------------------------
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(BUY_FILTER, h.buyer_start)],
        states={
            h.BUYER_MAIN: [
                CallbackQueryHandler(h.buyer_category_chosen, pattern="^flow_buy_cat_"),
                cancel,
            ],
            h.BUYER_ACTION: [
                CallbackQueryHandler(h.buyer_action_chosen, pattern="^flow_buy_action_"),
                cancel,
            ],
            h.BUYER_SUB: [
                CallbackQueryHandler(h.buyer_sub_chosen, pattern="^flow_buy_sub_"),
                cancel,
            ],
            h.BUYER_PROPERTY: [
                CallbackQueryHandler(h.buyer_property_chosen, pattern="^flow_buy_prop_"),
                cancel,
            ],
            h.BUYER_HTYPE: [
                CallbackQueryHandler(h.buyer_htype_chosen, pattern="^flow_buy_htype_"),
                cancel,
            ],
            h.BUYER_BUDGET_RANGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.buyer_budget_range),
                cancel,
            ],
            h.BUYER_ALERT: [
                CallbackQueryHandler(h.buyer_alert_choice, pattern="^alert_"),
                cancel,
            ],
            h.BUYER_DETAILS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.buyer_details),
                cancel,
            ],
            h.BUYER_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.buyer_phone),
                cancel,
            ],
        },
        fallbacks=[CommandHandler("start", h.start), cancel],
        allow_reentry=True,
        name="buyer_conversation",
    )

    # ---------------------------------------------------------------
    # SELLER Conversation
    # ---------------------------------------------------------------
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(SELL_FILTER, h.seller_start)],
        states={
            h.SELLER_MAIN: [
                CallbackQueryHandler(h.seller_category_chosen, pattern="^flow_sell_cat_"),
                cancel,
            ],
            h.SELLER_ACTION: [
                CallbackQueryHandler(h.seller_action_chosen, pattern="^flow_sell_action_"),
                cancel,
            ],
            h.SELLER_SUB: [
                CallbackQueryHandler(h.seller_sub_chosen, pattern="^flow_sell_sub_"),
                cancel,
            ],
            h.SELLER_PROPERTY: [
                CallbackQueryHandler(h.seller_property_chosen, pattern="^flow_sell_prop_"),
                cancel,
            ],
            h.SELLER_HTYPE: [
                CallbackQueryHandler(h.seller_htype_chosen, pattern="^flow_sell_htype_"),
                cancel,
            ],
            h.SELLER_CONDITION: [
                CallbackQueryHandler(h.seller_condition_chosen, pattern="^flow_sell_cond_"),
                cancel,
            ],
            h.SELLER_HOUSE_CONDITION: [
                CallbackQueryHandler(h.seller_house_condition_chosen, pattern="^flow_sell_hcond_"),
                cancel,
            ],
            h.SELLER_FUEL: [
                CallbackQueryHandler(h.seller_fuel_chosen, pattern="^flow_sell_fuel_"),
                cancel,
            ],
            h.SELLER_TRANSMISSION: [
                CallbackQueryHandler(h.seller_transmission_chosen, pattern="^flow_sell_trans_"),
                cancel,
            ],
            h.SELLER_MILEAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.seller_mileage),
                cancel,
            ],
            h.SELLER_BEDROOMS: [
                CallbackQueryHandler(h.seller_bedrooms_chosen, pattern="^bed_"),
                cancel,
            ],
            h.SELLER_PARKING: [
                CallbackQueryHandler(h.seller_parking_chosen, pattern="^park_"),
                cancel,
            ],
            h.SELLER_DETAILS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.seller_details),
                cancel,
            ],
            h.SELLER_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.seller_price),
                cancel,
            ],
            h.SELLER_NEGOTIABLE: [
                CallbackQueryHandler(h.seller_negotiable_chosen, pattern="^negotiable_"),
                cancel,
            ],
            h.SELLER_URGENT: [
                CallbackQueryHandler(h.seller_urgent_chosen, pattern="^urgent_"),
                cancel,
            ],
            h.SELLER_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.seller_phone),
                cancel,
            ],
            h.SELLER_PHOTO: [
                MessageHandler(filters.PHOTO, h.seller_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.seller_photo),
                cancel,
            ],
        },
        fallbacks=[CommandHandler("start", h.start), cancel],
        allow_reentry=True,
        name="seller_conversation",
    )

    # ---------------------------------------------------------------
    # BROKER Registration Conversation
    # ---------------------------------------------------------------
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(BROKER_REG_FILTER, h.broker_reg_start)],
        states={
            h.BROKER_ROLE: [
                CallbackQueryHandler(h.broker_role_chosen, pattern="^role_"),
                cancel,
            ],
            h.BROKER_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, h.broker_reg_phone),
                cancel,
            ],
            h.BROKER_SUBCITY: [
                CallbackQueryHandler(h.broker_reg_subcity, pattern="^broker_sc_"),
                cancel,
            ],
            h.BROKER_NID_PHOTO: [
                MessageHandler(filters.PHOTO, h.broker_reg_nid_photo),
                cancel,
            ],
        },
        fallbacks=[CommandHandler("start", h.start), cancel],
        allow_reentry=True,
        name="broker_conversation",
    )

    # ---------------------------------------------------------------
    # Register everything
    # ---------------------------------------------------------------
    application.add_handler(CommandHandler("start", h.start))
    application.add_handler(buyer_conv)
    application.add_handler(seller_conv)
    application.add_handler(broker_conv)

    application.add_handler(MessageHandler(filters.Regex(r"^\s*🛒\s*የገበያ ቦታ\s*$"), h.marketplace_choice))
    application.add_handler(MessageHandler(filters.Regex(r"^\s*📋\s*የፈላጊዎች ጥያቄዎች\s*$"), h.requests_choice))
    application.add_handler(MessageHandler(filters.Regex(r"^\s*👥\s*የደላሎች መድረክ\s*$"), h.view_brokers_directory))
    application.add_handler(MessageHandler(filters.Regex(r"^\s*📞\s*እገዛ\s*/\s*Support\s*$"), h.help_command))
    application.add_handler(MessageHandler(filters.Regex(r"^\s*⚙️\s*የማሳወቂያ ማስተካከያ\s*$"), h.notification_prefs_start))
    application.add_handler(cancel)

    application.add_handler(CallbackQueryHandler(h.go_home, pattern="^flow_home$"))
    application.add_handler(CallbackQueryHandler(h.text_mode_callback, pattern=r"^(text_mode_|tm_sold_|tm_call_)"))
    application.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"))
    application.add_handler(CallbackQueryHandler(h.admin_approval_callback, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(h.filter_brokers_by_subcity_callback, pattern="^dir_sc_"))
    application.add_handler(CallbackQueryHandler(h.notification_prefs_callback, pattern="^notif_pref_"))

    application.add_error_handler(h.error_handler)

    logger.info("🚀 Adika Marketplace Bot started successfully")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
