import asyncio
import logging
import os
import threading
import re
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from functools import lru_cache
from contextlib import contextmanager
from collections import defaultdict
import time
import json

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
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
class Config:
    """Centralized configuration management"""
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "0")
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    PORT = int(os.environ.get("PORT", 8080))
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "production")
    MAX_REQUESTS_PER_MINUTE = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", 20))
    CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", 60))
    ITEMS_PER_PAGE = int(os.environ.get("ITEMS_PER_PAGE", 5))
    
    @classmethod
    def validate(cls):
        if not cls.BOT_TOKEN:
            raise RuntimeError("❌ BOT_TOKEN environment variable is required")
        try:
            cls.ADMIN_CHAT_ID_INT = int(cls.ADMIN_CHAT_ID)
        except ValueError:
            cls.ADMIN_CHAT_ID_INT = 0

Config.validate()

# ==============================================================================
# 1. LOGGING SETUP
# ==============================================================================
import structlog
from structlog.processors import JSONRenderer, TimeStamper

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        JSONRenderer() if Config.ENVIRONMENT == "production" else structlog.dev.ConsoleRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# ==============================================================================
# 2. DATABASE CONNECTION POOL
# ==============================================================================
connection_pool = None

def init_connection_pool():
    """Initialize database connection pool"""
    global connection_pool
    if Config.DATABASE_URL:
        try:
            db_url = Config.DATABASE_URL.replace("postgres://", "postgresql://", 1)
            connection_pool = psycopg2.pool.SimpleConnectionPool(
                1, 20,
                dsn=db_url,
                cursor_factory=RealDictCursor
            )
            logger.info("Database connection pool initialized", pool_size=20)
        except Exception as e:
            logger.error("Failed to initialize connection pool", error=str(e), exc_info=True)
            raise
    else:
        logger.info("Using SQLite (no connection pool)")

@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    conn = None
    try:
        if connection_pool:
            conn = connection_pool.getconn()
        else:
            import sqlite3
            conn = sqlite3.connect("adika_marketplace.db")
            conn.row_factory = sqlite3.Row
        yield conn
    except Exception as e:
        logger.error("Database connection error", error=str(e), exc_info=True)
        if conn and connection_pool:
            connection_pool.putconn(conn)
        elif conn:
            conn.close()
        raise
    finally:
        if conn and connection_pool:
            connection_pool.putconn(conn)
        elif conn:
            conn.close()

@contextmanager
def transaction(conn):
    """Transaction management context manager"""
    try:
        yield
        if not Config.DATABASE_URL:  # SQLite
            conn.commit()
    except Exception as e:
        if not Config.DATABASE_URL:  # SQLite
            conn.rollback()
        logger.error("Transaction failed", error=str(e), exc_info=True)
        raise

# ==============================================================================
# 3. CACHE MANAGEMENT
# ==============================================================================
class Cache:
    """Simple TTL-based cache"""
    def __init__(self, ttl_seconds: int = Config.CACHE_TTL_SECONDS):
        self.cache = {}
        self.ttl = ttl_seconds
        self._lock = threading.Lock()
    
    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self.cache:
                value, timestamp = self.cache[key]
                if datetime.now() - timestamp < timedelta(seconds=self.ttl):
                    return value
                del self.cache[key]
            return None
    
    def set(self, key: str, value: Any):
        with self._lock:
            self.cache[key] = (value, datetime.now())
    
    def invalidate(self, key: str = None):
        with self._lock:
            if key:
                self.cache.pop(key, None)
            else:
                self.cache.clear()

cache = Cache()

# ==============================================================================
# 4. RATE LIMITER
# ==============================================================================
class RateLimiter:
    """Rate limiter for user requests"""
    def __init__(self, max_requests: int = Config.MAX_REQUESTS_PER_MINUTE, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
        self._lock = threading.Lock()
    
    def is_allowed(self, user_id: int) -> bool:
        with self._lock:
            now = time.time()
            user_requests = [t for t in self.requests[user_id] if now - t < self.time_window]
            
            if len(user_requests) >= self.max_requests:
                return False
            
            user_requests.append(now)
            self.requests[user_id] = user_requests
            return True

rate_limiter = RateLimiter()

# ==============================================================================
# 5. INPUT VALIDATION
# ==============================================================================
from pydantic import BaseModel, validator, ValidationError

def validate_phone(phone: str) -> bool:
    """Validate phone numbers (local and international formats)"""
    phone = phone.replace(' ', '').replace('-', '')
    pattern = r'^(09|07|01)\d{8}$|^\+251(9|7|1)\d{8}$'
    return bool(re.match(pattern, phone))

def validate_price(price: str) -> bool:
    """Validate price is numeric"""
    price = price.replace(',', '').replace(' ', '')
    return price.isdigit()

def sanitize_input(text: str) -> str:
    """Sanitize user input to prevent injection"""
    if not text:
        return ""
    # Remove potentially dangerous characters
    return re.sub(r'[<>"\'%;]', '', text.strip())

class ListingRequest(BaseModel):
    """Pydantic model for listing validation"""
    user_chat_id: int
    user_name: str
    req_type: str
    main_category: str
    sub_type: str
    action_type: str
    description: str
    price: Optional[str] = None
    phone: str
    photo_file_id: Optional[str] = None
    
    @validator('phone')
    def validate_phone_field(cls, v):
        if not validate_phone(v):
            raise ValueError('Invalid phone number format')
        return v
    
    @validator('price')
    def validate_price_field(cls, v):
        if v and not validate_price(v):
            raise ValueError('Invalid price format')
        return v
    
    @validator('description')
    def validate_description(cls, v):
        if len(v.strip()) < 5:
            raise ValueError('Description must be at least 5 characters')
        return sanitize_input(v)

class BrokerRegistration(BaseModel):
    """Pydantic model for broker registration"""
    chat_id: int
    full_name: str
    phone: str
    role_type: str
    sub_city: str
    national_id_photo: str
    
    @validator('phone')
    def validate_phone_field(cls, v):
        if not validate_phone(v):
            raise ValueError('Invalid phone number format')
        return v
    
    @validator('full_name')
    def validate_name(cls, v):
        if len(v.strip()) < 2:
            raise ValueError('Name must be at least 2 characters')
        return sanitize_input(v)

# ==============================================================================
# 6. CONSTANTS & KEYBOARDS
# ==============================================================================
SUB_CITIES = [
    "ቦሌ", "የካ", "አራዳ", "ልደታ",
    "ቂርቆስ", "አዲስ ከተማ", "ንፋስ ስልክ ላፍቶ",
    "ኮልፌ ቀራኒዮ", "አቃቂ ቃሊቲ", "ጉሌሌ", "ለሚ ኩራ",
]

CAR_SUB_CATEGORIES = ["🚗 የቤት መኪና", "🚚 የሥራ መኪና", "🚜 ከባድ ተሽከርካሪ/ማሽን"]
HOUSE_TYPES = ["🏡 ቪላ", "🏢 አፓርታማ", "🏢 ኮንዶሚኒየም", "🏢 ሪል እስቴት", "🏞️ መሬት/ቦታ"]
COMMERCIAL_TYPES = ["🏢 ቢሮ", "🏪 ሱቅ", "🏭 መጋዘን/ፋብሪካ", "🅿️ ሌላ የስራ ቦታ"]

MAIN_CATEGORIES = [("car", "🚗 መኪና"), ("house", "🏠 ቤት / ቦታ"), ("commercial", "🏢 የሥራ ቦታ / ንግድ")]

MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ/ደላላ መመዝገብ", "📋 የፈላጊዎች ዝርዝር"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"],
]
HOME_ONLY_KEYBOARD = ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
MAIN_MARKUP = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)

# ==============================================================================
# 7. DATABASE OPERATIONS (Repository Pattern)
# ==============================================================================
class ListingRepository:
    """Database operations for listings"""
    
    @staticmethod
    def create(listing_data: Dict) -> Optional[int]:
        """Create a new listing"""
        try:
            validated = ListingRequest(**listing_data)
        except ValidationError as e:
            logger.error("Validation error", errors=e.errors())
            return None
        
        with get_db_connection() as conn:
            with transaction(conn):
                cursor = conn.cursor()
                if Config.DATABASE_URL:
                    query = """
                        INSERT INTO listings 
                        (user_chat_id, user_name, req_type, main_category, sub_type,
                         action_type, description, price, phone, photo_file_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """
                    cursor.execute(query, (
                        validated.user_chat_id, validated.user_name,
                        validated.req_type, validated.main_category,
                        validated.sub_type, validated.action_type,
                        validated.description, validated.price,
                        validated.phone, validated.photo_file_id
                    ))
                    return cursor.fetchone()[0]
                else:
                    query = """
                        INSERT INTO listings 
                        (user_chat_id, user_name, req_type, main_category, sub_type,
                         action_type, description, price, phone, photo_file_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    cursor.execute(query, (
                        validated.user_chat_id, validated.user_name,
                        validated.req_type, validated.main_category,
                        validated.sub_type, validated.action_type,
                        validated.description, validated.price,
                        validated.phone, validated.photo_file_id
                    ))
                    return cursor.lastrowid
        except Exception as e:
            logger.error("Failed to create listing", error=str(e), exc_info=True)
            return None
    
    @staticmethod
    def get_pending(limit: int = 10, offset: int = 0) -> List[Dict]:
        """Get pending listings with pagination"""
        cache_key = f"listings_pending_{limit}_{offset}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if Config.DATABASE_URL:
                query = """
                    SELECT * FROM listings 
                    WHERE status = 'pending' 
                    ORDER BY created_at DESC 
                    LIMIT %s OFFSET %s
                """
                cursor.execute(query, (limit, offset))
            else:
                query = """
                    SELECT * FROM listings 
                    WHERE status = 'pending' 
                    ORDER BY created_at DESC 
                    LIMIT ? OFFSET ?
                """
                cursor.execute(query, (limit, offset))
            
            rows = cursor.fetchall()
            result = [dict(row) for row in rows]
            cache.set(cache_key, result)
            return result
    
    @staticmethod
    def count_pending() -> int:
        """Count pending listings"""
        cache_key = "listings_count_pending"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM listings WHERE status = 'pending'")
            count = cursor.fetchone()[0]
            cache.set(cache_key, count)
            return count
    
    @staticmethod
    def update_status(listing_id: int, status: str) -> bool:
        """Update listing status"""
        try:
            with get_db_connection() as conn:
                with transaction(conn):
                    cursor = conn.cursor()
                    if Config.DATABASE_URL:
                        cursor.execute(
                            "UPDATE listings SET status = %s WHERE id = %s",
                            (status, listing_id)
                        )
                    else:
                        cursor.execute(
                            "UPDATE listings SET status = ? WHERE id = ?",
                            (status, listing_id)
                        )
                    # Invalidate cache
                    cache.invalidate()
                    return True
        except Exception as e:
            logger.error("Failed to update listing status", error=str(e), exc_info=True)
            return False

class BrokerRepository:
    """Database operations for brokers"""
    
    @staticmethod
    def create_or_update(broker_data: Dict) -> Optional[int]:
        """Create or update broker registration"""
        try:
            validated = BrokerRegistration(**broker_data)
        except ValidationError as e:
            logger.error("Validation error", errors=e.errors())
            return None
        
        with get_db_connection() as conn:
            with transaction(conn):
                cursor = conn.cursor()
                
                # Check if broker exists
                if Config.DATABASE_URL:
                    cursor.execute("SELECT id FROM brokers WHERE chat_id = %s", (validated.chat_id,))
                else:
                    cursor.execute("SELECT id FROM brokers WHERE chat_id = ?", (validated.chat_id,))
                
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing
                    if Config.DATABASE_URL:
                        query = """
                            UPDATE brokers 
                            SET full_name = %s, phone = %s, role_type = %s,
                                national_id_photo = %s, sub_city = %s, status = 'pending'
                            WHERE chat_id = %s
                            RETURNING id
                        """
                        cursor.execute(query, (
                            validated.full_name, validated.phone,
                            validated.role_type, validated.national_id_photo,
                            validated.sub_city, validated.chat_id
                        ))
                        broker_id = cursor.fetchone()[0]
                    else:
                        query = """
                            UPDATE brokers 
                            SET full_name = ?, phone = ?, role_type = ?,
                                national_id_photo = ?, sub_city = ?, status = 'pending'
                            WHERE chat_id = ?
                        """
                        cursor.execute(query, (
                            validated.full_name, validated.phone,
                            validated.role_type, validated.national_id_photo,
                            validated.sub_city, validated.chat_id
                        ))
                        broker_id = existing[0]
                else:
                    # Insert new
                    if Config.DATABASE_URL:
                        query = """
                            INSERT INTO brokers 
                            (chat_id, full_name, phone, role_type, national_id_photo, sub_city, status)
                            VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                            RETURNING id
                        """
                        cursor.execute(query, (
                            validated.chat_id, validated.full_name,
                            validated.phone, validated.role_type,
                            validated.national_id_photo, validated.sub_city
                        ))
                        broker_id = cursor.fetchone()[0]
                    else:
                        query = """
                            INSERT INTO brokers 
                            (chat_id, full_name, phone, role_type, national_id_photo, sub_city, status)
                            VALUES (?, ?, ?, ?, ?, ?, 'pending')
                        """
                        cursor.execute(query, (
                            validated.chat_id, validated.full_name,
                            validated.phone, validated.role_type,
                            validated.national_id_photo, validated.sub_city
                        ))
                        broker_id = cursor.lastrowid
                
                # Invalidate cache
                cache.invalidate()
                return broker_id
        except Exception as e:
            logger.error("Failed to create/update broker", error=str(e), exc_info=True)
            return None
    
    @staticmethod
    def get_approved() -> List[int]:
        """Get list of approved broker chat IDs"""
        cache_key = "brokers_approved"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT chat_id FROM brokers WHERE status = 'approved'")
            rows = cursor.fetchall()
            result = [dict(row)['chat_id'] for row in rows]
            cache.set(cache_key, result)
            return result
    
    @staticmethod
    def get_by_chat_id(chat_id: int) -> Optional[Dict]:
        """Get broker by chat ID"""
        cache_key = f"broker_{chat_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            if Config.DATABASE_URL:
                cursor.execute("SELECT * FROM brokers WHERE chat_id = %s", (chat_id,))
            else:
                cursor.execute("SELECT * FROM brokers WHERE chat_id = ?", (chat_id,))
            
            row = cursor.fetchone()
            result = dict(row) if row else None
            if result:
                cache.set(cache_key, result)
            return result
    
    @staticmethod
    def update_status(chat_id: int, status: str) -> bool:
        """Update broker status"""
        try:
            with get_db_connection() as conn:
                with transaction(conn):
                    cursor = conn.cursor()
                    if Config.DATABASE_URL:
                        cursor.execute(
                            "UPDATE brokers SET status = %s WHERE chat_id = %s",
                            (status, chat_id)
                        )
                    else:
                        cursor.execute(
                            "UPDATE brokers SET status = ? WHERE chat_id = ?",
                            (status, chat_id)
                        )
                    # Invalidate cache
                    cache.invalidate()
                    return True
        except Exception as e:
            logger.error("Failed to update broker status", error=str(e), exc_info=True)
            return False

# ==============================================================================
# 8. FLASK WEB SERVER
# ==============================================================================
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'service': 'Adika Marketplace Bot',
        'timestamp': datetime.now().isoformat()
    }), 200

@web_app.route('/health')
def health():
    """Health check endpoint"""
    status = {
        'status': 'healthy',
        'database': False,
        'bot': True,
        'timestamp': datetime.now().isoformat()
    }
    
    # Check database
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
        status['database'] = True
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        status['status'] = 'unhealthy'
        status['error'] = str(e)
    
    response_code = 200 if status['status'] == 'healthy' else 503
    return jsonify(status), response_code

@web_app.route('/metrics')
def metrics():
    """Simple metrics endpoint"""
    return jsonify({
        'pending_listings': ListingRepository.count_pending(),
        'approved_brokers': len(BrokerRepository.get_approved()),
        'cache_size': len(cache.cache) if hasattr(cache, 'cache') else 0,
    }), 200

def run_flask():
    web_app.run(host="0.0.0.0", port=Config.PORT)

# ==============================================================================
# 9. DATABASE INITIALIZATION
# ==============================================================================
def init_db():
    """Initialize database tables if they don't exist"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            if Config.DATABASE_URL:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS listings (
                        id SERIAL PRIMARY KEY,
                        user_chat_id BIGINT NOT NULL,
                        user_name TEXT,
                        req_type TEXT NOT NULL,
                        main_category TEXT NOT NULL,
                        sub_type TEXT,
                        action_type TEXT,
                        description TEXT NOT NULL,
                        price TEXT,
                        phone TEXT,
                        photo_file_id TEXT,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
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
                    )
                """)
                # Add indexes for performance
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at DESC)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_brokers_status ON brokers(status)")
            else:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS listings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_chat_id INTEGER NOT NULL,
                        user_name TEXT,
                        req_type TEXT NOT NULL,
                        main_category TEXT NOT NULL,
                        sub_type TEXT,
                        action_type TEXT,
                        description TEXT NOT NULL,
                        price TEXT,
                        phone TEXT,
                        photo_file_id TEXT,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
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
                    )
                """)
                # SQLite indexes
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at DESC)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_brokers_status ON brokers(status)")
            
            if not Config.DATABASE_URL:
                conn.commit()
            
            logger.info("Database initialized successfully")
    except Exception as e:
        logger.error("Database initialization failed", error=str(e), exc_info=True)
        raise

# ==============================================================================
# 10. HELPER FUNCTIONS
# ==============================================================================
def build_indexed_keyboard(options: List[str], prefix: str, columns: int = 1, extra_home: bool = True):
    """Build inline keyboard with indexed callback data"""
    buttons = [InlineKeyboardButton(opt, callback_data=f"{prefix}{i}") for i, opt in enumerate(options)]
    keyboard = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    if extra_home:
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    return InlineKeyboardMarkup(keyboard)

async def notify_brokers(context: ContextTypes.DEFAULT_TYPE, message_text: str, req_id: int, buyer_id: int):
    """Broadcast to approved brokers with rate limiting"""
    approved_brokers = BrokerRepository.get_approved()
    if not approved_brokers:
        logger.info("No approved brokers to notify")
        return
    
    logger.info("Notifying brokers", count=len(approved_brokers), request_id=req_id)
    
    for b_id in approved_brokers:
        try:
            kbd = [[InlineKeyboardButton(f"👉 አለኝ - #{req_id}", callback_data=f"have_item_{req_id}_{buyer_id}")]]
            await context.bot.send_message(
                chat_id=b_id,
                text=message_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kbd),
            )
            # Small delay to avoid hitting rate limits
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error("Failed to send notification to broker", broker_id=b_id, error=str(e))

async def safe_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    """Safely send message with retry logic"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if update.callback_query:
                await update.callback_query.message.reply_text(text, **kwargs)
            else:
                await update.message.reply_text(text, **kwargs)
            return True
        except Exception as e:
            logger.warning("Failed to send message", attempt=attempt + 1, error=str(e))
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
            else:
                logger.error("Failed to send message after retries", error=str(e), exc_info=True)
                return False
    return False

# ==============================================================================
# 11. CONVERSATION STATES
# ==============================================================================
(
    BUYER_MAIN, BUYER_ACTION, BUYER_SUBTYPE, BUYER_DETAILS, BUYER_PHONE,
    SELLER_MAIN, SELLER_ACTION, SELLER_SUBTYPE, SELLER_DETAILS, SELLER_PRICE, SELLER_PHONE, SELLER_PHOTO,
    BROKER_ROLE, BROKER_NAME, BROKER_PHONE, BROKER_SUBCITY, BROKER_NID_PHOTO,
    BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO,
) = range(19)

# ==============================================================================
# 12. HANDLERS - START & HOME
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    user_id = update.effective_user.id
    
    # Rate limiting check
    if not rate_limiter.is_allowed(user_id):
        await update.message.reply_text("⏳ እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።")
        return ConversationHandler.END
    
    context.user_data.clear()
    welcome_text = (
        "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
        "የሀገሪቱ ታላቁ የመኪና፣ የቤት እና የንብረት ገበያ ማዕከል።\n\n"
        "እባክዎን ከታች ካሉት አማራጮች አንዱን ይምረጡ፦"
    )
    await safe_send_message(update, context, welcome_text, parse_mode="Markdown", reply_markup=MAIN_MARKUP)
    return ConversationHandler.END

async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to home menu"""
    context.user_data.clear()
    welcome_text = "👋 **ወደ ዋና ገጽ ተመልሰዋል!**\n\nእባክዎን አማራጭ ይምረጡ፦"
    
    if update.message:
        await safe_send_message(update, context, welcome_text, parse_mode="Markdown", reply_markup=MAIN_MARKUP)
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.delete_message()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=welcome_text,
            parse_mode="Markdown",
            reply_markup=MAIN_MARKUP,
        )
    return ConversationHandler.END

# ==============================================================================
# 13. HANDLERS - BUYER FLOW
# ==============================================================================
async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start buyer flow"""
    if not rate_limiter.is_allowed(update.effective_user.id):
        await safe_send_message(update, context, "⏳ እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።")
        return ConversationHandler.END
    
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    
    keyboard = [[InlineKeyboardButton(label, callback_data=f"flow_buy_cat_{code}")] for code, label in MAIN_CATEGORIES]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await safe_send_message(
        update, context,
        "🔍 **የሚፈልጉትን ምድብ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return BUYER_MAIN

async def buyer_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buyer category selection"""
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    cat = query.data.replace("flow_buy_cat_", "")
    context.user_data['main_category'] = cat
    
    action_label = "🛍️ መግዛት" if cat != "commercial" else "🛍️ ማግኘት"
    keyboard = [
        [InlineKeyboardButton(action_label, callback_data="flow_buy_action_buy")],
        [InlineKeyboardButton("🔑 መከራየት", callback_data="flow_buy_action_rent")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await query.edit_message_text(
        "❓ **የሚፈልጉትን የድርጊት አይነት ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return BUYER_ACTION

async def buyer_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buyer action selection"""
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    action = query.data.replace("flow_buy_action_", "")
    context.user_data['action_type'] = "መግዛት" if action == "buy" else "መከራየት"
    
    cat = context.user_data.get('main_category')
    if cat == "car":
        await query.edit_message_text(
            "🚗 **የመኪና ንኡስ ምድብ ይምረጡ፦**",
            reply_markup=build_indexed_keyboard(CAR_SUB_CATEGORIES, "flow_buy_carsub_"),
            parse_mode="Markdown",
        )
    elif cat == "house":
        await query.edit_message_text(
            "🏠 **የቤቱ/ቦታው አይነት ይምረጡ፦**",
            reply_markup=build_indexed_keyboard(HOUSE_TYPES, "flow_buy_type_"),
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text(
            "🏢 **የስራ ቦታው አይነት ይምረጡ፦**",
            reply_markup=build_indexed_keyboard(COMMERCIAL_TYPES, "flow_buy_type_"),
            parse_mode="Markdown",
        )
    return BUYER_SUBTYPE

async def buyer_subtype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buyer subtype selection"""
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    cat = context.user_data.get('main_category')
    
    if query.data.startswith("flow_buy_carsub_"):
        idx = int(query.data.replace("flow_buy_carsub_", ""))
        sub = CAR_SUB_CATEGORIES[idx]
    else:
        idx = int(query.data.replace("flow_buy_type_", ""))
        options = HOUSE_TYPES if cat == "house" else COMMERCIAL_TYPES
        sub = options[idx]
    
    context.user_data['sub_type'] = sub
    
    example = "ቶዮታ ቪትዝ 2020፣ ባጀት እስከ 2.5 ሚሊዮን ብር" if cat == "car" else "ቦሌ 2 መኝታ፣ ባጀት እስከ 10 ሚሊዮን ብር"
    await query.edit_message_text(
        f"✅ {sub}\n\n✍️ **ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* {example}",
        parse_mode="Markdown",
    )
    return BUYER_DETAILS

async def buyer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buyer details input"""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data['description'] = sanitize_input(update.message.text)
    await safe_send_message(
        update, context,
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**",
        parse_mode="Markdown",
        reply_markup=HOME_ONLY_KEYBOARD,
    )
    return BUYER_PHONE

async def buyer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buyer phone input"""
    user = update.effective_user
    phone = update.message.text
    
    if phone == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(phone):
        await safe_send_message(
            update, context,
            "❌ ስልክ ቁጥሩ ትክክል አይደለም! እባክዎ እንደገና ያስገቡ።\n(ምሳሌ፦ 0911223344 ወይም +251911223344)"
        )
        return BUYER_PHONE
    
    # Prepare listing data
    listing_data = {
        'user_chat_id': user.id,
        'user_name': user.first_name or "ተጠቃሚ",
        'req_type': 'BUY',
        'main_category': context.user_data.get('main_category', ''),
        'sub_type': context.user_data.get('sub_type', ''),
        'action_type': context.user_data.get('action_type', ''),
        'description': context.user_data.get('description', ''),
        'phone': phone,
        'price': None,
        'photo_file_id': None
    }
    
    # Create listing
    req_id = ListingRepository.create(listing_data)
    
    if req_id:
        category_title = {
            "car": "🚗 አዲስ የመኪና ጥያቄ",
            "house": "🏠 አዲስ የቤት/ቦታ ጥያቄ",
            "commercial": "🏢 አዲስ የስራ ቦታ ጥያቄ"
        }.get(listing_data['main_category'], "📌 አዲስ ጥያቄ")
        
        full_desc = (
            f"📌 **{category_title}**\n"
            f"🔹 አይነት: {listing_data['sub_type']}\n"
            f"🔄 ፍላጎት: {listing_data['action_type']}\n"
            f"📝 ዝርዝር: {listing_data['description']}\n"
            f"📞 ስልክ: {phone}"
        )
        
        await safe_send_message(
            update, context,
            f"✅ **ጥያቄዎ በጥሩ ሁኔታ ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"📌 ጥያቄዎ ለተረጋገጡ ደላሎች የተላከ ሲሆን፣ ንብረቱ ያላቸው ደላሎች አማራጮችን ሲልኩልዎ እዚሁ ቴሌግራም ላይ ይደርስዎታል።",
            reply_markup=MAIN_MARKUP,
        )
        
        # Notify brokers
        notification_text = (
            f"🔔 **{category_title}! (#REQ-{req_id})**\n\n"
            f"{full_desc}\n\n"
            f"👉 ይህ ንብረት በእጅዎ ካለ ከታች **'አለኝ'** የሚለውን በመጫን ለፈላጊው መረጃ ይላኩ!"
        )
        await notify_brokers(context, notification_text, req_id, user.id)
    else:
        await safe_send_message(
            update, context,
            "❌ ጥያቄውን መመዝገብ አልተቻለም። እባክዎ እንደገና ይሞክሩ።",
            reply_markup=MAIN_MARKUP,
        )
    
    return ConversationHandler.END

# ==============================================================================
# 14. HANDLERS - SELLER FLOW
# ==============================================================================
async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start seller flow"""
    if not rate_limiter.is_allowed(update.effective_user.id):
        await safe_send_message(update, context, "⏳ እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።")
        return ConversationHandler.END
    
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    
    keyboard = [[InlineKeyboardButton(label, callback_data=f"flow_sell_cat_{code}")] for code, label in MAIN_CATEGORIES]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await safe_send_message(
        update, context,
        "📢 **የሚሸጡትን ወይም የሚያከራዩትን ምድብ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return SELLER_MAIN

async def seller_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller category selection"""
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    cat = query.data.replace("flow_sell_cat_", "")
    context.user_data['main_category'] = cat
    
    keyboard = [
        [InlineKeyboardButton("🛍️ መሸጥ", callback_data="flow_sell_action_sell")],
        [InlineKeyboardButton("🔑 ማከራየት", callback_data="flow_sell_action_rent")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await query.edit_message_text(
        "❓ **የድርጊት አይነት ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return SELLER_ACTION

async def seller_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller action selection"""
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    action = query.data.replace("flow_sell_action_", "")
    context.user_data['action_type'] = "መሸጥ" if action == "sell" else "ማከራየት"
    
    cat = context.user_data.get('main_category')
    if cat == "car":
        await query.edit_message_text(
            "🚗 **የመኪና ንኡስ ምድብ ይምረጡ፦**",
            reply_markup=build_indexed_keyboard(CAR_SUB_CATEGORIES, "flow_sell_carsub_"),
            parse_mode="Markdown",
        )
    elif cat == "house":
        await query.edit_message_text(
            "🏠 **የቤቱ/ቦታው አይነት ይምረጡ፦**",
            reply_markup=build_indexed_keyboard(HOUSE_TYPES, "flow_sell_type_"),
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text(
            "🏢 **የስራ ቦታው አይነት ይምረጡ፦**",
            reply_markup=build_indexed_keyboard(COMMERCIAL_TYPES, "flow_sell_type_"),
            parse_mode="Markdown",
        )
    return SELLER_SUBTYPE

async def seller_subtype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller subtype selection"""
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    cat = context.user_data.get('main_category')
    
    if query.data.startswith("flow_sell_carsub_"):
        idx = int(query.data.replace("flow_sell_carsub_", ""))
        sub = CAR_SUB_CATEGORIES[idx]
    else:
        idx = int(query.data.replace("flow_sell_type_", ""))
        options = HOUSE_TYPES if cat == "house" else COMMERCIAL_TYPES
        sub = options[idx]
    
    context.user_data['sub_type'] = sub
    
    example = "ቶዮታ ቪትዝ 2020፣ 60,000 ኪሜ የሄደ" if cat == "car" else "ቦሌ አትላስ አካባቢ 3 መኝታ ቤት"
    await query.edit_message_text(
        f"✅ {sub}\n\n✍️ **ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* {example}",
        parse_mode="Markdown",
    )
    return SELLER_DETAILS

async def seller_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller details input"""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data['description'] = sanitize_input(update.message.text)
    await safe_send_message(
        update, context,
        "💰 **የሚሸጡበትን/ሚያከራዩበትን ዋጋ ያስገቡ፦**",
        reply_markup=HOME_ONLY_KEYBOARD,
    )
    return SELLER_PRICE

async def seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller price input"""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_price(update.message.text):
        await safe_send_message(update, context, "❌ እባክዎ ቁጥር ብቻ ያስገቡ።")
        return SELLER_PRICE
    
    context.user_data['price'] = update.message.text
    await safe_send_message(update, context, "📞 **የስልክ ቁጥርዎን ያስገቡ፦**")
    return SELLER_PHONE

async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller phone input"""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(update.message.text):
        await safe_send_message(
            update, context,
            "❌ ትክክለኛ የስልክ ቁጥር ያስገቡ። (ምሳሌ፦ 0911223344 ወይም +251911223344)"
        )
        return SELLER_PHONE
    
    context.user_data['phone'] = update.message.text
    await safe_send_message(update, context, "📸 **የንብረቱን ፎቶ ይላኩ፦**")
    return SELLER_PHOTO

async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller photo input"""
    user = update.effective_user
    
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    if not photo_id:
        await safe_send_message(update, context, "❌ እባክዎ ፎቶ ይላኩ!")
        return SELLER_PHOTO
    
    # Prepare listing data
    listing_data = {
        'user_chat_id': user.id,
        'user_name': user.first_name or "ተጠቃሚ",
        'req_type': 'SELL',
        'main_category': context.user_data.get('main_category', ''),
        'sub_type': context.user_data.get('sub_type', ''),
        'action_type': context.user_data.get('action_type', ''),
        'description': context.user_data.get('description', ''),
        'price': context.user_data.get('price', ''),
        'phone': context.user_data.get('phone', ''),
        'photo_file_id': photo_id
    }
    
    # Create listing
    req_id = ListingRepository.create(listing_data)
    
    if req_id:
        await safe_send_message(
            update, context,
            "✅ **የማስታወቂያ ጥያቄዎ በስኬት ተመዝግቧል!**",
            reply_markup=MAIN_MARKUP,
        )
    else:
        await safe_send_message(
            update, context,
            "❌ ማስታወቂያውን መመዝገብ አልተቻለም። እባክዎ እንደገና ይሞክሩ።",
            reply_markup=MAIN_MARKUP,
        )
    
    return ConversationHandler.END

# ==============================================================================
# 15. HANDLERS - BROKER REGISTRATION
# ==============================================================================
async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start broker registration"""
    if not rate_limiter.is_allowed(update.effective_user.id):
        await safe_send_message(update, context, "⏳ እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።")
        return ConversationHandler.END
    
    context.user_data.clear()
    
    keyboard = [
        [InlineKeyboardButton("👨💼 ደላላ", callback_data="role_broker")],
        [InlineKeyboardButton("🚢 አስመጪ / አቅራቢ", callback_data="role_importer")],
        [InlineKeyboardButton("👤 ባለቤት / አቅራቢ", callback_data="role_owner")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await safe_send_message(
        update, context,
        "📝 **የምዝገባ አይነት ይምረጡ፦**\n\n"
        "💡 *ማብራሪያ፦*\n"
        "• ደላላ - ሽያጭ/ኪራይ የሚያመቻች\n"
        "• አስመጪ/አቅራቢ - ከውጭ የሚያስገባ\n"
        "• ባለቤት/አቅራቢ - ንብረት ያለው",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return BROKER_ROLE

async def broker_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broker role selection"""
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    role_map = {"role_broker": "ደላላ", "role_importer": "አስመጪ/አቅራቢ", "role_owner": "ባለቤት/አቅራቢ"}
    role = role_map.get(query.data, "አቅራቢ")
    context.user_data['broker_role'] = role
    
    await query.edit_message_text(f"👤 **ምዝገባ፦ {role}**\n\n1️⃣ ሙሉ ስምዎን ያስገቡ፦")
    return BROKER_NAME

async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broker name input"""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data['broker_name'] = sanitize_input(update.message.text)
    await safe_send_message(update, context, "2️⃣ የስልክ ቁጥርዎን ያስገቡ፦")
    return BROKER_PHONE

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broker phone input"""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(update.message.text):
        await safe_send_message(
            update, context,
            "❌ ትክክለኛ የስልክ ቁጥር ያስገቡ። (ለምሳሌ፦ 0911223344)"
        )
        return BROKER_PHONE
    
    context.user_data['broker_phone'] = update.message.text
    await safe_send_message(
        update, context,
        "3️⃣ የሚሰሩበትን ክፍለ ከተማ ይምረጡ፦",
        reply_markup=build_indexed_keyboard(SUB_CITIES, "broker_sc_", columns=2),
    )
    return BROKER_SUBCITY

async def broker_reg_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broker sub-city selection"""
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    idx = int(query.data.replace("broker_sc_", ""))
    sub_city = SUB_CITIES[idx]
    context.user_data['broker_subcity'] = sub_city
    
    await query.edit_message_text(
        "4️⃣ **የፋይዳ (National ID) ወይም የነዋሪነት መታወቂያ ፎቶ ያንሱና ይላኩ፦**\n\n💡 *ይህ ለማረጋገጫ ብቻ ነው*"
    )
    return BROKER_NID_PHOTO

async def broker_reg_nid_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broker NID photo upload"""
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    user = update.effective_user
    
    if not update.message or not update.message.photo:
        await safe_send_message(
            update, context,
            "❌ **እባክዎ የመታወቂያዎን ፎቶ ይላኩ!**\n\n"
            "📸 ፎቶውን ከቴሌግራም ፋይል አባሪ አማራጭ በመጠቀም ይላኩ።\n✏️ ጽሁፍ አይቀበልም።"
        )
        return BROKER_NID_PHOTO
    
    photo_id = update.message.photo[-1].file_id
    role = context.user_data.get('broker_role', 'አቅራቢ')
    name = context.user_data.get('broker_name', user.first_name)
    phone = context.user_data.get('broker_phone', '')
    sub_city = context.user_data.get('broker_subcity', '')
    
    await safe_send_message(
        update, context,
        f"📝 **የምዝገባ መረጃዎ፦**\n\n"
        f"👤 ስም: {name}\n"
        f"🎭 ሚና: {role}\n"
        f"📞 ስልክ: {phone}\n"
        f"📍 ክፍለ ከተማ: {sub_city}\n"
        f"🆔 Telegram ID: `{user.id}`\n\n"
        f"⏳ እባክዎ ይጠብቁ፣ እያስመዘገብን ነው...",
        parse_mode="Markdown",
    )
    
    # Create broker registration
    broker_data = {
        'chat_id': user.id,
        'full_name': name,
        'phone': phone,
        'role_type': role,
        'sub_city': sub_city,
        'national_id_photo': photo_id
    }
    
    broker_id = BrokerRepository.create_or_update(broker_data)
    
    if broker_id:
        await safe_send_message(
            update, context,
            "✅ **ምዝገባዎ በስኬት ተጠናቋል!** 🎉\n\n"
            "⏳ አድሚኑ መረጃዎን ካረጋገጠ በኋላ ማስታወቂያ ይደርስዎታል።\n\n"
            "📋 ምዝገባዎ ከጸደቀ በኋላ '📋 የፈላጊዎች ዝርዝር' ማየት ይችላሉ።",
            reply_markup=MAIN_MARKUP,
        )
        
        # Notify admin
        if Config.ADMIN_CHAT_ID_INT != 0:
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
                    InlineKeyboardButton("❌ ሰርዝ", callback_data=f"admin_reje_{user.id}"),
                ],
                [InlineKeyboardButton("👤 ዝርዝር", callback_data=f"admin_view_{user.id}")],
            ])
            try:
                await context.bot.send_photo(
                    chat_id=Config.ADMIN_CHAT_ID_INT,
                    photo=photo_id,
                    caption=admin_msg,
                    parse_mode="Markdown",
                    reply_markup=admin_kbd,
                )
                logger.info("Admin notification sent", broker_id=user.id)
            except Exception as e:
                logger.error("Failed to send admin notification", error=str(e))
                await safe_send_message(
                    update, context,
                    "⚠️ ለአድሚን መላክ አልተቻለም፣ ነገር ግን ምዝገባዎ ተመዝግቧል።"
                )
        else:
            logger.warning("ADMIN_CHAT_ID not set")
    else:
        await safe_send_message(
            update, context,
            "❌ **ምዝገባውን ማጠናቀቅ አልተቻለም!**\n\n"
            "💡 እባክዎ የሚከተሉትን ያረጋግጡ፦\n"
            "• መረጃዎቹ ሙሉ መሆናቸውን\n"
            "• የበይነመረብ ግንኙነትዎን\n\n"
            "🔄 እንደገና ለመሞከር '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይጫኑ።",
            reply_markup=MAIN_MARKUP,
        )
    
    return ConversationHandler.END

# ==============================================================================
# 16. HANDLERS - BROKER RESPONSE
# ==============================================================================
async def broker_have_item_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broker 'I have it' click"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    broker = BrokerRepository.get_by_chat_id(user_id)
    
    if not broker or broker.get('status') != 'approved':
        await safe_send_message(
            update, context,
            "⛔ ይህን ማድረግ የሚችሉት በአድሚን የተረጋገጡ ደላሎች/አቅራቢዎች ብቻ ናቸው!"
        )
        return ConversationHandler.END
    
    parts = query.data.split('_')
    if len(parts) < 3:
        logger.error("Invalid callback data", data=query.data)
        return ConversationHandler.END
    
    req_id = parts[2]
    buyer_id = parts[3] if len(parts) > 3 else None
    
    context.user_data['target_req_id'] = req_id
    context.user_data['target_buyer_id'] = buyer_id
    
    await safe_send_message(
        update, context,
        f"✅ **ጥያቄ #{req_id}**\n\n"
        f"✍️ **ያለዎትን ንብረት ዝርዝር መረጃ እና ዋጋ ያስገቡ፦**\n"
        f"(ለምሳሌ፦ ቶዮታ ቪትዝ 2021፣ 30,000 KM የሄደ፣ ዋጋ 2.4 ሚሊዮን፣ ስልክ 0911...)",
        reply_markup=HOME_ONLY_KEYBOARD,
    )
    return BROKER_OFFER_TEXT

async def broker_offer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broker offer text"""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data['offer_text'] = sanitize_input(update.message.text)
    await safe_send_message(
        update, context,
        "📸 **የንብረቱን ፎቶ ይላኩ፦**\n(ፎቶ ከሌልዎት 'ፎቶ የለውም' ብለው ይጻፉ)"
    )
    return BROKER_OFFER_PHOTO

async def broker_offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broker offer photo"""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    buyer_id = int(context.user_data.get('target_buyer_id', 0))
    req_id = context.user_data.get('target_req_id')
    offer_text = context.user_data.get('offer_text', '')
    broker_name = update.effective_user.first_name or "አቅራቢ"
    
    if not buyer_id or not req_id:
        await safe_send_message(update, context, "❌ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።")
        return ConversationHandler.END
    
    # Update listing status
    ListingRepository.update_status(int(req_id), 'responded')
    
    message_to_buyer = (
        f"🎉 **ለጥያቄዎ (#REQ-{req_id}) አዲስ የቀረበ አማራጭ አለ!**\n\n"
        f"👤 **ደላላ/አቅራቢ፦** {broker_name}\n"
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
            await context.bot.send_message(
                chat_id=buyer_id,
                text=message_to_buyer,
                parse_mode="Markdown"
            )
        
        await safe_send_message(
            update, context,
            "✅ **መረጃዎ ለፈላጊው በስኬት ተልኳል!**\n\n"
            "📌 ጥያቄው ከ'📋 የፈላጊዎች ዝርዝር' ተወግዷል።",
            reply_markup=MAIN_MARKUP,
        )
        
        logger.info("Offer sent to buyer", request_id=req_id, buyer_id=buyer_id)
    except Exception as e:
        logger.error("Failed to send offer to buyer", error=str(e), exc_info=True)
        await safe_send_message(
            update, context,
            "❌ መረጃውን ለፈላጊው መላክ አልተቻለም።",
            reply_markup=MAIN_MARKUP,
        )
    
    return ConversationHandler.END

# ==============================================================================
# 17. HANDLERS - VIEW REQUESTS
# ==============================================================================
async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show pending requests to brokers"""
    user_id = update.effective_user.id
    broker = BrokerRepository.get_by_chat_id(user_id)
    
    if not broker:
        await safe_send_message(
            update, context,
            "⛔ ይህን ገጽ ማየት የሚችሉት የተመዘገቡ አቅራቢዎች/ደላሎች ብቻ ናቸው!\n\n"
            "📝 እባክዎን መጀመሪያ '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይጫኑ።",
            reply_markup=MAIN_MARKUP,
        )
        return
    
    if broker.get('status') != 'approved':
        await safe_send_message(
            update, context,
            "⏳ **ምዝገባዎ ገና በአድሚን አልጸደቀም!**\n\n"
            "⏳ ምዝገባዎ በአድሚን ሲረጋገጥ ማስታወቂያ ይደርስዎታል።\n📞 ለተጨማሪ መረጃ ድጋፍን ይጠቀሙ።",
            reply_markup=MAIN_MARKUP,
        )
        return
    
    context.user_data['view_page'] = 0
    await show_requests_page(update, context)

async def show_requests_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show paginated requests"""
    try:
        if update.callback_query and update.callback_query.data.startswith("page_"):
            context.user_data['view_page'] = int(update.callback_query.data.replace("page_", ""))
        
        page = context.user_data.get('view_page', 0)
        offset = page * Config.ITEMS_PER_PAGE
        
        listings = ListingRepository.get_pending(limit=Config.ITEMS_PER_PAGE, offset=offset)
        total = ListingRepository.count_pending()
        total_pages = max(1, (total + Config.ITEMS_PER_PAGE - 1) // Config.ITEMS_PER_PAGE)
        
        if not listings:
            text = "📭 ምንም ንቁ ጥያቄዎች የሉም።"
            if update.message:
                await safe_send_message(update, context, text, reply_markup=MAIN_MARKUP)
            else:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(text)
            return
        
        text = f"📋 **የፈላጊዎች ዝርዝር** (ገጽ {page + 1}/{total_pages})\n\n"
        for listing in listings:
            listing_id = listing.get('id', '')
            description = listing.get('description', '')
            text += f"━━━━━━━━━━━━━━━━━━━━\n📌 **#{listing_id}**\n{description}\n"
        
        keyboard = []
        for listing in listings:
            l_id = listing.get('id')
            u_id = listing.get('user_chat_id')
            keyboard.append([InlineKeyboardButton(f"👉 አለኝ - #{l_id}", callback_data=f"have_item_{l_id}_{u_id}")])
        
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ ቀዳሚ", callback_data=f"page_{page - 1}"))
        if offset + Config.ITEMS_PER_PAGE < total:
            nav_buttons.append(InlineKeyboardButton("➡️ ቀጣይ", callback_data=f"page_{page + 1}"))
        nav_buttons.append(InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home"))
        keyboard.append(nav_buttons)
        
        if update.message:
            await safe_send_message(
                update, context,
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
        logger.error("Error showing requests page", error=str(e), exc_info=True)
        await safe_send_message(
            update, context,
            "❌ ዝርዝሩን ማሳየት አልተቻለም። እባክዎ እንደገና ይሞክሩ።"
        )

# ==============================================================================
# 18. HANDLERS - ADMIN
# ==============================================================================
async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin approval/rejection"""
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("admin_appr_"):
        target_id = int(data.replace("admin_appr_", ""))
        if BrokerRepository.update_status(target_id, 'approved'):
            await query.edit_message_caption(
                caption=(query.message.caption or "") + "\n\n✅ **ሁኔታ፦ በስኬት ጸድቋል (Approved)**",
                parse_mode="Markdown"
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="🎉 **እንኳን ደስ አለዎት!** የምዝገባ ጥያቄዎ በአድሚን ጸድቋል።\n\n📋 አሁን '📋 የፈላጊዎች ዝርዝር' በመጠቀም ጥያቄዎችን ማየት ይችላሉ።",
                    reply_markup=MAIN_MARKUP,
                )
                logger.info("Broker approved", broker_id=target_id)
            except Exception as e:
                logger.error("Failed to notify approved broker", error=str(e))
    
    elif data.startswith("admin_reje_"):
        target_id = int(data.replace("admin_reje_", ""))
        if BrokerRepository.update_status(target_id, 'rejected'):
            await query.edit_message_caption(
                caption=(query.message.caption or "") + "\n\n❌ **ሁኔታ፦ ተሰርዟል (Rejected)**",
                parse_mode="Markdown"
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="❌ የምዝገባ ጥያቄዎ ተሰርዟል።\n\nለተጨማሪ መረጃ እባክዎን አድሚንን ያግኙ።",
                    reply_markup=MAIN_MARKUP,
                )
                logger.info("Broker rejected", broker_id=target_id)
            except Exception as e:
                logger.error("Failed to notify rejected broker", error=str(e))
    
    elif data.startswith("admin_view_"):
        target_id = int(data.replace("admin_view_", ""))
        broker = BrokerRepository.get_by_chat_id(target_id)
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
# 19. HANDLERS - HELP
# ==============================================================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command handler"""
    help_text = """
❓ **እንዴት እንደሚጠቀሙ**

🔍 **መግዛት ከፈለጉ:**
• '🔍 መግዛት / መከራየት' ይምረጡ
• ምድብ ይምረጡ (መኪና/ቤት/ንግድ)
• የድርጊት አይነት እና ንኡስ ምድብ ይምረጡ
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

🏠 **ዋና ገጽ:**
• ቀደም ሲል የነበረውን ሂደት ያጽዳል እና አዲስ ሜኑ ያመጣል
"""
    await safe_send_message(update, context, help_text, parse_mode="Markdown")

# ==============================================================================
# 20. MAIN APPLICATION
# ==============================================================================
def main():
    """Main entry point"""
    # Initialize database
    init_db()
    
    # Initialize connection pool
    init_connection_pool()
    
    # Start Flask server in background
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info("Flask server started", port=Config.PORT)
    
    # Create bot application
    app = Application.builder().token(Config.BOT_TOKEN).build()
    
    # Add handlers
    app.add_handler(CommandHandler("start", start))
    
    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)
    
    # Buyer conversation
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
        states={
            BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_|^flow_home$")],
            BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_|^flow_home$")],
            BUYER_SUBTYPE: [CallbackQueryHandler(buyer_subtype_chosen, pattern="^flow_buy_carsub_|^flow_buy_type_|^flow_home$")],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details)],
            BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone)],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    # Seller conversation
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_|^flow_home$")],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_|^flow_home$")],
            SELLER_SUBTYPE: [CallbackQueryHandler(seller_subtype_chosen, pattern="^flow_sell_carsub_|^flow_sell_type_|^flow_home$")],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details)],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price)],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone)],
            SELLER_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, seller_photo)],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    # Broker registration conversation
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ/ደላላ መመዝገብ$"), broker_reg_start)],
        states={
            BROKER_ROLE: [CallbackQueryHandler(broker_role_chosen, pattern="^role_|^flow_home$")],
            BROKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name)],
            BROKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone)],
            BROKER_SUBCITY: [CallbackQueryHandler(broker_reg_subcity, pattern="^broker_sc_|^flow_home$")],
            BROKER_NID_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, broker_reg_nid_photo)],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    # Broker response conversation
    broker_response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broker_have_item_click, pattern="^have_item_")],
        states={
            BROKER_OFFER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text)],
            BROKER_OFFER_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, broker_offer_photo)],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    # Register all handlers
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
    
    logger.info("🚀 Adika Marketplace Bot started successfully!")
    logger.info(f"Environment: {Config.ENVIRONMENT}")
    logger.info(f"Database: {'PostgreSQL' if Config.DATABASE_URL else 'SQLite'}")
    
    # Start the bot
    app.run_polling()

if __name__ == "__main__":
    main()
