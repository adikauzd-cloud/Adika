import logging
import os
import threading
import re
import sys
from typing import Optional, List, Dict, Any, Tuple
import psycopg2
from flask import Flask, jsonify
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
# 0. FLASK WEB SERVER - MODIFIED FOR RENDER
# ==============================================================================
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return jsonify({
        "status": "online",
        "service": "Adika Marketplace Bot",
        "version": "2.0.0",
        "environment": os.environ.get("RENDER", "development")
    }), 200

@web_app.route('/health')
def health():
    try:
        # Check database connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return jsonify({
        "status": "healthy",
        "database": db_status,
        "timestamp": time.time()
    }), 200

def run_flask():
    # Render provides PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    # Bind to 0.0.0.0 to accept all connections
    web_app.run(host="0.0.0.0", port=port, debug=False)

# ==============================================================================
# 1. CONFIGURATION & LOGGING
# ==============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "0")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable ውስጥ አልተገኘም።")

ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 0

# Configure logging for production
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("adika_bot.log")
    ]
)
logger = logging.getLogger(__name__)

# ==============================================================================
# 2. DATABASE - WITH RETRY LOGIC FOR RENDER
# ==============================================================================
def get_db_connection():
    """Get database connection with retry logic for Render"""
    max_retries = 5
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            if DATABASE_URL:
                db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
                conn = psycopg2.connect(db_url)
                conn.autocommit = True
                return conn
            else:
                import sqlite3
                return sqlite3.connect("adika_marketplace.db")
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Database connection attempt {attempt + 1} failed: {e}")
                time.sleep(retry_delay)
            else:
                logger.error(f"All database connection attempts failed: {e}")
                raise

def get_placeholder():
    return "%s" if DATABASE_URL else "?"

def init_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Drop existing tables for clean setup
        if DATABASE_URL:
            cursor.execute("DROP TABLE IF EXISTS listings CASCADE;")
            cursor.execute("DROP TABLE IF EXISTS brokers CASCADE;")
        else:
            cursor.execute("DROP TABLE IF EXISTS listings;")
            cursor.execute("DROP TABLE IF EXISTS brokers;")
        
        # Listings table - EXACTLY 11 COLUMNS
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE listings (
                    id SERIAL PRIMARY KEY,
                    user_chat_id BIGINT NOT NULL,
                    user_name TEXT,
                    req_type TEXT NOT NULL,
                    main_category TEXT NOT NULL,
                    sub_category TEXT,
                    action_type TEXT,
                    property_type TEXT,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_chat_id INTEGER NOT NULL,
                    user_name TEXT,
                    req_type TEXT NOT NULL,
                    main_category TEXT NOT NULL,
                    sub_category TEXT,
                    action_type TEXT,
                    property_type TEXT,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        # Brokers table
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE brokers (
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
                CREATE TABLE brokers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    location TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        # Indexes
        if DATABASE_URL:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_category ON listings(main_category, sub_category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_brokers_chat_id ON brokers(chat_id)")
        else:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_category ON listings(main_category, sub_category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_brokers_chat_id ON brokers(chat_id)")
        
        if DATABASE_URL:
            conn.commit()
        logger.info("✅ Database initialized successfully with 11 columns")
        
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise
    finally:
        if conn:
            conn.close()

# ========== LISTING FUNCTIONS ==========
def add_listing(user_chat_id, user_name, req_type, main_category, sub_category, 
                action_type, property_type, description):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        if DATABASE_URL:
            cursor.execute(f"""
                INSERT INTO listings 
                (user_chat_id, user_name, req_type, main_category, sub_category, 
                 action_type, property_type, description)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) RETURNING id
            """, (user_chat_id, user_name, req_type, main_category, sub_category, 
                  action_type, property_type, description))
            req_id = cursor.fetchone()[0]
            conn.commit()
        else:
            cursor.execute("""
                INSERT INTO listings 
                (user_chat_id, user_name, req_type, main_category, sub_category, 
                 action_type, property_type, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_chat_id, user_name, req_type, main_category, sub_category, 
                  action_type, property_type, description))
            req_id = cursor.lastrowid
            conn.commit()
        return req_id
    except Exception as e:
        logger.error(f"Add listing error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_listings_by_category(main_category=None, sub_category=None, action_type=None, 
                             property_type=None, limit=10, offset=0):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        query = "SELECT * FROM listings WHERE status = 'pending'"
        params = []
        
        if main_category:
            query += f" AND main_category = {p}"
            params.append(main_category)
        if sub_category:
            query += f" AND sub_category = {p}"
            params.append(sub_category)
        if action_type:
            query += f" AND action_type = {p}"
            params.append(action_type)
        if property_type:
            query += f" AND property_type = {p}"
            params.append(property_type)
        
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        if DATABASE_URL:
            cursor.execute(query.replace("?", p), params)
        else:
            cursor.execute(query, params)
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logger.error(f"Get listings error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_listing(req_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        if DATABASE_URL:
            cursor.execute(f"SELECT * FROM listings WHERE id = {p}", (req_id,))
        else:
            cursor.execute("SELECT * FROM listings WHERE id = ?", (req_id,))
        row = cursor.fetchone()
        return row
    except Exception as e:
        logger.error(f"Get listing error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def update_listing_status(req_id, status):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        if DATABASE_URL:
            cursor.execute(f"UPDATE listings SET status = {p} WHERE id = {p}", (status, req_id))
        else:
            cursor.execute("UPDATE listings SET status = ? WHERE id = ?", (status, req_id))
        if DATABASE_URL:
            conn.commit()
        else:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Update listing error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def count_listings(main_category=None, sub_category=None, action_type=None, property_type=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        query = "SELECT COUNT(*) FROM listings WHERE status = 'pending'"
        params = []
        
        if main_category:
            query += f" AND main_category = {p}"
            params.append(main_category)
        if sub_category:
            query += f" AND sub_category = {p}"
            params.append(sub_category)
        if action_type:
            query += f" AND action_type = {p}"
            params.append(action_type)
        if property_type:
            query += f" AND property_type = {p}"
            params.append(property_type)
        
        if DATABASE_URL:
            cursor.execute(query.replace("?", p), params)
        else:
            cursor.execute(query, params)
        count = cursor.fetchone()[0]
        return count
    except Exception as e:
        logger.error(f"Count listings error: {e}")
        return 0
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
            cursor.execute("""
                INSERT INTO brokers (chat_id, full_name, phone, location)
                VALUES (?, ?, ?, ?)
            """, (chat_id, full_name, phone, location))
            broker_id = cursor.lastrowid
            conn.commit()
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
        if DATABASE_URL:
            cursor.execute(f"SELECT * FROM brokers WHERE chat_id = {p}", (chat_id,))
        else:
            cursor.execute("SELECT * FROM brokers WHERE chat_id = ?", (chat_id,))
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
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ መመዝገብ", "📋 የፈላጊዎች ዝርዝር"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]

LOCATIONS = ["ቦሌ", "ሲኤምሲ", "ሳሪስ", "አያት", "ገርጂ", "ካዛንችስ", "መገናኛ", "ቃሊቲ", "ልደታ", "አራዳ"]

CAR_SUB_CATEGORIES = ["🚗 የቤት መኪና", "🚚 የሥራ መኪና", "🚜 ከባድ ተሽከርካሪ/ማሽን"]

HOUSE_TYPES = ["🏡 ቪላ", "🏢 ሙሉ ግቢ", "🏢 አፓርታማ", "🏢 ሪል እስቴት", "🏞️ መሬት/ቦታ"]

ACTION_TYPES = ["🛍️ ሽያጭ", "🔑 ኪራይ"]

PROPERTY_TYPES = ["🏠 መኖሪያ", "🏢 የሥራ ቦታ"]

# ==============================================================================
# 4. CONVERSATION STATES
# ==============================================================================
BUYER_MAIN, BUYER_ACTION, BUYER_CATEGORY, BUYER_SUB, BUYER_PROPERTY, BUYER_DETAILS, BUYER_PHONE = range(7)

SELLER_MAIN, SELLER_ACTION, SELLER_CATEGORY, SELLER_SUB, SELLER_PROPERTY, \
SELLER_LOCATION, SELLER_DETAILS, SELLER_PRICE, SELLER_NEGO, \
SELLER_PHOTO, SELLER_PHONE, SELLER_CONFIRM = range(7, 18)

BROKER_NAME, BROKER_PHONE, BROKER_LOCATION = range(18, 21)

RESP_MAIN, RESP_ROLE, RESP_PROPERTY, RESP_SUB, RESP_DETAILS, RESP_PRICE, RESP_NEGO, RESP_PHONE, RESP_PHOTO = range(21, 30)

# ==============================================================================
# 5. HELPER FUNCTIONS
# ==============================================================================
def validate_phone(phone: str) -> bool:
    phone = phone.replace(' ', '').replace('-', '')
    pattern = r'^(09|07|01)\d{8}$|^\+251(09|07|01)\d{8}$'
    return bool(re.match(pattern, phone))

def validate_price(price: str) -> bool:
    price = price.replace(',', '').replace(' ', '')
    pattern = r'^[\d]+(\.[\d]{2})?$'
    return bool(re.match(pattern, price))

# ==============================================================================
# 6. START & MAIN MENU
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = (
        "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
        "የሀገሪቱ ታላቁ የመኪና፣ የቤት እና የንብረት ገበያ ማዕከል።\n\n"
        "እባክዎን ከታች ካሉት አማራጮች አንዱን ይምረጡ፦"
    )
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    return ConversationHandler.END

# ==============================================================================
# 7. CANCEL & HOME HANDLER
# ==============================================================================
async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = (
        "👋 **ወደ ዋና ገጽ ተመልሰዋል!**\n\n"
        "እባክዎን ከታች ካሉት አማራጮች አንዱን ይምረጡ፦"
    )
    reply_markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
    
    return ConversationHandler.END

# ==============================================================================
# 8. BUYER FLOW - (የቀደሙት ተግባራት እዚህ ይቀመጣሉ)
# ==============================================================================
# [BUYER FLOW FUNCTIONS - SAME AS BEFORE]
# buyer_start, buyer_category_chosen, buyer_sub_chosen, buyer_action_chosen,
# buyer_property_chosen, buyer_htype_chosen, buyer_details, buyer_phone

# ==============================================================================
# 9. VIEW REQUESTS - WITH SAFE UNPACKING
# ==============================================================================
ITEMS_PER_PAGE = 5

async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    broker = get_broker(user_id)
    if not broker:
        await update.message.reply_text(
            "⛔ ይህን ገጽ ማየት የሚችሉት የተመዘገቡ አቅራቢዎች/ደላሎች ብቻ ናቸው!\n\n"
            "📝 እባክዎን መጀመሪያ '📝 እንደ አቅራቢ መመዝገብ' ይምረጡ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    context.user_data['view_page'] = 0
    await show_requests_page(update, context)

async def show_requests_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        page = context.user_data.get('view_page', 0)
        offset = page * ITEMS_PER_PAGE
        
        listings = get_listings_by_category(limit=ITEMS_PER_PAGE, offset=offset)
        total = count_listings()
        total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        
        if not listings:
            text = "📭 ምንም ንቁ ጥያቄዎች የሉም።"
            if update.message:
                await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
            else:
                query = update.callback_query
                await query.answer()
                await query.edit_message_text(text, reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
            return
        
        text = f"📋 **የፈላጊዎች ዝርዝር** (ገጽ {page+1}/{total_pages})\n\n"
        
        # SAFE UNPACKING - EXACTLY 11 COLUMNS
        for row in listings:
            if len(row) >= 11:
                (listing_id, user_chat_id, user_name, req_type, main_category, 
                 sub_category, action_type, property_type, description, 
                 status, created_at) = row[:11]
            else:
                # Fallback for safety
                listing_id = row[0] if len(row) > 0 else "N/A"
                user_chat_id = row[1] if len(row) > 1 else "N/A"
                user_name = row[2] if len(row) > 2 else "Unknown"
                req_type = row[3] if len(row) > 3 else "N/A"
                main_category = row[4] if len(row) > 4 else "N/A"
                sub_category = row[5] if len(row) > 5 else "N/A"
                action_type = row[6] if len(row) > 6 else "N/A"
                property_type = row[7] if len(row) > 7 else "N/A"
                description = row[8] if len(row) > 8 else "No Description"
                status = row[9] if len(row) > 9 else "pending"
                created_at = row[10] if len(row) > 10 else None
            
            icon = "🚗" if main_category == "car" else "🏠" if main_category == "house" else "🏢"
            action_icon = "🛍️" if action_type == "sell" else "🔑"
            
            desc_text = description[:100] if description else ''
            if len(description) > 100:
                desc_text += "..."
            
            text += f"{icon} **#{listing_id}** {action_icon}\n"
            text += f"👤 {user_name}\n"
            text += f"📝 {desc_text}\n"
            
            if created_at and hasattr(created_at, 'strftime'):
                text += f"📅 {created_at.strftime('%Y-%m-%d %H:%M')}\n"
            text += "────────────────────\n"
        
        # Response buttons
        keyboard = []
        for row in listings:
            if len(row) >= 11:
                (listing_id, user_chat_id, user_name, req_type, main_category, 
                 sub_category, action_type, property_type, description, 
                 status, created_at) = row[:11]
            else:
                listing_id = row[0] if len(row) > 0 else "N/A"
                user_chat_id = row[1] if len(row) > 1 else "N/A"
                main_category = row[4] if len(row) > 4 else "car"
            
            keyboard.append([
                InlineKeyboardButton(
                    f"✅ አለኝ - #{listing_id}",
                    callback_data=f"item_resp_{listing_id}_{user_chat_id}_{main_category}"
                )
            ])
        
        # Pagination
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ ቀዳሚ", callback_data=f"page_{page-1}"))
        if offset + ITEMS_PER_PAGE < total:
            nav_buttons.append(InlineKeyboardButton("➡️ ቀጣይ", callback_data=f"page_{page+1}"))
        nav_buttons.append(InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home"))
        keyboard.append(nav_buttons)
        
        if update.message:
            await update.message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        else:
            query = update.callback_query
            await query.answer()
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logger.error(f"Error in show_requests_page: {e}")
        error_text = "❌ የሆነ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።"
        if update.message:
            await update.message.reply_text(error_text, reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
        else:
            query = update.callback_query
            await query.answer()
            await query.edit_message_text(error_text, reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))

# ==============================================================================
# 10. RESPONSE FLOW - (የቀደሙት ተግባራት እዚህ ይቀመጣሉ)
# ==============================================================================
# [RESPONSE FLOW FUNCTIONS - SAME AS BEFORE]
# start_item_response, resp_role_chosen, resp_property_chosen, resp_htype_chosen,
# resp_details, resp_price, resp_nego, resp_phone, resp_photo

# ==============================================================================
# 11. BROKER REGISTRATION - (የቀደሙት ተግባራት እዚህ ይቀመጣሉ)
# ==============================================================================
# [BROKER REGISTRATION FUNCTIONS - SAME AS BEFORE]
# broker_reg_start, broker_reg_name, broker_reg_phone, broker_reg_location

# ==============================================================================
# 12. HELP & ERROR HANDLER
# ==============================================================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
❓ **እንዴት እንደሚጠቀሙ**

🔍 **መግዛት ከፈለጉ:**
• '🔍 መግዛት / መከራየት' ይምረጡ
• ምድብ ይምረጡ (መኪና/ቤት/ንግድ)
• ንኡስ ምድብ ይምረጡ
• መረጃ ይሙሉ

📢 **መሸጥ ከፈለጉ:**
• '📢 መሸጥ / ማከራየት' ይምረጡ
• የድርጊት አይነት ይምረጡ
• ምድብ ይምረጡ
• በቅደም ተከተል መረጃዎችን ይሙሉ
• በመጨረሻ ማረጋገጫ ይስጡ

📝 **እንደ አቅራቢ ለመመዝገብ:**
• '📝 እንደ አቅራቢ መመዝገብ' ይምረጡ
• መረጃ ይሙሉ
• ጥያቄዎችን ማየት ይችላሉ

📋 **የፈላጊዎች ዝርዝር:**
• ለተመዘገቡ አቅራቢዎች ብቻ
• ንቁ ጥያቄዎችን ያሳያል
• በገጽ ይከፋፈላል
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}", exc_info=True)
    
    if update and hasattr(update, 'effective_user'):
        try:
            await context.bot.send_message(
                chat_id=update.effective_user.id,
                text="❌ የሆነ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ ወይም እርዳታ ለማግኘት '📞 ድጋፍ' ይጫኑ።",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        except Exception as e:
            logger.error(f"Error sending error message: {e}")

# ==============================================================================
# 13. MAIN FUNCTION - MODIFIED FOR RENDER
# ==============================================================================
def main():
    try:
        # Initialize database
        init_db()
        logger.info("✅ Database initialized successfully")
        
        # Start Flask server in a separate thread
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        logger.info(f"✅ Flask server started on port {os.environ.get('PORT', 8080)}")
        
        # Create and configure bot application
        app = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_command))
        
        cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
        cancel_message_handler = MessageHandler(cancel_filter, go_home)
        
        # ===== BUYER CONVERSATION =====
        buyer_conv = ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
            states={
                BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_message_handler],
                BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_"), cancel_message_handler],
                BUYER_CATEGORY: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_message_handler],
                BUYER_SUB: [CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_"), 
                           CallbackQueryHandler(buyer_htype_chosen, pattern="^flow_buy_htype_"), cancel_message_handler],
                BUYER_PROPERTY: [CallbackQueryHandler(buyer_property_chosen, pattern="^flow_buy_prop_"), cancel_message_handler],
                BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details), cancel_message_handler],
                BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone), cancel_message_handler],
            },
            fallbacks=[CommandHandler("start", start), cancel_message_handler],
            allow_reentry=True,
        )
        
        # ===== BROKER REGISTRATION =====
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
        
        # ===== RESPONSE CONVERSATION =====
        response_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(start_item_response, pattern="^item_resp_")],
            states={
                RESP_MAIN: [CallbackQueryHandler(resp_role_chosen, pattern="^resp_role_"), cancel_message_handler],
                RESP_PROPERTY: [CallbackQueryHandler(resp_property_chosen, pattern="^resp_prop_"), cancel_message_handler],
                RESP_SUB: [CallbackQueryHandler(resp_htype_chosen, pattern="^resp_htype_"), cancel_message_handler],
                RESP_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_details), cancel_message_handler],
                RESP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_price), cancel_message_handler],
                RESP_NEGO: [CallbackQueryHandler(resp_nego, pattern="^resp_nego_"), cancel_message_handler],
                RESP_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_phone), cancel_message_handler],
                RESP_PHOTO: [MessageHandler(filters.PHOTO, resp_photo), cancel_message_handler],
            },
            fallbacks=[CommandHandler("start", start), cancel_message_handler],
            allow_reentry=True,
        )
        
        # ===== OTHER HANDLERS =====
        app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
        app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
        app.add_handler(MessageHandler(cancel_filter, go_home))
        
        app.add_handler(CallbackQueryHandler(show_requests_page, pattern="^page_"))
        app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
        
        # ===== ADD CONVERSATIONS =====
        app.add_handler(buyer_conv)
        app.add_handler(broker_conv)
        app.add_handler(response_conv)
        
        # ===== ERROR HANDLER =====
        app.add_error_handler(error_handler)
        
        # ===== START BOT =====
        logger.info("🚀 Adika Marketplace Bot is starting...")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    # Add time module for health check
    import time
    main()