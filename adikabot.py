import logging
import os
import threading
import re
from typing import Optional, List, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor
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
# 2. CONSTANTS & KEYBOARDS
# ==============================================================================
MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ/ደላላ መመዝገብ", "📋 የፈላጊዎች ዝርዝር"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]

# ✅ 11 ክፍለ ከተሞች
SUB_CITIES = [
    "ቦሌ", "የካ", "አራዳ", "ልደታ", 
    "ቂርቆስ", "አዲስ ከተማ", "ንፋስ ስልክ ላፍቶ", 
    "ኮልፌ ቀራኒዮ", "አቃቂ ቃሊቲ", "ጉሌሌ", "ላምበርት/የካ"
]

CAR_SUB_CATEGORIES = ["🚗 የቤት መኪና", "🚚 የሥራ መኪና", "🚜 ከባድ ተሽከርካሪ/ማሽን"]

# ✅ የቤት አይነቶች (ኮንዶሚኒየም ተጨምሯል)
HOUSE_TYPES = ["🏡 ቪላ", "🏢 አፓርታማ", "🏢 ኮንዶሚኒየም", "🏢 ሪል እስቴት", "🏞️ መሬት/ቦታ"]
PROPERTY_TYPES = ["🏠 መኖሪያ ቤት", "🏢 የሥራ ቦታ / ንግድ"]

# ==============================================================================
# 3. DATABASE UTILITIES
# ==============================================================================
def get_db_connection():
    if DATABASE_URL:
        db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect("adika_marketplace.db")
        conn.row_factory = sqlite3.Row
        return conn

def get_placeholder():
    return "%s" if DATABASE_URL else "?"

def init_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Drop existing tables to avoid conflicts
        if DATABASE_URL:
            cursor.execute("DROP TABLE IF EXISTS brokers CASCADE")
            cursor.execute("DROP TABLE IF EXISTS listings CASCADE")
            
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
                );
                CREATE TABLE brokers (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    role_type TEXT NOT NULL,
                    national_id_photo TEXT,
                    sub_city TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
        else:
            cursor.execute("DROP TABLE IF EXISTS brokers")
            cursor.execute("DROP TABLE IF EXISTS listings")
            
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
                );
                CREATE TABLE brokers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    role_type TEXT NOT NULL,
                    national_id_photo TEXT,
                    sub_city TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
            
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    finally:
        if conn:
            conn.close()

# ========== LISTING DB OPERATIONS ==========
def add_listing(user_chat_id, user_name, req_type, main_category, sub_category, action_type, property_type, description):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        query = f"""
            INSERT INTO listings (user_chat_id, user_name, req_type, main_category, sub_category, action_type, property_type, description)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        params = (user_chat_id, user_name, req_type, main_category, sub_category, action_type, property_type, description)
        
        if DATABASE_URL:
            cursor.execute(query + " RETURNING id", params)
            req_id = cursor.fetchone()[0]
        else:
            cursor.execute(query, params)
            req_id = cursor.lastrowid
            conn.commit()
            
        return req_id
    except Exception as e:
        logger.error(f"Add listing error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_listings_by_category(limit=10, offset=0):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor) if DATABASE_URL else conn.cursor()
        p = get_placeholder()
        
        query = f"SELECT * FROM listings WHERE status = 'pending' ORDER BY created_at DESC LIMIT {p} OFFSET {p}"
        cursor.execute(query, (limit, offset))
        rows = cursor.fetchall()
        
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Get listings error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def count_listings():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM listings WHERE status = 'pending'")
        return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Count listings error: {e}")
        return 0
    finally:
        if conn:
            conn.close()

def get_listing_by_id(listing_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor) if DATABASE_URL else conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM listings WHERE id = {p}", (listing_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Get listing by id error: {e}")
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
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Update listing error: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ========== BROKER DB OPERATIONS ==========
def add_broker(chat_id, full_name, phone, role_type, national_id_photo, sub_city):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        # Check if user already exists
        cursor.execute(f"SELECT id FROM brokers WHERE chat_id = {p}", (chat_id,))
        existing = cursor.fetchone()
        
        if existing:
            # Update existing
            if DATABASE_URL:
                query = f"""
                    UPDATE brokers 
                    SET full_name = {p}, phone = {p}, role_type = {p}, 
                        national_id_photo = {p}, sub_city = {p}, status = 'pending'
                    WHERE chat_id = {p}
                    RETURNING id
                """
                cursor.execute(query, (full_name, phone, role_type, national_id_photo, sub_city, chat_id))
                broker_id = cursor.fetchone()[0]
            else:
                query = """
                    UPDATE brokers 
                    SET full_name = ?, phone = ?, role_type = ?, 
                        national_id_photo = ?, sub_city = ?, status = 'pending'
                    WHERE chat_id = ?
                """
                cursor.execute(query, (full_name, phone, role_type, national_id_photo, sub_city, chat_id))
                broker_id = existing[0]
                conn.commit()
        else:
            # Insert new
            if DATABASE_URL:
                query = f"""
                    INSERT INTO brokers (chat_id, full_name, phone, role_type, national_id_photo, sub_city, status)
                    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, 'pending')
                    RETURNING id
                """
                cursor.execute(query, (chat_id, full_name, phone, role_type, national_id_photo, sub_city))
                broker_id = cursor.fetchone()[0]
            else:
                query = """
                    INSERT INTO brokers (chat_id, full_name, phone, role_type, national_id_photo, sub_city, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """
                cursor.execute(query, (chat_id, full_name, phone, role_type, national_id_photo, sub_city))
                broker_id = cursor.lastrowid
                conn.commit()
            
        return broker_id
    except Exception as e:
        logger.error(f"Add broker error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_approved_brokers():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor) if DATABASE_URL else conn.cursor()
        cursor.execute("SELECT chat_id FROM brokers WHERE status = 'approved'")
        rows = cursor.fetchall()
        return [dict(row)['chat_id'] for row in rows]
    except Exception as e:
        logger.error(f"Get approved brokers error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def update_broker_status(chat_id, status):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"UPDATE brokers SET status = {p} WHERE chat_id = {p}", (status, chat_id))
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Update broker status error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_broker(chat_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor) if DATABASE_URL else conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM brokers WHERE chat_id = {p}", (chat_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"Get broker error: {e}")
        return None
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 4. CONVERSATION STATES (የተስተካከለ)
# ==============================================================================
(
    BUYER_MAIN, BUYER_ACTION, BUYER_SUB, BUYER_PROPERTY, BUYER_DETAILS, BUYER_PHONE,
    BROKER_ROLE, BROKER_NAME, BROKER_PHONE, BROKER_SUBCITY, BROKER_NID_PHOTO,
    SELLER_MAIN, SELLER_ACTION, SELLER_SUB, SELLER_PROPERTY, SELLER_DETAILS, SELLER_PRICE, SELLER_PHONE, SELLER_PHOTO,
    BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO
) = range(21)

# ==============================================================================
# 5. HELPER FUNCTIONS
# ==============================================================================
def validate_phone(phone: str) -> bool:
    """✅ የተስተካከለ የስልክ ቁጥር ማረጋገጫ"""
    phone = phone.replace(' ', '').replace('-', '')
    pattern = r'^(09|07|01)\d{8}$|^\+251(9|7|1)\d{8}$'
    return bool(re.match(pattern, phone))

def validate_price(price: str) -> bool:
    price = price.replace(',', '').replace(' ', '')
    return price.isdigit()

async def notify_brokers(context: ContextTypes.DEFAULT_TYPE, message_text: str, req_id: int, buyer_id: int):
    approved_brokers = get_approved_brokers()
    if not approved_brokers:
        logger.info("No approved brokers found to notify")
        return
    
    for b_id in approved_brokers:
        try:
            kbd = [[InlineKeyboardButton(f"👉 አለኝ - #{req_id}", callback_data=f"have_item_{req_id}_{buyer_id}")]]
            await context.bot.send_message(
                chat_id=b_id,
                text=message_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kbd)
            )
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to send notification to broker {b_id}: {e}")

# ==============================================================================
# 6. START & CANCEL HANDLERS
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

async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = "👋 **ወደ ዋና ገጽ ተመልሰዋል!**\n\nእባክዎን አማራጭ ይምረጡ፦"
    reply_markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.delete_message()
        except:
            pass
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=welcome_text,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    return ConversationHandler.END

# ==============================================================================
# 7. BUYER FLOW (ፈላጊ) - የተሻሻለ
# ==============================================================================
async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    
    keyboard = [
        [InlineKeyboardButton("🚗 መኪና", callback_data="flow_buy_cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ", callback_data="flow_buy_cat_house")],
        [InlineKeyboardButton("🏢 የሥራ ቦታ / ንግድ", callback_data="flow_buy_cat_commercial")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🔍 **የሚፈልጉትን ምድብ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BUYER_MAIN

async def buyer_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    cat = query.data.replace("flow_buy_cat_", "")
    context.user_data['main_category'] = cat
    
    if cat == "car":
        keyboard = [[InlineKeyboardButton(sub, callback_data=f"flow_buy_sub_{sub}")] for sub in CAR_SUB_CATEGORIES]
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
        await query.edit_message_text(
            "🚗 **የመኪና ንኡስ ምድብ ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return BUYER_SUB
    else:
        keyboard = [
            [InlineKeyboardButton("🛍️ መግዛት", callback_data="flow_buy_action_buy")],
            [InlineKeyboardButton("🔑 መከራየት", callback_data="flow_buy_action_rent")],
            [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
        ]
        await query.edit_message_text(
            "❓ **የሚፈልጉትን የድርጊት አይነት ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return BUYER_ACTION

async def buyer_sub_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    sub = query.data.replace("flow_buy_sub_", "")
    context.user_data['sub_category'] = sub
    
    keyboard = [
        [InlineKeyboardButton("🛍️ መግዛት", callback_data="flow_buy_action_buy")],
        [InlineKeyboardButton("🔑 መከራየት", callback_data="flow_buy_action_rent")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await query.edit_message_text(
        f"✅ {sub}\n\n❓ **የሚፈልጉትን የድርጊት አይነት ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BUYER_ACTION

async def buyer_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    action = query.data.replace("flow_buy_action_", "")
    context.user_data['action_type'] = "መግዛት" if action == "buy" else "መከራየት"
    
    if context.user_data.get('main_category') == "car":
        await query.edit_message_text(
            "✍️ **የሚፈልጉትን መኪና ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020፣ ባጀት እስከ 2.5 ሚሊዮን ብር",
            parse_mode="Markdown"
        )
        return BUYER_DETAILS
    else:
        keyboard = [[InlineKeyboardButton(ptype, callback_data=f"flow_buy_prop_{ptype}")] for ptype in PROPERTY_TYPES]
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
        await query.edit_message_text(
            "🏠 **የንብረት አይነት ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return BUYER_PROPERTY

async def buyer_property_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    prop = query.data.replace("flow_buy_prop_", "")
    context.user_data['property_type'] = prop
    
    keyboard = [[InlineKeyboardButton(htype, callback_data=f"flow_buy_htype_{htype}")] for htype in HOUSE_TYPES]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await query.edit_message_text(
        "🏠 **የቤቱ አይነት ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BUYER_SUB

async def buyer_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    htype = query.data.replace("flow_buy_htype_", "")
    context.user_data['property_subtype'] = htype
    
    await query.edit_message_text(
        f"🏠 **የቤቱ አይነት፦ {htype}**\n\n✍️ **የሚፈልጉትን ቤት/ቦታ ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቦሌ 2 መኝታ፣ ባጀት እስከ 10 ሚሊዮን ብር",
        parse_mode="Markdown"
    )
    return BUYER_DETAILS

async def buyer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['description'] = update.message.text
    await update.message.reply_text(
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return BUYER_PHONE

async def buyer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    phone = update.message.text
    
    if phone == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(phone):
        await update.message.reply_text("❌ ስልክ ቁጥሩ ትክክል አይደለም! እባክዎ እንደገና ያስገቡ።")
        return BUYER_PHONE
    
    main_cat = context.user_data.get('main_category', '')
    sub_cat = context.user_data.get('sub_category', '')
    action_type = context.user_data.get('action_type', '')
    prop_subtype = context.user_data.get('property_subtype', '')
    description = context.user_data.get('description', '')
    
    category_title = "🚗 አዲስ የመኪና ጥያቄ" if main_cat == "car" else "🏠 አዲስ የቤት/ቦታ ጥያቄ"
    
    full_desc = (
        f"📌 **{category_title}**\n"
        f"🔹 አይነት: {prop_subtype if prop_subtype else sub_cat}\n"
        f"🔄 ፍላጎት: {action_type}\n"
        f"📝 ዝርዝር: {description}\n"
        f"📞 ስልክ: {phone}"
    )
    
    req_id = add_listing(user.id, user.first_name, 'BUY', main_cat, sub_cat, action_type, prop_subtype, full_desc)
    
    if req_id:
        await update.message.reply_text(
            f"✅ **ጥያቄዎ በጥሩ ሁኔታ ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"📌 ጥያቄዎ ለተረጋገጡ ደላሎች የተላከ ሲሆን፣ ንብረቱ ያላቸው ደላሎች አማራጮችን ሲልኩልዎ እዚሁ ቴሌግራም ላይ ይደርስዎታል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        notification_text = (
            f"🔔 **{category_title}! (#REQ-{req_id})**\n\n"
            f"{full_desc}\n\n"
            f"👉 ይህ ንብረት በእጅዎ ካለ ከታች **'አለኝ'** የሚለውን በመጫን ለፈላጊው መረጃ ይላኩ!"
        )
        await notify_brokers(context, notification_text, req_id, user.id)
    else:
        await update.message.reply_text("❌ ጥያቄውን መመዝገብ አልተቻለም። እባክዎ እንደገና ይሞክሩ።")

    return ConversationHandler.END

# ==============================================================================
# 8. BROKER RESPONSE FLOW (ደላላው "አለኝ" ሲል) - የተሻሻለ
# ==============================================================================
async def broker_have_item_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    broker = get_broker(user_id)
    
    if not broker or broker.get('status') != 'approved':
        await query.message.reply_text("⛔ ይህን ማድረግ የሚችሉት በአድሚን የተረጋገጡ ደላሎች/አቅራቢዎች ብቻ ናቸው!")
        return ConversationHandler.END
        
    parts = query.data.split('_')
    if len(parts) < 3:
        await query.message.reply_text("❌ የተሳሳተ መረጃ ተላኳል።")
        return ConversationHandler.END
        
    req_id = parts[2]
    buyer_id = parts[3]
    
    context.user_data['target_req_id'] = req_id
    context.user_data['target_buyer_id'] = buyer_id
    
    await query.message.reply_text(
        f"✅ **ጥያቄ #{req_id}**\n\n"
        f"✍️ **ያለዎትን ንብረት ዝርዝር መረጃ እና ዋጋ ያስገቡ፦**\n"
        f"(ለምሳሌ፦ ቶዮታ ቪትዝ 2021፣ 30,000 KM የሄደ፣ ዋጋ 2.4 ሚሊዮን፣ ስልክ 0911...)"
    )
    return BROKER_OFFER_TEXT

async def broker_offer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
        
    context.user_data['offer_text'] = update.message.text
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ይላኩ፦**\n(ፎቶ ከሌልዎት 'ፎቶ የለውም' ብለው ይጻፉ)"
    )
    return BROKER_OFFER_PHOTO

async def broker_offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buyer_id = int(context.user_data.get('target_buyer_id'))
    req_id = context.user_data.get('target_req_id')
    offer_text = context.user_data.get('offer_text')
    broker_name = update.effective_user.first_name
    
    # ✅ የደላላውን ስልክ ቁጥር ማግኘት
    broker = get_broker(update.effective_user.id)
    broker_phone = broker.get('phone', '') if broker else ''
    
    # Update listing status to 'responded'
    update_listing_status(int(req_id), 'responded')
    
    message_to_buyer = (
        f"🎉 **ለጥያቄዎ (#REQ-{req_id}) አዲስ የቀረበ አማራጭ አለ!**\n\n"
        f"👤 **ደላላ/አቅራቢ፦** {broker_name}\n"
        f"📞 **ስልክ:** {broker_phone}\n"
        f"📝 **የንብረቱ ዝርዝር፦**\n{offer_text}\n\n"
        f"💡 *ከፈለጉ ደውለው መገበያየት ይችላሉ!*"
    )
    
    try:
        if update.message.photo:
            photo_id = update.message.photo[-1].file_id
            await context.bot.send_photo(
                chat_id=buyer_id,
                photo=photo_id,
                caption=message_to_buyer,
                parse_mode="Markdown"
            )
        else:
            # ✅ ፎቶ ከሌለ በቀላሉ መልእክት መላክ
            await context.bot.send_message(
                chat_id=buyer_id,
                text=message_to_buyer,
                parse_mode="Markdown"
            )
            
        await update.message.reply_text(
            "✅ **መረጃዎ ለፈላጊው በስኬት ተልኳል!**\n\n"
            "📌 ጥያቄው ከ'📋 የፈላጊዎች ዝርዝር' ተወግዷል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    except Exception as e:
        logger.error(f"Failed to send offer to buyer: {e}")
        await update.message.reply_text(
            "❌ መረጃውን ለፈላጊው መላክ አልተቻለም።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
    return ConversationHandler.END

# ==============================================================================
# 9. SELLER FLOW (መሸጥ / ማከራየት) - የተሻሻለ
# ==============================================================================
async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    
    keyboard = [
        [InlineKeyboardButton("🚗 መኪና", callback_data="flow_sell_cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ", callback_data="flow_sell_cat_house")],
        [InlineKeyboardButton("🏢 የሥራ ቦታ / ንግድ", callback_data="flow_sell_cat_commercial")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "📢 **የሚሸጡትን ወይም የሚያከራዩትን ምድብ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_MAIN

async def seller_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    cat = query.data.replace("flow_sell_cat_", "")
    context.user_data['main_category'] = cat
    
    if cat == "car":
        keyboard = [[InlineKeyboardButton(sub, callback_data=f"flow_sell_sub_{sub}")] for sub in CAR_SUB_CATEGORIES]
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
        await query.edit_message_text(
            "🚗 **የመኪና ንኡስ ምድብ ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return SELLER_SUB
    else:
        keyboard = [
            [InlineKeyboardButton("🛍️ መሸጥ", callback_data="flow_sell_action_sell")],
            [InlineKeyboardButton("🔑 ማከራየት", callback_data="flow_sell_action_rent")],
            [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
        ]
        await query.edit_message_text(
            "❓ **የድርጊት አይነት ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return SELLER_ACTION

async def seller_sub_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    sub = query.data.replace("flow_sell_sub_", "")
    context.user_data['sub_category'] = sub
    
    keyboard = [
        [InlineKeyboardButton("🛍️ መሸጥ", callback_data="flow_sell_action_sell")],
        [InlineKeyboardButton("🔑 ማከራየት", callback_data="flow_sell_action_rent")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await query.edit_message_text(
        f"✅ {sub}\n\n❓ **የድርጊት አይነት ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_ACTION

async def seller_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    action = query.data.replace("flow_sell_action_", "")
    context.user_data['action_type'] = "መሸጥ" if action == "sell" else "ማከራየት"
    
    if context.user_data.get('main_category') == "car":
        await query.edit_message_text(
            "✍️ **የመኪናውን ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020፣ 60,000 ኪሜ የሄደ",
            parse_mode="Markdown"
        )
        return SELLER_DETAILS
    else:
        keyboard = [[InlineKeyboardButton(ptype, callback_data=f"flow_sell_prop_{ptype}")] for ptype in PROPERTY_TYPES]
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
        await query.edit_message_text(
            "🏠 **የንብረት አይነት ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return SELLER_PROPERTY

async def seller_property_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    prop = query.data.replace("flow_sell_prop_", "")
    context.user_data['property_type'] = prop
    
    keyboard = [[InlineKeyboardButton(htype, callback_data=f"flow_sell_htype_{htype}")] for htype in HOUSE_TYPES]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await query.edit_message_text(
        "🏠 **የቤቱ አይነት ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_SUB

async def seller_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    htype = query.data.replace("flow_sell_htype_", "")
    context.user_data['property_subtype'] = htype
    
    await query.edit_message_text(
        f"🏠 **{htype}**\n\n✍️ **የቤቱን/ቦታውን ዝርዝር መረጃ ያስገቡ፦**\n💡 *ምሳሌ፦* ቦሌ አትላስ አካባቢ 3 መኝታ ቤት",
        parse_mode="Markdown"
    )
    return SELLER_DETAILS

async def seller_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['description'] = update.message.text
    await update.message.reply_text("💰 **የሚሸጡበትን/ሚያከራዩበትን ዋጋ ያስገቡ፦**", reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True))
    return SELLER_PRICE

async def seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_price(update.message.text):
        await update.message.reply_text("❌ እባክዎ ቁጥር ብቻ ያስገቡ።")
        return SELLER_PRICE
    
    context.user_data['price'] = update.message.text
    await update.message.reply_text("📞 **የስልክ ቁጥርዎን ያስገቡ፦**")
    return SELLER_PHONE

async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(update.message.text):
        await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ።")
        return SELLER_PHONE
    
    context.user_data['phone'] = update.message.text
    await update.message.reply_text("📸 **የንብረቱን ፎቶ ይላኩ፦**")
    return SELLER_PHOTO

async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    
    # ✅ ፎቶ ካልተላከም መቀጠል
    if not photo_id:
        await update.message.reply_text("📸 **ፎቶ አልተላከም**\n\nያለ ፎቶ ማስታወቂያዎን ማስመዝገብ ይችላሉ።")
    
    property_subtype = context.user_data.get('property_subtype', '')
    description = context.user_data.get('description', '')
    if property_subtype:
        description = f"🏠 {property_subtype}\n{description}"
    
    desc = (
        f"📢 **አዲስ የሽያጭ/ኪራይ ማስታወቂያ!**\n"
        f"🔄 አይነት: {context.user_data.get('action_type')}\n"
        f"📝 ዝርዝር: {description}\n"
        f"💰 ዋጋ: {context.user_data.get('price')} ብር\n"
        f"📞 ስልክ: {context.user_data.get('phone')}"
    )
    
    req_id = add_listing(
        user.id, 
        user.first_name, 
        'SELL', 
        context.user_data.get('main_category'), 
        context.user_data.get('sub_category', ''), 
        context.user_data.get('action_type'), 
        context.user_data.get('property_type', ''), 
        desc
    )
    
    if req_id:
        await update.message.reply_text(
            "✅ **ማስታወቂያዎ በስኬት ተመዝግቧል!** 🎉\n\n"
            "📌 ማስታወቂያዎ ለደላሎች ተልኳል።\n"
            "📋 '📋 የፈላጊዎች ዝርዝር' ውስጥ ይታያል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        # ✅ ለደላሎች ማሳወቅ
        notification_text = (
            f"📢 **አዲስ የሽያጭ/ኪራይ ማስታወቂያ!**\n\n"
            f"{desc}\n\n"
            f"👉 ይህን ማስታወቂያ ለፈላጊዎች ማሳወቅ ይችላሉ!"
        )
        await notify_brokers(context, notification_text, req_id, user.id)
    else:
        await update.message.reply_text(
            "❌ ማስታወቂያውን መመዝገብ አልተቻለም።\n\n"
            "💡 እባክዎ እንደገና ይሞክሩ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 10. BROKER REGISTRATION (የተሻሻለ)
# ==============================================================================
async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    
    keyboard = [
        [InlineKeyboardButton("👨💼 ደላላ", callback_data="role_broker")],
        [InlineKeyboardButton("🚢 አስመጪ / አቅራቢ", callback_data="role_importer")],
        [InlineKeyboardButton("👤 ባለቤት / አቅራቢ", callback_data="role_owner")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "📝 **የምዝገባ አይነት ይምረጡ፦**\n\n"
        "💡 *ማብራሪያ፦*\n"
        "• ደላላ - ሽያጭ/ኪራይ የሚያመቻች\n"
        "• አስመጪ/አቅራቢ - ከውጭ የሚያስገባ\n"
        "• ባለቤት/አቅራቢ - ንብረት ያለው",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BROKER_ROLE

async def broker_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    role_map = {
        "role_broker": "ደላላ",
        "role_importer": "አስመጪ/አቅራቢ",
        "role_owner": "ባለቤት/አቅራቢ"
    }
    role = role_map.get(query.data, "አቅራቢ")
    context.user_data['broker_role'] = role
    
    await query.edit_message_text(f"👤 **ምዝገባ፦ {role}**\n\n1️⃣ ሙሉ ስምዎን ያስገቡ፦")
    return BROKER_NAME

async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['broker_name'] = update.message.text
    await update.message.reply_text("2️⃣ የስልክ ቁጥርዎን ያስገቡ፦")
    return BROKER_PHONE

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(update.message.text):
        await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ። (ለምሳሌ፦ 0911223344)")
        return BROKER_PHONE
    
    context.user_data['broker_phone'] = update.message.text
    
    keyboard = [[InlineKeyboardButton(sc, callback_data=f"broker_sc_{sc}")] for sc in SUB_CITIES]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await update.message.reply_text("3️⃣ የሚሰሩበትን ክፍለ ከተማ ይምረጡ፦", reply_markup=InlineKeyboardMarkup(keyboard))
    return BROKER_SUBCITY

async def broker_reg_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    sub_city = query.data.replace("broker_sc_", "")
    context.user_data['broker_subcity'] = sub_city
    
    await query.edit_message_text(
        "4️⃣ **የፋይዳ (National ID) ወይም የነዋሪነት መታወቂያ ፎቶ ያንሱና ይላኩ፦**\n\n"
        "💡 *ይህ ለማረጋገጫ ብቻ ነው*"
    )
    return BROKER_NID_PHOTO

async def broker_reg_nid_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    user = update.effective_user
    
    # Check if it's a photo
    if not update.message or not update.message.photo:
        await update.message.reply_text(
            "❌ **እባክዎ የመታወቂያዎን ፎቶ ይላኩ!**\n\n"
            "📸 ፎቶውን ከቴሌግራም ፋይል አባሪ አማራጭ በመጠቀም ይላኩ።\n"
            "✏️ ጽሁፍ አይቀበልም።"
        )
        return BROKER_NID_PHOTO
        
    photo_id = update.message.photo[-1].file_id
    role = context.user_data.get('broker_role', 'አቅራቢ')
    name = context.user_data.get('broker_name', user.first_name)
    phone = context.user_data.get('broker_phone', '')
    sub_city = context.user_data.get('broker_subcity', '')
    
    # Show registration info
    await update.message.reply_text(
        f"📝 **የምዝገባ መረጃዎ፦**\n\n"
        f"👤 ስም: {name}\n"
        f"🎭 ሚና: {role}\n"
        f"📞 ስልክ: {phone}\n"
        f"📍 ክፍለ ከተማ: {sub_city}\n"
        f"🆔 Telegram ID: `{user.id}`\n\n"
        f"⏳ እባክዎ ይጠብቁ፣ እያስመዘገብን ነው...",
        parse_mode="Markdown"
    )
    
    # Save to database
    broker_id = add_broker(user.id, name, phone, role, photo_id, sub_city)
    
    if broker_id:
        await update.message.reply_text(
            "✅ **ምዝገባዎ በስኬት ተጠናቋል!** 🎉\n\n"
            "⏳ አድሚኑ መረጃዎን ካረጋገጠ በኋላ ማስታወቂያ ይደርስዎታል።\n\n"
            "📋 ምዝገባዎ ከጸደቀ በኋላ '📋 የፈላጊዎች ዝርዝር' ማየት ይችላሉ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        # Send to admin for approval
        if ADMIN_CHAT_ID_INT != 0:
            admin_msg = (
                f"🚨 **አዲስ የ{role} ምዝገባ ጥያቄ!**\n\n"
                f"👤 ስም: {name}\n"
                f"🎭 ሚና: {role}\n"
                f"📞 ስልክ: {phone}\n"
                f"📍 ክፍለ ከተማ: {sub_city}\n"
                f"🆔 Telegram ID: `{user.id}`"
            )
            admin_kbd = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ አጽድቅ", callback_data=f"admin_appr_{user.id}"),
                    InlineKeyboardButton("❌ ሰርዝ", callback_data=f"admin_reje_{user.id}")
                ],
                [InlineKeyboardButton("👤 ዝርዝር", callback_data=f"admin_view_{user.id}")]
            ])
            try:
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID_INT,
                    photo=photo_id,
                    caption=admin_msg,
                    parse_mode="Markdown",
                    reply_markup=admin_kbd
                )
                logger.info(f"Admin notification sent for broker {user.id}")
            except Exception as e:
                logger.error(f"Failed to send admin approval message: {e}")
                await update.message.reply_text(
                    "⚠️ ለአድሚን መላክ አልተቻለም፣ ነገር ግን ምዝገባዎ ተመዝግቧል።"
                )
    else:
        await update.message.reply_text(
            "❌ **ምዝገባውን ማጠናቀቅ አልተቻለም!**\n\n"
            "💡 እባክዎ የሚከተሉትን ያረጋግጡ፦\n"
            "• መረጃዎቹ ሙሉ መሆናቸውን\n"
            "• የበይነመረብ ግንኙነትዎን\n"
            "• አስቀድመው ካልተመዘገቡ\n\n"
            "🔄 እንደገና ለመሞከር '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይጫኑ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 11. ADMIN APPROVAL HANDLER
# ==============================================================================
async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("admin_appr_"):
        target_id = int(data.replace("admin_appr_", ""))
        update_broker_status(target_id, 'approved')
        
        await query.edit_message_caption(
            caption=query.message.caption + "\n\n✅ **ሁኔታ፦ በስኬት ጸድቋል (Approved)**",
            parse_mode="Markdown"
        )
        
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="🎉 **እንኳን ደስ አለዎት!** የምዝገባ ጥያቄዎ በአድሚን ጸድቋል።\n\n"
                     "📋 አሁን '📋 የፈላጊዎች ዝርዝር' በመጠቀም ጥያቄዎችን ማየት ይችላሉ።",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        except Exception as e:
            logger.error(f"Could not notify approved user: {e}")
            
    elif data.startswith("admin_reje_"):
        target_id = int(data.replace("admin_reje_", ""))
        update_broker_status(target_id, 'rejected')
        
        await query.edit_message_caption(
            caption=query.message.caption + "\n\n❌ **ሁኔታ፦ ተሰርዟል (Rejected)**",
            parse_mode="Markdown"
        )
        
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="❌ የምዝገባ ጥያቄዎ ተሰርዟል።\n\n"
                     "ለተጨማሪ መረጃ እባክዎን አድሚንን ያግኙ።",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        except Exception as e:
            logger.error(f"Could not notify rejected user: {e}")
            
    elif data.startswith("admin_view_"):
        target_id = int(data.replace("admin_view_", ""))
        broker = get_broker(target_id)
        if broker:
            view_text = (
                f"👤 **የአቅራቢው ዝርዝር**\n\n"
                f"🆔 ID: {broker.get('id')}\n"
                f"👤 ስም: {broker.get('full_name')}\n"
                f"🎭 ሚና: {broker.get('role_type')}\n"
                f"📞 ስልክ: {broker.get('phone')}\n"
                f"📍 ክፍለ ከተማ: {broker.get('sub_city')}\n"
                f"🆔 Telegram ID: {broker.get('chat_id')}\n"
                f"📅 የተመዘገበ: {broker.get('created_at')}\n"
                f"📊 ሁኔታ: {broker.get('status')}"
            )
            await query.message.reply_text(view_text, parse_mode="Markdown")


# ==============================================================================
# 12. VIEW REQUESTS (የተሻሻለ - ቁልፍ ከጥያቄው አጠገብ)
# ==============================================================================
ITEMS_PER_PAGE = 8

def format_listing_card(listing: Dict, idx: int) -> str:
    """Professional compact card format with button indicator"""
    listing_id = listing.get('id', 'N/A')
    main_cat = listing.get('main_category', '').upper()
    sub_cat = listing.get('sub_category', '')
    action_type = listing.get('action_type', '')
    description = listing.get('description', '')
    created_at = listing.get('created_at', '')
    
    # Category emojis
    cat_emojis = {
        'car': '🚗',
        'house': '🏠',
        'commercial': '🏢'
    }
    emoji = cat_emojis.get(listing.get('main_category', ''), '📌')
    
    # Extract phone number from description
    phone_match = re.search(r'📞 ስልክ:\s*([\d+]+)', description)
    phone = phone_match.group(1) if phone_match else 'N/A'
    
    # Clean description
    clean_desc = re.sub(r'\n📞 ስልክ:\s*[\d+]+', '', description)
    if len(clean_desc) > 50:
        clean_desc = clean_desc[:50] + "..."
    
    # Format date
    date_str = created_at[:10] if created_at else 'N/A'
    
    # Professional compact card with button indicator
    card = f"""
┌─── 📌 #{listing_id} ──────────────────────
│ {emoji} {main_cat} | {sub_cat if sub_cat else 'N/A'} | {action_type if action_type else 'N/A'}
│ 📞 {phone} | 📅 {date_str}
│ 📝 {clean_desc}
│ 👉 ለመልስ [{idx}] የታችኛውን ቁልፍ ይጫኑ
└─────────────────────────────────────────
"""
    return card

async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    broker = get_broker(user_id)
    
    if not broker:
        await update.message.reply_text(
            "⛔ ይህን ገጽ ማየት የሚችሉት የተመዘገቡ አቅራቢዎች/ደላሎች ብቻ ናቸው!\n\n"
            "📝 እባክዎን መጀመሪያ '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይጫኑ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    if broker.get('status') != 'approved':
        await update.message.reply_text(
            "⏳ **ምዝገባዎ ገና በአድሚን አልጸደቀም!**\n\n"
            "⏳ ምዝገባዎ በአድሚን ሲረጋገጥ ማስታወቂያ ይደርስዎታል።\n"
            "📞 ለተጨማሪ መረጃ ድጋፍን ይጠቀሙ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    context.user_data['view_page'] = 0
    await show_requests_page(update, context)

async def show_requests_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Handle page navigation from callback
        if update.callback_query and update.callback_query.data.startswith("page_"):
            page = int(update.callback_query.data.replace("page_", ""))
            context.user_data['view_page'] = page
            query = update.callback_query
            await query.answer()
        else:
            page = context.user_data.get('view_page', 0)
        
        offset = page * ITEMS_PER_PAGE
        
        listings = get_listings_by_category(limit=ITEMS_PER_PAGE, offset=offset)
        total = count_listings()
        total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        
        if not listings:
            text = """
📭 **ምንም ንቁ ጥያቄዎች የሉም**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 ሁሉም ጥያቄዎች ተመልሰዋል ወይም በሂደት ላይ ናቸው።
🔄 ቆይተው እንደገና ይሞክሩ።
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
            if update.message:
                await update.message.reply_text(text, parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
            else:
                await update.callback_query.edit_message_text(text, parse_mode="Markdown")
            return
        
        # Compact professional header
        broker_data = get_broker(update.effective_user.id)
        broker_name = broker_data.get('full_name', 'ደላላ') if broker_data else 'ደላላ'
        
        header = f"""
📋 **የፈላጊዎች ዝርዝር**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👤 {broker_name} | 📊 {total} ጥያቄዎች | 📄 ገጽ {page + 1}/{total_pages}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        
        # Build compact listing cards
        body = ""
        for idx, listing in enumerate(listings, 1):
            body += format_listing_card(listing, idx)
            if idx < len(listings):
                body += ""
        
        # ✅ Build keyboard with buttons next to each listing
        keyboard = []
        for idx, listing in enumerate(listings, 1):
            l_id = listing.get('id')
            u_id = listing.get('user_chat_id')
            # Button with listing number for easy reference
            keyboard.append([InlineKeyboardButton(
                f"✅ አለኝ - #{l_id}", 
                callback_data=f"have_item_{l_id}_{u_id}"
            )])
        
        # Navigation buttons in one row
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ ቀዳሚ", callback_data=f"page_{page-1}"))
        nav_buttons.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="page_info"))
        if offset + ITEMS_PER_PAGE < total:
            nav_buttons.append(InlineKeyboardButton("➡️ ቀጣይ", callback_data=f"page_{page+1}"))
        nav_buttons.append(InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home"))
        keyboard.append(nav_buttons)
        
        text = header + body
        
        if update.message:
            await update.message.reply_text(
                text, 
                reply_markup=InlineKeyboardMarkup(keyboard), 
                parse_mode="Markdown"
            )
        else:
            await update.callback_query.edit_message_text(
                text, 
                reply_markup=InlineKeyboardMarkup(keyboard), 
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logger.error(f"Error in show_requests_page: {e}")
        error_text = """
❌ **ስህተተ!**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ዝርዝሩን ማሳየት አልተቻለም።
💡 እባክዎ እንደገና ይሞክሩ።
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        if update.message:
            await update.message.reply_text(error_text, parse_mode="Markdown")
        else:
            await update.callback_query.edit_message_text(error_text, parse_mode="Markdown")
# ==============================================================================
# 13. HELP COMMAND
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
• ምድብ ይምረጡ
• መረጃ ይሙሉ

📝 **እንደ አቅራቢ ለመመዝገብ:**
• '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይምረጡ
• ሚናዎን ይምረጡ (ደላላ/አስመጪ/ባለቤት)
• የፋይዳ መታወቂያ ፎቶ ይላኩ
• አስተዳዳሪ ማጽደቅ ይጠብቁ

📋 **የፈላጊዎች ዝርዝር:**
• ለተመዘገቡ እና ለተጸደቁ አቅራቢዎች ብቻ
• ንቁ ጥያቄዎችን ያሳያል
• በገጽ ይከፋፈላል

🏠 **ዋና ገጽ:**
• ቀደም ሲል የነበረውን መልእክት ያጽዳል
• አዲስ ሜኑ ያመጣል
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ==============================================================================
# 14. MAIN ENGINE
# ==============================================================================
def main():
    import asyncio
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))

    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)

    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
        states={
            BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_message_handler],
            BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_"), cancel_message_handler],
            BUYER_SUB: [CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_"), CallbackQueryHandler(buyer_htype_chosen, pattern="^flow_buy_htype_"), cancel_message_handler],
            BUYER_PROPERTY: [CallbackQueryHandler(buyer_property_chosen, pattern="^flow_buy_prop_"), cancel_message_handler],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details), cancel_message_handler],
            BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_"), cancel_message_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_message_handler],
            SELLER_SUB: [CallbackQueryHandler(seller_sub_chosen, pattern="^flow_sell_sub_"), CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_"), cancel_message_handler],
            SELLER_PROPERTY: [CallbackQueryHandler(seller_property_chosen, pattern="^flow_sell_prop_"), cancel_message_handler],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details), cancel_message_handler],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price), cancel_message_handler],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone), cancel_message_handler],
            SELLER_PHOTO: [MessageHandler(filters.PHOTO, seller_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ/ደላላ መመዝገብ$"), broker_reg_start)],
        states={
            BROKER_ROLE: [CallbackQueryHandler(broker_role_chosen, pattern="^role_"), cancel_message_handler],
            BROKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name), cancel_message_handler],
            BROKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone), cancel_message_handler],
            BROKER_SUBCITY: [CallbackQueryHandler(broker_reg_subcity, pattern="^broker_sc_"), cancel_message_handler],
            BROKER_NID_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, broker_reg_nid_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    broker_response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broker_have_item_click, pattern="^have_item_")],
        states={
            BROKER_OFFER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text), cancel_message_handler],
            BROKER_OFFER_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, broker_offer_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(MessageHandler(cancel_filter, go_home))
    app.add_handler(CallbackQueryHandler(show_requests_page, pattern="^page_"))
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(admin_approval_callback, pattern="^admin_"))

    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(broker_response_conv)

    logger.info("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()
