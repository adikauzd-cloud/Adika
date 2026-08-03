import logging
import os
import asyncio
import psycopg2
from flask import Flask, request
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
    return "✅ Adika Marketplace Bot በስኬት እየሰራ ይገኛል!", 200

@web_app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook requests"""
    if not bot_application:
        return "Bot not initialized", 500
    
    try:
        update = Update.de_json(request.get_json(force=True), bot_application.bot)
        asyncio.create_task(bot_application.process_update(update))
        return "OK", 200
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return "Error", 500

def run_flask_with_webhook(app_instance):
    """Run Flask with webhook configured"""
    global bot_application
    bot_application = app_instance
    
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# ==============================================================================
# 1. CONFIGURATION & LOGGING
# ==============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "0")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")  # https://adika-vrkk.onrender.com

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable ውስጥ አልተገኘም።")

ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 0

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
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

def get_placeholder():
    return "%s" if DATABASE_URL else "?"

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
                    req_type TEXT NOT NULL,
                    main_category TEXT NOT NULL,
                    sub_category TEXT,
                    action_type TEXT,
                    property_type TEXT,
                    description TEXT NOT NULL,
                    price TEXT,
                    negotiable TEXT,
                    contact_method TEXT,
                    contact_info TEXT,
                    status TEXT DEFAULT 'pending',
                    request_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS brokers (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    location TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_chat_id INTEGER NOT NULL,
                    user_name TEXT,
                    req_type TEXT NOT NULL,
                    main_category TEXT NOT NULL,
                    sub_category TEXT,
                    action_type TEXT,
                    property_type TEXT,
                    description TEXT NOT NULL,
                    price TEXT,
                    negotiable TEXT,
                    contact_method TEXT,
                    contact_info TEXT,
                    status TEXT DEFAULT 'pending',
                    request_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS brokers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    location TEXT NOT NULL,
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

# ========== LISTING FUNCTIONS ==========
def add_listing(user_chat_id, user_name, req_type, main_category, sub_category, action_type, 
                property_type, description, price, negotiable, contact_method, contact_info):
    conn = None
    try:
        from datetime import datetime
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        prefix = "CAR" if main_category == "car" else "HSE"
        req_id = f"{prefix}-{user_chat_id}-{int(datetime.now().timestamp()) % 10000}"
        
        if DATABASE_URL:
            cursor.execute(f"""
                INSERT INTO listings 
                (user_chat_id, user_name, req_type, main_category, sub_category, action_type, 
                 property_type, description, price, negotiable, contact_method, contact_info, request_id)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) RETURNING id
            """, (user_chat_id, user_name, req_type, main_category, sub_category, action_type, 
                  property_type, description, price, negotiable, contact_method, contact_info, req_id))
            listing_id = cursor.fetchone()[0]
            conn.commit()
        else:
            cursor.execute(f"""
                INSERT INTO listings 
                (user_chat_id, user_name, req_type, main_category, sub_category, action_type, 
                 property_type, description, price, negotiable, contact_method, contact_info, request_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_chat_id, user_name, req_type, main_category, sub_category, action_type, 
                  property_type, description, price, negotiable, contact_method, contact_info, req_id))
            listing_id = cursor.lastrowid
        
        return listing_id, req_id
    except Exception as e:
        logger.error(f"Add listing error: {e}")
        return None, None
    finally:
        if conn:
            conn.close()

def get_user_listings(user_chat_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM listings WHERE user_chat_id = {p} ORDER BY created_at DESC", (user_chat_id,))
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logger.error(f"Get user listings error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def update_listing_status(req_id, status):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"UPDATE listings SET status = {p} WHERE id = {p}", (status, req_id))
        if DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Update listing error: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ========== BROKER FUNCTIONS ==========
def add_broker(chat_id, full_name, phone, location):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        if DATABASE_URL:
            cursor.execute(f"""
                INSERT INTO brokers (chat_id, full_name, phone, location)
                VALUES ({p}, {p}, {p}, {p}) RETURNING id
            """, (chat_id, full_name, phone, location))
            broker_id = cursor.fetchone()[0]
            conn.commit()
        else:
            cursor.execute(f"""
                INSERT INTO brokers (chat_id, full_name, phone, location)
                VALUES (?, ?, ?, ?)
            """, (chat_id, full_name, phone, location))
            broker_id = cursor.lastrowid
        return broker_id
    except Exception as e:
        logger.error(f"Add broker error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_broker(chat_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM brokers WHERE chat_id = {p}", (chat_id,))
        row = cursor.fetchone()
        return row
    except Exception as e:
        logger.error(f"Get broker error: {e}")
        return None
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 3. KEYBOARDS & CONSTANTS
# ==============================================================================
MAIN_KEYBOARD = [
    ["🚗 መኪና (ለመግዛት / ለመሸጥ)"],
    ["🏠 ቤት/ቦታ (ለመግዛት / ለመሸጥ)"],
    ["📋 የእኔ ጥያቄዎች / ማስታወቂያዎች"],
    ["📞 እኛን ለማነጋገር", "🏠 ወደ ዋና ገጽ"]
]

# ==============================================================================
# 4. CONVERSATION STATES
# ==============================================================================
CAR_BUYER_MODEL, CAR_BUYER_YEAR, CAR_BUYER_BUDGET, CAR_BUYER_CONTACT = range(4)
CAR_SELLER_MODEL, CAR_SELLER_YEAR_COND, CAR_SELLER_PRICE, CAR_SELLER_NEGO, CAR_SELLER_CONTACT = range(4, 9)
HOUSE_BUYER_TYPE, HOUSE_BUYER_LOCATION, HOUSE_BUYER_PRICE, HOUSE_BUYER_NEGO, HOUSE_BUYER_CONTACT = range(9, 14)
HOUSE_SELLER_TYPE, HOUSE_SELLER_LOCATION, HOUSE_SELLER_PRICE, HOUSE_SELLER_NEGO, HOUSE_SELLER_CONTACT = range(14, 19)
COMMON_CONTACT, COMMON_CONFIRM = range(19, 21)
BROKER_NAME, BROKER_PHONE, BROKER_LOCATION = range(21, 24)

# ==============================================================================
# 5. HANDLERS
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
        "🏢 **የሪል እስቴት እና የመኪና ደላላ አገልግሎት**\n\n"
        "በፍጥነት ይግዙ፣ ይሽጡ ወይም ያከራዩ።\n\n"
        "እባክዎን ከታች ካሉት አማራጮች ይምረጡ፦"
    )
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    return ConversationHandler.END

async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = (
        "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
        "🏢 **የሪል እስቴት እና የመኪና ደላላ አገልግሎት**\n\n"
        "በፍጥነት ይግዙ፣ ይሽጡ ወይም ያከራዩ።\n\n"
        "እባክዎን ከታች ካሉት አማራጮች ይምረጡ፦"
    )
    
    if update.message:
        await update.message.reply_text(
            welcome_text,
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    else:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            welcome_text,
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    return ConversationHandler.END

# ==============================================================================
# 6. MAIN FUNCTION - FIXED FOR RENDER
# ==============================================================================
def main():
    init_db()
    
    # Create application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # ===== ADD ALL HANDLERS =====
    # Add start command
    app.add_handler(CommandHandler("start", start))
    
    # Add cancel handler
    cancel_filter = filters.Regex("^🏠 ወደ ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)
    app.add_handler(cancel_message_handler)
    
    # Add other handlers
    # ... (add your conversation handlers here) ...
    
    # ===== CHOOSE RUNNING MODE =====
    if WEBHOOK_URL:
        logger.info(f"🔗 Setting webhook to: {WEBHOOK_URL}/webhook")
        
        try:
            # Delete any existing webhook
            app.bot.delete_webhook()
            logger.info("✅ Old webhook deleted")
            
            # Set new webhook
            webhook_full_url = f"{WEBHOOK_URL}/webhook"
            app.bot.set_webhook(url=webhook_full_url)
            logger.info(f"✅ Webhook set to: {webhook_full_url}")
            
            # Start Flask with webhook
            logger.info("🚀 Starting bot in webhook mode on Render...")
            run_flask_with_webhook(app)
            
        except Exception as e:
            logger.error(f"Webhook setup error: {e}")
            logger.info("🔄 Falling back to polling mode...")
            app.run_polling()
    else:
        # Use polling mode (for local development)
        logger.info("🚀 Starting bot in polling mode...")
        app.run_polling()

# ==============================================================================
# 7. QUICK COMMANDS
# ==============================================================================
async def clear_webhook():
    """Clear webhook - run this once if you have issues"""
    app = Application.builder().token(BOT_TOKEN).build()
    await app.bot.delete_webhook()
    print("✅ Webhook cleared!")

# ==============================================================================
# 8. ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    from datetime import datetime
    
    # Check if we need to clear webhook
    if os.environ.get("CLEAR_WEBHOOK", "").lower() == "true":
        import asyncio
        asyncio.run(clear_webhook())
    
    main()
