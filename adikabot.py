import logging
import os
import threading
import re
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
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

SUB_CITIES = [
    "ቦሌ", "የካ", "አራዳ", "ልደታ", 
    "ቂርቆስ", "አዲስ ከተማ", "ንፋስ ስልክ ላፍቶ", 
    "ኮልፌ ቀራኒዮ", "አቃቂ ቃሊቲ", "ጉሌሌ", "ላምበርት/የካ"
]

CAR_SUB_CATEGORIES = ["🚗 የቤት መኪና", "🚚 የሥራ መኪና", "🚜 ከባድ ተሽከርካሪ/ማሽን"]
HOUSE_TYPES = ["🏡 ቪላ", "🏢 አፓርታማ", "🏢 ኮንዶሚኒየም", "🏢 ሪል እስቴት", "🏞️ መሬት/ቦታ"]
PROPERTY_TYPES = ["🏠 መኖሪያ ቤት", "🏢 የሥራ ቦታ / ንግድ"]

# ==============================================================================
# 3. CONVERSATION STATES
# ==============================================================================
(
    BUYER_GOAL, BUYER_BRAND, BUYER_OTHER_BRAND, BUYER_MODEL, BUYER_OTHER_MODEL,
    BUYER_YEAR_FROM, BUYER_YEAR_TO, BUYER_TRANSMISSION, BUYER_CONDITION, BUYER_BUDGET, 
    BUYER_NEGOTIABLE, BUYER_PHONE, BUYER_EXPIRY,
    SELLER_GOAL, SELLER_ACTION, SELLER_BRAND, SELLER_OTHER_BRAND, SELLER_MODEL, 
    SELLER_OTHER_MODEL, SELLER_YEAR, SELLER_TRANSMISSION, SELLER_CONDITION,
    SELLER_PRICE, SELLER_DESCRIPTION, SELLER_PHONE, SELLER_PHOTO, SELLER_CATEGORY,
    BROKER_ROLE, BROKER_NAME, BROKER_PHONE, BROKER_SUBCITY, BROKER_NID_PHOTO,
    BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO
) = range(34)

# ==============================================================================
# 4. DATABASE UTILITIES
# ==============================================================================
def get_db_connection():
    if DATABASE_URL:
        cleaned_url = DATABASE_URL.strip().strip('"').strip("'")
        if cleaned_url.startswith("postgres://"):
            cleaned_url = cleaned_url.replace("postgres://", "postgresql://", 1)
        try:
            conn = psycopg2.connect(cleaned_url)
            conn.autocommit = True
            return conn
        except Exception as e:
            logging.error(f"❌ PostgreSQL connection failed: {e}")
            raise e
    else:
        import sqlite3
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "adika_marketplace.db")
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

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
                    car_brand TEXT,
                    car_model TEXT,
                    year_from INTEGER,
                    year_to INTEGER,
                    transmission TEXT,
                    car_condition TEXT,
                    budget BIGINT,
                    negotiable BOOLEAN DEFAULT TRUE,
                    phone TEXT,
                    expiry_date TIMESTAMP,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
                CREATE INDEX IF NOT EXISTS idx_listings_expiry ON listings(expiry_date);
                CREATE INDEX IF NOT EXISTS idx_listings_car_brand ON listings(car_brand);
                
                CREATE TABLE IF NOT EXISTS brokers (
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
                    car_brand TEXT,
                    car_model TEXT,
                    year_from INTEGER,
                    year_to INTEGER,
                    transmission TEXT,
                    car_condition TEXT,
                    budget INTEGER,
                    negotiable BOOLEAN DEFAULT 1,
                    phone TEXT,
                    expiry_date TIMESTAMP,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS brokers (
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
            
        logging.info("✅ Adika Database initialized successfully")
        
    except Exception as e:
        logging.error(f"❌ Database initialization error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 5. DATABASE OPERATIONS
# ==============================================================================
def add_listing_enhanced(
    user_chat_id, user_name, req_type, main_category, sub_category, 
    action_type, property_type, description, car_brand=None, car_model=None,
    year_from=None, year_to=None, transmission=None, car_condition=None,
    budget=None, negotiable=True, phone=None, expiry_date=None
):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        query = f"""
            INSERT INTO listings (
                user_chat_id, user_name, req_type, main_category, sub_category, 
                action_type, property_type, description, car_brand, car_model,
                year_from, year_to, transmission, car_condition, budget, 
                negotiable, phone, expiry_date
            )
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, 
                    {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        params = (
            user_chat_id, user_name, req_type, main_category, sub_category,
            action_type, property_type, description, car_brand, car_model,
            year_from, year_to, transmission, car_condition, budget,
            negotiable, phone, expiry_date
        )
        
        if DATABASE_URL:
            cursor.execute(query + " RETURNING id", params)
            req_id = cursor.fetchone()[0]
        else:
            cursor.execute(query, params)
            req_id = cursor.lastrowid
            conn.commit()
            
        return req_id
    except Exception as e:
        logging.error(f"Add listing enhanced error: {e}")
        return None
    finally:
        if conn:
            conn.close()

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
        logging.error(f"Add listing error: {e}")
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
        
        query = f"""
            SELECT * FROM listings 
            WHERE status = 'pending' 
            AND (expiry_date IS NULL OR expiry_date > datetime('now'))
            ORDER BY created_at DESC 
            LIMIT {p} OFFSET {p}
        """
        cursor.execute(query, (limit, offset))
        rows = cursor.fetchall()
        
        return [dict(row) for row in rows]
    except Exception as e:
        logging.error(f"Get listings error: {e}")
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
        logging.error(f"Count listings error: {e}")
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
        logging.error(f"Get listing by id error: {e}")
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
        logging.error(f"Update listing error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def add_broker(chat_id, full_name, phone, role_type, national_id_photo, sub_city):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        cursor.execute(f"SELECT id FROM brokers WHERE chat_id = {p}", (chat_id,))
        existing = cursor.fetchone()
        
        if existing:
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
        logging.error(f"Add broker error: {e}")
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
        logging.error(f"Get approved brokers error: {e}")
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
        logging.error(f"Update broker status error: {e}")
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
        logging.error(f"Get broker error: {e}")
        return None
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 6. HELPER FUNCTIONS
# ==============================================================================
def validate_phone(phone: str) -> bool:
    phone = phone.replace(' ', '').replace('-', '')
    pattern = r'^(09|07|01)\d{8}$|^\+251(9|7|1)\d{8}$'
    return bool(re.match(pattern, phone))

def validate_price(price: str) -> bool:
    price = price.replace(',', '').replace(' ', '')
    return price.isdigit()

def validate_year(year: str) -> bool:
    try:
        y = int(year)
        return 1990 <= y <= datetime.now().year
    except:
        return False

def format_number(num):
    return f"{num:,}".replace(',', ',')

def get_models_by_brand(brand):
    models = {
        "Toyota": ["Vitz", "Corolla", "Camry", "Land Cruiser", "Prado", "Hilux", "Yaris", "Avanza"],
        "Honda": ["Civic", "Accord", "CR-V", "HR-V", "Fit", "Pilot"],
        "Suzuki": ["Swift", "Alto", "Vitara", "Ertiga", "Jimny"],
        "Hyundai": ["Elantra", "Sonata", "Tucson", "Santa Fe", "Accent"],
        "Kia": ["Rio", "Sportage", "Sorento", "Cerato", "Stinger"],
        "Nissan": ["Sunny", "X-Trail", "Pathfinder", "Patrol", "Qashqai"],
        "Mitsubishi": ["Lancer", "Pajero", "Outlander", "ASX", "Delica"],
        "Mercedes": ["C-Class", "E-Class", "S-Class", "GLC", "GLE"],
        "BMW": ["3 Series", "5 Series", "7 Series", "X3", "X5"],
        "Volkswagen": ["Golf", "Passat", "Tiguan", "Jetta", "Polo"],
        "Ford": ["Focus", "Fiesta", "Mustang", "Ranger", "Explorer"],
        "Chevrolet": ["Cruze", "Malibu", "Trax", "Tahoe", "Suburban"],
    }
    return models.get(brand, ["ሌላ"])

async def notify_brokers(context: ContextTypes.DEFAULT_TYPE, message_text: str, req_id: int, buyer_id: int):
    approved_brokers = get_approved_brokers()
    if not approved_brokers:
        logger.info("No approved brokers found to notify")
        return
    
    for b_id in approved_brokers:
        try:
            kbd = [[
                InlineKeyboardButton(f"👉 አለኝ - #{req_id}", callback_data=f"have_item_{req_id}_{buyer_id}"),
                InlineKeyboardButton(f"📋 ዝርዝር", callback_data=f"view_req_{req_id}")
            ]]
            await context.bot.send_message(
                chat_id=b_id,
                text=f"🔔 **አዲስ ጥያቄ! (#{req_id})**\n\n{message_text}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kbd)
            )
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to send notification to broker {b_id}: {e}")

# ==============================================================================
# 7. START & CANCEL HANDLERS
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
# 7. BUYER FLOW - UPDATED WITH BUYER_CONTACT STATE (የተሻሻለ)
# ==============================================================================
# Update conversation states
(
    BUYER_MAIN, BUYER_ACTION, BUYER_SUB, BUYER_PROPERTY, BUYER_DETAILS, BUYER_PHONE,
    BROKER_ROLE, BROKER_NAME, BROKER_PHONE, BROKER_SUBCITY, BROKER_NID_PHOTO,
    SELLER_MAIN, SELLER_ACTION, SELLER_SUB, SELLER_PROPERTY, SELLER_DETAILS, SELLER_PRICE, SELLER_PHONE, SELLER_PHOTO,
    BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO, BUYER_CONTACT  # ✅ BUYER_CONTACT added
) = range(22)

async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start buyer flow - ask for category"""
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    
    keyboard = [
        [InlineKeyboardButton("🚗 መኪና", callback_data="flow_buy_cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ", callback_data="flow_buy_cat_house")],
        [InlineKeyboardButton("🏢 የሥራ ቦታ / ንግድ", callback_data="flow_buy_cat_commercial")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🔍 **የሚፈልጉትን ምድብ ይምረጡ፦**\n\n"
        "💡 *ምድብ ከመረጡ በኋላ ዝርዝር መረጃ ይሙሉ*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BUYER_MAIN

async def buyer_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection"""
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
    """Handle sub-category selection for car"""
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
    """Handle action selection"""
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    action = query.data.replace("flow_buy_action_", "")
    context.user_data['action_type'] = "መግዛት" if action == "buy" else "መከራየት"
    
    await query.edit_message_text(
        "✍️ **የሚፈልጉትን ዝርዝር መረጃ ያስገቡ፦**\n\n"
        "📝 **መረጃ ማስገቢያ ቅርጸት**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ **አይነት/ሞዴል** (ለመኪና) ወይም **የቤት አይነት**\n"
        "2️⃣ **አካባቢ** (የሚፈልጉት ቦታ)\n"
        "3️⃣ **በጀት** (ያዘጋጁት መጠን)\n\n"
        "💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020 ፣ አካባቢ: ቦሌ ፣ በጀት: 2.5 ሚሊዮን\n"
        "💡 *ምሳሌ፦* 2 መኝታ ቪላ ፣ አካባቢ: ሰሚ ፣ በጀት: 10 ሚሊዮን\n\n"
        "📝 ሙሉ መረጃዎን በአንድ መልእክት ይላኩ።",
        parse_mode="Markdown"
    )
    return BUYER_DETAILS

async def buyer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle details input - extract category, location and budget"""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    desc_text = update.message.text
    context.user_data['description'] = desc_text
    
    # Extract location
    location_match = re.search(r'አካባቢ[:\s]*([^\n,，;]+)', desc_text, re.IGNORECASE)
    location = location_match.group(1).strip() if location_match else "አልተጠቀሰም"
    context.user_data['location'] = location
    
    # Extract budget
    budget_match = re.search(r'በጀት[:\s]*([^\n,，;]+)', desc_text, re.IGNORECASE)
    budget = budget_match.group(1).strip() if budget_match else "አልተጠቀሰም"
    context.user_data['budget'] = budget
    
    # Extract car model or house type
    main_cat = context.user_data.get('main_category', '')
    if main_cat == 'car':
        car_model_match = re.search(r'(ቶዮታ|ቪትዝ|ኮሮላ|ያሪስ|ፕሪየስ|ሌላ|ቤት|ሥራ|ከባድ)[^\n,，;]*', desc_text, re.IGNORECASE)
        if car_model_match:
            model = car_model_match.group(0).strip()
            context.user_data['sub_category'] = model
    
    # Show extracted info for confirmation
    info_text = (
        "📝 **ያስገቡት መረጃ**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 **አካባቢ:** {location}\n"
        f"💰 **በጀት:** {budget}\n"
        f"📌 **ዝርዝር:** {desc_text[:100]}{'...' if len(desc_text) > 100 else ''}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**"
    )
    
    await update.message.reply_text(
        info_text,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return BUYER_CONTACT

async def buyer_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle contact input (phone) and finalize"""
    user = update.effective_user
    phone = update.message.text
    
    if phone == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    # Validate phone
    if not validate_phone(phone):
        await update.message.reply_text(
            "❌ **የስልክ ቁጥሩ ትክክል አይደለም!**\n\n"
            "📱 ትክክለኛ የስልክ ቁጥር ያስገቡ፦\n"
            "• 09XXXXXXXX (ለኢትዮጵያ)\n"
            "• +2519XXXXXXXX (ከውጭ)\n\n"
            "🔄 እባክዎ እንደገና ይሞክሩ።"
        )
        return BUYER_CONTACT
    
    # Get all data
    main_cat = context.user_data.get('main_category', '')
    sub_cat = context.user_data.get('sub_category', '')
    action_type = context.user_data.get('action_type', '')
    prop_subtype = context.user_data.get('property_subtype', '')
    description = context.user_data.get('description', '')
    location = context.user_data.get('location', '')
    budget = context.user_data.get('budget', '')
    
    # Determine category title
    if main_cat == "car":
        category_title = "🚗 አዲስ የመኪና ጥያቄ"
    elif main_cat == "house":
        category_title = "🏠 አዲስ የቤት/ቦታ ጥያቄ"
    else:
        category_title = "📌 አዲስ ጥያቄ"
    
    # Build full description with location and budget
    full_desc = (
        f"📌 **{category_title}**\n"
        f"🔹 አይነት: {prop_subtype if prop_subtype else sub_cat}\n"
        f"🔄 ፍላጎት: {action_type}\n"
        f"📍 አካባቢ: {location}\n"
        f"💰 በጀት: {budget}\n"
        f"📝 ዝርዝር: {description}\n"
        f"📞 ስልክ: {phone}"
    )
    
    # Save to database
    try:
        req_id = add_listing(
            user.id, 
            user.first_name, 
            'BUY', 
            main_cat, 
            sub_cat, 
            action_type, 
            prop_subtype, 
            full_desc
        )
    except Exception as e:
        logger.error(f"Error adding listing: {e}")
        req_id = None
    
    if req_id:
        # Success message
        success_text = (
            "✅ **ጥያቄዎ በተሳካ ሁኔታ ተመዝግቧል!**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **የጥያቄ ቁጥር:** `#{req_id}`\n"
            "📌 **ሁኔታ:** በመጠበቅ ላይ (Pending)\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📢 **ማሳወቂያ**\n"
            "ጥያቄዎ ለሁሉም የተመዘገቡ እና የተረጋገጡ ደላሎች ተልኳል።\n"
            "ተስማሚ አማራጭ ያለው ደላላ በቀጥታ ያገኝዎታል።\n\n"
            "📝 **ያስገቡት መረጃ**\n"
            f"• 🏷️ ምድብ: {main_cat.upper()}\n"
            f"• 🔄 ፍላጎት: {action_type}\n"
            f"• 📍 አካባቢ: {location}\n"
            f"• 💰 በጀት: {budget}\n"
            f"• 📞 ስልክ: {phone}\n\n"
            "💡 **ማሳሰቢያ**\n"
            "• ጥያቄዎን ማጥፋት ከፈለጉ '📋 የፈላጊዎች ዝርዝር' ውስጥ በመግባት ማጥፋት ይችላሉ።\n"
            "• ደላላ ሲያገኝዎት የጥያቄ ቁጥርዎን ይጥቀሱ።"
        )
        await update.message.reply_text(
            success_text,
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        # Notify brokers
        notification_text = (
            f"🔔 **{category_title}! (#REQ-{req_id})**\n\n"
            f"{full_desc}\n\n"
            f"👉 ይህ ንብረት በእጅዎ ካለ ከታች **'አለኝ'** የሚለውን በመጫን ለፈላጊው መረጃ ይላኩ!"
        )
        await notify_brokers(context, notification_text, req_id, user.id)
        
    else:
        # Error message
        await update.message.reply_text(
            "❌ **ጥያቄውን መመዝገብ አልተቻለም!**\n\n"
            "💡 እባክዎ የሚከተሉትን ያረጋግጡ፦\n"
            "• መረጃዎቹ ሙሉ መሆናቸውን\n"
            "• የበይነመረብ ግንኙነትዎን\n\n"
            "🔄 እንደገና ለመሞከር '🔍 መግዛት / መከራየት' ይጫኑ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )

    return ConversationHandler.END

# ==============================================================================
# BUYER CONVERSATION HANDLER (የተሻሻለ)
# ==============================================================================
buyer_conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('buy', buyer_start),
        MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start),
        CallbackQueryHandler(buyer_start, pattern='^flow_buy_start$')
    ],
    states={
        BUYER_MAIN: [
            CallbackQueryHandler(buyer_category_chosen, pattern='^flow_buy_cat_')
        ],
        BUYER_SUB: [
            CallbackQueryHandler(buyer_sub_chosen, pattern='^flow_buy_sub_')
        ],
        BUYER_ACTION: [
            CallbackQueryHandler(buyer_action_chosen, pattern='^flow_buy_action_')
        ],
        BUYER_DETAILS: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details)
        ],
        BUYER_CONTACT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_contact)
        ]
    },
    fallbacks=[
        CommandHandler('start', go_home),
        CallbackQueryHandler(go_home, pattern='^flow_home$'),
        MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), go_home)
    ],
    allow_reentry=True
)
# ==============================================================================
# 7. BUYER FLOW - COMPLETE FIX (የተስተካከለ)
# ==============================================================================
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
    
    try:
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
            await update.message.reply_text(
                "❌ **ጥያቄውን መመዝገብ አልተቻለም!**\n\n"
                "💡 እባክዎ የሚከተሉትን ያረጋግጡ፦\n"
                "• መረጃዎቹ ሙሉ መሆናቸውን\n"
                "• የበይነመረብ ግንኙነትዎን\n\n"
                "🔄 እንደገና ለመሞከር '🔍 መግዛት / መከራየት' ይጫኑ።",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
    except Exception as e:
        logger.error(f"Error in buyer_phone: {e}")
        await update.message.reply_text(
            f"❌ **ስህተተ!**\n\n"
            f"📝 ስህተት: {str(e)}\n\n"
            f"💡 እባክዎ እንደገና ይሞክሩ ወይም ድጋፍን ያግኙ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )

    return ConversationHandler.END
# ==============================================================================
# 9. BUYER CONFIRMATION HANDLERS
# ==============================================================================
async def confirm_buyer_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    data = context.user_data
    
    description = f"""
🚗 **አዲስ የመኪና ጥያቄ**

🎯 አገልግሎት: {data.get('goal', '')}
🚗 መኪና: {data.get('car_brand', '')} {data.get('car_model', '')}
📅 ዘመን: {data.get('year_from', '')} - {data.get('year_to', '')}
⚙️ ትራንስሚሽን: {data.get('transmission', '')}
🔧 ሁኔታ: {data.get('condition', '')}
💰 በጀት: {format_number(data.get('budget', 0))} ብር
🤝 ተደራዳሪ: {data.get('negotiable', '')}
📞 ስልክ: {data.get('phone', 'አልተሞላም')}
⏰ ያበቃል: {data.get('expiry', '')}
👤 ተጠቃሚ: @{user.username if user.username else user.first_name}
"""
    
    req_id = add_listing_enhanced(
        user_chat_id=user.id,
        user_name=user.first_name,
        req_type='BUY',
        main_category='CAR',
        sub_category=data.get('car_model', ''),
        action_type=data.get('goal', ''),
        property_type='',
        description=description,
        car_brand=data.get('car_brand', ''),
        car_model=data.get('car_model', ''),
        year_from=data.get('year_from', 0),
        year_to=data.get('year_to', 0),
        transmission=data.get('transmission', ''),
        car_condition=data.get('condition', ''),
        budget=data.get('budget', 0),
        negotiable=(data.get('negotiable') == "✅ ተደራዳሪ"),
        phone=data.get('phone', ''),
        expiry_date=data.get('expiry', ''),
    )
    
    if req_id:
        success_text = f"""
🎉 **ጥያቄዎ በስኬት ተልኳል!**

✅ **የጥያቄ ቁጥር፡** #{req_id}

📌 ጥያቄዎ ለተረጋገጡ ደላሎች ተልኳል።
⏰ እስከ {data.get('expiry', '')} ድረስ ንቁ ሆኖ ይቆያል።

💡 መልስ ሲያገኙ እዚሁ ቴሌግራም ላይ ይደርስዎታል።

🏠 ወደ ዋና ገጽ ለመመለስ ከታች ይጫኑ።
"""
        
        await query.edit_message_text(
            success_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
            ]),
            parse_mode="Markdown"
        )
        
        await notify_brokers(context, description, req_id, user.id)
        
    else:
        await query.edit_message_text(
            "❌ **ጥያቄውን መላክ አልተቻለም**\n\n"
            "💡 እባክዎ እንደገና ይሞክሩ።\n"
            "🔄 ችግሩ ከቀጠለ ድጋፍን ያግኙ።",
            parse_mode="Markdown"
        )

async def confirm_buyer_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "✏️ **መረጃ ለመቀየር ዝግጁ ነዎት**\n\n"
        "📝 የሚፈልጉትን መረጃ እንደገና ያስገቡ።",
        parse_mode="Markdown"
    )
    
    return await buyer_start(update, context)

async def confirm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🗑️ **ጥያቄዎ ተሰርዟል**\n\n"
        "💡 እንደገና ለመጀመር '🔍 መግዛት / መከራየት' ይጫኑ።",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ==============================================================================
# 10. SELLER FLOW - SIMPLIFIED FOR THIS VERSION
# ==============================================================================
async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    
    keyboard = [
        [InlineKeyboardButton("🚗 መኪና", callback_data="sell_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ", callback_data="sell_house")],
        [InlineKeyboardButton("🏢 የሥራ ቦታ / ንግድ", callback_data="sell_commercial")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    
    await update.message.reply_text(
        "📢 **የሚሸጡትን ወይም የሚያከራዩትን ምድብ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_GOAL

async def seller_goal_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    category = query.data.replace("sell_", "")
    context.user_data['main_category'] = category
    
    if category == "car":
        keyboard = [
            [
                InlineKeyboardButton("🛍️ መሸጥ", callback_data="sell_action_sell"),
                InlineKeyboardButton("🔑 ማከራየት", callback_data="sell_action_rent")
            ],
            [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
        ]
        
        await query.edit_message_text(
            "❓ **የድርጊት አይነት ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return SELLER_ACTION
    else:
        keyboard = [
            [InlineKeyboardButton("🛍️ መሸጥ", callback_data="sell_action_sell")],
            [InlineKeyboardButton("🔑 ማከራየት", callback_data="sell_action_rent")],
            [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
        ]
        await query.edit_message_text(
            "❓ **የድርጊት አይነት ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return SELLER_ACTION

async def seller_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    action = query.data.replace("sell_action_", "")
    context.user_data['action_type'] = "መሸጥ" if action == "sell" else "ማከራየት"
    
    main_cat = context.user_data.get('main_category', '')
    
    if main_cat == "car":
        car_brands = [
            "Toyota", "Honda", "Suzuki", "Hyundai", 
            "Kia", "Nissan", "Mitsubishi", "Mercedes",
            "BMW", "Volkswagen", "Ford", "Chevrolet",
            "ሌላ"
        ]
        
        keyboard = []
        row = []
        for i, brand in enumerate(car_brands):
            row.append(InlineKeyboardButton(brand, callback_data=f"sell_brand_{brand}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
        
        await query.edit_message_text(
            "🚗 **የመኪና ብራንድ ይምረጡ**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return SELLER_BRAND
    else:
        # For house/commercial
        keyboard = [[InlineKeyboardButton(ptype, callback_data=f"sell_prop_{ptype}")] for ptype in PROPERTY_TYPES]
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
        await query.edit_message_text(
            "🏠 **የንብረት አይነት ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return SELLER_CATEGORY

async def seller_brand_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    brand = query.data.replace("sell_brand_", "")
    context.user_data['car_brand'] = brand
    
    if brand == "ሌላ":
        await query.edit_message_text(
            "✍️ **የመኪና ብራንድ ያስገቡ**",
            parse_mode="Markdown"
        )
        return SELLER_OTHER_BRAND
    
    models = get_models_by_brand(brand)
    keyboard = []
    for model in models[:8]:
        keyboard.append([InlineKeyboardButton(model, callback_data=f"sell_model_{model}")])
    keyboard.append([InlineKeyboardButton("✍️ ሌላ ሞዴል", callback_data="sell_model_other")])
    keyboard.append([InlineKeyboardButton("◀️ ተመለስ", callback_data="back_sell_brand")])
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await query.edit_message_text(
        f"🚗 **{brand} - ሞዴል ይምረጡ**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_MODEL

async def seller_other_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['car_brand'] = update.message.text
    await update.message.reply_text(
        f"✍️ **የሞዴሉን ስም ያስገቡ**\n\n🚗 {context.user_data['car_brand']} ሞዴል፡",
        parse_mode="Markdown"
    )
    return SELLER_OTHER_MODEL

async def seller_other_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['car_model'] = update.message.text
    
    current_year = datetime.now().year
    years = list(range(current_year, 1999, -1))
    
    keyboard = []
    row = []
    for i, year in enumerate(years[:20]):
        row.append(InlineKeyboardButton(str(year), callback_data=f"sell_year_from_{year}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("✍️ በጽሁፍ አስገባ", callback_data="sell_year_from_text")])
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await update.message.reply_text(
        f"🚗 **{context.user_data['car_brand']} {context.user_data['car_model']}**\n\n"
        f"📅 **የተሰራበት ዘመን ይምረጡ ወይም ያስገቡ**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_YEAR

async def seller_model_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_sell_brand":
        return await seller_action_chosen(update, context)
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    if query.data == "sell_model_other":
        await query.edit_message_text(
            "✍️ **የመኪናውን ሞዴል ያስገቡ**",
            parse_mode="Markdown"
        )
        return SELLER_OTHER_MODEL
    
    model = query.data.replace("sell_model_", "")
    context.user_data['car_model'] = model
    
    current_year = datetime.now().year
    years = list(range(current_year, 1999, -1))
    
    keyboard = []
    row = []
    for i, year in enumerate(years[:20]):
        row.append(InlineKeyboardButton(str(year), callback_data=f"sell_year_from_{year}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("✍️ በጽሁፍ አስገባ", callback_data="sell_year_from_text")])
    keyboard.append([InlineKeyboardButton("◀️ ተመለስ", callback_data="back_sell_model")])
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await query.edit_message_text(
        f"🚗 **{context.user_data['car_brand']} {model}**\n\n"
        f"📅 **የተሰራበት ዘመን ይምረጡ ወይም ያስገቡ**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_YEAR

async def seller_year_from_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_sell_model":
        return await seller_model_chosen(update, context)
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    if query.data == "sell_year_from_text":
        await query.edit_message_text(
            "✍️ **የመጀመሪያውን ዘመን በቁጥር ያስገቡ**",
            parse_mode="Markdown"
        )
        return SELLER_YEAR
    
    year = int(query.data.replace("sell_year_from_", ""))
    context.user_data['year_from'] = year
    
    current_year = datetime.now().year
    years = list(range(current_year, 1999, -1))
    
    keyboard = []
    row = []
    for i, year in enumerate(years[:20]):
        row.append(InlineKeyboardButton(str(year), callback_data=f"sell_year_to_{year}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("✍️ በጽሁፍ አስገባ", callback_data="sell_year_to_text")])
    keyboard.append([InlineKeyboardButton("◀️ ተመለስ", callback_data="back_sell_year_from")])
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await query.edit_message_text(
        f"📅 **ከ {context.user_data['year_from']} እስከ መቼ?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_YEAR

async def seller_year_from_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    year_text = update.message.text.strip()
    if not validate_year(year_text):
        await update.message.reply_text("❌ ትክክለኛ ዘመን አይደለም!")
        return SELLER_YEAR
    
    context.user_data['year_from'] = int(year_text)
    
    current_year = datetime.now().year
    years = list(range(current_year, 1999, -1))
    
    keyboard = []
    row = []
    for i, year in enumerate(years[:20]):
        row.append(InlineKeyboardButton(str(year), callback_data=f"sell_year_to_{year}"))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("✍️ በጽሁፍ አስገባ", callback_data="sell_year_to_text")])
    keyboard.append([InlineKeyboardButton("◀️ ተመለስ", callback_data="back_sell_year_from")])
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await update.message.reply_text(
        f"📅 **ከ {context.user_data['year_from']} እስከ መቼ?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_YEAR

async def seller_year_to_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "back_sell_year_from":
        return await seller_year_from_chosen(update, context)
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    if query.data == "sell_year_to_text":
        await query.edit_message_text(
            "✍️ **የመጨረሻውን ዘመን በቁጥር ያስገቡ**",
            parse_mode="Markdown"
        )
        return SELLER_YEAR
    
    year = int(query.data.replace("sell_year_to_", ""))
    context.user_data['year_to'] = year
    
    keyboard = [
        [
            InlineKeyboardButton("⚙️ አውቶማቲክ", callback_data="sell_trans_auto"),
            InlineKeyboardButton("⚙️ ማኑዋል", callback_data="sell_trans_manual")
        ],
        [
            InlineKeyboardButton("⚙️ አይመርጥም", callback_data="sell_trans_any")
        ],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    
    await query.edit_message_text(
        f"🚗 **{context.user_data['car_brand']} {context.user_data['car_model']}**\n"
        f"📅 **ዘመን፡** {context.user_data['year_from']} - {year}\n\n"
        f"⚙️ **የትራንስሚሽን አይነት ይምረጡ**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_TRANSMISSION

async def seller_year_to_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    year_text = update.message.text.strip()
    if not validate_year(year_text):
        await update.message.reply_text("❌ ትክክለኛ ዘመን አይደለም!")
        return SELLER_YEAR
    
    context.user_data['year_to'] = int(year_text)
    
    keyboard = [
        [
            InlineKeyboardButton("⚙️ አውቶማቲክ", callback_data="sell_trans_auto"),
            InlineKeyboardButton("⚙️ ማኑዋል", callback_data="sell_trans_manual")
        ],
        [
            InlineKeyboardButton("⚙️ አይመርጥም", callback_data="sell_trans_any")
        ],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    
    await update.message.reply_text(
        f"🚗 **{context.user_data['car_brand']} {context.user_data['car_model']}**\n"
        f"📅 **ዘመን፡** {context.user_data['year_from']} - {context.user_data['year_to']}\n\n"
        f"⚙️ **የትራንስሚሽን አይነት ይምረጡ**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_TRANSMISSION

async def seller_transmission_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    trans_map = {
        "sell_trans_auto": "አውቶማቲክ",
        "sell_trans_manual": "ማኑዋል",
        "sell_trans_any": "አይመርጥም"
    }
    context.user_data['transmission'] = trans_map.get(query.data, "አይመርጥም")
    
    keyboard = [
        [
            InlineKeyboardButton("🆕 አዲስ", callback_data="sell_cond_new"),
            InlineKeyboardButton("🔧 የሰራ", callback_data="sell_cond_used")
        ],
        [
            InlineKeyboardButton("✅ ልዩነት የለውም", callback_data="sell_cond_any")
        ],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    
    await query.edit_message_text(
        f"🚗 **{context.user_data['car_brand']} {context.user_data['car_model']}**\n"
        f"📅 **ዘመን፡** {context.user_data['year_from']} - {context.user_data['year_to']}\n"
        f"⚙️ **ትራንስሚሽን፡** {context.user_data['transmission']}\n\n"
        f"🔧 **የመኪና ሁኔታ ይምረጡ**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_CONDITION

async def seller_condition_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    cond_map = {
        "sell_cond_new": "🆕 አዲስ",
        "sell_cond_used": "🔧 የሰራ",
        "sell_cond_any": "✅ ልዩነት የለውም"
    }
    context.user_data['condition'] = cond_map.get(query.data, "ልዩነት የለውም")
    
    await query.edit_message_text(
        "💰 **ዋጋ ያስገቡ**\n\n💡 በብር ያስገቡ።",
        parse_mode="Markdown"
    )
    return SELLER_PRICE

async def seller_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    price_text = update.message.text.replace(',', '').replace(' ', '')
    if not price_text.isdigit():
        await update.message.reply_text("❌ ትክክለኛ ቁጥር ያስገቡ")
        return SELLER_PRICE
    
    context.user_data['price'] = int(price_text)
    
    await update.message.reply_text(
        "📝 **የመኪናውን ዝርዝር መረጃ ያስገቡ**",
        parse_mode="Markdown"
    )
    return SELLER_DESCRIPTION

async def seller_description_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data['description'] = update.message.text
    
    await update.message.reply_text(
        "📞 **የስልክ ቁጥርዎን ያስገቡ**",
        parse_mode="Markdown"
    )
    return SELLER_PHONE

async def seller_phone_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(update.message.text):
        await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ")
        return SELLER_PHONE
    
    context.user_data['phone'] = update.message.text
    
    await update.message.reply_text(
        "📸 **የመኪናውን ፎቶ ይላኩ**\n\n💡 ፎቶ ከሌለዎት '⏭️ ዝለል' ብለው ይጻፉ",
        parse_mode="Markdown"
    )
    return SELLER_PHOTO

async def seller_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo_id = None
    
    if update.message.text and update.message.text == "⏭️ ዝለል":
        photo_id = None
    elif update.message.photo:
        photo_id = update.message.photo[-1].file_id
    else:
        await update.message.reply_text("❌ እባክዎ ፎቶ ይላኩ ወይም '⏭️ ዝለል' ይጻፉ")
        return SELLER_PHOTO
    
    data = context.user_data
    
    description = f"""
📢 **አዲስ የሽያጭ ማስታወቂያ!**

🚗 መኪና: {data.get('car_brand', '')} {data.get('car_model', '')}
📅 ዘመን: {data.get('year_from', '')} - {data.get('year_to', '')}
⚙️ ትራንስሚሽን: {data.get('transmission', '')}
🔧 ሁኔታ: {data.get('condition', '')}
💰 ዋጋ: {format_number(data.get('price', 0))} ብር
📝 ዝርዝር: {data.get('description', '')}
📞 ስልክ: {data.get('phone', '')}
👤 ተጠቃሚ: @{user.username if user.username else user.first_name}
"""
    
    req_id = add_listing_enhanced(
        user_chat_id=user.id,
        user_name=user.first_name,
        req_type='SELL',
        main_category='CAR',
        sub_category=data.get('car_model', ''),
        action_type=data.get('action_type', ''),
        property_type='',
        description=description,
        car_brand=data.get('car_brand', ''),
        car_model=data.get('car_model', ''),
        year_from=data.get('year_from', 0),
        year_to=data.get('year_to', 0),
        transmission=data.get('transmission', ''),
        car_condition=data.get('condition', ''),
        budget=data.get('price', 0),
        negotiable=True,
        phone=data.get('phone', ''),
        expiry_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"),
    )
    
    if req_id:
        await update.message.reply_text(
            f"🎉 **ማስታወቂያዎ በስኬት ተልኳል!** (#{req_id})",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        await notify_brokers(context, description, req_id, user.id)
    else:
        await update.message.reply_text(
            "❌ **ማስታወቂያውን መላክ አልተቻለም**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 11. SELLER HOUSE/PROPERTY HANDLERS
# ==============================================================================
async def seller_property_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    prop = query.data.replace("sell_prop_", "")
    context.user_data['property_type'] = prop
    
    keyboard = [[InlineKeyboardButton(htype, callback_data=f"sell_htype_{htype}")] for htype in HOUSE_TYPES]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await query.edit_message_text(
        "🏠 **የቤቱ አይነት ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_CATEGORY

async def seller_house_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    htype = query.data.replace("sell_htype_", "")
    context.user_data['property_subtype'] = htype
    
    await query.edit_message_text(
        "💰 **ዋጋ ያስገቡ**",
        parse_mode="Markdown"
    )
    return SELLER_PRICE

async def seller_house_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    price_text = update.message.text.replace(',', '').replace(' ', '')
    if not price_text.isdigit():
        await update.message.reply_text("❌ ትክክለኛ ቁጥር ያስገቡ")
        return SELLER_PRICE
    
    context.user_data['price'] = int(price_text)
    await update.message.reply_text("📝 **የቤቱን/ቦታውን ዝርዝር መረጃ ያስገቡ**")
    return SELLER_DESCRIPTION

async def seller_house_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['description'] = update.message.text
    await update.message.reply_text("📞 **የስልክ ቁጥርዎን ያስገቡ**")
    return SELLER_PHONE

async def seller_house_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(update.message.text):
        await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ")
        return SELLER_PHONE
    
    context.user_data['phone'] = update.message.text
    await update.message.reply_text("📸 **የቤቱን/ቦታውን ፎቶ ይላኩ**")
    return SELLER_PHOTO

async def seller_house_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo_id = None
    
    if update.message.text and update.message.text == "⏭️ ዝለል":
        photo_id = None
    elif update.message.photo:
        photo_id = update.message.photo[-1].file_id
    else:
        await update.message.reply_text("❌ እባክዎ ፎቶ ይላኩ ወይም '⏭️ ዝለል' ይጻፉ")
        return SELLER_PHOTO
    
    data = context.user_data
    
    description = f"""
📢 **አዲስ የ{data.get('action_type', '')} ማስታወቂያ!**

🏠 {data.get('property_subtype', '')}
📝 {data.get('description', '')}
💰 {format_number(data.get('price', 0))} ብር
📞 {data.get('phone', '')}
👤 @{user.username if user.username else user.first_name}
"""
    
    req_id = add_listing(
        user_chat_id=user.id,
        user_name=user.first_name,
        req_type='SELL',
        main_category=data.get('main_category', ''),
        sub_category=data.get('property_subtype', ''),
        action_type=data.get('action_type', ''),
        property_type=data.get('property_type', ''),
        description=description
    )
    
    if req_id:
        await update.message.reply_text(
            f"🎉 **ማስታወቂያዎ በስኬት ተልኳል!** (#{req_id})",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        await notify_brokers(context, description, req_id, user.id)
    else:
        await update.message.reply_text(
            "❌ **ማስታወቂያውን መላክ አልተቻለም**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 12. BROKER REGISTRATION
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
        "📝 **የምዝገባ አይነት ይምረጡ፦**",
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
        await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ።")
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
        "4️⃣ **የፋይዳ (National ID) ወይም የነዋሪነት መታወቂያ ፎቶ ያንሱና ይላኩ፦**"
    )
    return BROKER_NID_PHOTO

async def broker_reg_nid_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    user = update.effective_user
    
    if not update.message or not update.message.photo:
        await update.message.reply_text("❌ **እባክዎ የመታወቂያዎን ፎቶ ይላኩ!**")
        return BROKER_NID_PHOTO
        
    existing_broker = get_broker(user.id)
    if existing_broker:
        await update.message.reply_text(
            "ℹ️ **አስቀድመው ተመዝግበዋል!**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return ConversationHandler.END
        
    photo_id = update.message.photo[-1].file_id
    role = context.user_data.get('broker_role', 'አቅራቢ')
    name = context.user_data.get('broker_name', user.first_name)
    phone = context.user_data.get('broker_phone', '')
    sub_city = context.user_data.get('broker_subcity', '')
    
    broker_id = add_broker(user.id, name, phone, role, photo_id, sub_city)
    
    if broker_id:
        await update.message.reply_text(
            "✅ **ምዝገባዎ በስኬት ተጠናቋል!** 🎉\n\n⏳ አድሚኑ መረጃዎን ካረጋገጠ በኋላ ማስታወቂያ ይደርስዎታል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID_INT != 0:
            admin_msg = (
                f"🚨 **አዲስ የ{role} ምዝገባ ጥያቄ!**\n\n"
                f"👤 ስም: {name}\n🎭 ሚና: {role}\n📞 ስልክ: {phone}\n📍 ክፍለ ከተማ: {sub_city}\n🆔 Telegram ID: `{user.id}`"
            )
            admin_kbd = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ አጽድቅ", callback_data=f"admin_appr_{user.id}"),
                 InlineKeyboardButton("❌ ሰርዝ", callback_data=f"admin_reje_{user.id}")]
            ])
            try:
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID_INT,
                    photo=photo_id,
                    caption=admin_msg,
                    parse_mode="Markdown",
                    reply_markup=admin_kbd
                )
            except Exception as e:
                logger.error(f"Failed to send admin approval: {e}")
    else:
        await update.message.reply_text(
            "❌ **ምዝገባውን ማጠናቀቅ አልተቻለም!**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 13. ADMIN APPROVAL HANDLER
# ==============================================================================
async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("admin_appr_"):
        target_id = int(data.replace("admin_appr_", ""))
        update_broker_status(target_id, 'approved')
        await query.edit_message_caption(
            caption=query.message.caption + "\n\n✅ **ሁኔታ፦ በስኬት ጸድቋል**",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="🎉 **እንኳን ደስ አለዎት!** ምዝገባዎ ተጸደቀ።",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        except Exception as e:
            logger.error(f"Could not notify approved user: {e}")
            
    elif data.startswith("admin_reje_"):
        target_id = int(data.replace("admin_reje_", ""))
        update_broker_status(target_id, 'rejected')
        await query.edit_message_caption(
            caption=query.message.caption + "\n\n❌ **ሁኔታ፦ ተሰርዟል**",
            parse_mode="Markdown"
        )

# ==============================================================================
# 14. VIEW REQUESTS
# ==============================================================================
async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID_INT)
    broker = get_broker(user_id)
    
    if not is_admin and not broker:
        await update.message.reply_text(
            "⛔ ይህን ገጽ ማየት የሚችሉት የተመዘገቡ አቅራቢዎች/ደላሎች ወይም አድሚን ብቻ ናቸው!",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    if not is_admin and broker.get('status') != 'approved':
        await update.message.reply_text(
            "⏳ **ምዝገባዎ ገና በአድሚን አልጸደቀም!**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    context.user_data['view_page'] = 1
    await show_requests_page(update, context)

ITEMS_PER_PAGE = 5

async def show_requests_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.callback_query and update.callback_query.data.startswith("page_"):
            page = int(update.callback_query.data.replace("page_", ""))
            context.user_data['view_page'] = page
            query = update.callback_query
            await query.answer()
        else:
            page = context.user_data.get('view_page', 1)
        
        offset = (page - 1) * ITEMS_PER_PAGE
        listings = get_listings_by_category(limit=ITEMS_PER_PAGE, offset=offset)
        total = count_listings()
        
        total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        
        if page > total_pages:
            page = total_pages
            context.user_data['view_page'] = page
        
        if not listings:
            text = "📭 **ምንም ንቁ ጥያቄዎች የሉም**"
            if update.message:
                await update.message.reply_text(text, parse_mode="Markdown")
            else:
                await update.callback_query.edit_message_text(text, parse_mode="Markdown")
            return
        
        user_id = update.effective_user.id
        is_admin = (user_id == ADMIN_CHAT_ID_INT)
        
        if is_admin:
            broker_name = "👑 አድሚን"
        else:
            broker_data = get_broker(user_id)
            broker_name = broker_data.get('full_name', 'ደላላ') if broker_data else 'ደላላ'
        
        message = f"📋 **የፈላጊዎች ዝርዝር** | 👤 {broker_name}\n"
        message += f"━━━━━━━━━━━━━━━━━━━━━━\n"
        message += f"🔹 ገጽ {page}/{total_pages} (ጠቅላላ፡ {total} ጥያቄዎች)\n\n"
        
        for listing in listings:
            req_id = listing.get('id')
            description = listing.get('description', '')
            action_type = listing.get('action_type', 'N/A')
            car_brand = listing.get('car_brand', '')
            car_model = listing.get('car_model', '')
            
            phone_match = re.search(r'📞 ስልክ:\s*([\d+]+)', description)
            phone = phone_match.group(1) if phone_match else 'N/A'
            
            if car_brand and car_model:
                title = f"🚗 {car_brand} {car_model}"
            elif listing.get('main_category') == 'CAR':
                title = "🚗 መኪና"
            else:
                title = "🏠 ንብረት"
            
            message += f"📌 **#{req_id}** - {title}\n"
            message += f"   {action_type} | 📞 {phone}\n"
            message += "   ─────────────\n\n"
        
        keyboard = []
        pagination_row = []
        if page > 1:
            pagination_row.append(InlineKeyboardButton("◀️ ፊተኛ", callback_data=f"page_{page-1}"))
        pagination_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="none"))
        if page < total_pages:
            pagination_row.append(InlineKeyboardButton("ቀጣይ ▶️", callback_data=f"page_{page+1}"))
        keyboard.append(pagination_row)
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
        
        if update.message:
            await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await update.callback_query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            
    except Exception as e:
        logger.error(f"Error in show_requests_page: {e}", exc_info=True)
        error_text = "❌ **ስህተተ!** ዝርዝሩን ማሳየት አልተቻለም።"
        if update.message:
            await update.message.reply_text(error_text, parse_mode="Markdown")
        else:
            await update.callback_query.edit_message_text(error_text, parse_mode="Markdown")

# ==============================================================================
# 15. BROKER RESPONSE FLOW
# ==============================================================================
async def broker_have_item_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    broker = get_broker(user_id)
    
    if not broker or broker.get('status') != 'approved':
        await query.message.reply_text("⛔ ይህን ማድረግ የሚችሉት የተረጋገጡ ደላሎች ብቻ ናቸው!")
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
        f"✅ **ጥያቄ #{req_id}**\n\n✍️ **ያለዎትን ንብረት ዝርዝር መረጃ እና ዋጋ ያስገቡ፦**"
    )
    return BROKER_OFFER_TEXT

async def broker_offer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
        
    context.user_data['offer_text'] = update.message.text
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ይላኩ፦**\n(ፎቶ ከሌልዎት '⏭️ ዝለል' ብለው ይጻፉ)"
    )
    return BROKER_OFFER_PHOTO

async def broker_offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buyer_id = int(context.user_data.get('target_buyer_id'))
    req_id = context.user_data.get('target_req_id')
    offer_text = context.user_data.get('offer_text')
    broker_name = update.effective_user.first_name
    
    broker = get_broker(update.effective_user.id)
    broker_phone = broker.get('phone', '') if broker else ''
    
    message_to_buyer = (
        f"🎉 **ለጥያቄዎ (#REQ-{req_id}) አዲስ የቀረበ አማራጭ አለ!**\n\n"
        f"👤 **ደላላ/አቅራቢ፦** {broker_name}\n"
        f"📞 **ስልክ:** {broker_phone}\n"
        f"📝 **የንብረቱ ዝርዝር፦**\n{offer_text}"
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
            await context.bot.send_message(
                chat_id=buyer_id,
                text=message_to_buyer,
                parse_mode="Markdown"
            )
            
        await update.message.reply_text(
            "✅ **መረጃዎ ለፈላጊው በስኬት ተልኳል!**",
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
# 16. DELETE REQUEST HANDLER
# ==============================================================================
async def delete_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID_INT)
    
    parts = query.data.split('_')
    if len(parts) < 3:
        await query.message.reply_text("❌ የተሳሳተ መረጃ ተላኳል።")
        return
    
    req_id = int(parts[2])
    listing = get_listing_by_id(req_id)
    
    if not listing:
        await query.message.reply_text("❌ ጥያቄው አልተገኘም።")
        return
    
    if not is_admin and listing.get('user_chat_id') != user_id:
        await query.message.reply_text("⛔ ይህን ጥያቄ የማጥፋት ፈቃድ የለዎትም!")
        return
    
    success = update_listing_status(req_id, 'deleted')
    
    if success:
        await query.edit_message_text(
            f"🗑️ **ጥያቄ #{req_id} ተሰርዟል**",
            parse_mode="Markdown"
        )
    else:
        await query.message.reply_text("❌ ጥያቄውን ማጥፋት አልተቻለም።")

# ==============================================================================
# 17. HELP COMMAND
# ==============================================================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
❓ **እንዴት እንደሚጠቀሙ**

🔍 **መግዛት ከፈለጉ:**
• '🔍 መግዛት / መከራየት' ይምረጡ
• የመኪና ብራንድ ይምረጡ
• ሞዴል፣ ዘመን፣ ትራንስሚሽን ይምረጡ
• በጀት እና መረጃ ይሙሉ

📢 **መሸጥ ከፈለጉ:**
• '📢 መሸጥ / ማከራየት' ይምረጡ
• የመኪና ብራንድ ይምረጡ
• ሞዴል፣ ዘመን፣ ትራንስሚሽን ይምረጡ
• ዋጋ እና መረጃ ይሙሉ

📝 **እንደ አቅራቢ ለመመዝገብ:**
• '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይምረጡ
• ሚናዎን ይምረጡ
• የፋይዳ መታወቂያ ፎቶ ይላኩ

📋 **የፈላጊዎች ዝርዝር:**
• ለተመዘገቡ እና ለተጸደቁ አቅራቢዎች ብቻ
• ንቁ ጥያቄዎችን ያሳያል
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ==============================================================================
# 18. MAIN ENGINE
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))

    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)

    # BUYER CONVERSATION
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
        states={
            BUYER_GOAL: [CallbackQueryHandler(buyer_goal_chosen, pattern="^goal_"), cancel_message_handler],
            BUYER_BRAND: [CallbackQueryHandler(buyer_brand_chosen, pattern="^brand_"), cancel_message_handler],
            BUYER_OTHER_BRAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_other_brand), cancel_message_handler],
            BUYER_MODEL: [CallbackQueryHandler(buyer_model_chosen, pattern="^model_"), cancel_message_handler],
            BUYER_OTHER_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_other_model), cancel_message_handler],
            BUYER_YEAR_FROM: [CallbackQueryHandler(buyer_year_from_chosen, pattern="^year_from_"), MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_year_from_text), cancel_message_handler],
            BUYER_YEAR_TO: [CallbackQueryHandler(buyer_year_to_chosen, pattern="^year_to_"), MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_year_to_text), cancel_message_handler],
            BUYER_TRANSMISSION: [CallbackQueryHandler(buyer_transmission_chosen, pattern="^trans_"), cancel_message_handler],
            BUYER_CONDITION: [CallbackQueryHandler(buyer_condition_chosen, pattern="^cond_"), cancel_message_handler],
            BUYER_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_budget), cancel_message_handler],
            BUYER_NEGOTIABLE: [CallbackQueryHandler(buyer_negotiable_chosen, pattern="^nego_"), cancel_message_handler],
            BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone_enhanced), cancel_message_handler],
            BUYER_EXPIRY: [CallbackQueryHandler(buyer_expiry_chosen, pattern="^exp_"), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # SELLER CONVERSATION
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_GOAL: [CallbackQueryHandler(seller_goal_chosen, pattern="^sell_"), cancel_message_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^sell_action_"), cancel_message_handler],
            SELLER_BRAND: [CallbackQueryHandler(seller_brand_chosen, pattern="^sell_brand_"), cancel_message_handler],
            SELLER_OTHER_BRAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_other_brand), cancel_message_handler],
            SELLER_MODEL: [CallbackQueryHandler(seller_model_chosen, pattern="^sell_model_"), cancel_message_handler],
            SELLER_OTHER_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_other_model), cancel_message_handler],
            SELLER_YEAR: [CallbackQueryHandler(seller_year_from_chosen, pattern="^sell_year_from_"), CallbackQueryHandler(seller_year_to_chosen, pattern="^sell_year_to_"), MessageHandler(filters.TEXT & ~filters.COMMAND, seller_year_from_text), MessageHandler(filters.TEXT & ~filters.COMMAND, seller_year_to_text), cancel_message_handler],
            SELLER_TRANSMISSION: [CallbackQueryHandler(seller_transmission_chosen, pattern="^sell_trans_"), cancel_message_handler],
            SELLER_CONDITION: [CallbackQueryHandler(seller_condition_chosen, pattern="^sell_cond_"), cancel_message_handler],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price_input), cancel_message_handler],
            SELLER_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_description_input), cancel_message_handler],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone_input), cancel_message_handler],
            SELLER_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, seller_photo_input), cancel_message_handler],
            SELLER_CATEGORY: [CallbackQueryHandler(seller_property_type_chosen, pattern="^sell_prop_"), CallbackQueryHandler(seller_house_type_chosen, pattern="^sell_htype_"), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # BROKER REGISTRATION CONVERSATION
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

    # BROKER RESPONSE CONVERSATION
    broker_response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broker_have_item_click, pattern="^have_item_")],
        states={
            BROKER_OFFER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text), cancel_message_handler],
            BROKER_OFFER_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, broker_offer_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # Add all handlers
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
    app.add_handler(MessageHandler(cancel_filter, go_home))
    app.add_handler(CallbackQueryHandler(show_requests_page, pattern="^page_"))
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(admin_approval_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(delete_request_callback, pattern="^delete_item_"))
    app.add_handler(CallbackQueryHandler(confirm_buyer_submit, pattern="^confirm_buyer_submit$"))
    app.add_handler(CallbackQueryHandler(confirm_buyer_edit, pattern="^confirm_buyer_edit$"))
    app.add_handler(CallbackQueryHandler(confirm_cancel, pattern="^confirm_cancel$"))

    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(broker_response_conv)

    logger.info("🚀 Adika Marketplace Bot ተጀምሯል... (Enhanced Version)")
    app.run_polling()

if __name__ == "__main__":
    main()
