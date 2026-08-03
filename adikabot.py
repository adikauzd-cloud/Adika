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
        
        cursor.execute(query.replace("?", p) if DATABASE_URL else query, params)
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
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ መመዝገብ", "📋 የፈላጊዎች ዝርዝር"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]

LOCATIONS = ["ቦሌ", "ሲኤምሲ", "ሳሪስ", "አያት", "ገርጂ", "ካዛንችስ", "መገናኛ", "ቃሊቲ", "ልደታ", "አራዳ"]

# Sub-categories
CAR_SUB_CATEGORIES = ["🚗 የቤት መኪና", "🚚 የሥራ መኪና", "🚜 ከባድ ተሽከርካሪ/ማሽን"]

HOUSE_TYPES = ["🏡 ቪላ", "🏢 ሙሉ ግቢ", "🏢 አፓርታማ", "🏢 ሪል እስቴት", "🏞️ መሬት/ቦታ"]

# Action types
ACTION_TYPES = ["🛍️ ሽያጭ", "🔑 ኪራይ"]

# Property types for house
PROPERTY_TYPES = ["🏠 መኖሪያ", "🏢 የሥራ ቦታ"]

# ==============================================================================
# 4. CONVERSATION STATES
# ==============================================================================
# Buyer Flow States
BUYER_MAIN, BUYER_ACTION, BUYER_CATEGORY, BUYER_SUB, BUYER_PROPERTY, BUYER_DETAILS, BUYER_PHONE = range(7)

# Seller Flow States
SELLER_MAIN, SELLER_ACTION, SELLER_CATEGORY, SELLER_SUB, SELLER_PROPERTY, SELLER_DETAILS, SELLER_PRICE, SELLER_NEGO, SELLER_PHONE, SELLER_PHOTO = range(7, 17)

# Broker Registration States
BROKER_NAME, BROKER_PHONE, BROKER_LOCATION = range(17, 20)

# Response Flow States
RESP_MAIN, RESP_ACTION, RESP_CATEGORY, RESP_SUB, RESP_PROPERTY, RESP_DETAILS, RESP_PRICE, RESP_NEGO, RESP_PHONE, RESP_PHOTO = range(20, 30)

# ==============================================================================
# 5. START & MAIN MENU
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
# 6. CANCEL HANDLER
# ==============================================================================
async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = (
        "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
        "የሀገሪቱ ታላቁ የመኪና፣ የቤት እና የንብረት ገበያ ማዕከል።\n\n"
        "እባክዎን ከታች ካሉት አማራጮች አንዱን ይምረጡ፦"
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
# 7. BUYER FLOW - NESTED HANDLERS
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
    
    # Show sub-categories or action type based on main category
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
        # House or Commercial - show action type first
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
    
    # For car, show action type
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
        # Show property type for house/commercial
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
    
    # Show house types
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
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return BUYER_PHONE

async def buyer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    phone = update.message.text
    
    main_cat = context.user_data.get('main_category', '')
    sub_cat = context.user_data.get('sub_category', '')
    action_type = context.user_data.get('action_type', '')
    property_type = context.user_data.get('property_type', '')
    description = context.user_data.get('description', '')
    
    # Build description
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
    
    return ConversationHandler.END

# ==============================================================================
# 8. SELLER FLOW - NESTED HANDLERS
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
        # Show property type for house/commercial
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

async def seller_sub_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    sub = query.data.replace("flow_sell_sub_", "")
    context.user_data['sub_category'] = sub
    
    await query.edit_message_text(
        "✍️ **የመኪናውን ዝርዝር መረጃ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020፣ 50,000 ኪሎ ሜትር",
        parse_mode="Markdown"
    )
    return SELLER_DETAILS

async def seller_property_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "🏠 **የቤት አይነት ይምረጡ፦**",
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
        "✍️ **የቤቱን/ቦታውን ዝርዝር መረጃ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* ቦሌ አትላስ አካባቢ 3 መኝታ ቤት",
        parse_mode="Markdown"
    )
    return SELLER_DETAILS

async def seller_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['description'] = update.message.text
    await update.message.reply_text(
        "💰 **የመሸጫ/የመከራያ ዋጋ ያስገቡ፦**",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return SELLER_PRICE

async def seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🔄 ድርድር አለው", callback_data="flow_sell_nego_yes")],
        [InlineKeyboardButton("❌ ድርድር የለውም", callback_data="flow_sell_nego_no")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🔄 **የዋጋ ድርድር ሁኔታ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_NEGO

async def seller_nego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['negotiable'] = "✅ ድርድር አለው" if query.data == "flow_sell_nego_yes" else "❌ ድርድር የለውም"
    
    await query.edit_message_text(
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**",
        parse_mode="Markdown"
    )
    return SELLER_PHONE

async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['phone'] = update.message.text
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ያስገቡ፦**",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return SELLER_PHOTO

async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return SELLER_PHOTO
    
    desc = (
        f"📝 {context.user_data.get('description')}\n"
        f"💰 {context.user_data.get('price')}\n"
        f"🔄 {context.user_data.get('negotiable')}\n"
        f"📞 {context.user_data.get('phone')}"
    )
    
    req_id = add_listing(
        user.id, user.first_name, 'SELL',
        context.user_data.get('main_category', ''),
        context.user_data.get('sub_category', ''),
        context.user_data.get('action_type', ''),
        context.user_data.get('property_type', ''),
        desc
    )
    
    if req_id:
        action_kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ እፈልገዋለሁ", callback_data=f"item_resp_{req_id}_{user.id}_{context.user_data.get('main_category', '')}")]
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
                    caption=f"🔔 አዲስ ማስታወቂያ!\n\n{desc}",
                    reply_markup=action_kbd,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    
    return ConversationHandler.END

# ==============================================================================
# 9. BROKER REGISTRATION
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
    context.user_data['broker_name'] = update.message.text
    await update.message.reply_text(
        "2️⃣ የስልክ ቁጥርዎን ያስገቡ፦",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return BROKER_PHONE

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
# 10. VIEW REQUESTS - WITH PAGINATION
# ==============================================================================
ITEMS_PER_PAGE = 5

async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check if user is registered broker
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
    
    if not listings:
        await update.message.reply_text(
            "📭 ምንም ንቁ ጥያቄዎች የሉም።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    text = f"📋 **የፈላጊዎች ዝርዝር** (ገጽ {page+1})\n\n"
    
    for idx, listing in enumerate(listings, 1):
        req_id, chat_id, name, req_type, main_cat, sub_cat, action_type, prop_type, desc, status, created = listing
        icon = "🚗" if main_cat == "car" else "🏠"
        action_icon = "🛍️" if action_type == "sell" else "🔑"
        
        text += f"{icon} **#{req_id}** {action_icon}\n"
        text += f"📝 {desc[:100]}...\n" if len(desc) > 100 else f"📝 {desc}\n"
        text += f"📅 {created.strftime('%Y-%m-%d') if hasattr(created, 'strftime') else created}\n"
        text += f"🆔 {chat_id}\n"
        
        # Add response button for each listing
        keyboard = [[InlineKeyboardButton(f"✅ አለኝ - #{req_id}", callback_data=f"item_resp_{req_id}_{chat_id}_{main_cat}")]]
        text += "────────────────────\n"
    
    # Pagination buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ ቀዳሚ", callback_data=f"page_{page-1}"))
    if offset + ITEMS_PER_PAGE < total:
        nav_buttons.append(InlineKeyboardButton("➡️ ቀጣይ", callback_data=f"page_{page+1}"))
    nav_buttons.append(InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home"))
    
    keyboard = [[InlineKeyboardButton("📋 ሙሉ ዝርዝር አሳይ", callback_data=f"detail_view_{listings[0][0]}")]]
    if nav_buttons:
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
# 11. RESPONSE FLOW
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
    context.user_data['resp_details'] = update.message.text
    await update.message.reply_text(
        "💰 **ዋጋ ያስገቡ፦**",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return RESP_PRICE

async def resp_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**",
        parse_mode="Markdown"
    )
    return RESP_PHONE

async def resp_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_phone'] = update.message.text
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ያስገቡ፦**",
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
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
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
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    
    return ConversationHandler.END

# ==============================================================================
# 12. HELP
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
• መረጃ ይሙሉ

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
# 13. MAIN FUNCTION
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))

    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)

    # ===== BUYER CONVERSATION =====
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

    # ===== SELLER CONVERSATION =====
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

    # ===== OTHER HANDLERS =====
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(MessageHandler(cancel_filter, go_home))
    
    # Pagination handler
    app.add_handler(CallbackQueryHandler(show_requests_page, pattern="^page_"))
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))

    # ===== ADD CONVERSATIONS =====
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(response_conv)

    # ===== ERROR HANDLER =====
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} caused error: {context.error}", exc_info=True)

    app.add_error_handler(error_handler)

    logger.info("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()
