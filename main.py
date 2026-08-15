# ==============================================================================
# main.py — Entry point
# ==============================================================================
import sys
import os
import threading
import time
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters,
)

from config import BOT_TOKEN, logger, MAIN_KEYBOARD
from models import init_db, expire_old_listings
import webapp as webapp_module
from webapp import run_flask
from handlers import (
    start, go_home, error_handler,
    buyer_start, buyer_category_chosen, buyer_action_chosen, buyer_sub_chosen,
    buyer_property_chosen, buyer_htype_chosen, buyer_budget_range, buyer_alert_choice,
    buyer_details, buyer_phone,
    seller_start, seller_category_chosen, seller_action_chosen, seller_sub_chosen,
    seller_property_chosen, seller_htype_chosen, seller_condition_chosen,
    seller_house_condition_chosen, seller_fuel_chosen, seller_transmission_chosen,
    seller_mileage, seller_bedrooms_chosen, seller_parking_chosen, seller_details,
    seller_price, seller_negotiable_chosen, seller_urgent_chosen, seller_phone, seller_photo,
    broker_reg_start, broker_reg_name, broker_reg_phone,
    broker_reg_category, broker_reg_subcity,
    broker_rate_cb, broker_star_cb, broker_del_cb, broker_call_cb,
    broker_have_item_click, broker_offer_text, broker_offer_photo,
    marketplace_choice, requests_choice, text_mode_callback,
    view_brokers_directory, filter_brokers_by_subcity_callback,
    help_command, notification_prefs_start, notification_prefs_callback,
    admin_approval_callback, delete_request_callback, nohave_item_callback,
    mark_sold_callback, have_buyer_callback, want_myself_callback,
    BUYER_MAIN, BUYER_ACTION, BUYER_SUB, BUYER_PROPERTY, BUYER_HTYPE,
    BUYER_DETAILS, BUYER_PHONE, BUYER_BUDGET_RANGE, BUYER_ALERT,
    SELLER_MAIN, SELLER_ACTION, SELLER_SUB, SELLER_PROPERTY, SELLER_HTYPE,
    SELLER_DETAILS, SELLER_PRICE, SELLER_NEGOTIABLE, SELLER_URGENT,
    SELLER_CONDITION, SELLER_FUEL, SELLER_TRANSMISSION, SELLER_MILEAGE,
    SELLER_BEDROOMS, SELLER_PARKING, SELLER_PHONE, SELLER_PHOTO, SELLER_HOUSE_CONDITION,
    BROKER_NAME, BROKER_PHONE, BROKER_CATEGORY, BROKER_SUBCITY,
    BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO,
)


def start_cleanup_scheduler():
    def _loop():
        time.sleep(90)
        while True:
            try:
                expire_old_listings(30)
            except Exception as e:
                logger.error(f"cleanup: {e}")
            time.sleep(24 * 3600)
    threading.Thread(target=_loop, daemon=True, name="adika-cleanup").start()
    logger.info("🧹 Cleanup scheduler started")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("❌ BOT_TOKEN environment variable is required")

    # Python 3.10+ / 3.12: ensure a MainThread event loop exists for PTB
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    init_db()
    threading.Thread(target=run_flask, daemon=True, name="flask").start()
    start_cleanup_scheduler()

    async def _post_init(application: Application):
        # Store running loop so Flask threads can schedule coroutines safely
        webapp_module.bot_loop = asyncio.get_running_loop()
        logger.info("Event loop captured for cross-thread notifications")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(_post_init)
        .build()
    )
    webapp_module.bot_app = app
    webapp_module.bot_loop = None

    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_handler = MessageHandler(cancel_filter, go_home)

    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 ለመግዛት / ለመከራየት$"), buyer_start)],
        states={
            BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_handler],
            BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_"), cancel_handler],
            BUYER_SUB: [CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_"), cancel_handler],
            BUYER_PROPERTY: [CallbackQueryHandler(buyer_property_chosen, pattern="^flow_buy_prop_"), cancel_handler],
            BUYER_HTYPE: [CallbackQueryHandler(buyer_htype_chosen, pattern="^flow_buy_htype_"), cancel_handler],
            BUYER_BUDGET_RANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_budget_range), cancel_handler],
            BUYER_ALERT: [CallbackQueryHandler(buyer_alert_choice, pattern="^alert_"), cancel_handler],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details), cancel_handler],
            BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone), cancel_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 ለመሸጥ / ለማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_"), cancel_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_handler],
            SELLER_SUB: [CallbackQueryHandler(seller_sub_chosen, pattern="^flow_sell_sub_"), cancel_handler],
            SELLER_PROPERTY: [CallbackQueryHandler(seller_property_chosen, pattern="^flow_sell_prop_"), cancel_handler],
            SELLER_HTYPE: [CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_"), cancel_handler],
            SELLER_CONDITION: [CallbackQueryHandler(seller_condition_chosen, pattern="^flow_sell_cond_"), cancel_handler],
            SELLER_HOUSE_CONDITION: [CallbackQueryHandler(seller_house_condition_chosen, pattern="^flow_sell_hcond_"), cancel_handler],
            SELLER_FUEL: [CallbackQueryHandler(seller_fuel_chosen, pattern="^flow_sell_fuel_"), cancel_handler],
            SELLER_TRANSMISSION: [CallbackQueryHandler(seller_transmission_chosen, pattern="^flow_sell_trans_"), cancel_handler],
            SELLER_MILEAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_mileage), cancel_handler],
            SELLER_BEDROOMS: [CallbackQueryHandler(seller_bedrooms_chosen, pattern="^bed_"), cancel_handler],
            SELLER_PARKING: [CallbackQueryHandler(seller_parking_chosen, pattern="^park_"), cancel_handler],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details), cancel_handler],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price), cancel_handler],
            SELLER_NEGOTIABLE: [CallbackQueryHandler(seller_negotiable_chosen, pattern="^negotiable_"), cancel_handler],
            SELLER_URGENT: [CallbackQueryHandler(seller_urgent_chosen, pattern="^urgent_"), cancel_handler],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone), cancel_handler],
            SELLER_PHOTO: [
                MessageHandler(filters.PHOTO, seller_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_photo),
                cancel_handler,
            ],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✍️ የደላላ/አቅራቢ መመዝገቢያ$"), broker_reg_start)],
        states={
            BROKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name), cancel_handler],
            BROKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone), cancel_handler],
            BROKER_CATEGORY: [CallbackQueryHandler(broker_reg_category, pattern=r"^(bcat_\d+|flow_home)$")],
            BROKER_SUBCITY: [CallbackQueryHandler(broker_reg_subcity, pattern=r"^(bsc_\d+|flow_home)$")],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    broker_response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broker_have_item_click, pattern="^have_item_")],
        states={
            BROKER_OFFER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text), cancel_handler],
            BROKER_OFFER_PHOTO: [
                MessageHandler(filters.PHOTO, broker_offer_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_photo),
                cancel_handler,
            ],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(broker_response_conv)

    app.add_handler(MessageHandler(filters.Regex("^🛒 የገበያ ቦታ$"), marketplace_choice))
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ጥያቄዎች$"), requests_choice))
    app.add_handler(MessageHandler(filters.Regex("^👥 የደላሎች መድረክ$"), view_brokers_directory))
    app.add_handler(MessageHandler(filters.Regex("^📞 እገዛ / Support$"), help_command))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ የማሳወቂያ ማስተካከያ$"), notification_prefs_start))
    app.add_handler(cancel_handler)

    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(text_mode_callback, pattern=r"^(text_mode_|tm_sold_|tm_call_)"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(admin_approval_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(delete_request_callback, pattern=r"^delete_req_"))
    app.add_handler(CallbackQueryHandler(nohave_item_callback, pattern="^nohave_item_"))
    app.add_handler(CallbackQueryHandler(filter_brokers_by_subcity_callback, pattern="^dir_sc_"))
    app.add_handler(CallbackQueryHandler(mark_sold_callback, pattern="^mark_sold_"))
    app.add_handler(CallbackQueryHandler(have_buyer_callback, pattern="^have_buyer_"))
    app.add_handler(CallbackQueryHandler(want_myself_callback, pattern="^want_myself_"))
    app.add_handler(CallbackQueryHandler(notification_prefs_callback, pattern="^notif_pref_"))
    app.add_handler(CallbackQueryHandler(broker_call_cb, pattern="^broker_call_"))
    app.add_handler(CallbackQueryHandler(broker_rate_cb, pattern="^broker_rate_"))
    app.add_handler(CallbackQueryHandler(broker_star_cb, pattern="^broker_star_"))
    app.add_handler(CallbackQueryHandler(broker_del_cb, pattern="^broker_del_"))

    app.add_error_handler(error_handler)

    logger.info("🚀 Adika Marketplace Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
