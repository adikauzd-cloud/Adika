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
        
        # Listings table
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id SERIAL PRIMARY KEY,
                    user_chat_id BIGINT NOT NULL,
                    user_name TEXT,
                    req_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
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
                    req_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
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
def add_listing(user_chat_id, user_name, req_type, category, description):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        if DATABASE_URL:
            cursor.execute(f"""
                INSERT INTO listings (user_chat_id, user_name, req_type, category, description)
                VALUES ({p}, {p}, {p}, {p}, {p}) RETURNING id
            """, (user_chat_id, user_name, req_type, category, description))
            req_id = cursor.fetchone()[0]
            conn.commit()
        else:
            cursor.execute(f"""
                INSERT INTO listings (user_chat_id, user_name, req_type, category, description)
                VALUES (?, ?, ?, ?, ?)
            """, (user_chat_id, user_name, req_type, category, description))
            req_id = cursor.lastrowid
        return req_id
    except Exception as e:
        logger.error(f"Add listing error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_all_listings():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM listings WHERE status = 'pending' ORDER BY created_at DESC")
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

def get_all_brokers():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM brokers ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logger.error(f"Get all brokers error: {e}")
        return []
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 3. KEYBOARDS
# ==============================================================================
MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ መመዝገብ", "📋 የፈላጊዎች ዝርዝር"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]

LOCATIONS = ["ቦሌ", "ሲኤምሲ", "ሳሪስ", "አያት", "ገርጂ", "ካዛንችስ", "መገናኛ", "ቃሊቲ", "ልደታ", "አራዳ"]

HOUSE_TYPES = ["ቪላ", "ሰርቪስ", "አፓርታማ", "መሬት/የጨረቃ", "ሪል እስቴት"]

# ==============================================================================
# 4. CONVERSATION STATES
# ==============================================================================
# Buyer Car States
BUYER_CAR_MODEL, BUYER_CAR_YEAR, BUYER_CAR_BUDGET, BUYER_CAR_PHONE = range(4)

# Buyer House States
BUYER_HOUSE_LOCATION, BUYER_HOUSE_TYPE, BUYER_HOUSE_BUDGET, BUYER_HOUSE_PHONE = range(4, 8)

# Seller Car States
SELLER_CAR_MODEL, SELLER_CAR_YEAR, SELLER_CAR_PRICE, SELLER_CAR_NEGOTIABLE, SELLER_CAR_PHONE, SELLER_CAR_PHOTO = range(8, 14)

# Seller House States
SELLER_HOUSE_LOCATION, SELLER_HOUSE_TYPE, SELLER_HOUSE_SQFT, SELLER_HOUSE_CONDITION, SELLER_HOUSE_PRICE, SELLER_HOUSE_NEGOTIABLE, SELLER_HOUSE_PHONE, SELLER_HOUSE_PHOTO = range(14, 22)

# Response States
RESP_ROLE, RESP_CAR_MODEL, RESP_CAR_YEAR, RESP_CAR_PRICE, RESP_CAR_NEGOTIABLE, RESP_CAR_PHONE, RESP_CAR_PHOTO = range(22, 29)
RESP_HOUSE_LOCATION, RESP_HOUSE_SQFT, RESP_HOUSE_CONDITION, RESP_HOUSE_PRICE, RESP_HOUSE_NEGOTIABLE, RESP_HOUSE_PHONE, RESP_HOUSE_PHOTO = range(29, 36)

# Broker Registration States
BROKER_NAME, BROKER_PHONE, BROKER_LOCATION = range(36, 39)

# ==============================================================================
# 5. CANCEL HANDLER
# ==============================================================================
async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ሂደቱን ትቶ ወደ ዋና ገጽ ይመልሳል"""
    context.user_data.clear()
    await update.message.reply_text(
        "🏠 ወደ ዋና ገጽ ተመልሰሃል።",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    return ConversationHandler.END

# ==============================================================================
# 6. START & MAIN MENU
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
# 7. BUYER FLOW - CAR
# ==============================================================================
async def buyer_car_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    context.user_data['category'] = 'cat_car'
    await update.message.reply_text(
        "🚗 **የመኪና ጥያቄ**\n\n"
        "1️⃣ የሚፈልጉትን የመኪና ሞዴል ያስገቡ፦\n"
        "💡 *ምሳሌ፦* Toyota Vitz, Hyundai Tucson, Suzuki Swift...",
        parse_mode="Markdown"
    )
    return BUYER_CAR_MODEL

async def buyer_car_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['car_model'] = update.message.text
    await update.message.reply_text(
        "2️⃣ የምርት ዘመን (Year Range) ያስገቡ፦\n"
        "💡 *ምሳሌ፦* 2015 - 2020",
        parse_mode="Markdown"
    )
    return BUYER_CAR_YEAR

async def buyer_car_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['car_year'] = update.message.text
    await update.message.reply_text(
        "3️⃣ ያዘጋጁትን ባጀት (Budget Range) ያስገቡ፦\n"
        "💡 *ምሳሌ፦* 1.5 - 2.5 ሚሊዮን ብር",
        parse_mode="Markdown"
    )
    return BUYER_CAR_BUDGET

async def buyer_car_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['car_budget'] = update.message.text
    await update.message.reply_text(
        "4️⃣ እርስዎን የሚያገኙበትን የስልክ ቁጥር ያስገቡ፦\n"
        "💡 *ምሳሌ፦* 0911XXXXXX",
        parse_mode="Markdown"
    )
    return BUYER_CAR_PHONE

async def buyer_car_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    phone = update.message.text
    
    desc = (
        f"🚗 **መኪና ጥያቄ**\n"
        f"📌 ሞዴል: {context.user_data.get('car_model')}\n"
        f"📅 ዘመን: {context.user_data.get('car_year')}\n"
        f"💰 ባጀት: {context.user_data.get('car_budget')}\n"
        f"📞 ስልክ: {phone}"
    )
    
    req_id = add_listing(user.id, user.first_name, 'BUY', 'cat_car', desc)
    
    if req_id:
        action_kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ አለኝ", callback_data=f"item_resp_{req_id}_{user.id}_cat_car")]
        ])
        
        await update.message.reply_text(
            f"✅ **ጥያቄዎ ተመዝግቧል!** (#REQ-{req_id})\n\n{desc}",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID_INT:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID_INT,
                    text=f"🔔 አዲስ የመኪና ጥያቄ!\n\n{desc}",
                    reply_markup=action_kbd,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    
    return ConversationHandler.END

# ==============================================================================
# 8. BUYER FLOW - HOUSE
# ==============================================================================
async def buyer_house_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    context.user_data['category'] = 'cat_house'
    
    keyboard = []
    for loc in LOCATIONS:
        keyboard.append([InlineKeyboardButton(loc, callback_data=f"hbuy_loc_{loc}")])
    
    await update.message.reply_text(
        "🏠 **የቤት/ቦታ ጥያቄ**\n\n"
        "1️⃣ የሚፈልጉትን አካባቢ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BUYER_HOUSE_LOCATION

async def buyer_house_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['house_location'] = query.data.replace("hbuy_loc_", "")
    
    keyboard = []
    for htype in HOUSE_TYPES:
        keyboard.append([InlineKeyboardButton(htype, callback_data=f"hbuy_type_{htype}")])
    
    await query.edit_message_text(
        f"📍 አካባቢ: {context.user_data['house_location']}\n\n"
        "2️⃣ የቤት አይነት ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BUYER_HOUSE_TYPE

async def buyer_house_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['house_type'] = query.data.replace("hbuy_type_", "")
    
    await query.edit_message_text(
        f"📍 {context.user_data['house_location']}\n"
        f"🏠 {context.user_data['house_type']}\n\n"
        "3️⃣ ያዘጋጁትን ባጀት ያስገቡ፦\n"
        "💡 *ምሳሌ፦* እስከ 10 ሚሊዮን ብር",
        parse_mode="Markdown"
    )
    return BUYER_HOUSE_BUDGET

async def buyer_house_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['house_budget'] = update.message.text
    await update.message.reply_text(
        "4️⃣ እርስዎን የሚያገኙበትን የስልክ ቁጥር ያስገቡ፦",
        parse_mode="Markdown"
    )
    return BUYER_HOUSE_PHONE

async def buyer_house_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    phone = update.message.text
    
    desc = (
        f"🏠 **ቤት ጥያቄ**\n"
        f"📍 አካባቢ: {context.user_data.get('house_location')}\n"
        f"🏠 አይነት: {context.user_data.get('house_type')}\n"
        f"💰 ባጀት: {context.user_data.get('house_budget')}\n"
        f"📞 ስልክ: {phone}"
    )
    
    req_id = add_listing(user.id, user.first_name, 'BUY', 'cat_house', desc)
    
    if req_id:
        action_kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ አለኝ", callback_data=f"item_resp_{req_id}_{user.id}_cat_house")]
        ])
        
        await update.message.reply_text(
            f"✅ **ጥያቄዎ ተመዝግቧል!** (#REQ-{req_id})\n\n{desc}",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID_INT:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID_INT,
                    text=f"🔔 አዲስ የቤት ጥያቄ!\n\n{desc}",
                    reply_markup=action_kbd,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    
    return ConversationHandler.END

# ==============================================================================
# 9. SELLER FLOW - CAR
# ==============================================================================
async def seller_car_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    context.user_data['category'] = 'cat_car'
    await update.message.reply_text(
        "🚗 **መኪና ለሽያጭ**\n\n"
        "1️⃣ የመኪናውን ሞዴል ያስገቡ፦\n"
        "💡 *ምሳሌ፦* Toyota Vitz 2020",
        parse_mode="Markdown"
    )
    return SELLER_CAR_MODEL

async def seller_car_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_car_model'] = update.message.text
    await update.message.reply_text(
        "2️⃣ የምርት ዘመን ያስገቡ፦\n"
        "💡 *ምሳሌ፦* 2020",
        parse_mode="Markdown"
    )
    return SELLER_CAR_YEAR

async def seller_car_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_car_year'] = update.message.text
    await update.message.reply_text(
        "3️⃣ የመሸጫ ዋጋ ያስገቡ፦\n"
        "💡 *ምሳሌ፦* 2,500,000 ብር",
        parse_mode="Markdown"
    )
    return SELLER_CAR_PRICE

async def seller_car_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_car_price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🔄 ድርድር አለው", callback_data="car_nego_yes")],
        [InlineKeyboardButton("❌ ድርድር የለውም", callback_data="car_nego_no")]
    ]
    await update.message.reply_text(
        "4️⃣ የዋጋ ድርድር ሁኔታ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_CAR_NEGOTIABLE

async def seller_car_negotiable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['sell_car_nego'] = "✅ ድርድር አለው" if query.data == "car_nego_yes" else "❌ ድርድር የለውም"
    
    await query.edit_message_text(
        f"💰 ዋጋ: {context.user_data.get('sell_car_price')}\n"
        f"🔄 {context.user_data['sell_car_nego']}\n\n"
        "5️⃣ እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦",
        parse_mode="Markdown"
    )
    return SELLER_CAR_PHONE

async def seller_car_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_car_phone'] = update.message.text
    await update.message.reply_text(
        "6️⃣ የመኪናውን ፎቶ ያስገቡ፦",
        parse_mode="Markdown"
    )
    return SELLER_CAR_PHOTO

async def seller_car_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return SELLER_CAR_PHOTO
    
    desc = (
        f"🚗 **መኪና ለሽያጭ**\n"
        f"📌 ሞዴል: {context.user_data.get('sell_car_model')}\n"
        f"📅 ዘመን: {context.user_data.get('sell_car_year')}\n"
        f"💰 ዋጋ: {context.user_data.get('sell_car_price')}\n"
        f"🔄 {context.user_data.get('sell_car_nego')}\n"
        f"📞 ስልክ: {context.user_data.get('sell_car_phone')}"
    )
    
    req_id = add_listing(user.id, user.first_name, 'SELL', 'cat_car', desc)
    
    if req_id:
        action_kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ እፈልገዋለሁ", callback_data=f"item_resp_{req_id}_{user.id}_cat_car")]
        ])
        
        await update.message.reply_photo(
            photo=photo_id,
            caption=f"✅ **ማስታወቂያ ተመዝግቧል!** (#REQ-{req_id})\n\n{desc}",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID_INT:
            try:
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID_INT,
                    photo=photo_id,
                    caption=f"🔔 አዲስ የመኪና ማስታወቂያ!\n\n{desc}",
                    reply_markup=action_kbd,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    
    return ConversationHandler.END

# ==============================================================================
# 10. SELLER FLOW - HOUSE
# ==============================================================================
async def seller_house_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    context.user_data['category'] = 'cat_house'
    
    keyboard = []
    for loc in LOCATIONS:
        keyboard.append([InlineKeyboardButton(loc, callback_data=f"sell_house_loc_{loc}")])
    
    await update.message.reply_text(
        "🏠 **ቤት/ቦታ ለሽያጭ**\n\n"
        "1️⃣ አካባቢ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_HOUSE_LOCATION

async def seller_house_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['sell_house_location'] = query.data.replace("sell_house_loc_", "")
    
    keyboard = []
    for htype in HOUSE_TYPES:
        keyboard.append([InlineKeyboardButton(htype, callback_data=f"sell_house_type_{htype}")])
    
    await query.edit_message_text(
        f"📍 {context.user_data['sell_house_location']}\n\n"
        "2️⃣ የቤት አይነት ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_HOUSE_TYPE

async def seller_house_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['sell_house_type'] = query.data.replace("sell_house_type_", "")
    
    await query.edit_message_text(
        f"📍 {context.user_data['sell_house_location']}\n"
        f"🏠 {context.user_data['sell_house_type']}\n\n"
        "3️⃣ የቤቱን/ቦታውን ስፋት (ካሬ ሜትር) ያስገቡ፦\n"
        "💡 *ምሳሌ፦* 150 ካሬ",
        parse_mode="Markdown"
    )
    return SELLER_HOUSE_SQFT

async def seller_house_sqft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_house_sqft'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("🆕 አዲስ", callback_data="hcond_new")],
        [InlineKeyboardButton("✅ ያጠናቀቀ", callback_data="hcond_complete")],
        [InlineKeyboardButton("🔧 ቀሪ ስራ ያለው", callback_data="hcond_unfinished")]
    ]
    await update.message.reply_text(
        "4️⃣ የቤቱ/ቦታው ሁኔታ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_HOUSE_CONDITION

async def seller_house_condition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cond_map = {"hcond_new": "🆕 አዲስ", "hcond_complete": "✅ ያጠናቀቀ", "hcond_unfinished": "🔧 ቀሪ ስራ ያለው"}
    context.user_data['sell_house_condition'] = cond_map.get(query.data, "ያልተጠቀሰ")
    
    await query.edit_message_text(
        f"📍 {context.user_data.get('sell_house_location')}\n"
        f"🏠 {context.user_data.get('sell_house_type')}\n"
        f"📐 {context.user_data.get('sell_house_sqft')} ካሬ\n"
        f"📊 {context.user_data['sell_house_condition']}\n\n"
        "5️⃣ የመሸጫ ዋጋ ያስገቡ፦",
        parse_mode="Markdown"
    )
    return SELLER_HOUSE_PRICE

async def seller_house_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_house_price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🔄 ድርድር አለው", callback_data="hnego_yes")],
        [InlineKeyboardButton("❌ ድርድር የለውም", callback_data="hnego_no")]
    ]
    await update.message.reply_text(
        "6️⃣ የዋጋ ድርድር ሁኔታ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_HOUSE_NEGOTIABLE

async def seller_house_negotiable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['sell_house_nego'] = "✅ ድርድር አለው" if query.data == "hnego_yes" else "❌ ድርድር የለውም"
    
    await query.edit_message_text(
        "7️⃣ እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦",
        parse_mode="Markdown"
    )
    return SELLER_HOUSE_PHONE

async def seller_house_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_house_phone'] = update.message.text
    await update.message.reply_text(
        "8️⃣ የቤቱን/ቦታውን ፎቶ ያስገቡ፦",
        parse_mode="Markdown"
    )
    return SELLER_HOUSE_PHOTO

async def seller_house_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return SELLER_HOUSE_PHOTO
    
    desc = (
        f"🏠 **ቤት ለሽያጭ**\n"
        f"📍 አካባቢ: {context.user_data.get('sell_house_location')}\n"
        f"🏠 አይነት: {context.user_data.get('sell_house_type')}\n"
        f"📐 ስፋት: {context.user_data.get('sell_house_sqft')} ካሬ\n"
        f"📊 ሁኔታ: {context.user_data.get('sell_house_condition')}\n"
        f"💰 ዋጋ: {context.user_data.get('sell_house_price')}\n"
        f"🔄 {context.user_data.get('sell_house_nego')}\n"
        f"📞 ስልክ: {context.user_data.get('sell_house_phone')}"
    )
    
    req_id = add_listing(user.id, user.first_name, 'SELL', 'cat_house', desc)
    
    if req_id:
        action_kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ እፈልገዋለሁ", callback_data=f"item_resp_{req_id}_{user.id}_cat_house")]
        ])
        
        await update.message.reply_photo(
            photo=photo_id,
            caption=f"✅ **ማስታወቂያ ተመዝግቧል!** (#REQ-{req_id})\n\n{desc}",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID_INT:
            try:
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID_INT,
                    photo=photo_id,
                    caption=f"🔔 አዲስ የቤት ማስታወቂያ!\n\n{desc}",
                    reply_markup=action_kbd,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    
    return ConversationHandler.END

# ==============================================================================
# 11. BROKER REGISTRATION
# ==============================================================================
async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "📝 **እንደ አቅራቢ/ደላላ መመዝገብ**\n\n"
        "1️⃣ ሙሉ ስምዎን ያስገቡ፦\n"
        "💡 *ምሳሌ፦* አበል ካሳ",
        parse_mode="Markdown"
    )
    return BROKER_NAME

async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['broker_name'] = update.message.text
    await update.message.reply_text(
        "2️⃣ የስልክ ቁጥርዎን ያስገቡ፦\n"
        "💡 *ምሳሌ፦* 0911XXXXXX",
        parse_mode="Markdown"
    )
    return BROKER_PHONE

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['broker_phone'] = update.message.text
    
    keyboard = []
    for loc in LOCATIONS:
        keyboard.append([InlineKeyboardButton(loc, callback_data=f"broker_loc_{loc}")])
    
    await update.message.reply_text(
        "3️⃣ የሚሰሩበትን አካባቢ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BROKER_LOCATION

async def broker_reg_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    location = query.data.replace("broker_loc_", "")
    
    user = update.effective_user
    broker_id = add_broker(user.id, context.user_data['broker_name'], context.user_data['broker_phone'], location)
    
    if broker_id:
        await query.edit_message_text(
            f"✅ **በስኬት ተመዝግበዋል!**\n\n"
            f"👤 {context.user_data['broker_name']}\n"
            f"📞 {context.user_data['broker_phone']}\n"
            f"📍 {location}\n\n"
            f"📋 አሁን '📋 የፈላጊዎች ዝርዝር' በመጠቀም ጥያቄዎችን ማየት ይችላሉ!",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            "❌ አስቀድመው ተመዝግበዋል!",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 12. VIEW REQUESTS (FOR BROKERS ONLY)
# ==============================================================================
async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check if user is registered broker
    broker = get_broker(user_id)
    if not broker:
        await update.message.reply_text(
            "⛔ ይህን ገጽ ማየት የሚችሉት የተመዘገቡ አቅራቢዎች/ደላሎች ብቻ ናቸው!\n\n"
            "📝 እባክዎን መጀመሪያ '📝 እንደ አቅራቢ መመዝገብ' የሚለውን ተጭነው ይመዝገቡ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    listings = get_all_listings()
    
    if not listings:
        await update.message.reply_text(
            "📭 ምንም ንቁ ጥያቄዎች የሉም።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    text = "📋 **የፈላጊዎች ዝርዝር**\n\n"
    for listing in listings:
        req_id, chat_id, name, req_type, category, desc, status, created = listing
        icon = "🚗" if category == "cat_car" else "🏠"
        text += f"{icon} **#{req_id}** - {desc[:100]}...\n"
        text += f"📅 {created}\n"
        text += f"🆔 {chat_id}\n"
        text += "────────────────────\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ==============================================================================
# 13. RESPONSE FLOW
# ==============================================================================
async def start_item_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    
    context.user_data.clear()
    context.user_data['target_req_id'] = parts[2]
    context.user_data['target_user_id'] = int(parts[3])
    context.user_data['target_cat'] = parts[4] if len(parts) > 4 else "cat_car"
    
    keyboard = [
        [InlineKeyboardButton("👤 የንብረቱ ባለቤት ነኝ", callback_data="resp_role_owner")],
        [InlineKeyboardButton("👨‍💼 ደላላ ነኝ", callback_data="resp_role_broker")]
    ]
    await query.message.reply_text(
        "📋 **የምላሽ ሰጭ ማንነት፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RESP_ROLE

async def resp_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['resp_role'] = "👤 ባለቤት" if query.data == "resp_role_owner" else "👨‍💼 ደላላ"
    
    target_cat = context.user_data.get('target_cat', 'cat_car')
    
    if target_cat == "cat_car":
        await query.edit_message_text(
            "🚘 **መኪና መልስ**\n\n"
            "1️⃣ የመኪናውን ሞዴል ያስገቡ፦",
            parse_mode="Markdown"
        )
        return RESP_CAR_MODEL
    else:
        keyboard = []
        for loc in LOCATIONS:
            keyboard.append([InlineKeyboardButton(loc, callback_data=f"res_house_loc_{loc}")])
        
        await query.edit_message_text(
            "🏠 **ቤት መልስ**\n\n"
            "1️⃣ አካባቢ ይምረጡ፦",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return RESP_HOUSE_LOCATION

# ===== CAR RESPONSE =====
async def resp_car_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_car_model'] = update.message.text
    await update.message.reply_text(
        "2️⃣ የምርት ዘመን ያስገቡ፦",
        parse_mode="Markdown"
    )
    return RESP_CAR_YEAR

async def resp_car_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_car_year'] = update.message.text
    await update.message.reply_text(
        "3️⃣ ዋጋ ያስገቡ፦",
        parse_mode="Markdown"
    )
    return RESP_CAR_PRICE

async def resp_car_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_car_price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🔄 ድርድር አለው", callback_data="rcar_nego_yes")],
        [InlineKeyboardButton("❌ ድርድር የለውም", callback_data="rcar_nego_no")]
    ]
    await update.message.reply_text(
        "4️⃣ የዋጋ ድርድር ሁኔታ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RESP_CAR_NEGOTIABLE

async def resp_car_negotiable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['resp_car_nego'] = "✅ ድርድር አለው" if query.data == "rcar_nego_yes" else "❌ ድርድር የለውም"
    
    await query.edit_message_text(
        "5️⃣ እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦",
        parse_mode="Markdown"
    )
    return RESP_CAR_PHONE

async def resp_car_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_car_phone'] = update.message.text
    await update.message.reply_text(
        "6️⃣ የመኪናውን ፎቶ ያስገቡ፦",
        parse_mode="Markdown"
    )
    return RESP_CAR_PHOTO

async def resp_car_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    responder = update.effective_user
    target_user_id = context.user_data.get('target_user_id')
    req_id = context.user_data.get('target_req_id')
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return RESP_CAR_PHOTO
    
    role = context.user_data.get('resp_role', 'አቅራቢ')
    
    desc = (
        f"🎉 **አዲስ አማራጭ!** (#REQ-{req_id})\n\n"
        f"🎭 ሚና: {role}\n"
        f"🚘 ሞዴል: {context.user_data.get('resp_car_model')}\n"
        f"📅 ዘመን: {context.user_data.get('resp_car_year')}\n"
        f"💰 ዋጋ: {context.user_data.get('resp_car_price')}\n"
        f"🔄 {context.user_data.get('resp_car_nego')}\n"
        f"📞 ስልክ: {context.user_data.get('resp_car_phone')}\n"
        f"👤 @{responder.username if responder.username else responder.first_name}"
    )
    
    await context.bot.send_photo(
        chat_id=target_user_id,
        photo=photo_id,
        caption=desc,
        parse_mode="Markdown"
    )
    
    await update.message.reply_text(
        "✅ **መረጃዎች ለፈላጊው ተልከዋል!**",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    
    update_listing_status(int(req_id), 'responded')
    return ConversationHandler.END

# ===== HOUSE RESPONSE =====
async def resp_house_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['resp_house_location'] = query.data.replace("res_house_loc_", "")
    
    await query.edit_message_text(
        f"📍 {context.user_data['resp_house_location']}\n\n"
        "2️⃣ የቤቱን/ቦታውን ስፋት (ካሬ ሜትር) ያስገቡ፦",
        parse_mode="Markdown"
    )
    return RESP_HOUSE_SQFT

async def resp_house_sqft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_house_sqft'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("🆕 አዲስ", callback_data="rhcond_new")],
        [InlineKeyboardButton("✅ ያጠናቀቀ", callback_data="rhcond_complete")],
        [InlineKeyboardButton("🔧 ቀሪ ስራ ያለው", callback_data="rhcond_unfinished")]
    ]
    await update.message.reply_text(
        "3️⃣ የቤቱ/ቦታው ሁኔታ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RESP_HOUSE_CONDITION

async def resp_house_condition(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cond_map = {"rhcond_new": "🆕 አዲስ", "rhcond_complete": "✅ ያጠናቀቀ", "rhcond_unfinished": "🔧 ቀሪ ስራ ያለው"}
    context.user_data['resp_house_condition'] = cond_map.get(query.data, "ያልተጠቀሰ")
    
    await query.edit_message_text(
        f"📍 {context.user_data.get('resp_house_location')}\n"
        f"📐 {context.user_data.get('resp_house_sqft')} ካሬ\n"
        f"📊 {context.user_data['resp_house_condition']}\n\n"
        "4️⃣ ዋጋ ያስገቡ፦",
        parse_mode="Markdown"
    )
    return RESP_HOUSE_PRICE

async def resp_house_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_house_price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🔄 ድርድር አለው", callback_data="rhnego_yes")],
        [InlineKeyboardButton("❌ ድርድር የለውም", callback_data="rhnego_no")]
    ]
    await update.message.reply_text(
        "5️⃣ የዋጋ ድርድር ሁኔታ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RESP_HOUSE_NEGOTIABLE

async def resp_house_negotiable(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['resp_house_nego'] = "✅ ድርድር አለው" if query.data == "rhnego_yes" else "❌ ድርድር የለውም"
    
    await query.edit_message_text(
        "6️⃣ እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦",
        parse_mode="Markdown"
    )
    return RESP_HOUSE_PHONE

async def resp_house_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_house_phone'] = update.message.text
    await update.message.reply_text(
        "7️⃣ የቤቱን/ቦታውን ፎቶ ያስገቡ፦",
        parse_mode="Markdown"
    )
    return RESP_HOUSE_PHOTO

async def resp_house_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    responder = update.effective_user
    target_user_id = context.user_data.get('target_user_id')
    req_id = context.user_data.get('target_req_id')
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return RESP_HOUSE_PHOTO
    
    role = context.user_data.get('resp_role', 'አቅራቢ')
    
    desc = (
        f"🎉 **አዲስ አማራጭ!** (#REQ-{req_id})\n\n"
        f"🎭 ሚና: {role}\n"
        f"📍 አካባቢ: {context.user_data.get('resp_house_location')}\n"
        f"📐 ስፋት: {context.user_data.get('resp_house_sqft')} ካሬ\n"
        f"📊 ሁኔታ: {context.user_data.get('resp_house_condition')}\n"
        f"💰 ዋጋ: {context.user_data.get('resp_house_price')}\n"
        f"🔄 {context.user_data.get('resp_house_nego')}\n"
        f"📞 ስልክ: {context.user_data.get('resp_house_phone')}\n"
        f"👤 @{responder.username if responder.username else responder.first_name}"
    )
    
    await context.bot.send_photo(
        chat_id=target_user_id,
        photo=photo_id,
        caption=desc,
        parse_mode="Markdown"
    )
    
    await update.message.reply_text(
        "✅ **መረጃዎች ለፈላጊው ተልከዋል!**",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    
    update_listing_status(int(req_id), 'responded')
    return ConversationHandler.END

# ==============================================================================
# 14. HELP
# ==============================================================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
❓ **እንዴት እንደሚጠቀሙ**

🔍 **መግዛት ከፈለጉ:**
• '🔍 መግዛት / መከራየት' ይምረጡ
• መኪና ወይም ቤት ይምረጡ
• መረጃ ይሙሉ
• ጥያቄዎ ለደላሎች ይላካል

📢 **መሸጥ ከፈለጉ:**
• '📢 መሸጥ / ማከራየት' ይምረጡ
• መረጃ ይሙሉ
• ማስታወቂያዎ ይታተማል

📝 **እንደ አቅራቢ ለመመዝገብ:**
• '📝 እንደ አቅራቢ መመዝገብ' ይምረጡ
• መረጃ ይሙሉ
• ጥያቄዎችን ማየት ይችላሉ

📋 **የፈላጊዎች ዝርዝር:**
• ለተመዘገቡ አቅራቢዎች ብቻ
• ንቁ ጥያቄዎችን ያሳያል
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

    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)

    # ===== BUYER CAR CONVERSATION =====
    buyer_car_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_car_start)],
        states={
            BUYER_CAR_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_car_model), cancel_message_handler],
            BUYER_CAR_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_car_year), cancel_message_handler],
            BUYER_CAR_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_car_budget), cancel_message_handler],
            BUYER_CAR_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_car_phone), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== BUYER HOUSE CONVERSATION =====
    buyer_house_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_house_start)],
        states={
            BUYER_HOUSE_LOCATION: [CallbackQueryHandler(buyer_house_location, pattern="^hbuy_loc_"), cancel_message_handler],
            BUYER_HOUSE_TYPE: [CallbackQueryHandler(buyer_house_type, pattern="^hbuy_type_"), cancel_message_handler],
            BUYER_HOUSE_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_house_budget), cancel_message_handler],
            BUYER_HOUSE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_house_phone), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== SELLER CAR CONVERSATION =====
    seller_car_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_car_start)],
        states={
            SELLER_CAR_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_car_model), cancel_message_handler],
            SELLER_CAR_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_car_year), cancel_message_handler],
            SELLER_CAR_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_car_price), cancel_message_handler],
            SELLER_CAR_NEGOTIABLE: [CallbackQueryHandler(seller_car_negotiable, pattern="^car_nego_"), cancel_message_handler],
            SELLER_CAR_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_car_phone), cancel_message_handler],
            SELLER_CAR_PHOTO: [MessageHandler(filters.PHOTO, seller_car_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== SELLER HOUSE CONVERSATION =====
    seller_house_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_house_start)],
        states={
            SELLER_HOUSE_LOCATION: [CallbackQueryHandler(seller_house_location, pattern="^sell_house_loc_"), cancel_message_handler],
            SELLER_HOUSE_TYPE: [CallbackQueryHandler(seller_house_type, pattern="^sell_house_type_"), cancel_message_handler],
            SELLER_HOUSE_SQFT: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_house_sqft), cancel_message_handler],
            SELLER_HOUSE_CONDITION: [CallbackQueryHandler(seller_house_condition, pattern="^hcond_"), cancel_message_handler],
            SELLER_HOUSE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_house_price), cancel_message_handler],
            SELLER_HOUSE_NEGOTIABLE: [CallbackQueryHandler(seller_house_negotiable, pattern="^hnego_"), cancel_message_handler],
            SELLER_HOUSE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_house_phone), cancel_message_handler],
            SELLER_HOUSE_PHOTO: [MessageHandler(filters.PHOTO, seller_house_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== BROKER REGISTRATION =====
    broker_reg_conv = ConversationHandler(
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
            RESP_ROLE: [CallbackQueryHandler(resp_role_chosen, pattern="^resp_role_"), cancel_message_handler],
            RESP_CAR_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_model), cancel_message_handler],
            RESP_CAR_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_year), cancel_message_handler],
            RESP_CAR_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_price), cancel_message_handler],
            RESP_CAR_NEGOTIABLE: [CallbackQueryHandler(resp_car_negotiable, pattern="^rcar_nego_"), cancel_message_handler],
            RESP_CAR_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_phone), cancel_message_handler],
            RESP_CAR_PHOTO: [MessageHandler(filters.PHOTO, resp_car_photo), cancel_message_handler],
            RESP_HOUSE_LOCATION: [CallbackQueryHandler(resp_house_location, pattern="^res_house_loc_"), cancel_message_handler],
            RESP_HOUSE_SQFT: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_house_sqft), cancel_message_handler],
            RESP_HOUSE_CONDITION: [CallbackQueryHandler(resp_house_condition, pattern="^rhcond_"), cancel_message_handler],
            RESP_HOUSE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_house_price), cancel_message_handler],
            RESP_HOUSE_NEGOTIABLE: [CallbackQueryHandler(resp_house_negotiable, pattern="^rhnego_"), cancel_message_handler],
            RESP_HOUSE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_house_phone), cancel_message_handler],
            RESP_HOUSE_PHOTO: [MessageHandler(filters.PHOTO, resp_house_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== OTHER HANDLERS =====
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(MessageHandler(cancel_filter, go_home))

    # ===== ADD CONVERSATIONS =====
    app.add_handler(buyer_car_conv)
    app.add_handler(buyer_house_conv)
    app.add_handler(seller_car_conv)
    app.add_handler(seller_house_conv)
    app.add_handler(broker_reg_conv)
    app.add_handler(response_conv)

    # ===== ERROR HANDLER =====
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} caused error: {context.error}", exc_info=True)

    app.add_error_handler(error_handler)

    logger.info("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()
