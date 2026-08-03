import logging
import os
import asyncio
import sys
import json
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
from datetime import datetime

# ==============================================================================
# 0. FLASK WEB SERVER
# ==============================================================================
web_app = Flask(__name__)
bot_application = None

@web_app.route('/')
def home():
    """Home page with status"""
    try:
        # Test bot token
        test_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
        import requests
        response = requests.get(test_url, timeout=5)
        bot_valid = response.ok
        bot_info = response.json().get('result', {}) if bot_valid else {}
    except:
        bot_valid = False
        bot_info = {}
    
    return f"""
    <html>
    <head><title>Adika Marketplace Bot</title></head>
    <body style="font-family: Arial; padding: 20px;">
        <h1>🚀 Adika Marketplace Bot</h1>
        <hr>
        <h2>📊 Status</h2>
        <ul>
            <li><b>Bot Status:</b> {'✅ Valid' if bot_valid else '❌ Invalid Token'}</li>
            <li><b>Bot Name:</b> {bot_info.get('first_name', 'Unknown') if bot_valid else 'N/A'}</li>
            <li><b>Bot Username:</b> @{bot_info.get('username', 'Unknown') if bot_valid else 'N/A'}</li>
            <li><b>Webhook URL:</b> {WEBHOOK_URL}/webhook</li>
            <li><b>Database:</b> {'✅ PostgreSQL' if DATABASE_URL else '⚠️ SQLite'}</li>
            <li><b>Admin Chat ID:</b> {ADMIN_CHAT_ID}</li>
        </ul>
        <hr>
        <p>
            <a href="/webhook_info">📋 Webhook Info</a> | 
            <a href="/set_webhook">⚙️ Set Webhook</a> | 
            <a href="/health">💚 Health Check</a> |
            <a href="/test_bot">🤖 Test Bot</a>
        </p>
        <p>🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </body>
    </html>
    """

@web_app.route('/test_bot')
def test_bot():
    """Test bot token"""
    try:
        import requests
        response = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
        if response.ok:
            result = response.json().get('result', {})
            return jsonify({
                "status": "✅ Valid",
                "bot_name": result.get('first_name'),
                "bot_username": result.get('username'),
                "bot_id": result.get('id')
            })
        else:
            return jsonify({
                "status": "❌ Invalid",
                "error": response.text
            }), 400
    except Exception as e:
        return jsonify({"status": "❌ Error", "error": str(e)}), 500

@web_app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook requests"""
    global bot_application
    
    if not bot_application:
        logging.error("❌ Bot application not initialized!")
        return "Bot not initialized", 500
    
    try:
        json_data = request.get_json(force=True)
        logging.info(f"📥 Webhook received")
        
        update = Update.de_json(json_data, bot_application.bot)
        asyncio.create_task(bot_application.process_update(update))
        
        return "OK", 200
    except Exception as e:
        logging.error(f"❌ Webhook error: {e}")
        return f"Error: {str(e)}", 500

@web_app.route('/webhook_info')
def webhook_info():
    """Get webhook info from Telegram"""
    try:
        import requests
        response = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo", timeout=5)
        if response.ok:
            return jsonify(response.json())
        else:
            return jsonify({"error": response.text}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@web_app.route('/set_webhook')
def set_webhook():
    """Manually set webhook"""
    try:
        import requests
        webhook_url = f"{WEBHOOK_URL}/webhook"
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": webhook_url},
            timeout=5
        )
        
        if response.ok:
            return f"""
            <html>
            <body>
                <h2>✅ Webhook Configured</h2>
                <p><b>URL:</b> {webhook_url}</p>
                <p><b>Result:</b> {response.json()}</p>
                <p><a href="/webhook_info">Check Webhook Info</a></p>
            </body>
            </html>
            """
        else:
            return f"❌ Error: {response.text}"
    except Exception as e:
        return f"❌ Error: {str(e)}"

@web_app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "bot_token": BOT_TOKEN[:10] + "..." if BOT_TOKEN else "NOT SET",
        "webhook_url": f"{WEBHOOK_URL}/webhook" if WEBHOOK_URL else "NOT SET",
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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ==============================================================================
# 2. DATABASE
# ==============================================================================
def get_db_connection():
    if DATABASE_URL:
        db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        return conn
    else:
        import sqlite3
        return sqlite3.connect("adika_marketplace.db")

def init_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id SERIAL PRIMARY KEY,
                    user_chat_id BIGINT NOT NULL,
                    user_name TEXT,
                    req_type TEXT,
                    main_category TEXT,
                    description TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_chat_id INTEGER NOT NULL,
                    user_name TEXT,
                    req_type TEXT,
                    main_category TEXT,
                    description TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        if DATABASE_URL:
            conn.commit()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 3. KEYBOARDS
# ==============================================================================
MAIN_KEYBOARD = [
    ["🚗 መኪና (ለመግዛት / ለመሸጥ)"],
    ["🏠 ቤት/ቦታ (ለመግዛት / ለመሸጥ)"],
    ["📋 የእኔ ጥያቄዎች"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]

# ==============================================================================
# 4. HANDLERS
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"✅ Start command from user: {update.effective_user.id}")
    
    welcome_text = (
        "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
        "🏢 **የሪል እስቴት እና የመኪና ደላላ አገልግሎት**\n\n"
        "በፍጥነት ይግዙ፣ ይሽጡ ወይም ያከራዩ።"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    return ConversationHandler.END

async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"✅ Go home from user: {update.effective_user.id}")
    context.user_data.clear()
    await start(update, context)
    return ConversationHandler.END

async def handle_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"🚗 Car selected by user: {update.effective_user.id}")
    await update.message.reply_text(
        "🚗 **መኪና**\n\n"
        "እባክዎን የሚፈልጉትን ይምረጡ:\n"
        "• ለመግዛት\n"
        "• ለመሸጥ\n\n"
        "በቅርቡ ሙሉ አማራጮች ይጨመራሉ።",
        parse_mode="Markdown"
    )

async def handle_house(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"🏠 House selected by user: {update.effective_user.id}")
    await update.message.reply_text(
        "🏠 **ቤት/ቦታ**\n\n"
        "እባክዎን የሚፈልጉትን ይምረጡ:\n"
        "• ለመግዛት\n"
        "• ለመሸጥ\n\n"
        "በቅርቡ ሙሉ አማራጮች ይጨመራሉ።",
        parse_mode="Markdown"
    )

async def my_listings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"📋 My listings requested by user: {update.effective_user.id}")
    await update.message.reply_text(
        "📋 **የእኔ ጥያቄዎች**\n\n"
        "እስካሁን ምንም የተመዘገበ ነገር የለም።",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"📞 Help requested by user: {update.effective_user.id}")
    help_text = """
📞 **እኛን ለማነጋገር**

📱 ስልክ: +251 911 00 00 00
✈️ ቴሌግራም: @AdikaSupport

🕐 የስራ ሰዓት: ሰኞ - ቅዳሜ 8:00 - 18:00
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"📝 Message from user: {update.effective_user.id} - {update.message.text}")
    await update.message.reply_text(
        f"📝 መልእክትዎ ተቀብለናል!\n\n"
        f"💡 እባክዎን ከላይ ካሉት አማራጮች ይምረጡ።"
    )

# ==============================================================================
# 5. MAIN FUNCTION
# ==============================================================================
def main():
    logger.info("=" * 50)
    logger.info("🚀 Starting Adika Marketplace Bot...")
    logger.info(f"📌 Bot Token: {BOT_TOKEN[:10]}...{BOT_TOKEN[-5:]}")
    logger.info(f"📌 Webhook URL: {WEBHOOK_URL if WEBHOOK_URL else 'NOT SET'}")
    logger.info("=" * 50)
    
    # Test bot token
    try:
        import requests
        response = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
        if response.ok:
            result = response.json().get('result', {})
            logger.info(f"✅ Bot validated: @{result.get('username')} ({result.get('first_name')})")
        else:
            logger.error(f"❌ Bot token invalid: {response.text}")
            sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Bot validation error: {e}")
        sys.exit(1)
    
    # Initialize database
    init_db()
    
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    
    app.add_handler(MessageHandler(filters.Regex("^🚗 መኪና (ለመግዛት / ለመሸጥ)$"), handle_car))
    app.add_handler(MessageHandler(filters.Regex("^🏠 ቤት/ቦታ (ለመግዛት / ለመሸጥ)$"), handle_house))
    app.add_handler(MessageHandler(filters.Regex("^📋 የእኔ ጥያቄዎች$"), my_listings))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), go_home))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    
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
# 6. ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    main()
