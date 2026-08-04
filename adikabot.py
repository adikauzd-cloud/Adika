import logging
import os
import threading
import re
from typing import Optional, List, Dict, Any, Tuple
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
        
        # Drop existing tables to ensure clean schema
        if DATABASE_URL:
            cursor.execute("""
                DROP TABLE IF EXISTS listings CASCADE;
                DROP TABLE IF EXISTS brokers CASCADE;
            """)
        else:
            cursor.execute("""
                DROP TABLE IF EXISTS listings;
                DROP TABLE IF EXISTS brokers;
            """)
        
        # Listings table - simplified with only essential columns
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
        
        if DATABASE_URL:
            conn.commit()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    finally:
        if conn:
            conn.close()

# ========== LISTING FUNCTIONS ==========
def add_listing(user_chat_id, user_name, req_type, main_category, sub_category, action_type, property_type, description):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        if DATABASE_URL:
            cursor.execute(f"""
                INSERT INTO listings (user_chat_id, user_name, req_type, main_category, sub_category, action_type, property_type, description)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) RETURNING id
            """, (user_chat_id, user_name, req_type, main_category, sub_category, action_type, property_type, description))
            req_id = cursor.fetchone()[0]
            conn.commit()
        else:
            cursor.execute(f"""
                INSERT INTO listings (user_chat_id, user_name, req_type, main_category, sub_category, action_type, property_type, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_chat_id, user_name, req_type, main_category, sub_category, action_type, property_type, description))
            req_id = cursor.lastrowid
            conn.commit()
        return req_id
    except Exception as e:
        logger.error(f"Add listing error: {e}")
        return None
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
        
        if DATABASE_URL:
            cursor.execute(query.replace("?", p), params)
        else:
            cursor.execute(query, params)
        rows = cursor.fetchall()
        
        # Convert to list of dictionaries for easier handling
        result = []
        for row in rows:
            if DATABASE_URL:
                # For PostgreSQL, row is a tuple
                result.append({
                    'id': row[0],
                    'user_chat_id': row[1],
                    'user_name': row[2],
                    'req_type': row[3],
                    'main_category': row[4],
                    'sub_category': row[5],
                    'action_type': row[6],
                    'property_type': row[7],
                    'description': row[8],
                    'status': row[9],
                    'created_at': row[10]
                })
            else:
                # For SQLite, row is a sqlite3.Row
                result.append(dict(row))
        return result
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
        if row:
            if DATABASE_URL:
                return {
                    'id': row[0],
                    'user_chat_id': row[1],
                    'user_name': row[2],
                    'req_type': row[3],
                    'main_category': row[4],
                    'sub_category': row[5],
                    'action_type': row[6],
                    'property_type': row[7],
                    'description': row[8],
                    'status': row[9],
                    'created_at': row[10]
                }
            else:
                return dict(row)
        return None
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
        if row:
            if DATABASE_URL:
                return {
                    'id': row[0],
                    'chat_id': row[1],
                    'full_name': row[2],
                    'phone': row[3],
                    'location': row[4],
                    'created_at': row[5]
                }
            else:
                return dict(row)
        return None
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
# Buyer Flow States
BUYER_MAIN, BUYER_ACTION, BUYER_CATEGORY, BUYER_SUB, BUYER_PROPERTY, BUYER_DETAILS, BUYER_PHONE = range(7)

# Seller Flow States
SELLER_MAIN, SELLER_ACTION, SELLER_CATEGORY, SELLER_SUB, SELLER_PROPERTY, \
SELLER_LOCATION, SELLER_DETAILS, SELLER_PRICE, SELLER_NEGO, \
SELLER_PHOTO, SELLER_PHONE, SELLER_CONFIRM = range(7, 18)

# Broker Registration States
BROKER_NAME, BROKER_PHONE, BROKER_LOCATION = range(18, 21)

# Response Flow States
RESP_MAIN, RESP_ROLE, RESP_PROPERTY, RESP_SUB, RESP_DETAILS, RESP_PRICE, RESP_NEGO, RESP_PHONE, RESP_PHOTO = range(21, 30)

# ==============================================================================
# 5. HELPER FUNCTIONS
# ==============================================================================
def validate_phone(phone: str) -> bool:
    """Validate Ethiopian phone number"""
    phone = phone.replace(' ', '').replace('-', '')
    pattern = r'^(09|07|01)\d{8}$|^\+251(09|07|01)\d{8}$'
    return bool(re.match(pattern, phone))

def validate_price(price: str) -> bool:
    """Validate price input"""
    price = price.replace(',', '').replace(' ', '')
    pattern = r'^[\d]+(\.[\d]{2})?$'
    return bool(re.match(pattern, price))

def format_listing_for_confirmation(data: Dict[str, Any], main_cat: str) -> str:
    """Format listing data for confirmation"""
    if main_cat == "car":
        return (
            "📋 **የመኪና ማስታወቂያ ማጠቃለያ**\n\n"
            f"📍 ቦታ: {data.get('location', '')}\n"
            f"🚗 ዝርዝር: {data.get('car_details', '')}\n"
            f"💰 ዋጋ: {data.get('price', '')}\n"
            f"🔄 ድርድር: {data.get('negotiable', '')}\n"
            f"📞 ስልክ: {data.get('phone', '')}\n"
            f"📸 ፎቶ: {'✅ ተላኳል' if data.get('photo_id') else '⏭️ ተዘልሏል'}\n\n"
            "✅ መረጃው ትክክል ከሆነ 'አረጋግጥ' ይጫኑ።\n"
            "❌ ለመሰረዝ '🏠 ዋና ገጽ' ይጫኑ።"
        )
    else:
        property_subtype = data.get('property_subtype', '')
        detail_label = "📐 ስፋት" if "መሬት" in property_subtype or "ቦታ" in property_subtype else "🛏️ መኝታ"
        
        return (
            "📋 **የንብረት ማስታወቂያ ማጠቃለያ**\n\n"
            f"📍 ቦታ: {data.get('location', '')}\n"
            f"🏠 አይነት: {data.get('property_subtype', '')}\n"
            f"{detail_label}: {data.get('property_details', '')}\n"
            f"💰 ዋጋ: {data.get('price', '')}\n"
            f"🔄 ድርድር: {data.get('negotiable', '')}\n"
            f"📞 ስልክ: {data.get('phone', '')}\n"
            f"📸 ፎቶ: {'✅ ተላኳል' if data.get('photo_id') else '⏭️ ተዘልሏል'}\n\n"
            "✅ መረጃው ትክክል ከሆነ 'አረጋግጥ' ይጫኑ።\n"
            "❌ ለመሰረዝ '🏠 ዋና ገጽ' ይጫኑ።"
        )

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
    """Go back to main menu"""
    context.user_data.clear()
    
    welcome_text = (
        "👋 **ወደ ዋና ገጽ ተመልሰዋል!**\n\n"
        "እባክዎን ከታች ካሉት አማራጮች አንዱን ይምረጡ፦"
    )
    
    reply_markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    
    if update.message:
        await update.message.reply_text(
            welcome_text,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            welcome_text,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    else:
        await update.effective_message.reply_text(
            welcome_text,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    
    return ConversationHandler.END

# ==============================================================================
# 8. BUYER FLOW
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
        keyboard = []
        for sub in CAR_SUB_CATEGORIES:
            keyboard.append([InlineKeyboardButton(sub, callback_data=f"flow_buy_sub_{sub}")])
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
        await query.edit_message_text(
            "🚗 **የመኪና ንኡስ ምድብ ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return BUYER_SUB
    else:
        keyboard = [
            [InlineKeyboardButton("🛍️ ሽያጭ", callback_data="flow_buy_action_sell")],
            [InlineKeyboardButton("🔑 ኪራይ", callback_data="flow_buy_action_rent")],
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
        [InlineKeyboardButton("🛍️ ሽያጭ", callback_data="flow_buy_action_sell")],
        [InlineKeyboardButton("🔑 ኪራይ", callback_data="flow_buy_action_rent")],
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
    context.user_data['action_type'] = "sell" if action == "sell" else "rent"
    action_label = "ሽያጭ" if action == "sell" else "ኪራይ"
    
    main_cat = context.user_data.get('main_category', '')
    
    if main_cat == "car":
        await query.edit_message_text(
            "✍️ **የሚፈልጉትን መኪና ዝርዝር መረጃ ያስገቡ፦**\n\n"
            "💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020፣ ባጀት እስከ 2.5 ሚሊዮን ብር",
            parse_mode="Markdown"
        )
        return BUYER_DETAILS
    else:
        keyboard = []
        for ptype in PROPERTY_TYPES:
            keyboard.append([InlineKeyboardButton(ptype, callback_data=f"flow_buy_prop_{ptype}")])
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
        await query.edit_message_text(
            f"🏠 **የ{action_label} የቤት/ቦታ አይነት ይምረጡ፦**",
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
    
    keyboard = []
    for htype in HOUSE_TYPES:
        keyboard.append([InlineKeyboardButton(htype, callback_data=f"flow_buy_htype_{htype}")])
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await query.edit_message_text(
        f"🏠 **የቤት አይነት ይምረጡ፦**",
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
        f"🏠 **{htype}**\n\n"
        "✍️ **የሚፈልጉትን ቤት/ቦታ ዝርዝር መረጃ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* ቦሌ አትላስ አካባቢ 2 መኝታ፣ ባጀት እስከ 10 ሚሊዮን ብር",
        parse_mode="Markdown"
    )
    return BUYER_DETAILS

async def buyer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['description'] = update.message.text
    await update.message.reply_text(
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* 0912345678",
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
        await update.message.reply_text(
            "❌ ስልክ ቁጥሩ ትክክል አይደለም! እባክዎ ትክክለኛ የኢትዮጵያ ስልክ ቁጥር ያስገቡ።",
            parse_mode="Markdown"
        )
        return BUYER_PHONE
    
    main_cat = context.user_data.get('main_category', '')
    sub_cat = context.user_data.get('sub_category', '')
    action_type = context.user_data.get('action_type', '')
    property_type = context.user_data.get('property_type', '')
    description = context.user_data.get('description', '')
    
    desc = f"📝 {description}\n📞 {phone}"
    
    req_id = add_listing(
        user.id, user.first_name, 'BUY', main_cat, sub_cat, action_type, property_type, desc
    )
    
    if req_id:
        action_kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ አለኝ", callback_data=f"item_resp_{req_id}_{user.id}_{main_cat}")]
        ])
        
        await update.message.reply_text(
            f"✅ **ጥያቄዎ ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"📝 {description}\n"
            f"📞 {phone}\n\n"
            f"📌 ጥያቄዎ በ'📋 የፈላጊዎች ዝርዝር' ውስጥ ይታያል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID_INT:
            try:
                admin_msg = f"🔔 አዲስ ጥያቄ!\n\n{desc}"
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID_INT,
                    text=admin_msg,
                    reply_markup=action_kbd,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    else:
        await update.message.reply_text(
            "❌ ጥያቄዎ ሲመዘገብ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።"
        )
    
    return ConversationHandler.END

# ==============================================================================
# 9. SELLER FLOW
# ==============================================================================
async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    
    keyboard = [
        [InlineKeyboardButton("🛍️ ሽያጭ", callback_data="flow_sell_action_sell")],
        [InlineKeyboardButton("🔑 ኪራይ", callback_data="flow_sell_action_rent")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "📢 **የሚፈልጉትን የድርጊት አይነት ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_MAIN

async def seller_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    action = query.data.replace("flow_sell_action_", "")
    context.user_data['action_type'] = "sell" if action == "sell" else "rent"
    
    keyboard = [
        [InlineKeyboardButton("🚗 መኪና", callback_data="flow_sell_cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ", callback_data="flow_sell_cat_house")],
        [InlineKeyboardButton("🏢 የሥራ ቦታ / ንግድ", callback_data="flow_sell_cat_commercial")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await query.edit_message_text(
        "🏷️ **የሚሸጡትን/የሚከራዩትን ምድብ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_CATEGORY

async def seller_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    cat = query.data.replace("flow_sell_cat_", "")
    context.user_data['main_category'] = cat
    
    if cat == "car":
        keyboard = []
        for sub in CAR_SUB_CATEGORIES:
            keyboard.append([InlineKeyboardButton(sub, callback_data=f"flow_sell_sub_{sub}")])
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
        await query.edit_message_text(
            "🚗 **የመኪና ንኡስ ምድብ ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return SELLER_SUB
    else:
        keyboard = []
        for ptype in PROPERTY_TYPES:
            keyboard.append([InlineKeyboardButton(ptype, callback_data=f"flow_sell_prop_{ptype}")])
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
        await query.edit_message_text(
            "🏠 **የቤት/ቦታ አይነት ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return SELLER_PROPERTY

# ===== CAR SELLER FLOW =====
async def seller_car_sub_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    sub = query.data.replace("flow_sell_sub_", "")
    context.user_data['sub_category'] = sub
    
    await query.edit_message_text(
        "📍 **ደረጃ 1/6: መኪናው የሚገኝበት አድራሻ/ቦታ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* አዲስ አበባ፣ ቦሌ",
        parse_mode="Markdown"
    )
    return SELLER_LOCATION

async def seller_car_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['location'] = update.message.text
    
    await update.message.reply_text(
        "🚗 **ደረጃ 2/6: የመኪናውን ዝርዝር መረጃ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* ቶዮታ ያሪስ 2018፣ አውቶማቲክ፣ 50,000 ኪሎ ሜትር",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return SELLER_DETAILS

async def seller_car_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['car_details'] = update.message.text
    
    await update.message.reply_text(
        "💰 **ደረጃ 3/6: የመሸጫ ዋጋ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* 2,500,000 ብር",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return SELLER_PRICE

async def seller_car_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_price(update.message.text):
        await update.message.reply_text(
            "❌ ዋጋው ትክክል አይደለም! እባክዎ ቁጥር ብቻ ያስገቡ።\n"
            "💡 *ምሳሌ፦* 2500000 ወይም 2,500,000",
            parse_mode="Markdown"
        )
        return SELLER_PRICE
    
    context.user_data['price'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("🔄 ድርድር አለው", callback_data="flow_sell_nego_yes")],
        [InlineKeyboardButton("❌ ድርድር የለውም", callback_data="flow_sell_nego_no")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🔄 **ደረጃ 4/6: የዋጋ ድርድር ሁኔታ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_NEGO

async def seller_car_nego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['negotiable'] = "✅ ድርድር አለው" if query.data == "flow_sell_nego_yes" else "❌ ድርድር የለውም"
    
    await query.edit_message_text(
        "📸 **ደረጃ 5/6: የመኪናውን ፎቶ ያስገቡ፦**\n\n"
        "📸 *ፎቶ ለመላክ ፎቶውን ይላኩ*\n"
        "⏩ *ፎቶ ሳይላኩ ለመቀጠል '⏭️ ዝለል' ይጫኑ*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ ዝለል", callback_data="flow_sell_skip_photo")],
            [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
        ]),
        parse_mode="Markdown"
    )
    return SELLER_PHOTO

async def seller_car_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "flow_sell_skip_photo":
            context.user_data['photo_id'] = None
            await query.edit_message_text(
                "📞 **ደረጃ 6/6: እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**\n\n"
                "💡 *ምሳሌ፦* 0912345678\n"
                "👤 *ወይም የቴሌግራም አድራሻዎን ይላኙ*",
                parse_mode="Markdown"
            )
            return SELLER_PHONE
        else:
            return await go_home(update, context)
    
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
        context.user_data['photo_id'] = photo_id
        
        await update.message.reply_text(
            "📞 **ደረጃ 6/6: እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**\n\n"
            "💡 *ምሳሌ፦* 0912345678\n"
            "👤 *ወይም የቴሌግራም አድራሻዎን ይላኙ*",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
        )
        return SELLER_PHONE
    else:
        await update.message.reply_text(
            "❌ እባክዎ ትክክለኛ ፎቶ ይላኩ ወይም '⏭️ ዝለል' ይጫኑ!",
            parse_mode="Markdown"
        )
        return SELLER_PHOTO

# ===== PROPERTY SELLER FLOW =====
async def seller_property_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    prop = query.data.replace("flow_sell_prop_", "")
    context.user_data['property_type'] = prop
    
    keyboard = []
    for htype in HOUSE_TYPES:
        keyboard.append([InlineKeyboardButton(htype, callback_data=f"flow_sell_htype_{htype}")])
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await query.edit_message_text(
        "🏠 **የቤት/ቦታ አይነት ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_SUB

async def seller_property_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    htype = query.data.replace("flow_sell_htype_", "")
    context.user_data['property_subtype'] = htype
    
    await query.edit_message_text(
        "📍 **ደረጃ 1/6: ንብረቱ የሚገኝበት ቦታ/አካባቢ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* የካ፣ አያት፣ ቦሌ",
        parse_mode="Markdown"
    )
    return SELLER_LOCATION

async def seller_property_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['location'] = update.message.text
    
    property_subtype = context.user_data.get('property_subtype', '')
    if "መሬት" in property_subtype or "ቦታ" in property_subtype:
        await update.message.reply_text(
            "📐 **ደረጃ 2/6: የመሬቱን ስፋት በካሬ ሜትር (m²) ያስገቡ፦**\n\n"
            "💡 *ምሳሌ፦* 200 ካሬ ሜትር",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
        )
    else:
        await update.message.reply_text(
            "🛏️ **ደረጃ 2/6: የመኝታ ቤት ብዛት ያስገቡ፦**\n\n"
            "💡 *ምሳሌ፦* 2 መኝታ",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
        )
    return SELLER_DETAILS

async def seller_property_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['property_details'] = update.message.text
    
    await update.message.reply_text(
        "💰 **ደረጃ 3/6: የመሸጫ ዋጋ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* 5,000,000 ብር",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return SELLER_PRICE

async def seller_property_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_price(update.message.text):
        await update.message.reply_text(
            "❌ ዋጋው ትክክል አይደለም! እባክዎ ቁጥር ብቻ ያስገቡ።\n"
            "💡 *ምሳሌ፦* 5000000 ወይም 5,000,000",
            parse_mode="Markdown"
        )
        return SELLER_PRICE
    
    context.user_data['price'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("🔄 ድርድር አለው", callback_data="flow_sell_nego_yes")],
        [InlineKeyboardButton("❌ ድርድር የለውም", callback_data="flow_sell_nego_no")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🔄 **ደረጃ 4/6: የዋጋ ድርድር ሁኔታ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_NEGO

async def seller_property_nego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['negotiable'] = "✅ ድርድር አለው" if query.data == "flow_sell_nego_yes" else "❌ ድርድር የለውም"
    
    await query.edit_message_text(
        "📸 **ደረጃ 5/6: የንብረቱን ፎቶ ያስገቡ፦**\n\n"
        "📸 *ፎቶ/ሳይት ፕላን ለመላክ ፎቶውን ይላኩ*\n"
        "⏩ *ፎቶ ሳይላኩ ለመቀጠል '⏭️ ዝለል' ይጫኑ*",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ ዝለል", callback_data="flow_sell_skip_photo")],
            [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
        ]),
        parse_mode="Markdown"
    )
    return SELLER_PHOTO

async def seller_property_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        if query.data == "flow_sell_skip_photo":
            context.user_data['photo_id'] = None
            await query.edit_message_text(
                "📞 **ደረጃ 6/6: እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**\n\n"
                "💡 *ምሳሌ፦* 0912345678\n"
                "👤 *ወይም የቴሌግራም አድራሻዎን ይላኙ*",
                parse_mode="Markdown"
            )
            return SELLER_PHONE
        else:
            return await go_home(update, context)
    
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
        context.user_data['photo_id'] = photo_id
        
        await update.message.reply_text(
            "📞 **ደረጃ 6/6: እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**\n\n"
            "💡 *ምሳሌ፦* 0912345678\n"
            "👤 *ወይም የቴሌግራም አድራሻዎን ይላኙ*",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
        )
        return SELLER_PHONE
    else:
        await update.message.reply_text(
            "❌ እባክዎ ትክክለኛ ፎቶ ይላኩ ወይም '⏭️ ዝለል' ይጫኑ!",
            parse_mode="Markdown"
        )
        return SELLER_PHOTO

# ===== SHARED SELLER FUNCTIONS =====
async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    phone_input = update.message.text.strip()
    
    if phone_input.startswith('@'):
        context.user_data['phone'] = phone_input
    elif validate_phone(phone_input):
        context.user_data['phone'] = phone_input
    else:
        await update.message.reply_text(
            "❌ ስልክ ቁጥሩ ትክክል አይደለም! እባክዎ ትክክለኛ የኢትዮጵያ ስልክ ቁጥር ያስገቡ።\n"
            "💡 *ምሳሌ፦* 0912345678 ወይም @username",
            parse_mode="Markdown"
        )
        return SELLER_PHONE
    
    main_cat = context.user_data.get('main_category', '')
    
    if main_cat == "car":
        data = {
            'location': context.user_data.get('location', ''),
            'car_details': context.user_data.get('car_details', ''),
            'price': context.user_data.get('price', ''),
            'negotiable': context.user_data.get('negotiable', ''),
            'phone': context.user_data.get('phone', ''),
            'photo_id': context.user_data.get('photo_id')
        }
    else:
        data = {
            'location': context.user_data.get('location', ''),
            'property_subtype': context.user_data.get('property_subtype', ''),
            'property_details': context.user_data.get('property_details', ''),
            'price': context.user_data.get('price', ''),
            'negotiable': context.user_data.get('negotiable', ''),
            'phone': context.user_data.get('phone', ''),
            'photo_id': context.user_data.get('photo_id')
        }
    
    confirmation_text = format_listing_for_confirmation(data, main_cat)
    
    keyboard = [
        [InlineKeyboardButton("✅ አረጋግጥ", callback_data="flow_sell_confirm_yes")],
        [InlineKeyboardButton("✏️ አርም", callback_data="flow_sell_confirm_edit")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    
    await update.message.reply_text(
        confirmation_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_CONFIRM

async def seller_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    if query.data == "flow_sell_confirm_edit":
        await query.edit_message_text(
            "✏️ **መረጃዎችን ለማርም እንደገና ይጀምሩ።**\n\n"
            "📢 '📢 መሸጥ / ማከራየት' ይምረጡ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        context.user_data.clear()
        return ConversationHandler.END
    
    if query.data == "flow_sell_confirm_yes":
        user = update.effective_user
        main_cat = context.user_data.get('main_category', '')
        
        if main_cat == "car":
            desc = (
                f"📍 {context.user_data.get('location', '')}\n"
                f"🚗 {context.user_data.get('car_details', '')}\n"
                f"💰 {context.user_data.get('price', '')}\n"
                f"🔄 {context.user_data.get('negotiable', '')}\n"
                f"📞 {context.user_data.get('phone', '')}"
            )
        else:
            desc = (
                f"📍 {context.user_data.get('location', '')}\n"
                f"🏠 {context.user_data.get('property_subtype', '')}\n"
                f"📐 {context.user_data.get('property_details', '')}\n"
                f"💰 {context.user_data.get('price', '')}\n"
                f"🔄 {context.user_data.get('negotiable', '')}\n"
                f"📞 {context.user_data.get('phone', '')}"
            )
        
        req_id = add_listing(
            user.id,
            user.first_name,
            'SELL',
            main_cat,
            context.user_data.get('sub_category', ''),
            context.user_data.get('action_type', ''),
            context.user_data.get('property_type', ''),
            desc
        )
        
        if req_id:
            action_kbd = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ እፈልገዋለሁ", callback_data=f"item_resp_{req_id}_{user.id}_{main_cat}")]
            ])
            
            success_message = f"✅ **ማስታወቂያ ተመዝግቧል!** (#REQ-{req_id})\n\n{desc}"
            
            await query.edit_message_text(
                success_message,
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
                parse_mode="Markdown"
            )
            
            if ADMIN_CHAT_ID_INT:
                try:
                    photo_id = context.user_data.get('photo_id')
                    if photo_id:
                        await context.bot.send_photo(
                            chat_id=ADMIN_CHAT_ID_INT,
                            photo=photo_id,
                            caption=f"🔔 **አዲስ ማስታወቂያ!**\nID: #{req_id}\nUser: {user.first_name}\n\n{desc}",
                            reply_markup=action_kbd,
                            parse_mode="Markdown"
                        )
                    else:
                        admin_msg = f"🔔 **አዲስ ማስታወቂያ!**\nID: #{req_id}\nUser: {user.first_name}\n\n{desc}"
                        await context.bot.send_message(
                            chat_id=ADMIN_CHAT_ID_INT,
                            text=admin_msg,
                            reply_markup=action_kbd,
                            parse_mode="Markdown"
                        )
                except Exception as e:
                    logger.error(f"Admin notify error: {e}")
            
            logger.info(f"New listing created: #{req_id} by user {user.id}")
            context.user_data.clear()
            return ConversationHandler.END
        else:
            await query.edit_message_text(
                "❌ ማስታወቂያ ሲመዘገብ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
                parse_mode="Markdown"
            )
            context.user_data.clear()
            return ConversationHandler.END

# ==============================================================================
# 10. BROKER REGISTRATION
# ==============================================================================
async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "📝 **እንደ አቅራቢ/ደላላ መመዝገብ**\n\n"
        "1️⃣ ሙሉ ስምዎን ያስገቡ፦",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return BROKER_NAME

async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['broker_name'] = update.message.text
    await update.message.reply_text(
        "2️⃣ የስልክ ቁጥርዎን ያስገቡ፦",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return BROKER_PHONE

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(update.message.text):
        await update.message.reply_text(
            "❌ ስልክ ቁጥሩ ትክክል አይደለም! እባክዎ ትክክለኛ የኢትዮጵያ ስልክ ቁጥር ያስገቡ።",
            parse_mode="Markdown"
        )
        return BROKER_PHONE
    
    context.user_data['broker_phone'] = update.message.text
    
    keyboard = []
    for loc in LOCATIONS:
        keyboard.append([InlineKeyboardButton(loc, callback_data=f"broker_loc_{loc}")])
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await update.message.reply_text(
        "3️⃣ የሚሰሩበትን አካባቢ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BROKER_LOCATION

async def broker_reg_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
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
# 11. VIEW REQUESTS WITH PAGINATION
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
    page = context.user_data.get('view_page', 0)
    offset = page * ITEMS_PER_PAGE
    
    listings = get_listings_by_category(limit=ITEMS_PER_PAGE, offset=offset)
    total = count_listings()
    total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    
    if not listings:
        text = "📭 ምንም ንቁ ጥያቄዎች የሉም።"
        if update.message:
            await update.message.reply_text(
                text,
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        else:
            query = update.callback_query
            await query.answer()
            await query.edit_message_text(
                text,
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        return
    
    text = f"📋 **የፈላጊዎች ዝርዝር** (ገጽ {page+1}/{total_pages})\n\n"
    
    for listing in listings:
        icon = "🚗" if listing['main_category'] == "car" else "🏠" if listing['main_category'] == "house" else "🏢"
        action_icon = "🛍️" if listing.get('action_type') == "sell" else "🔑"
        
        text += f"{icon} **#{listing['id']}** {action_icon}\n"
        desc = listing['description'][:100] + "..." if len(listing['description']) > 100 else listing['description']
        text += f"📝 {desc}\n"
        if listing.get('created_at') and hasattr(listing['created_at'], 'strftime'):
            text += f"📅 {listing['created_at'].strftime('%Y-%m-%d %H:%M')}\n"
        text += "────────────────────\n"
    
    keyboard = []
    for listing in listings:
        keyboard.append([
            InlineKeyboardButton(
                f"✅ አለኝ - #{listing['id']}",
                callback_data=f"item_resp_{listing['id']}_{listing['user_chat_id']}_{listing['main_category']}"
            )
        ])
    
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

# ==============================================================================
# 12. RESPONSE FLOW
# ==============================================================================
async def start_item_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    
    context.user_data.clear()
    context.user_data['target_req_id'] = parts[2]
    context.user_data['target_user_id'] = int(parts[3])
    context.user_data['target_cat'] = parts[4] if len(parts) > 4 else "car"
    
    keyboard = [
        [InlineKeyboardButton("👤 የንብረቱ ባለቤት ነኝ", callback_data="resp_role_owner")],
        [InlineKeyboardButton("👨‍💼 ደላላ ነኝ", callback_data="resp_role_broker")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await query.message.reply_text(
        "📋 **የምላሽ ሰጭ ማንነት፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RESP_MAIN

async def resp_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['resp_role'] = "👤 ባለቤት" if query.data == "resp_role_owner" else "👨‍💼 ደላላ"
    
    target_cat = context.user_data.get('target_cat', 'car')
    
    if target_cat == "car":
        await query.edit_message_text(
            "🚘 **መኪና መልስ**\n\n"
            "1️⃣ የመኪናውን ሞዴል ያስገቡ፦",
            parse_mode="Markdown"
        )
        return RESP_DETAILS
    else:
        keyboard = []
        for ptype in PROPERTY_TYPES:
            keyboard.append([InlineKeyboardButton(ptype, callback_data=f"resp_prop_{ptype}")])
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
        await query.edit_message_text(
            "🏠 **ቤት መልስ**\n\n"
            "1️⃣ የቤት/ቦታ አይነት ይምረጡ፦",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return RESP_PROPERTY

async def resp_property_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    prop = query.data.replace("resp_prop_", "")
    context.user_data['resp_property'] = prop
    
    keyboard = []
    for htype in HOUSE_TYPES:
        keyboard.append([InlineKeyboardButton(htype, callback_data=f"resp_htype_{htype}")])
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await query.edit_message_text(
        "🏠 **የቤት አይነት ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RESP_SUB

async def resp_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    htype = query.data.replace("resp_htype_", "")
    context.user_data['resp_htype'] = htype
    
    await query.edit_message_text(
        "📍 **አካባቢ ያስገቡ፦**\n"
        "💡 *ምሳሌ፦* ቦሌ አትላስ",
        parse_mode="Markdown"
    )
    return RESP_DETAILS

async def resp_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['resp_details'] = update.message.text
    await update.message.reply_text(
        "💰 **ዋጋ ያስገቡ፦**",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return RESP_PRICE

async def resp_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_price(update.message.text):
        await update.message.reply_text(
            "❌ ዋጋው ትክክል አይደለም! እባክዎ ቁጥር ብቻ ያስገቡ።",
            parse_mode="Markdown"
        )
        return RESP_PRICE
    
    context.user_data['resp_price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🔄 ድርድር አለው", callback_data="resp_nego_yes")],
        [InlineKeyboardButton("❌ ድርድር የለውም", callback_data="resp_nego_no")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🔄 **የዋጋ ድርድር ሁኔታ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RESP_NEGO

async def resp_nego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['resp_nego'] = "✅ ድርድር አለው" if query.data == "resp_nego_yes" else "❌ ድርድር የለውም"
    
    await query.edit_message_text(
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* 0912345678",
        parse_mode="Markdown"
    )
    return RESP_PHONE

async def resp_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(update.message.text):
        await update.message.reply_text(
            "❌ ስልክ ቁጥሩ ትክክል አይደለም! እባክዎ ትክክለኛ የኢትዮጵያ ስልክ ቁጥር ያስገቡ።",
            parse_mode="Markdown"
        )
        return RESP_PHONE
    
    context.user_data['resp_phone'] = update.message.text
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ያስገቡ፦**\n\n"
        "📸 *ፎቶ ለመላክ ፎቶውን ይላኙ*",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return RESP_PHOTO

async def resp_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    responder = update.effective_user
    target_user_id = context.user_data.get('target_user_id')
    req_id = context.user_data.get('target_req_id')
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    
    if not photo_id:
        await update.message.reply_text(
            "❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!",
            parse_mode="Markdown"
        )
        return RESP_PHOTO
    
    role = context.user_data.get('resp_role', 'አቅራቢ')
    target_cat = context.user_data.get('target_cat', 'car')
    
    if target_cat == "car":
        detail_str = f"🚘 {context.user_data.get('resp_details')}"
    else:
        detail_str = f"🏠 {context.user_data.get('resp_property')} - {context.user_data.get('resp_htype')}\n📍 {context.user_data.get('resp_details')}"
    
    desc = (
        f"🎉 **አዲስ አማራጭ!** (#REQ-{req_id})\n\n"
        f"🎭 ሚና: {role}\n"
        f"{detail_str}\n"
        f"💰 {context.user_data.get('resp_price')}\n"
        f"🔄 {context.user_data.get('resp_nego')}\n"
        f"📞 {context.user_data.get('resp_phone')}\n"
        f"👤 @{responder.username if responder.username else responder.first_name}"
    )
    
    try:
        await context.bot.send_photo(
            chat_id=target_user_id,
            photo=photo_id,
            caption=desc,
            parse_mode="Markdown"
        )
        
        update_listing_status(int(req_id), 'responded')
        
        await update.message.reply_text(
            "✅ **መረጃዎች ለፈላጊው ተልከዋል!**\n\n"
            "📌 ጥያቄው ከ'📋 የፈላጊዎች ዝርዝር' ተወግዷል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        
        logger.info(f"Response sent to user {target_user_id} for listing #{req_id}")
        
    except Exception as e:
        logger.error(f"Error sending response: {e}")
        await update.message.reply_text(
            "❌ ምላሽ ሲላክ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 13. HELP
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

# ==============================================================================
# 14. ERROR HANDLER
# ==============================================================================
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
# 15. MAIN FUNCTION
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    
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

    # ===== SELLER CONVERSATION =====
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_message_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_message_handler],
            SELLER_CATEGORY: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_"), cancel_message_handler],
            SELLER_SUB: [
                CallbackQueryHandler(seller_car_sub_chosen, pattern="^flow_sell_sub_"),
                CallbackQueryHandler(seller_property_type_chosen, pattern="^flow_sell_prop_"),
                CallbackQueryHandler(seller_property_htype_chosen, pattern="^flow_sell_htype_"),
                cancel_message_handler
            ],
            SELLER_PROPERTY: [CallbackQueryHandler(seller_property_type_chosen, pattern="^flow_sell_prop_"), cancel_message_handler],
            SELLER_LOCATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_car_location),
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_property_location),
                cancel_message_handler
            ],
            SELLER_DETAILS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_car_details),
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_property_details),
                cancel_message_handler
            ],
            SELLER_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_car_price),
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_property_price),
                cancel_message_handler
            ],
            SELLER_NEGO: [
                CallbackQueryHandler(seller_car_nego, pattern="^flow_sell_nego_"),
                CallbackQueryHandler(seller_property_nego, pattern="^flow_sell_nego_"),
                cancel_message_handler
            ],
            SELLER_PHOTO: [
                CallbackQueryHandler(seller_car_photo, pattern="^flow_sell_skip_photo"),
                CallbackQueryHandler(seller_property_photo, pattern="^flow_sell_skip_photo"),
                MessageHandler(filters.PHOTO, seller_car_photo),
                MessageHandler(filters.PHOTO, seller_property_photo),
                cancel_message_handler
            ],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone), cancel_message_handler],
            SELLER_CONFIRM: [CallbackQueryHandler(seller_confirm, pattern="^flow_sell_confirm_"), cancel_message_handler],
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
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(response_conv)

    # ===== ERROR HANDLER =====
    app.add_error_handler(error_handler)

    logger.info("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()
