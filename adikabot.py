import logging
import os
import threading
import time
from functools import wraps
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
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
# 0. CONFIGURATION
# ==============================================================================
@dataclass
class Config:
    BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")
    ADMIN_CHAT_ID: int = int(os.environ.get("ADMIN_CHAT_ID", "0"))
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
    PORT: int = int(os.environ.get("PORT", "8080"))
    ITEMS_PER_PAGE: int = 5
    MAX_PHOTO_SIZE: int = 20 * 1024 * 1024  # 20MB
    MAX_DESCRIPTION_LENGTH: int = 1000
    MAX_RETRIES: int = 3
    RETRY_DELAY: int = 1  # seconds

    def validate(self):
        if not self.BOT_TOKEN:
            raise ValueError("❌ BOT_TOKEN is required")
        if not self.DATABASE_URL:
            logging.warning("⚠️ DATABASE_URL not set, using SQLite")

config = Config()
config.validate()

# ==============================================================================
# 1. LOGGING
# ==============================================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("adika_bot.log")
    ]
)
logger = logging.getLogger(__name__)

# ==============================================================================
# 2. FLASK WEB SERVER
# ==============================================================================
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return jsonify({
        "status": "online",
        "service": "Adika Marketplace Bot",
        "version": "2.0.0"
    }), 200

@web_app.route('/health')
def health():
    try:
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
    web_app.run(host="0.0.0.0", port=config.PORT, debug=False)

# ==============================================================================
# 3. DATABASE MANAGER
# ==============================================================================
@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    conn = None
    try:
        if config.DATABASE_URL:
            db_url = config.DATABASE_URL.replace("postgres://", "postgresql://", 1)
            conn = psycopg2.connect(db_url)
            conn.autocommit = True
        else:
            import sqlite3
            conn = sqlite3.connect("adika_marketplace.db")
            conn.row_factory = sqlite3.Row
        
        yield conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise
    finally:
        if conn:
            try:
                conn.close()
            except Exception as e:
                logger.error(f"Error closing connection: {e}")

def retry_on_error(max_retries: int = 3, delay: int = 1):
    """Decorator for retrying database operations"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        time.sleep(delay * (attempt + 1))
                        logger.warning(f"Retry {attempt + 1}/{max_retries} for {func.__name__}")
                    else:
                        logger.error(f"All retries failed for {func.__name__}: {e}")
            raise last_error
        return wrapper
    return decorator

def init_db():
    """Initialize database tables"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Listings table
        if config.DATABASE_URL:
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_listings_status (status),
                    INDEX idx_listings_category (main_category, sub_category)
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_category ON listings(main_category, sub_category)")
        
        # Brokers table
        if config.DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS brokers (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    location TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_brokers_chat_id (chat_id)
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
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_brokers_chat_id ON brokers(chat_id)")
        
        # Responses table
        if config.DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS responses (
                    id SERIAL PRIMARY KEY,
                    listing_id INTEGER NOT NULL,
                    responder_chat_id BIGINT NOT NULL,
                    responder_name TEXT,
                    responder_role TEXT NOT NULL,
                    description TEXT NOT NULL,
                    price TEXT,
                    negotiable BOOLEAN DEFAULT TRUE,
                    phone TEXT NOT NULL,
                    photo_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (listing_id) REFERENCES listings(id),
                    INDEX idx_responses_listing_id (listing_id)
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS responses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER NOT NULL,
                    responder_chat_id INTEGER NOT NULL,
                    responder_name TEXT,
                    responder_role TEXT NOT NULL,
                    description TEXT NOT NULL,
                    price TEXT,
                    negotiable BOOLEAN DEFAULT TRUE,
                    phone TEXT NOT NULL,
                    photo_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (listing_id) REFERENCES listings(id)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_responses_listing_id ON responses(listing_id)")
        
        if config.DATABASE_URL:
            conn.commit()
        
        logger.info("✅ Database initialized successfully")

# ==============================================================================
# 4. DATABASE OPERATIONS
# ==============================================================================
@retry_on_error()
def add_listing(user_chat_id: int, user_name: str, req_type: str, main_category: str,
                sub_category: str, action_type: str, property_type: str, description: str) -> Optional[int]:
    """Add a new listing to the database"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if config.DATABASE_URL:
            cursor.execute("""
                INSERT INTO listings (user_chat_id, user_name, req_type, main_category, sub_category, 
                                     action_type, property_type, description)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (user_chat_id, user_name, req_type, main_category, sub_category, action_type, property_type, description))
            req_id = cursor.fetchone()[0]
        else:
            cursor.execute("""
                INSERT INTO listings (user_chat_id, user_name, req_type, main_category, sub_category, 
                                     action_type, property_type, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_chat_id, user_name, req_type, main_category, sub_category, action_type, property_type, description))
            req_id = cursor.lastrowid
        
        if not config.DATABASE_URL:
            conn.commit()
        return req_id

@retry_on_error()
def get_listing(listing_id: int) -> Optional[Dict]:
    """Get a single listing by ID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if config.DATABASE_URL:
            cursor.execute("SELECT * FROM listings WHERE id = %s", (listing_id,))
        else:
            cursor.execute("SELECT * FROM listings WHERE id = ?", (listing_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

@retry_on_error()
def get_listings(filters: Dict[str, Any] = None, limit: int = 10, offset: int = 0) -> List[Dict]:
    """Get listings with filters"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM listings WHERE status = 'pending'"
        params = []
        
        if filters:
            if filters.get('main_category'):
                query += f" AND main_category = {'%s' if config.DATABASE_URL else '?'}"
                params.append(filters['main_category'])
            if filters.get('sub_category'):
                query += f" AND sub_category = {'%s' if config.DATABASE_URL else '?'}"
                params.append(filters['sub_category'])
            if filters.get('action_type'):
                query += f" AND action_type = {'%s' if config.DATABASE_URL else '?'}"
                params.append(filters['action_type'])
            if filters.get('property_type'):
                query += f" AND property_type = {'%s' if config.DATABASE_URL else '?'}"
                params.append(filters['property_type'])
            if filters.get('req_type'):
                query += f" AND req_type = {'%s' if config.DATABASE_URL else '?'}"
                params.append(filters['req_type'])
        
        query += " ORDER BY created_at DESC LIMIT {} OFFSET {}".format(
            '%s' if config.DATABASE_URL else '?',
            '%s' if config.DATABASE_URL else '?'
        )
        params.extend([limit, offset])
        
        if config.DATABASE_URL:
            cursor.execute(query, params)
        else:
            cursor.execute(query, params)
        
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

@retry_on_error()
def update_listing_status(listing_id: int, status: str) -> bool:
    """Update listing status"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if config.DATABASE_URL:
            cursor.execute("UPDATE listings SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                          (status, listing_id))
        else:
            cursor.execute("UPDATE listings SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                          (status, listing_id))
        
        if not config.DATABASE_URL:
            conn.commit()
        return cursor.rowcount > 0

@retry_on_error()
def count_listings(filters: Dict[str, Any] = None) -> int:
    """Count listings with filters"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT COUNT(*) FROM listings WHERE status = 'pending'"
        params = []
        
        if filters:
            for key, value in filters.items():
                if value:
                    query += f" AND {key} = {'%s' if config.DATABASE_URL else '?'}"
                    params.append(value)
        
        if config.DATABASE_URL:
            cursor.execute(query, params)
        else:
            cursor.execute(query, params)
        
        return cursor.fetchone()[0]

@retry_on_error()
def add_broker(chat_id: int, full_name: str, phone: str, location: str) -> Optional[int]:
    """Add a new broker"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if config.DATABASE_URL:
            cursor.execute("""
                INSERT INTO brokers (chat_id, full_name, phone, location)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (chat_id) DO UPDATE SET 
                    full_name = EXCLUDED.full_name,
                    phone = EXCLUDED.phone,
                    location = EXCLUDED.location,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
            """, (chat_id, full_name, phone, location))
            broker_id = cursor.fetchone()[0]
        else:
            cursor.execute("""
                INSERT OR REPLACE INTO brokers (chat_id, full_name, phone, location)
                VALUES (?, ?, ?, ?)
            """, (chat_id, full_name, phone, location))
            broker_id = cursor.lastrowid
            conn.commit()
        return broker_id

@retry_on_error()
def get_broker(chat_id: int) -> Optional[Dict]:
    """Get broker by chat ID"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if config.DATABASE_URL:
            cursor.execute("SELECT * FROM brokers WHERE chat_id = %s", (chat_id,))
        else:
            cursor.execute("SELECT * FROM brokers WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

@retry_on_error()
def add_response(listing_id: int, responder_chat_id: int, responder_name: str,
                responder_role: str, description: str, price: str, negotiable: bool,
                phone: str, photo_id: str = None) -> Optional[int]:
    """Add a response to a listing"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if config.DATABASE_URL:
            cursor.execute("""
                INSERT INTO responses (listing_id, responder_chat_id, responder_name, responder_role,
                                      description, price, negotiable, phone, photo_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (listing_id, responder_chat_id, responder_name, responder_role,
                  description, price, negotiable, phone, photo_id))
            response_id = cursor.fetchone()[0]
        else:
            cursor.execute("""
                INSERT INTO responses (listing_id, responder_chat_id, responder_name, responder_role,
                                      description, price, negotiable, phone, photo_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (listing_id, responder_chat_id, responder_name, responder_role,
                  description, price, negotiable, phone, photo_id))
            response_id = cursor.lastrowid
            conn.commit()
        return response_id

# ==============================================================================
# 5. CONSTANTS & KEYBOARDS
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
# 6. CONVERSATION STATES
# ==============================================================================
# Buyer Flow
BUYER_MAIN, BUYER_ACTION, BUYER_CATEGORY, BUYER_SUB, BUYER_PROPERTY, BUYER_DETAILS, BUYER_PHONE = range(7)

# Seller Flow
SELLER_MAIN, SELLER_ACTION, SELLER_CATEGORY, SELLER_SUB, SELLER_PROPERTY, SELLER_DETAILS, SELLER_PRICE, SELLER_NEGO, SELLER_PHONE, SELLER_PHOTO = range(7, 17)

# Broker Registration
BROKER_NAME, BROKER_PHONE, BROKER_LOCATION = range(17, 20)

# Response Flow
RESP_MAIN, RESP_ROLE, RESP_PROPERTY, RESP_SUB, RESP_DETAILS, RESP_PRICE, RESP_NEGO, RESP_PHONE, RESP_PHOTO = range(20, 29)

# ==============================================================================
# 7. HELPER FUNCTIONS
# ==============================================================================
def create_keyboard(buttons: List[str], callback_prefix: str, row_width: int = 1, include_home: bool = True) -> InlineKeyboardMarkup:
    """Create an inline keyboard from a list of buttons"""
    keyboard = []
    for i in range(0, len(buttons), row_width):
        row = []
        for button in buttons[i:i + row_width]:
            row.append(InlineKeyboardButton(button, callback_data=f"{callback_prefix}_{button}"))
        keyboard.append(row)
    
    if include_home:
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    return InlineKeyboardMarkup(keyboard)

def create_pagination_keyboard(current_page: int, total_pages: int, callback_prefix: str = "page") -> InlineKeyboardMarkup:
    """Create pagination keyboard"""
    buttons = []
    
    if current_page > 0:
        buttons.append(InlineKeyboardButton("⬅️ ቀዳሚ", callback_data=f"{callback_prefix}_{current_page - 1}"))
    
    buttons.append(InlineKeyboardButton(f"📄 {current_page + 1}/{total_pages}", callback_data="noop"))
    
    if current_page < total_pages - 1:
        buttons.append(InlineKeyboardButton("➡️ ቀጣይ", callback_data=f"{callback_prefix}_{current_page + 1}"))
    
    keyboard = [buttons] if buttons else []
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    return InlineKeyboardMarkup(keyboard)

def format_listing(listing: Dict) -> str:
    """Format a listing for display"""
    main_cat = listing.get('main_category', '')
    icon = "🚗" if main_cat == "car" else "🏠" if main_cat == "house" else "🏢"
    action_icon = "🛍️" if listing.get('action_type') == "sell" else "🔑"
    
    text = f"{icon} **#{listing['id']}** {action_icon}\n"
    text += f"📝 {listing['description'][:200]}"
    if len(listing['description']) > 200:
        text += "..."
    text += "\n"
    
    if listing.get('created_at'):
        created = listing['created_at']
        if hasattr(created, 'strftime'):
            text += f"📅 {created.strftime('%Y-%m-%d %H:%M')}\n"
    
    return text

def validate_phone(phone: str) -> bool:
    """Validate phone number format"""
    import re
    # Ethiopian phone number pattern
    pattern = r'^(09|07|01)\d{8}$|^\+251(09|07|01)\d{8}$'
    return bool(re.match(pattern, phone.replace(' ', '').replace('-', '')))

def validate_price(price: str) -> bool:
    """Validate price format"""
    import re
    pattern = r'^[\d,]+(\.[\d]{2})?$|^[\d]+(\.[\d]{2})?$'
    return bool(re.match(pattern, price.replace(',', '')))

# ==============================================================================
# 8. START & MAIN MENU
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start command handler"""
    user = update.effective_user
    context.user_data.clear()
    
    welcome_text = (
        f"👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
        f"የሀገሪቱ ታላቁ የመኪና፣ የቤት እና የንብረት ገበያ ማዕከል።\n\n"
        f"እባክዎን ከታች ካሉት አማራጮች አንዱን ይምረጡ፦"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    
    logger.info(f"User {user.id} ({user.first_name}) started the bot")
    return ConversationHandler.END

# ==============================================================================
# 9. CANCEL & HOME HANDLER
# ==============================================================================
async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    
    return ConversationHandler.END

# ==============================================================================
# 10. BUYER FLOW
# ==============================================================================
async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start buyer flow"""
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

async def buyer_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle buyer category selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    cat = query.data.replace("flow_buy_cat_", "")
    context.user_data['main_category'] = cat
    
    if cat == "car":
        keyboard = create_keyboard(CAR_SUB_CATEGORIES, "flow_buy_sub")
        await query.edit_message_text(
            "🚗 **የመኪና ንኡስ ምድብ ይምረጡ፦**",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return BUYER_SUB
    else:
        keyboard = create_keyboard(ACTION_TYPES, "flow_buy_action")
        await query.edit_message_text(
            "❓ **የሚፈልጉትን የድርጊት አይነት ይምረጡ፦**",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return BUYER_ACTION

async def buyer_sub_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle buyer sub-category selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    sub = query.data.replace("flow_buy_sub_", "")
    context.user_data['sub_category'] = sub
    
    keyboard = create_keyboard(ACTION_TYPES, "flow_buy_action")
    await query.edit_message_text(
        f"✅ {sub}\n\n❓ **የሚፈልጉትን የድርጊት አይነት ይምረጡ፦**",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    return BUYER_ACTION

async def buyer_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle buyer action selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    action = query.data.replace("flow_buy_action_", "")
    context.user_data['action_type'] = "sell" if "ሽያጭ" in action else "rent"
    
    main_cat = context.user_data.get('main_category', '')
    
    if main_cat == "car":
        await query.edit_message_text(
            "✍️ **የሚፈልጉትን መኪና ዝርዝር መረጃ ያስገቡ፦**\n\n"
            "💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020፣ ባጀት እስከ 2.5 ሚሊዮን ብር",
            parse_mode="Markdown"
        )
        return BUYER_DETAILS
    else:
        keyboard = create_keyboard(PROPERTY_TYPES, "flow_buy_prop")
        await query.edit_message_text(
            f"🏠 **የቤት/ቦታ አይነት ይምረጡ፦**",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return BUYER_PROPERTY

async def buyer_property_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle buyer property type selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    prop = query.data.replace("flow_buy_prop_", "")
    context.user_data['property_type'] = prop
    
    keyboard = create_keyboard(HOUSE_TYPES, "flow_buy_htype")
    await query.edit_message_text(
        f"🏠 **የቤት አይነት ይምረጡ፦**",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    return BUYER_SUB

async def buyer_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle buyer house type selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    htype = query.data.replace("flow_buy_htype_", "")
    context.user_data['property_subtype'] = htype
    
    await query.edit_message_text(
        f"🏠 **{htype}**\n\n"
        "✍️ **የሚፈልጉትን ቤት/ቦታ ዝርዝር መረጃ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* ቦሌ አትላስ አካባቢ 2 መኝታ፣ ባጀት እስከ 10 ሚሊዮን ብር",
        parse_mode="Markdown"
    )
    return BUYER_DETAILS

async def buyer_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle buyer details input"""
    text = update.message.text
    
    if len(text) > config.MAX_DESCRIPTION_LENGTH:
        await update.message.reply_text(
            f"❌ መረጃ በጣም ረጅም ነው! እባክዎ ከ{config.MAX_DESCRIPTION_LENGTH} ፊደላት በታች ያስገቡ።"
        )
        return BUYER_DETAILS
    
    context.user_data['description'] = text
    
    await update.message.reply_text(
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* 0912345678",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return BUYER_PHONE

async def buyer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle buyer phone input"""
    phone = update.message.text.strip()
    
    if phone == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(phone):
        await update.message.reply_text(
            "❌ ስልክ ቁጥሩ ትክክል አይደለም! እባክዎ ትክክለኛ የኢትዮጵያ ስልክ ቁጥር ያስገቡ።\n"
            "💡 *ምሳሌ፦* 0912345678 ወይም +251912345678",
            parse_mode="Markdown"
        )
        return BUYER_PHONE
    
    user = update.effective_user
    req_id = add_listing(
        user.id,
        user.first_name,
        context.user_data.get('req_type', 'BUY'),
        context.user_data.get('main_category', ''),
        context.user_data.get('sub_category', ''),
        context.user_data.get('action_type', ''),
        context.user_data.get('property_type', ''),
        f"{context.user_data.get('description', '')}\n📞 {phone}"
    )
    
    if req_id:
        await update.message.reply_text(
            f"✅ **ጥያቄዎ ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"📌 ጥያቄዎ በ'📋 የፈላጊዎች ዝርዝር' ውስጥ ይታያል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        
        # Notify admin
        if config.ADMIN_CHAT_ID:
            try:
                admin_msg = (
                    f"🔔 **አዲስ ጥያቄ!**\n"
                    f"ID: #{req_id}\n"
                    f"User: {user.first_name} (@{user.username or 'No username'})\n"
                    f"Category: {context.user_data.get('main_category', '')}\n"
                    f"Phone: {phone}"
                )
                await context.bot.send_message(
                    chat_id=config.ADMIN_CHAT_ID,
                    text=admin_msg,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notification error: {e}")
    else:
        await update.message.reply_text(
            "❌ ጥያቄዎ ሲመዘገብ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 11. SELLER FLOW
# ==============================================================================
async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start seller flow"""
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    
    keyboard = create_keyboard(ACTION_TYPES, "flow_sell_action")
    await update.message.reply_text(
        "📢 **የሚፈልጉትን የድርጊት አይነት ይምረጡ፦**",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    return SELLER_MAIN

async def seller_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle seller action selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    action = query.data.replace("flow_sell_action_", "")
    context.user_data['action_type'] = "sell" if "ሽያጭ" in action else "rent"
    
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

async def seller_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle seller category selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    cat = query.data.replace("flow_sell_cat_", "")
    context.user_data['main_category'] = cat
    
    if cat == "car":
        keyboard = create_keyboard(CAR_SUB_CATEGORIES, "flow_sell_sub")
        await query.edit_message_text(
            "🚗 **የመኪና ንኡስ ምድብ ይምረጡ፦**",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return SELLER_SUB
    else:
        keyboard = create_keyboard(PROPERTY_TYPES, "flow_sell_prop")
        await query.edit_message_text(
            "🏠 **የቤት/ቦታ አይነት ይምረጡ፦**",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return SELLER_PROPERTY

async def seller_sub_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle seller sub-category selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    sub = query.data.replace("flow_sell_sub_", "")
    context.user_data['sub_category'] = sub
    
    await query.edit_message_text(
        "✍️ **የመኪናውን ዝርዝር መረጃ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020፣ 50,000 ኪሎ ሜትር",
        parse_mode="Markdown"
    )
    return SELLER_DETAILS

async def seller_property_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle seller property type selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    prop = query.data.replace("flow_sell_prop_", "")
    context.user_data['property_type'] = prop
    
    keyboard = create_keyboard(HOUSE_TYPES, "flow_sell_htype")
    await query.edit_message_text(
        "🏠 **የቤት አይነት ይምረጡ፦**",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    return SELLER_SUB

async def seller_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle seller house type selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    htype = query.data.replace("flow_sell_htype_", "")
    context.user_data['property_subtype'] = htype
    
    await query.edit_message_text(
        "✍️ **የቤቱን/ቦታውን ዝርዝር መረጃ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* ቦሌ አትላስ አካባቢ 3 መኝታ ቤት",
        parse_mode="Markdown"
    )
    return SELLER_DETAILS

async def seller_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle seller details input"""
    text = update.message.text
    
    if len(text) > config.MAX_DESCRIPTION_LENGTH:
        await update.message.reply_text(
            f"❌ መረጃ በጣም ረጅም ነው! እባክዎ ከ{config.MAX_DESCRIPTION_LENGTH} ፊደላት በታች ያስገቡ።"
        )
        return SELLER_DETAILS
    
    context.user_data['description'] = text
    
    await update.message.reply_text(
        "💰 **የመሸጫ/የመከራያ ዋጋ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* 2,500,000 ብር",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return SELLER_PRICE

async def seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle seller price input"""
    price = update.message.text.strip()
    
    if price == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_price(price):
        await update.message.reply_text(
            "❌ ዋጋው ትክክል አይደለም! እባክዎ ትክክለኛ ዋጋ ያስገቡ።\n"
            "💡 *ምሳሌ፦* 2,500,000",
            parse_mode="Markdown"
        )
        return SELLER_PRICE
    
    context.user_data['price'] = price
    
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

async def seller_nego(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle seller negotiable status"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    context.user_data['negotiable'] = query.data == "flow_sell_nego_yes"
    
    await query.edit_message_text(
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* 0912345678",
        parse_mode="Markdown"
    )
    return SELLER_PHONE

async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle seller phone input"""
    phone = update.message.text.strip()
    
    if phone == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(phone):
        await update.message.reply_text(
            "❌ ስልክ ቁጥሩ ትክክል አይደለም! እባክዎ ትክክለኛ የኢትዮጵያ ስልክ ቁጥር ያስገቡ።",
            parse_mode="Markdown"
        )
        return SELLER_PHONE
    
    context.user_data['phone'] = phone
    
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ያስገቡ፦**",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return SELLER_PHOTO

async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle seller photo input"""
    user = update.effective_user
    
    if not update.message.photo:
        await update.message.reply_text(
            "❌ እባክዎ ፎቶ ያስገቡ!",
            parse_mode="Markdown"
        )
        return SELLER_PHOTO
    
    photo = update.message.photo[-1]
    
    # Check file size
    file = await context.bot.get_file(photo.file_id)
    if file.file_size > config.MAX_PHOTO_SIZE:
        await update.message.reply_text(
            "❌ ፎቶው በጣም ትልቅ ነው! እባክዎ ከ20MB በታች የሆነ ፎቶ ይላኩ።"
        )
        return SELLER_PHOTO
    
    desc = (
        f"📝 {context.user_data.get('description')}\n"
        f"💰 {context.user_data.get('price')}\n"
        f"🔄 {'ድርድር አለው' if context.user_data.get('negotiable') else 'ድርድር የለውም'}\n"
        f"📞 {context.user_data.get('phone')}"
    )
    
    req_id = add_listing(
        user.id,
        user.first_name,
        context.user_data.get('req_type', 'SELL'),
        context.user_data.get('main_category', ''),
        context.user_data.get('sub_category', ''),
        context.user_data.get('action_type', ''),
        context.user_data.get('property_type', ''),
        desc
    )
    
    if req_id:
        await update.message.reply_photo(
            photo=photo.file_id,
            caption=f"✅ **ማስታወቂያ ተመዝግቧል!** (#REQ-{req_id})\n\n{desc}",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        
        # Notify admin
        if config.ADMIN_CHAT_ID:
            try:
                await context.bot.send_photo(
                    chat_id=config.ADMIN_CHAT_ID,
                    photo=photo.file_id,
                    caption=f"🔔 **አዲስ ማስታወቂያ!**\nID: #{req_id}\nUser: {user.first_name}\n\n{desc}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notification error: {e}")
    
    return ConversationHandler.END

# ==============================================================================
# 12. BROKER REGISTRATION
# ==============================================================================
async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start broker registration"""
    context.user_data.clear()
    
    await update.message.reply_text(
        "📝 **እንደ አቅራቢ/ደላላ መመዝገብ**\n\n"
        "1️⃣ ሙሉ ስምዎን ያስገቡ፦",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return BROKER_NAME

async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle broker name input"""
    name = update.message.text.strip()
    
    if name == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if len(name) < 2:
        await update.message.reply_text(
            "❌ ስም በጣም አጭር ነው! እባክዎ ሙሉ ስምዎን ያስገቡ።"
        )
        return BROKER_NAME
    
    context.user_data['broker_name'] = name
    
    await update.message.reply_text(
        "2️⃣ የስልክ ቁጥርዎን ያስገቡ፦\n\n"
        "💡 *ምሳሌ፦* 0912345678",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return BROKER_PHONE

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle broker phone input"""
    phone = update.message.text.strip()
    
    if phone == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(phone):
        await update.message.reply_text(
            "❌ ስልክ ቁጥሩ ትክክል አይደለም! እባክዎ ትክክለኛ የኢትዮጵያ ስልክ ቁጥር ያስገቡ።",
            parse_mode="Markdown"
        )
        return BROKER_PHONE
    
    context.user_data['broker_phone'] = phone
    
    keyboard = create_keyboard(LOCATIONS, "broker_loc", row_width=3)
    await update.message.reply_text(
        "3️⃣ የሚሰሩበትን አካባቢ ይምረጡ፦",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    return BROKER_LOCATION

async def broker_reg_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle broker location selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    location = query.data.replace("broker_loc_", "")
    user = update.effective_user
    
    broker_id = add_broker(
        user.id,
        context.user_data['broker_name'],
        context.user_data['broker_phone'],
        location
    )
    
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
        
        logger.info(f"New broker registered: {user.id} ({context.user_data['broker_name']})")
    else:
        await query.edit_message_text(
            "❌ መመዝገብ አልተሳካም። እባክዎ እንደገና ይሞክሩ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 13. VIEW REQUESTS WITH PAGINATION
# ==============================================================================
async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View pending requests"""
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

async def show_requests_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show paginated requests"""
    page = context.user_data.get('view_page', 0)
    offset = page * config.ITEMS_PER_PAGE
    
    listings = get_listings(limit=config.ITEMS_PER_PAGE, offset=offset)
    total = count_listings()
    total_pages = max(1, (total + config.ITEMS_PER_PAGE - 1) // config.ITEMS_PER_PAGE)
    
    if not listings:
        await update.message.reply_text(
            "📭 ምንም ንቁ ጥያቄዎች የሉም።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    text = f"📋 **የፈላጊዎች ዝርዝር** (ገጽ {page+1}/{total_pages})\n\n"
    
    for listing in listings:
        text += format_listing(listing)
        text += "────────────────────\n"
    
    # Response buttons
    keyboard = []
    for listing in listings:
        keyboard.append([
            InlineKeyboardButton(
                f"✅ አለኝ - #{listing['id']}",
                callback_data=f"item_resp_{listing['id']}_{listing['user_chat_id']}_{listing['main_category']}"
            )
        ])
    
    # Pagination
    pagination_keyboard = create_pagination_keyboard(page, total_pages)
    keyboard.extend(pagination_keyboard.keyboard)
    
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
# 14. RESPONSE FLOW
# ==============================================================================
async def start_item_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start response flow"""
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split("_")
    context.user_data['target_req_id'] = int(parts[2])
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

async def resp_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle response role selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
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
        keyboard = create_keyboard(PROPERTY_TYPES, "resp_prop")
        await query.edit_message_text(
            "🏠 **ቤት መልስ**\n\n"
            "1️⃣ የቤት/ቦታ አይነት ይምረጡ፦",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return RESP_PROPERTY

async def resp_property_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle response property type selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    prop = query.data.replace("resp_prop_", "")
    context.user_data['resp_property'] = prop
    
    keyboard = create_keyboard(HOUSE_TYPES, "resp_htype")
    await query.edit_message_text(
        "🏠 **የቤት አይነት ይምረጡ፦**",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    return RESP_SUB

async def resp_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle response house type selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    htype = query.data.replace("resp_htype_", "")
    context.user_data['resp_htype'] = htype
    
    await query.edit_message_text(
        "📍 **አካባቢ ያስገቡ፦**\n"
        "💡 *ምሳሌ፦* ቦሌ አትላስ",
        parse_mode="Markdown"
    )
    return RESP_DETAILS

async def resp_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle response details input"""
    text = update.message.text.strip()
    
    if text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if len(text) > config.MAX_DESCRIPTION_LENGTH:
        await update.message.reply_text(
            f"❌ መረጃ በጣም ረጅም ነው! እባክዎ ከ{config.MAX_DESCRIPTION_LENGTH} ፊደላት በታች ያስገቡ።"
        )
        return RESP_DETAILS
    
    context.user_data['resp_details'] = text
    
    await update.message.reply_text(
        "💰 **ዋጋ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* 2,500,000",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return RESP_PRICE

async def resp_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle response price input"""
    price = update.message.text.strip()
    
    if price == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_price(price):
        await update.message.reply_text(
            "❌ ዋጋው ትክክል አይደለም! እባክዎ ትክክለኛ ዋጋ ያስገቡ።",
            parse_mode="Markdown"
        )
        return RESP_PRICE
    
    context.user_data['resp_price'] = price
    
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

async def resp_nego(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle response negotiable status"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "flow_home":
        return await go_home(update, context)
    
    context.user_data['resp_nego'] = query.data == "resp_nego_yes"
    
    await query.edit_message_text(
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* 0912345678",
        parse_mode="Markdown"
    )
    return RESP_PHONE

async def resp_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle response phone input"""
    phone = update.message.text.strip()
    
    if phone == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(phone):
        await update.message.reply_text(
            "❌ ስልክ ቁጥሩ ትክክል አይደለም! እባክዎ ትክክለኛ የኢትዮጵያ ስልክ ቁጥር ያስገቡ።",
            parse_mode="Markdown"
        )
        return RESP_PHONE
    
    context.user_data['resp_phone'] = phone
    
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ያስገቡ፦**",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return RESP_PHOTO

async def resp_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle response photo input"""
    responder = update.effective_user
    
    if not update.message.photo:
        await update.message.reply_text(
            "❌ እባክዎ ፎቶ ያስገቡ!",
            parse_mode="Markdown"
        )
        return RESP_PHOTO
    
    photo = update.message.photo[-1]
    
    # Check file size
    file = await context.bot.get_file(photo.file_id)
    if file.file_size > config.MAX_PHOTO_SIZE:
        await update.message.reply_text(
            "❌ ፎቶው በጣም ትልቅ ነው! እባክዎ ከ20MB በታች የሆነ ፎቶ ይላኩ።"
        )
        return RESP_PHOTO
    
    target_user_id = context.user_data.get('target_user_id')
    req_id = context.user_data.get('target_req_id')
    role = context.user_data.get('resp_role', 'አቅራቢ')
    target_cat = context.user_data.get('target_cat', 'car')
    
    if target_cat == "car":
        detail_str = f"🚘 {context.user_data.get('resp_details')}"
    else:
        detail_str = (
            f"🏠 {context.user_data.get('resp_property')} - {context.user_data.get('resp_htype')}\n"
            f"📍 {context.user_data.get('resp_details')}"
        )
    
    desc = (
        f"🎉 **አዲስ አማራጭ!** (#REQ-{req_id})\n\n"
        f"🎭 ሚና: {role}\n"
        f"{detail_str}\n"
        f"💰 {context.user_data.get('resp_price')}\n"
        f"🔄 {'ድርድር አለው' if context.user_data.get('resp_nego') else 'ድርድር የለውም'}\n"
        f"📞 {context.user_data.get('resp_phone')}\n"
        f"👤 @{responder.username if responder.username else responder.first_name}"
    )
    
    try:
        await context.bot.send_photo(
            chat_id=target_user_id,
            photo=photo.file_id,
            caption=desc,
            parse_mode="Markdown"
        )
        
        # Save response to database
        add_response(
            listing_id=int(req_id),
            responder_chat_id=responder.id,
            responder_name=responder.first_name,
            responder_role=role,
            description=context.user_data.get('resp_details', ''),
            price=context.user_data.get('resp_price', ''),
            negotiable=context.user_data.get('resp_nego', True),
            phone=context.user_data.get('resp_phone', ''),
            photo_id=photo.file_id
        )
        
        update_listing_status(int(req_id), 'responded')
        
        await update.message.reply_text(
            "✅ **መረጃዎች ለፈላጊው ተልከዋል!**\n\n"
            "📌 ጥያቄው ከ'📋 የፈላጊዎች ዝርዝር' ተወግዷል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
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
# 15. HELP COMMAND
# ==============================================================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send help message"""
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

📞 **ለእርዳታ:**
• ለችግር ከተጋፈጡ '📞 ድጋፍ' ይምረጡ
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ==============================================================================
# 16. ERROR HANDLER
# ==============================================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors"""
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
# 17. MAIN FUNCTION
# ==============================================================================
def main():
    """Main entry point"""
    try:
        # Initialize database
        init_db()
        
        # Start Flask server
        threading.Thread(target=run_flask, daemon=True).start()
        logger.info(f"✅ Flask server started on port {config.PORT}")
        
        # Create application
        app = Application.builder().token(config.BOT_TOKEN).build()
        
        # Add command handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_command))
        
        # Add conversation handlers
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
            states={
                BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_")],
                BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_")],
                BUYER_CATEGORY: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_")],
                BUYER_SUB: [CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_"),
                           CallbackQueryHandler(buyer_htype_chosen, pattern="^flow_buy_htype_")],
                BUYER_PROPERTY: [CallbackQueryHandler(buyer_property_chosen, pattern="^flow_buy_prop_")],
                BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details)],
                BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone)],
            },
            fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), go_home)],
            allow_reentry=True,
        ))
        
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
            states={
                SELLER_MAIN: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_")],
                SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_")],
                SELLER_CATEGORY: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_")],
                SELLER_SUB: [CallbackQueryHandler(seller_sub_chosen, pattern="^flow_sell_sub_"),
                            CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_")],
                SELLER_PROPERTY: [CallbackQueryHandler(seller_property_chosen, pattern="^flow_sell_prop_")],
                SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details)],
                SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price)],
                SELLER_NEGO: [CallbackQueryHandler(seller_nego, pattern="^flow_sell_nego_")],
                SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone)],
                SELLER_PHOTO: [MessageHandler(filters.PHOTO, seller_photo)],
            },
            fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), go_home)],
            allow_reentry=True,
        ))
        
        app.add_handler(ConversationHandler(
            entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ መመዝገብ$"), broker_reg_start)],
            states={
                BROKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name)],
                BROKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone)],
                BROKER_LOCATION: [CallbackQueryHandler(broker_reg_location, pattern="^broker_loc_")],
            },
            fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), go_home)],
            allow_reentry=True,
        ))
        
        app.add_handler(ConversationHandler(
            entry_points=[CallbackQueryHandler(start_item_response, pattern="^item_resp_")],
            states={
                RESP_MAIN: [CallbackQueryHandler(resp_role_chosen, pattern="^resp_role_")],
                RESP_PROPERTY: [CallbackQueryHandler(resp_property_chosen, pattern="^resp_prop_")],
                RESP_SUB: [CallbackQueryHandler(resp_htype_chosen, pattern="^resp_htype_")],
                RESP_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_details)],
                RESP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_price)],
                RESP_NEGO: [CallbackQueryHandler(resp_nego, pattern="^resp_nego_")],
                RESP_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_phone)],
                RESP_PHOTO: [MessageHandler(filters.PHOTO, resp_photo)],
            },
            fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), go_home)],
            allow_reentry=True,
        ))
        
        # Add other handlers
        app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
        app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
        app.add_handler(MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), go_home))
        
        app.add_handler(CallbackQueryHandler(show_requests_page, pattern="^page_"))
        app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
        
        # Add error handler
        app.add_error_handler(error_handler)
        
        # Start bot
        logger.info("🚀 Adika Marketplace Bot started successfully!")
        app.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()