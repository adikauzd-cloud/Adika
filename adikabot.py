import logging
import os
import threading
import psycopg2
from flask import Flask
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
# 0. FLASK WEB SERVER
# ==============================================================================
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "✅ Adika Marketplace Bot በስኬት እየሰራ ይገኛል!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# ==============================================================================
# 1. CONFIGURATION & LOGGING
# ==============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "0")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

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
        
        # Listings table with enhanced fields
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
        
        # Brokers table
        if DATABASE_URL:
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
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        # Generate request ID
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

def get_listings_by_category(main_category=None, sub_category=None, action_type=None, property_type=None, limit=10, offset=0):
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
        
        cursor.execute(query.replace("?", p) if DATABASE_URL else query, params)
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logger.error(f"Get listings error: {e}")
        return []
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

def get_listing(req_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM listings WHERE id = {p}", (req_id,))
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
        
        cursor.execute(query.replace("?", p) if DATABASE_URL else query, params)
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

LOCATIONS = ["ቦሌ", "ሲኤምሲ", "ሳሪስ", "አያት", "ገርጂ", "ካዛንችስ", "መገናኛ", "ቃሊቲ", "ልደታ", "አራዳ"]

CAR_SUB_CATEGORIES = ["🚗 የቤት መኪና", "🚚 የሥራ መኪና", "🚜 ከባድ ተሽከርካሪ/ማሽን"]

HOUSE_TYPES = ["🏢 ኮንዶሚኒየም", "🏡 ቪላ / መኖሪያ ቤት", "🏬 ንግድ ቤት/ፎቅ", "📐 ባዶ ቦታ/መሬት"]

PROPERTY_TYPES = ["🏠 መኖሪያ", "🏢 የሥራ ቦታ"]

# ==============================================================================
# 4. CONVERSATION STATES
# ==============================================================================
# Car Buyer States
CAR_BUYER_MODEL, CAR_BUYER_YEAR, CAR_BUYER_BUDGET, CAR_BUYER_CONTACT = range(4)

# Car Seller States
CAR_SELLER_MODEL, CAR_SELLER_YEAR_COND, CAR_SELLER_PRICE, CAR_SELLER_NEGO, CAR_SELLER_CONTACT = range(4, 9)

# House States
HOUSE_BUYER_TYPE, HOUSE_BUYER_LOCATION, HOUSE_BUYER_PRICE, HOUSE_BUYER_NEGO, HOUSE_BUYER_CONTACT = range(9, 14)
HOUSE_SELLER_TYPE, HOUSE_SELLER_LOCATION, HOUSE_SELLER_PRICE, HOUSE_SELLER_NEGO, HOUSE_SELLER_CONTACT = range(14, 19)

# Common States
COMMON_PHOTO, COMMON_CONFIRM = range(19, 21)

# Broker Registration States
BROKER_NAME, BROKER_PHONE, BROKER_LOCATION = range(21, 24)

# ==============================================================================
# 5. START & MAIN MENU
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

# ==============================================================================
# 6. CANCEL HANDLER
# ==============================================================================
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
# 7. CAR BUYER FLOW
# ==============================================================================
async def car_buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    context.user_data['main_category'] = 'car'
    context.user_data['action_type'] = 'buy'
    
    await update.message.reply_text(
        "🚗 **መኪና ለመግዛት**\n\n"
        "1️⃣ እባክዎን የሚፈልጉትን የመኪና ዓይነት ወይም ሞዴል ያክሉ?\n"
        "💡 *ምሳሌ፦* Toyota Vitz, Hyundai Tucson, Ford...",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ወደ ዋና ገጽ"]], resize_keyboard=True)
    )
    return CAR_BUYER_MODEL

async def car_buyer_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['car_model'] = update.message.text
    await update.message.reply_text(
        "2️⃣ የምርት ዘመን ይምረጡ ወይም ያስገቡ (ከስንት እስከ ስንት)?\n"
        "💡 *ምሳሌ፦* 2015 - 2020",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ወደ ዋና ገጽ"]], resize_keyboard=True)
    )
    return CAR_BUYER_YEAR

async def car_buyer_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['car_year'] = update.message.text
    await update.message.reply_text(
        "3️⃣ መመደብ የሚችሉት የበጀት መጠን ስንት ነው?\n"
        "💡 *ምሳሌ፦* 2,000,000 - 3,000,000 ብር",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ወደ ዋና ገጽ"]], resize_keyboard=True)
    )
    return CAR_BUYER_BUDGET

async def car_buyer_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['budget'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("📱 ስልክ ቁጥር ለማስገባት", callback_data="contact_phone")],
        [InlineKeyboardButton("✈️ በTelegram Username", callback_data="contact_username")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "4️⃣ የፍላጎትዎን መረጃ መዝግበናል።\n\n"
        "እርስዎን ለማነጋገር የትኛውን የመገናኛ መንገድ ይጠቀማሉ?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CAR_BUYER_CONTACT

async def car_buyer_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    method = query.data.replace("contact_", "")
    context.user_data['contact_method'] = "phone" if method == "phone" else "username"
    
    if method == "phone":
        await query.edit_message_text(
            "📱 **እባክዎን የስልክ ቁጥርዎን ያስገቡ፦**\n"
            "💡 *ምሳሌ፦* 0911XXXXXX",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            "✈️ **እባክዎን የቴሌግራም አድራሻዎን ያስገቡ፦**\n"
            "💡 *ምሳሌ፦* @yourusername",
            parse_mode="Markdown"
        )
    return COMMON_CONTACT

# ==============================================================================
# 8. CAR SELLER FLOW
# ==============================================================================
async def car_seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    context.user_data['main_category'] = 'car'
    context.user_data['action_type'] = 'sell'
    
    await update.message.reply_text(
        "🚗 **መኪና ለመሸጥ**\n\n"
        "1️⃣ የሚሸጡትን መኪና ሞዴል እና የሰሪው ስም ያስገቡ\n"
        "💡 *ምሳሌ፦* Toyota Yaris Executive",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ወደ ዋና ገጽ"]], resize_keyboard=True)
    )
    return CAR_SELLER_MODEL

async def car_seller_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['car_model'] = update.message.text
    await update.message.reply_text(
        "2️⃣ የመኪናውን የምርት ዘመን (Year) እና ያገለገለበትን ሁኔታ ያስገቡ\n"
        "💡 *ምሳሌ፦* 2018፣ በኢትዮጵያ ያልተነዳ / ያገለገለ",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ወደ ዋና ገጽ"]], resize_keyboard=True)
    )
    return CAR_SELLER_YEAR_COND

async def car_seller_year_cond(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['car_year_cond'] = update.message.text
    await update.message.reply_text(
        "3️⃣ የመኪናው መሸጫ ዋጋ ስንት ነው?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ወደ ዋና ገጽ"]], resize_keyboard=True)
    )
    return CAR_SELLER_PRICE

async def car_seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🤝 ድርድር አለው", callback_data="nego_yes")],
        [InlineKeyboardButton("🔒 ቋሚ ዋጋ ነው", callback_data="nego_no")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🔄 **የዋጋው ሁኔታ እንዴት ነው?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CAR_SELLER_NEGO

async def car_seller_nego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['negotiable'] = "🤝 ድርድር አለው" if query.data == "nego_yes" else "🔒 ቋሚ ዋጋ"
    
    keyboard = [
        [InlineKeyboardButton("📱 ስልክ ቁጥር ለማስገባት", callback_data="contact_phone")],
        [InlineKeyboardButton("✈️ በTelegram Username", callback_data="contact_username")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await query.edit_message_text(
        "4️⃣ **የመገናኛ አማራጭዎን ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CAR_SELLER_CONTACT

async def car_seller_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    method = query.data.replace("contact_", "")
    context.user_data['contact_method'] = "phone" if method == "phone" else "username"
    
    if method == "phone":
        await query.edit_message_text(
            "📱 **እባክዎን የስልክ ቁጥርዎን ያስገቡ፦**",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            "✈️ **እባክዎን የቴሌግራም አድራሻዎን ያስገቡ፦**",
            parse_mode="Markdown"
        )
    return COMMON_CONTACT

# ==============================================================================
# 9. HOUSE BUYER FLOW
# ==============================================================================
async def house_buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    context.user_data['main_category'] = 'house'
    context.user_data['action_type'] = 'buy'
    
    keyboard = []
    for htype in HOUSE_TYPES:
        keyboard.append([InlineKeyboardButton(htype, callback_data=f"hbuy_type_{htype}")])
    keyboard.append([InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")])
    
    await update.message.reply_text(
        "🏠 **ቤት/ቦታ ለመግዛት**\n\n"
        "1️⃣ የሚፈልጉትን የቦታ/ንብረት አይነት ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_BUYER_TYPE

async def house_buyer_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['house_type'] = query.data.replace("hbuy_type_", "")
    context.user_data['property_type'] = "residential" if "ቪላ" in query.data or "ኮንዶ" in query.data else "commercial"
    
    await query.edit_message_text(
        f"🏠 **{context.user_data['house_type']}**\n\n"
        "2️⃣ ንብረቱ የሚገኝበትን ቦታ/አድራሻ ያስገቡ\n"
        "💡 *ምሳሌ፦* አዲስ አበባ፣ ቦሌ ክፍለ ከተማ፣ አትላስ አካባቢ",
        parse_mode="Markdown"
    )
    return HOUSE_BUYER_LOCATION

async def house_buyer_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['location'] = update.message.text
    await update.message.reply_text(
        "3️⃣ የንብረቱ ጠቅላላ ዋጋ ስንት ነው? (በብር)",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ወደ ዋና ገጽ"]], resize_keyboard=True)
    )
    return HOUSE_BUYER_PRICE

async def house_buyer_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🤝 ድርድር አለው", callback_data="nego_yes")],
        [InlineKeyboardButton("🔒 ቋሚ ዋጋ ነው", callback_data="nego_no")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🔄 **የዋጋው ሁኔታ እንዴት ነው?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_BUYER_NEGO

async def house_buyer_nego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['negotiable'] = "🤝 ድርድር አለው" if query.data == "nego_yes" else "🔒 ቋሚ ዋጋ"
    
    keyboard = [
        [InlineKeyboardButton("📱 ስልክ ቁጥር ለማስገባት", callback_data="contact_phone")],
        [InlineKeyboardButton("✈️ በTelegram Username", callback_data="contact_username")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await query.edit_message_text(
        "4️⃣ **የመገናኛ አማራጭዎን ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_BUYER_CONTACT

async def house_buyer_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    method = query.data.replace("contact_", "")
    context.user_data['contact_method'] = "phone" if method == "phone" else "username"
    
    if method == "phone":
        await query.edit_message_text(
            "📱 **እባክዎን የስልክ ቁጥርዎን ያስገቡ፦**",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            "✈️ **እባክዎን የቴሌግራም አድራሻዎን ያስገቡ፦**",
            parse_mode="Markdown"
        )
    return COMMON_CONTACT

# ==============================================================================
# 10. HOUSE SELLER FLOW
# ==============================================================================
async def house_seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    context.user_data['main_category'] = 'house'
    context.user_data['action_type'] = 'sell'
    
    keyboard = []
    for htype in HOUSE_TYPES:
        keyboard.append([InlineKeyboardButton(htype, callback_data=f"hsell_type_{htype}")])
    keyboard.append([InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")])
    
    await update.message.reply_text(
        "🏠 **ቤት/ቦታ ለመሸጥ**\n\n"
        "1️⃣ የሚሸጡትን የቦታ/ንብረት አይነት ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_SELLER_TYPE

async def house_seller_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['house_type'] = query.data.replace("hsell_type_", "")
    context.user_data['property_type'] = "residential" if "ቪላ" in query.data or "ኮንዶ" in query.data else "commercial"
    
    await query.edit_message_text(
        f"🏠 **{context.user_data['house_type']}**\n\n"
        "2️⃣ ንብረቱ የሚገኝበትን ቦታ/አድራሻ ያስገቡ\n"
        "💡 *ምሳሌ፦* አዲስ አበባ፣ ቦሌ ክፍለ ከተማ፣ አትላስ አካባቢ",
        parse_mode="Markdown"
    )
    return HOUSE_SELLER_LOCATION

async def house_seller_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['location'] = update.message.text
    await update.message.reply_text(
        "3️⃣ የንብረቱ ጠቅላላ ዋጋ ስንት ነው? (በብር)",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ወደ ዋና ገጽ"]], resize_keyboard=True)
    )
    return HOUSE_SELLER_PRICE

async def house_seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🤝 ድርድር አለው", callback_data="nego_yes")],
        [InlineKeyboardButton("🔒 ቋሚ ዋጋ ነው", callback_data="nego_no")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🔄 **የዋጋው ሁኔታ እንዴት ነው?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_SELLER_NEGO

async def house_seller_nego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['negotiable'] = "🤝 ድርድር አለው" if query.data == "nego_yes" else "🔒 ቋሚ ዋጋ"
    
    keyboard = [
        [InlineKeyboardButton("📱 ስልክ ቁጥር ለማስገባት", callback_data="contact_phone")],
        [InlineKeyboardButton("✈️ በTelegram Username", callback_data="contact_username")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await query.edit_message_text(
        "4️⃣ **የመገናኛ አማራጭዎን ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_SELLER_CONTACT

async def house_seller_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    method = query.data.replace("contact_", "")
    context.user_data['contact_method'] = "phone" if method == "phone" else "username"
    
    if method == "phone":
        await query.edit_message_text(
            "📱 **እባክዎን የስልክ ቁጥርዎን ያስገቡ፦**",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            "✈️ **እባክዎን የቴሌግራም አድራሻዎን ያስገቡ፦**",
            parse_mode="Markdown"
        )
    return COMMON_CONTACT

# ==============================================================================
# 11. COMMON CONTACT & CONFIRMATION
# ==============================================================================
COMMON_CONTACT = 50

async def common_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['contact_info'] = update.message.text
    
    # Build summary
    req_type = context.user_data.get('req_type', 'BUY')
    main_cat = context.user_data.get('main_category', '')
    action = context.user_data.get('action_type', '')
    
    if main_cat == 'car':
        if req_type == 'BUY':
            summary = (
                f"🚗 **መኪና ጥያቄ**\n\n"
                f"📌 ሞዴል: {context.user_data.get('car_model')}\n"
                f"📅 ዘመን: {context.user_data.get('car_year')}\n"
                f"💰 በጀት: {context.user_data.get('budget')}\n"
                f"📞 መገናኛ: {context.user_data.get('contact_method')} - {context.user_data.get('contact_info')}"
            )
        else:
            summary = (
                f"🚗 **መኪና ለሽያጭ**\n\n"
                f"📌 ሞዴል: {context.user_data.get('car_model')}\n"
                f"📅 ዘመን/ሁኔታ: {context.user_data.get('car_year_cond')}\n"
                f"💰 ዋጋ: {context.user_data.get('price')}\n"
                f"🔄 {context.user_data.get('negotiable')}\n"
                f"📞 መገናኛ: {context.user_data.get('contact_method')} - {context.user_data.get('contact_info')}"
            )
    else:
        if req_type == 'BUY':
            summary = (
                f"🏠 **ቤት ጥያቄ**\n\n"
                f"🏠 አይነት: {context.user_data.get('house_type')}\n"
                f"📍 አካባቢ: {context.user_data.get('location')}\n"
                f"💰 በጀት: {context.user_data.get('price')}\n"
                f"🔄 {context.user_data.get('negotiable')}\n"
                f"📞 መገናኛ: {context.user_data.get('contact_method')} - {context.user_data.get('contact_info')}"
            )
        else:
            summary = (
                f"🏠 **ቤት ለሽያጭ**\n\n"
                f"🏠 አይነት: {context.user_data.get('house_type')}\n"
                f"📍 አካባቢ: {context.user_data.get('location')}\n"
                f"💰 ዋጋ: {context.user_data.get('price')}\n"
                f"🔄 {context.user_data.get('negotiable')}\n"
                f"📞 መገናኛ: {context.user_data.get('contact_method')} - {context.user_data.get('contact_info')}"
            )
    
    keyboard = [
        [InlineKeyboardButton("✅ አረጋግጥ እና ላክ", callback_data="confirm_yes")],
        [InlineKeyboardButton("✏️ አስተካክል", callback_data="confirm_edit")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    
    await update.message.reply_text(
        f"📋 **እባክዎን መረጃዎቹን ያረጋግጡ**\n\n{summary}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return COMMON_CONFIRM

# ==============================================================================
# 12. CONFIRMATION HANDLER
# ==============================================================================
async def confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    
    if query.data == "confirm_edit":
        await query.edit_message_text(
            "✏️ **እባክዎን እንደገና ይሞክሩ።**\n\n"
            "ለመጀመር /start ይበሉ።",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    
    # Confirm and save
    user = update.effective_user
    
    # Prepare data
    req_type = context.user_data.get('req_type', 'BUY')
    main_cat = context.user_data.get('main_category', '')
    sub_cat = context.user_data.get('sub_category', '')
    action_type = context.user_data.get('action_type', '')
    property_type = context.user_data.get('property_type', '')
    
    # Build description
    if main_cat == 'car':
        if req_type == 'BUY':
            desc = f"ሞዴል: {context.user_data.get('car_model')}\nዘመን: {context.user_data.get('car_year')}\nበጀት: {context.user_data.get('budget')}"
        else:
            desc = f"ሞዴል: {context.user_data.get('car_model')}\nዘመን/ሁኔታ: {context.user_data.get('car_year_cond')}"
    else:
        desc = f"አይነት: {context.user_data.get('house_type')}\nአካባቢ: {context.user_data.get('location')}"
    
    # Add common fields
    desc += f"\nዋጋ: {context.user_data.get('price', 'N/A')}"
    desc += f"\n{context.user_data.get('negotiable', '')}"
    desc += f"\nመገናኛ: {context.user_data.get('contact_method')} - {context.user_data.get('contact_info')}"
    
    # Save to database
    listing_id, req_id = add_listing(
        user.id, user.first_name, req_type, main_cat, sub_cat, action_type,
        property_type, desc, context.user_data.get('price'), 
        context.user_data.get('negotiable'), context.user_data.get('contact_method'),
        context.user_data.get('contact_info')
    )
    
    if listing_id:
        action_kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ አለኝ", callback_data=f"item_resp_{listing_id}_{user.id}_{main_cat}")]
        ])
        
        await query.edit_message_text(
            f"✅ **መረጃዎ በስኬት ተመዝግቧል!**\n\n"
            f"🆔 የጥያቄ መለያ: `{req_id}`\n\n"
            f"📌 መረጃዎ በ'📋 የእኔ ጥያቄዎች' ውስጥ ይታያል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        
        if ADMIN_CHAT_ID_INT:
            try:
                admin_msg = f"🔔 አዲስ {req_type} ጥያቄ!\n🆔 {req_id}\n\n{desc}"
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID_INT,
                    text=admin_msg,
                    reply_markup=action_kbd,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    
    return ConversationHandler.END

# ==============================================================================
# 13. VIEW MY LISTINGS
# ==============================================================================
async def my_listings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    listings = get_user_listings(user_id)
    
    if not listings:
        await update.message.reply_text(
            "📋 ምንም የተመዘገበ ጥያቄ ወይም ማስታወቂያ የለዎትም።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    text = "📋 **የእኔ ጥያቄዎች / ማስታወቂያዎች**\n\n"
    for listing in listings:
        req_id, chat_id, name, req_type, main_cat, sub_cat, action_type, prop_type, desc, price, nego, contact_method, contact_info, status, request_id, created = listing
        
        icon = "🚗" if main_cat == "car" else "🏠"
        status_icon = "✅" if status == "pending" else "📌"
        
        text += f"{icon} **{request_id}** {status_icon}\n"
        text += f"📝 {desc[:100]}...\n" if len(desc) > 100 else f"📝 {desc}\n"
        text += f"📅 {created.strftime('%Y-%m-%d') if hasattr(created, 'strftime') else created}\n"
        text += f"📊 {status.upper()}\n"
        text += "────────────────────\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ==============================================================================
# 14. HELP
# ==============================================================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📞 **እኛን ለማነጋገር**

📱 ስልክ: +251 911 00 00 00
✈️ ቴሌግራም: @AdikaSupport
📧 ኢሜል: support@adika.com

🕐 የስራ ሰዓት: ሰኞ - ቅዳሜ 8:00 - 18:00

💡 ማንኛውም ጥያቄ ካለዎት ያነጋግሩን!
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ==============================================================================
# 15. MAIN FUNCTION
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))

    cancel_filter = filters.Regex("^🏠 ወደ ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)

    # ===== CAR BUYER CONVERSATION =====
    car_buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🚗 መኪና (ለመግዛት / ለመሸጥ)$"), car_buyer_start)],
        states={
            CAR_BUYER_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_buyer_model), cancel_message_handler],
            CAR_BUYER_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_buyer_year), cancel_message_handler],
            CAR_BUYER_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_buyer_budget), cancel_message_handler],
            CAR_BUYER_CONTACT: [CallbackQueryHandler(car_buyer_contact, pattern="^contact_"), cancel_message_handler],
            COMMON_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, common_contact), cancel_message_handler],
            COMMON_CONFIRM: [CallbackQueryHandler(confirm_handler, pattern="^confirm_"), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== CAR SELLER CONVERSATION =====
    car_seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🚗 መኪና (ለመግዛት / ለመሸጥ)$"), car_seller_start)],
        states={
            CAR_SELLER_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_seller_model), cancel_message_handler],
            CAR_SELLER_YEAR_COND: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_seller_year_cond), cancel_message_handler],
            CAR_SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_seller_price), cancel_message_handler],
            CAR_SELLER_NEGO: [CallbackQueryHandler(car_seller_nego, pattern="^nego_"), cancel_message_handler],
            CAR_SELLER_CONTACT: [CallbackQueryHandler(car_seller_contact, pattern="^contact_"), cancel_message_handler],
            COMMON_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, common_contact), cancel_message_handler],
            COMMON_CONFIRM: [CallbackQueryHandler(confirm_handler, pattern="^confirm_"), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== HOUSE BUYER CONVERSATION =====
    house_buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏠 ቤት/ቦታ (ለመግዛት / ለመሸጥ)$"), house_buyer_start)],
        states={
            HOUSE_BUYER_TYPE: [CallbackQueryHandler(house_buyer_type, pattern="^hbuy_type_"), cancel_message_handler],
            HOUSE_BUYER_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, house_buyer_location), cancel_message_handler],
            HOUSE_BUYER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, house_buyer_price), cancel_message_handler],
            HOUSE_BUYER_NEGO: [CallbackQueryHandler(house_buyer_nego, pattern="^nego_"), cancel_message_handler],
            HOUSE_BUYER_CONTACT: [CallbackQueryHandler(house_buyer_contact, pattern="^contact_"), cancel_message_handler],
            COMMON_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, common_contact), cancel_message_handler],
            COMMON_CONFIRM: [CallbackQueryHandler(confirm_handler, pattern="^confirm_"), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== HOUSE SELLER CONVERSATION =====
    house_seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏠 ቤት/ቦታ (ለመግዛት / ለመሸጥ)$"), house_seller_start)],
        states={
            HOUSE_SELLER_TYPE: [CallbackQueryHandler(house_seller_type, pattern="^hsell_type_"), cancel_message_handler],
            HOUSE_SELLER_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, house_seller_location), cancel_message_handler],
            HOUSE_SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, house_seller_price), cancel_message_handler],
            HOUSE_SELLER_NEGO: [CallbackQueryHandler(house_seller_nego, pattern="^nego_"), cancel_message_handler],
            HOUSE_SELLER_CONTACT: [CallbackQueryHandler(house_seller_contact, pattern="^contact_"), cancel_message_handler],
            COMMON_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, common_contact), cancel_message_handler],
            COMMON_CONFIRM: [CallbackQueryHandler(confirm_handler, pattern="^confirm_"), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== OTHER HANDLERS =====
    app.add_handler(MessageHandler(filters.Regex("^📋 የእኔ ጥያቄዎች / ማስታወቂያዎች$"), my_listings))
    app.add_handler(MessageHandler(filters.Regex("^📞 እኛን ለማነጋገር$"), help_command))
    app.add_handler(MessageHandler(cancel_filter, go_home))
    
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))

    # ===== ADD CONVERSATIONS =====
    app.add_handler(car_buyer_conv)
    app.add_handler(car_seller_conv)
    app.add_handler(house_buyer_conv)
    app.add_handler(house_seller_conv)

    # ===== ERROR HANDLER =====
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} caused error: {context.error}", exc_info=True)

    app.add_error_handler(error_handler)

    logger.info("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    from datetime import datetime
    main()
