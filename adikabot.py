import logging
import os
import threading
import asyncio
import psycopg2
from flask import Flask, request, jsonify
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# ==============================================================================
# 0. FLASK WEB SERVER WITH WEBHOOK
# ==============================================================================
web_app = Flask(__name__)
bot_application = None

@web_app.route('/')
def home():
    return """
    <html>
    <head><title>Adika Marketplace Bot</title></head>
    <body style="font-family: Arial; padding: 20px;">
        <h1>🚀 Adika Marketplace Bot</h1>
        <hr>
        <h2>📊 Status</h2>
        <ul>
            <li><b>Status:</b> ✅ Running</li>
            <li><b>Webhook:</b> {} {}</li>
            <li><b>Database:</b> {}</li>
        </ul>
        <hr>
        <p>🕐 {}</p>
    </body>
    </html>
    """.format(
        WEBHOOK_URL if WEBHOOK_URL else "❌ Not Set",
        f"→ <a href='{WEBHOOK_URL}/webhook'>/webhook</a>" if WEBHOOK_URL else "",
        "✅ PostgreSQL" if DATABASE_URL else "⚠️ SQLite",
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )

@web_app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook requests"""
    global bot_application
    
    if not bot_application:
        logging.error("❌ Bot application not initialized!")
        return "Bot not initialized", 500
    
    try:
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, bot_application.bot)
        asyncio.create_task(bot_application.process_update(update))
        return "OK", 200
    except Exception as e:
        logging.error(f"❌ Webhook error: {e}")
        return f"Error: {str(e)}", 500

@web_app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "webhook_url": WEBHOOK_URL,
        "database": "postgresql" if DATABASE_URL else "sqlite",
        "timestamp": datetime.now().isoformat()
    })

def run_flask_with_webhook(app_instance):
    """Run Flask with webhook configured"""
    global bot_application
    bot_application = app_instance
    
    port = int(os.environ.get("PORT", 8080))
    logging.info(f"🚀 Starting Flask on port: {port}")
    web_app.run(host="0.0.0.0", port=port, debug=False)

# ==============================================================================
# 1. CONFIGURATION & LOGGING
# ==============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "0")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable ውስጥ አልተገኘም።")

ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 0

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================================================================
# 2. DATABASE (ከእርስዎ ኮድ ጋር ተመሳሳይ)
# ==============================================================================
# ... ሁሉም የDATABASE ተግባራት እዚህ ይቀመጣሉ ...
# (ከላይ ያሉትን ሙሉ የDATABASE ክፍል ይቅዱ)

# ==============================================================================
# 3. KEYBOARDS & CONSTANTS (ከእርስዎ ኮድ ጋር ተመሳሳይ)
# ==============================================================================
# ... ሁሉም የKEYBOARDS እና CONSTANTS ክፍል እዚህ ይቀመጣል ...

# ==============================================================================
# 4. CONVERSATION STATES (ከእርስዎ ኮድ ጋር ተመሳሳይ)
# ==============================================================================
# ... ሁሉም የSTATES ክፍል እዚህ ይቀመጣል ...

# ==============================================================================
# 5. HANDLERS (ከእርስዎ ኮድ ጋር ተመሳሳይ)
# ==============================================================================
# ... ሁሉም የHANDLERS ክፍል እዚህ ይቀመጣል ...
# (ከላይ ያሉትን ሙሉ የHANDLERS ክፍል ይቅዱ)

# ==============================================================================
# 6. MAIN FUNCTION - RENDER READY
# ==============================================================================
def main():
    from datetime import datetime
    
    logger.info("=" * 50)
    logger.info("🚀 Starting Adika Marketplace Bot...")
    logger.info(f"📌 Bot Token: {BOT_TOKEN[:10]}...{BOT_TOKEN[-5:]}")
    logger.info(f"📌 Webhook URL: {WEBHOOK_URL if WEBHOOK_URL else 'NOT SET'}")
    logger.info(f"📌 Database: {'PostgreSQL' if DATABASE_URL else 'SQLite'}")
    logger.info("=" * 50)
    
    # Initialize database
    init_db()
    
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # ===== ADD ALL HANDLERS =====
    app.add_handler(CommandHandler("start", start))
    
    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)
    
    # Buyer Conversation
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
        states={
            BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_message_handler],
            BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_"), cancel_message_handler],
            BUYER_CATEGORY: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_message_handler],
            BUYER_SUB: [CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_"), cancel_message_handler],
            BUYER_PROPERTY: [CallbackQueryHandler(buyer_property_chosen, pattern="^flow_buy_prop_"), 
                           CallbackQueryHandler(buyer_htype_chosen, pattern="^flow_buy_htype_"), cancel_message_handler],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details), cancel_message_handler],
            BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    # Seller Conversation
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_message_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_message_handler],
            SELLER_CATEGORY: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_"), cancel_message_handler],
            SELLER_SUB: [CallbackQueryHandler(seller_sub_chosen, pattern="^flow_sell_sub_"), 
                        CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_"), cancel_message_handler],
            SELLER_PROPERTY: [CallbackQueryHandler(seller_property_chosen, pattern="^flow_sell_prop_"), cancel_message_handler],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details), cancel_message_handler],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price), cancel_message_handler],
            SELLER_NEGO: [CallbackQueryHandler(seller_nego, pattern="^flow_sell_nego_"), cancel_message_handler],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone), cancel_message_handler],
            SELLER_PHOTO: [MessageHandler(filters.PHOTO, seller_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    # Broker Registration
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ መመዝገብ$"), broker_reg_start)],
        states={
            BROKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name), cancel_message_handler],
            BROKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone), cancel_message_handler],
            BROKER_LOCATION: [CallbackQueryHandler(broker_reg_location, pattern="^broker_loc_"), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    # Response Conversation
    response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_item_response, pattern="^item_resp_")],
        states={
            RESP_MAIN: [CallbackQueryHandler(resp_role_chosen, pattern="^resp_role_"), cancel_message_handler],
            RESP_ACTION: [CallbackQueryHandler(resp_property_chosen, pattern="^resp_prop_"), cancel_message_handler],
            RESP_CATEGORY: [CallbackQueryHandler(resp_htype_chosen, pattern="^resp_htype_"), cancel_message_handler],
            RESP_SUB: [CallbackQueryHandler(resp_htype_chosen, pattern="^resp_htype_"), cancel_message_handler],
            RESP_PROPERTY: [CallbackQueryHandler(resp_property_chosen, pattern="^resp_prop_"), cancel_message_handler],
            RESP_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_details), cancel_message_handler],
            RESP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_price), cancel_message_handler],
            RESP_NEGO: [CallbackQueryHandler(resp_nego, pattern="^resp_nego_"), cancel_message_handler],
            RESP_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_phone), cancel_message_handler],
            RESP_PHOTO: [MessageHandler(filters.PHOTO, resp_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    # Add all handlers
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(response_conv)
    
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(MessageHandler(cancel_filter, go_home))
    
    app.add_handler(CallbackQueryHandler(show_requests_page, pattern="^page_"))
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    
    # ===== WEBHOOK OR POLLING =====
    if WEBHOOK_URL:
        logger.info(f"🔗 Setting webhook to: {WEBHOOK_URL}/webhook")
        
        try:
            app.bot.delete_webhook()
            logger.info("✅ Old webhook deleted")
            
            webhook_full_url = f"{WEBHOOK_URL}/webhook"
            result = app.bot.set_webhook(url=webhook_full_url)
            logger.info(f"✅ Webhook set to: {webhook_full_url}")
            logger.info(f"✅ Result: {result}")
            
            logger.info("🚀 Starting bot in webhook mode...")
            run_flask_with_webhook(app)
            
        except Exception as e:
            logger.error(f"❌ Webhook setup error: {e}")
            logger.info("🔄 Falling back to polling mode...")
            app.run_polling()
    else:
        logger.info("🚀 Starting bot in polling mode...")
        app.run_polling()

# ==============================================================================
# 7. ERROR HANDLER
# ==============================================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}", exc_info=True)

# ==============================================================================
# 8. ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    from datetime import datetime
    main()
