import logging
import os
import threading
import time
import re
from functools import wraps
from typing import Optional, List, Dict, Any
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
            conn.autocommit = False
        else:
            import sqlite3
            conn = sqlite3.connect("adika_marketplace.db")
            conn.row_factory = sqlite3.Row
        
        yield conn
        
        if config.DATABASE_URL:
            conn.commit()
            
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except:
                pass
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
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Drop existing tables if they exist (for clean setup)
            if config.DATABASE_URL:
                cursor.execute("""
                    DROP TABLE IF EXISTS responses CASCADE;
                    DROP TABLE IF EXISTS listings CASCADE;
                    DROP TABLE IF EXISTS brokers CASCADE;
                    DROP TABLE IF EXISTS users CASCADE;
                """)
            else:
                cursor.execute("""
                    DROP TABLE IF EXISTS responses;
                    DROP TABLE IF EXISTS listings;
                    DROP TABLE IF EXISTS brokers;
                    DROP TABLE IF EXISTS users;
                """)
            
            # Listings table
            if config.DATABASE_URL:
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("CREATE INDEX idx_listings_status ON listings(status)")
                cursor.execute("CREATE INDEX idx_listings_category ON listings(main_category, sub_category)")
                cursor.execute("CREATE INDEX idx_listings_created ON listings(created_at DESC)")
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("CREATE INDEX idx_listings_status ON listings(status)")
                cursor.execute("CREATE INDEX idx_listings_category ON listings(main_category, sub_category)")
            
            # Brokers table
            if config.DATABASE_URL:
                cursor.execute("""
                    CREATE TABLE brokers (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT NOT NULL UNIQUE,
                        full_name TEXT NOT NULL,
                        phone TEXT NOT NULL,
                        location TEXT NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("CREATE INDEX idx_brokers_chat_id ON brokers(chat_id)")
                cursor.execute("CREATE INDEX idx_brokers_location ON brokers(location)")
            else:
                cursor.execute("""
                    CREATE TABLE brokers (
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
                cursor.execute("CREATE INDEX idx_brokers_chat_id ON brokers(chat_id)")
            
            # Responses table
            if config.DATABASE_URL:
                cursor.execute("""
                    CREATE TABLE responses (
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
                        CONSTRAINT fk_responses_listing FOREIGN KEY (listing_id) 
                            REFERENCES listings(id) ON DELETE CASCADE
                    )
                """)
                cursor.execute("CREATE INDEX idx_responses_listing_id ON responses(listing_id)")
                cursor.execute("CREATE INDEX idx_responses_responder ON responses(responder_chat_id)")
                cursor.execute("CREATE INDEX idx_responses_status ON responses(status)")
            else:
                cursor.execute("""
                    CREATE TABLE responses (
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
                        FOREIGN KEY (listing_id) REFERENCES listings(id) ON DELETE CASCADE
                    )
                """)
                cursor.execute("CREATE INDEX idx_responses_listing_id ON responses(listing_id)")
                cursor.execute("CREATE INDEX idx_responses_responder ON responses(responder_chat_id)")
            
            # Users table
            if config.DATABASE_URL:
                cursor.execute("""
                    CREATE TABLE users (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT NOT NULL UNIQUE,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        is_broker BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("CREATE INDEX idx_users_chat_id ON users(chat_id)")
            else:
                cursor.execute("""
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL UNIQUE,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        is_broker BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("CREATE INDEX idx_users_chat_id ON users(chat_id)")
            
            if config.DATABASE_URL:
                conn.commit()
            
            logger.info("✅ Database initialized successfully")
            
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise

def check_db_tables():
    """Check if tables exist and have correct columns"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            if config.DATABASE_URL:
                cursor.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public'
                """)
                tables = [row[0] for row in cursor.fetchall()]
                logger.info(f"Existing tables: {tables}")
                
                # Check listings table columns
                if 'listings' in tables:
                    cursor.execute("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name = 'listings'
                    """)
                    columns = [row[0] for row in cursor.fetchall()]
                    logger.info(f"Listings columns: {columns}")
                    
                    required_columns = ['id', 'user_chat_id', 'user_name', 'req_type', 
                                      'main_category', 'sub_category', 'action_type', 
                                      'property_type', 'description', 'status', 'created_at']
                    
                    for col in required_columns:
                        if col not in columns:
                            logger.error(f"Missing column: {col}")
                            return False
                    
                    return True
            else:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                logger.info(f"Existing tables: {tables}")
                
                if 'listings' in tables:
                    cursor.execute("PRAGMA table_info(listings)")
                    columns = [row[1] for row in cursor.fetchall()]
                    logger.info(f"Listings columns: {columns}")
                    
                    required_columns = ['id', 'user_chat_id', 'user_name', 'req_type', 
                                      'main_category', 'sub_category', 'action_type', 
                                      'property_type', 'description', 'status', 'created_at']
                    
                    for col in required_columns:
                        if col not in columns:
                            logger.error(f"Missing column: {col}")
                            return False
                    
                    return True
            
            return False
    except Exception as e:
        logger.error(f"Error checking database: {e}")
        return False

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
            for key, value in filters.items():
                if value:
                    query += f" AND {key} = {'%s' if config.DATABASE_URL else '?'}"
                    params.append(value)
        
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
    phone = phone.replace(' ', '').replace('-', '')
    pattern = r'^(09|07|01)\d{8}$|^\+251(09|07|01)\d{8}$'
    return bool(re.match(pattern, phone))

def validate_price(price: str) -> bool:
    """Validate price format"""
    price = price.replace(',', '')
    pattern = r'^[\d]+(\.[\d]{2})?$'
    return bool(re.match(pattern, price))

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

# ... (continue with all the same handler functions as before)

# ==============================================================================
# 11. MAIN FUNCTION
# ==============================================================================
def main():
    """Main entry point"""
    try:
        # Check if database needs initialization
        logger.info("Checking database...")
        
        # Try to initialize database
        try:
            init_db()
            logger.info("✅ Database initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            logger.info("Attempting to check existing tables...")
            
            # Check if tables exist
            if check_db_tables():
                logger.info("✅ Tables exist, continuing...")
            else:
                logger.error("❌ Tables are corrupted. Please restart with fresh database.")
                raise
        
        # Start Flask server
        threading.Thread(target=run_flask, daemon=True).start()
        logger.info(f"✅ Flask server started on port {config.PORT}")
        
        # Create application
        app = Application.builder().token(config.BOT_TOKEN).build()
        
        # Add command handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", help_command))
        
        # Add conversation handlers (same as before)
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