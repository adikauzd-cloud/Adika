import asyncio
import logging
import os
import threading
import re
import sys
import fcntl
import atexit
import time
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from functools import lru_cache
from contextlib import contextmanager
from collections import defaultdict
from pathlib import Path

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
# 0. LOCK FILE MECHANISM
# ==============================================================================
LOCK_FILE = Path("/tmp/adika_bot.lock")
lock_fd = None

def acquire_lock():
    """Acquire a lock file to prevent multiple instances"""
    global lock_fd
    try:
        if not LOCK_FILE.exists():
            LOCK_FILE.touch()
        
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        
        def cleanup():
            try:
                if lock_fd:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    lock_fd.close()
                if LOCK_FILE.exists():
                    LOCK_FILE.unlink()
            except:
                pass
        
        atexit.register(cleanup)
        print(f"✅ Lock acquired (PID: {os.getpid()})")
        return True
        
    except IOError:
        if LOCK_FILE.exists():
            try:
                with open(LOCK_FILE, 'r') as f:
                    existing_pid = f.read().strip()
                print(f"❌ Another instance (PID: {existing_pid}) is already running!")
                print(f"   To force start: rm -f {LOCK_FILE}")
            except:
                print(f"❌ Another instance is already running!")
        return False
    except Exception as e:
        print(f"❌ Failed to acquire lock: {e}")
        return False

def release_lock():
    """Release the lock file"""
    global lock_fd
    try:
        if lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
        print("✅ Lock released")
    except Exception as e:
        print(f"⚠️ Failed to release lock: {e}")

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================
class Config:
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
            raise RuntimeError("❌ BOT_TOKEN is required")
        try:
            cls.ADMIN_CHAT_ID_INT = int(cls.ADMIN_CHAT_ID)
        except ValueError:
            cls.ADMIN_CHAT_ID_INT = 0

Config.validate()

# ==============================================================================
# 2. LOGGING
# ==============================================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================================================================
# 3. DATABASE CONNECTION POOL
# ==============================================================================
connection_pool = None

def init_connection_pool():
    global connection_pool
    if Config.DATABASE_URL:
        try:
            db_url = Config.DATABASE_URL.replace("postgres://", "postgresql://", 1)
            connection_pool = psycopg2.pool.SimpleConnectionPool(
                1, 20,
                dsn=db_url,
                cursor_factory=RealDictCursor
            )
            logger.info("Database connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to initialize connection pool: {e}")
            raise
    else:
        logger.info("Using SQLite (no connection pool)")

@contextmanager
def get_db_connection():
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
        logger.error(f"Database connection error: {e}")
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
    try:
        yield
        if not Config.DATABASE_URL:
            conn.commit()
    except Exception as e:
        if not Config.DATABASE_URL:
            conn.rollback()
        logger.error(f"Transaction failed: {e}")
        raise

# ==============================================================================
# 4. CACHE
# ==============================================================================
class Cache:
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
# 5. RATE LIMITER
# ==============================================================================
class RateLimiter:
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
# 6. INPUT VALIDATION
# ==============================================================================
def validate_phone(phone: str) -> bool:
    phone = phone.replace(' ', '').replace('-', '')
    pattern = r'^(09|07|01)\d{8}$|^\+251(9|7|1)\d{8}$'
    return bool(re.match(pattern, phone))

def validate_price(price: str) -> bool:
    price = price.replace(',', '').replace(' ', '')
    return price.isdigit()

def sanitize_input(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'[<>"\'%;]', '', text.strip())

def validate_listing_data(data: Dict) -> Optional[str]:
    required_fields = ['user_chat_id', 'user_name', 'req_type', 'main_category', 
                      'sub_category', 'action_type', 'property_type', 'description']
    
    for field in required_fields:
        if field not in data or not data[field]:
            return f"Missing required field: {field}"
    
    if len(data['description'].strip()) < 5:
        return "Description must be at least 5 characters"
    
    data['description'] = sanitize_input(data['description'])
    return None

def validate_broker_data(data: Dict) -> Optional[str]:
    required_fields = ['chat_id', 'full_name', 'phone', 'role_type', 'sub_city', 'national_id_photo']
    
    for field in required_fields:
        if field not in data or not data[field]:
            return f"Missing required field: {field}"
    
    if len(data['full_name'].strip()) < 2:
        return "Name must be at least 2 characters"
    
    if not validate_phone(data['phone']):
        return "Invalid phone number format"
    
    data['full_name'] = sanitize_input(data['full_name'])
    return None

# ==============================================================================
# 7. CONSTANTS
# ==============================================================================
SUB_CITIES = [
    "ቦሌ", "የካ", "አራዳ", "ልደታ",
    "ቂርቆስ", "አዲስ ከተማ", "ንፋስ ስልክ ላፍቶ",
    "ኮልፌ ቀራኒዮ", "አቃቂ ቃሊቲ", "ጉሌሌ", "ለሚ ኩራ",
]

CAR_SUB_CATEGORIES = ["🚗 የቤት መኪና", "🚚 የሥራ መኪና", "🚜 ከባድ ተሽከርካሪ/ማሽን"]
HOUSE_TYPES = ["🏡 ቪላ", "🏢 አፓርታማ", "🏢 ኮንዶሚኒየም", "🏢 ሪል እስቴት", "🏞️ መሬት/ቦታ"]
PROPERTY_TYPES = ["🏠 መኖሪያ ቤት", "🏢 የሥራ ቦታ / ንግድ"]

MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ/ደላላ መመዝገብ", "📋 የፈላጊዎች ዝርዝር"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]
MAIN_MARKUP = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
HOME_ONLY_KEYBOARD = ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)

# ==============================================================================
# 8. DATABASE OPERATIONS
# ==============================================================================
def get_placeholder():
    return "%s" if Config.DATABASE_URL else "?"

def init_db():
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
                        sub_category TEXT,
                        action_type TEXT,
                        property_type TEXT,
                        description TEXT NOT NULL,
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
                        sub_category TEXT,
                        action_type TEXT,
                        property_type TEXT,
                        description TEXT NOT NULL,
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
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at DESC)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_brokers_status ON brokers(status)")
            
            if not Config.DATABASE_URL:
                conn.commit()
            
            logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise

class ListingRepository:
    @staticmethod
    def create(listing_data: Dict) -> Optional[int]:
        error = validate_listing_data(listing_data)
        if error:
            logger.error(f"Validation error: {error}")
            return None
        
        with get_db_connection() as conn:
            with transaction(conn):
                cursor = conn.cursor()
                p = get_placeholder()
                query = f"""
                    INSERT INTO listings 
                    (user_chat_id, user_name, req_type, main_category, sub_category, 
                     action_type, property_type, description)
                    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                """
                params = (
                    listing_data['user_chat_id'], listing_data['user_name'],
                    listing_data['req_type'], listing_data['main_category'],
                    listing_data['sub_category'], listing_data['action_type'],
                    listing_data['property_type'], listing_data['description']
                )
                
                if Config.DATABASE_URL:
                    cursor.execute(query + " RETURNING id", params)
                    res = cursor.fetchone()
                    return res['id'] if res else None
                else:
                    cursor.execute(query, params)
                    return cursor.lastrowid
    
    @staticmethod
    def get_pending(limit: int = 10, offset: int = 0) -> List[Dict]:
        cache_key = f"listings_pending_{limit}_{offset}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            query = f"""
                SELECT * FROM listings 
                WHERE status = 'pending' 
                ORDER BY created_at DESC 
                LIMIT {p} OFFSET {p}
            """
            cursor.execute(query, (limit, offset))
            rows = cursor.fetchall()
            result = [dict(row) for row in rows]
            cache.set(cache_key, result)
            return result
    
    @staticmethod
    def count_pending() -> int:
        cache_key = "listings_count_pending"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM listings WHERE status = 'pending'")
            res = cursor.fetchone()
            count = res['count'] if Config.DATABASE_URL else res[0]
            cache.set(cache_key, count)
            return count
    
    @staticmethod
    def update_status(listing_id: int, status: str) -> bool:
        try:
            with get_db_connection() as conn:
                with transaction(conn):
                    cursor = conn.cursor()
                    p = get_placeholder()
                    cursor.execute(f"UPDATE listings SET status = {p} WHERE id = {p}", (status, listing_id))
                    cache.invalidate()
                    return True
        except Exception as e:
            logger.error(f"Failed to update listing status: {e}")
            return False

class BrokerRepository:
    @staticmethod
    def create_or_update(broker_data: Dict) -> Optional[int]:
        error = validate_broker_data(broker_data)
        if error:
            logger.error(f"Validation error: {error}")
            return None
        
        with get_db_connection() as conn:
            with transaction(conn):
                cursor = conn.cursor()
                p = get_placeholder()
                
                cursor.execute(f"SELECT id FROM brokers WHERE chat_id = {p}", (broker_data['chat_id'],))
                existing = cursor.fetchone()
                
                if existing:
                    existing_id = existing['id'] if Config.DATABASE_URL else existing[0]
                    if Config.DATABASE_URL:
                        query = f"""
                            UPDATE brokers 
                            SET full_name = {p}, phone = {p}, role_type = {p},
                                national_id_photo = {p}, sub_city = {p}, status = 'pending'
                            WHERE chat_id = {p}
                            RETURNING id
                        """
                        cursor.execute(query, (
                            broker_data['full_name'], broker_data['phone'],
                            broker_data['role_type'], broker_data['national_id_photo'],
                            broker_data['sub_city'], broker_data['chat_id']
                        ))
                        res = cursor.fetchone()
                        return res['id'] if res else None
                    else:
                        query = """
                            UPDATE brokers 
                            SET full_name = ?, phone = ?, role_type = ?,
                                national_id_photo = ?, sub_city = ?, status = 'pending'
                            WHERE chat_id = ?
                        """
                        cursor.execute(query, (
                            broker_data['full_name'], broker_data['phone'],
                            broker_data['role_type'], broker_data['national_id_photo'],
                            broker_data['sub_city'], broker_data['chat_id']
                        ))
                        return existing_id
                else:
                    if Config.DATABASE_URL:
                        query = f"""
                            INSERT INTO brokers 
                            (chat_id, full_name, phone, role_type, national_id_photo, sub_city, status)
                            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, 'pending')
                            RETURNING id
                        """
                        cursor.execute(query, (
                            broker_data['chat_id'], broker_data['full_name'],
                            broker_data['phone'], broker_data['role_type'],
                            broker_data['national_id_photo'], broker_data['sub_city']
                        ))
                        res = cursor.fetchone()
                        return res['id'] if res else None
                    else:
                        query = """
                            INSERT INTO brokers 
                            (chat_id, full_name, phone, role_type, national_id_photo, sub_city, status)
                            VALUES (?, ?, ?, ?, ?, ?, 'pending')
                        """
                        cursor.execute(query, (
                            broker_data['chat_id'], broker_data['full_name'],
                            broker_data['phone'], broker_data['role_type'],
                            broker_data['national_id_photo'], broker_data['sub_city']
                        ))
                        return cursor.lastrowid
    
    @staticmethod
    def get_approved() -> List[int]:
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
        cache_key = f"broker_{chat_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            cursor.execute(f"SELECT * FROM brokers WHERE chat_id = {p}", (chat_id,))
            row = cursor.fetchone()
            result = dict(row) if row else None
            if result:
                cache.set(cache_key, result)
            return result
    
    @staticmethod
    def update_status(chat_id: int, status: str) -> bool:
        try:
            with get_db_connection() as conn:
                with transaction(conn):
                    cursor = conn.cursor()
                    p = get_placeholder()
                    cursor.execute(f"UPDATE brokers SET status = {p} WHERE chat_id = {p}", (status, chat_id))
                    cache.invalidate()
                    return True
        except Exception as e:
            logger.error(f"Failed to update broker status: {e}")
            return False

# ==============================================================================
# 9. FLASK WEB SERVER
# ==============================================================================
web_app = Flask(__name__)
start_time = time.time()

@web_app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'service': 'Adika Marketplace Bot',
        'version': '2.0.0',
        'timestamp': datetime.now().isoformat()
    }), 200

@web_app.route('/health')
def health():
    status = {
        'status': 'healthy',
        'database': False,
        'bot': True,
        'timestamp': datetime.now().isoformat()
    }
    
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
        status['database'] = True
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        status['status'] = 'unhealthy'
        status['error'] = str(e)
    
    return jsonify(status), 200 if status['status'] == 'healthy' else 503

@web_app.route('/metrics')
def metrics():
    try:
        pending_count = ListingRepository.count_pending()
        approved_brokers = len(BrokerRepository.get_approved())
    except:
        pending_count = 0
        approved_brokers = 0
    
    return jsonify({
        'pending_listings': pending_count,
        'approved_brokers': approved_brokers,
        'cache_size': len(cache.cache) if hasattr(cache, 'cache') else 0,
        'uptime_seconds': int(time.time() - start_time),
        'environment': Config.ENVIRONMENT
    }), 200

def run_flask():
    web_app.run(host="0.0.0.0", port=Config.PORT)

# ==============================================================================
# 10. HELPER FUNCTIONS
# ==============================================================================
def build_indexed_keyboard(options: List[str], prefix: str, columns: int = 1, extra_home: bool = True):
    buttons = [InlineKeyboardButton(opt, callback_data=f"{prefix}{i}") for i, opt in enumerate(options)]
    keyboard = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    if extra_home:
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    return InlineKeyboardMarkup(keyboard)

async def notify_brokers(context: ContextTypes.DEFAULT_TYPE, message_text: str, req_id: int, buyer_id: int):
    approved_brokers = BrokerRepository.get_approved()
    if not approved_brokers:
        logger.info("No approved brokers to notify")
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
            logger.error(f"Failed to notify broker {b_id}: {e}")

async def safe_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if update and hasattr(update, 'callback_query') and update.callback_query:
                await update.callback_query.message.reply_text(text, **kwargs)
            elif update and hasattr(update, 'message') and update.message:
                await update.message.reply_text(text, **kwargs)
            else:
                chat_id = update.effective_user.id if update else None
                if chat_id:
                    await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
            return True
        except Exception as e:
            logger.warning(f"Failed to send message (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
            else:
                logger.error(f"Failed to send message after retries: {e}")
                return False
    return False

# ==============================================================================
# 11. CONVERSATION STATES
# ==============================================================================
(
    BUYER_MAIN, BUYER_ACTION, BUYER_CATEGORY, BUYER_SUB, BUYER_PROPERTY, BUYER_DETAILS, BUYER_PHONE,
    BROKER_ROLE, BROKER_NAME, BROKER_PHONE, BROKER_SUBCITY, BROKER_NID_PHOTO,
    SELLER_MAIN, SELLER_ACTION, SELLER_CATEGORY, SELLER_SUB, SELLER_PROPERTY, SELLER_DETAILS, SELLER_PRICE, SELLER_PHONE, SELLER_PHOTO,
    BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO
) = range(23)

# ==============================================================================
# 12. START & HOME HANDLERS
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not rate_limiter.is_allowed(update.effective_user.id):
        await safe_send_message(update, context, "⏳ እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።")
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
    context.user_data.clear()
    welcome_text = "👋 **ወደ ዋና ገጽ ተመልሰዋል!**\n\nእባክዎን አማራጭ ይምረጡ፦"
    
    if update.message:
        await safe_send_message(update, context, welcome_text, parse_mode="Markdown", reply_markup=MAIN_MARKUP)
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
            reply_markup=MAIN_MARKUP
        )
    return ConversationHandler.END

# ==============================================================================
# 13. BUYER HANDLERS
# ==============================================================================
async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not rate_limiter.is_allowed(update.effective_user.id):
        await safe_send_message(update, context, "⏳ እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።")
        return ConversationHandler.END
    
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    
    keyboard = [
        [InlineKeyboardButton("🚗 መኪና", callback_data="flow_buy_cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ", callback_data="flow_buy_cat_house")],
        [InlineKeyboardButton("🏢 የሥራ ቦታ / ንግድ", callback_data="flow_buy_cat_commercial")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await safe_send_message(
        update, context,
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
            [InlineKeyboardButton("🛍️ መግዛት", callback_data="flow_buy_action_sell")],
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
        [InlineKeyboardButton("🛍️ መግዛት", callback_data="flow_buy_action_sell")],
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
    context.user_data['action_type'] = "መግዛት" if action == "sell" else "መከራየት"
    
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
    
    context.user_data['description'] = sanitize_input(update.message.text)
    await safe_send_message(
        update, context,
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**",
        parse_mode="Markdown",
        reply_markup=HOME_ONLY_KEYBOARD
    )
    return BUYER_PHONE

async def buyer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    phone = update.message.text
    
    if phone == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(phone):
        await safe_send_message(
            update, context,
            "❌ ስልክ ቁጥሩ ትክክል አይደለም! እባክዎ እንደገና ያስገቡ።"
        )
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
    
    listing_data = {
        'user_chat_id': user.id,
        'user_name': user.first_name or "ተጠቃሚ",
        'req_type': 'BUY',
        'main_category': main_cat,
        'sub_category': sub_cat,
        'action_type': action_type,
        'property_type': prop_subtype,
        'description': full_desc
    }
    
    req_id = ListingRepository.create(listing_data)
    
    if req_id:
        await safe_send_message(
            update, context,
            f"✅ **ጥያቄዎ በጥሩ ሁኔታ ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"📌 ጥያቄዎ ለተረጋገጡ ደላሎች የተላከ ሲሆን፣ ንብረቱ ያላቸው ደላሎች አማራጮችን ሲልኩልዎ እዚሁ ቴሌግራም ላይ ይደርስዎታል።",
            reply_markup=MAIN_MARKUP
        )
        
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
            reply_markup=MAIN_MARKUP
        )
    
    return ConversationHandler.END

# ==============================================================================
# 14. SELLER HANDLERS
# ==============================================================================
async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not rate_limiter.is_allowed(update.effective_user.id):
        await safe_send_message(update, context, "⏳ እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።")
        return ConversationHandler.END
    
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    
    keyboard = [
        [InlineKeyboardButton("🚗 መኪና", callback_data="flow_sell_cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ", callback_data="flow_sell_cat_house")],
        [InlineKeyboardButton("🏢 የሥራ ቦታ / ንግድ", callback_data="flow_sell_cat_commercial")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await safe_send_message(
        update, context,
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

async def seller_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    action = query.data.replace("flow_sell_action_", "")
    context.user_data['action_type'] = "መሸጥ" if action == "sell" else "ማከራየት"
    
    if context.user_data.get('main_category') == "car":
        await query.edit_message_text("✍️ **የመኪናውን ዝርዝር መረጃ ያስገቡ፦**")
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
    
    context.user_data['description'] = sanitize_input(update.message.text)
    await safe_send_message(
        update, context,
        "💰 **የሚሸጡበትን/ሚያከራዩበትን ዋጋ ያስገቡ፦**",
        reply_markup=HOME_ONLY_KEYBOARD
    )
    return SELLER_PRICE

async def seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_price(update.message.text):
        await safe_send_message(update, context, "❌ እባክዎ ቁጥር ብቻ ያስገቡ።")
        return SELLER_PRICE
    
    context.user_data['price'] = update.message.text
    await safe_send_message(update, context, "📞 **የስልክ ቁጥርዎን ያስገቡ፦**")
    return SELLER_PHONE

async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(update.message.text):
        await safe_send_message(
            update, context,
            "❌ ትክክለኛ የስልክ ቁጥር ያስገቡ።"
        )
        return SELLER_PHONE
    
    context.user_data['phone'] = update.message.text
    await safe_send_message(update, context, "📸 **የንብረቱን ፎቶ ይላኩ፦**")
    return SELLER_PHOTO

async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    
    if not photo_id:
        await safe_send_message(update, context, "❌ እባክዎ ፎቶ ይላኩ!")
        return SELLER_PHOTO
    
    property_subtype = context.user_data.get('property_subtype', '')
    description = context.user_data.get('description', '')
    if property_subtype:
        description = f"🏠 {property_subtype}\n{description}"
    
    full_desc = (
        f"📢 **አዲስ የሽያጭ/ኪራይ ማስታወቂያ!**\n"
        f"🔄 አይነት: {context.user_data.get('action_type')}\n"
        f"📝 ዝርዝር: {description}\n"
        f"💰 ዋጋ: {context.user_data.get('price')} ብር\n"
        f"📞 ስልክ: {context.user_data.get('phone')}"
    )
    
    listing_data = {
        'user_chat_id': user.id,
        'user_name': user.first_name or "ተጠቃሚ",
        'req_type': 'SELL',
        'main_category': context.user_data.get('main_category', ''),
        'sub_category': '',
        'action_type': context.user_data.get('action_type', ''),
        'property_type': context.user_data.get('property_type', ''),
        'description': full_desc
    }
    
    req_id = ListingRepository.create(listing_data)
    
    if req_id:
        await safe_send_message(
            update, context,
            "✅ **የማስታወቂያ ጥያቄዎ በስኬት ተመዝግቧል!**",
            reply_markup=MAIN_MARKUP
        )
    else:
        await safe_send_message(
            update, context,
            "❌ ማስታወቂያውን መመዝገብ አልተቻለም። እባክዎ እንደገና ይሞክሩ።",
            reply_markup=MAIN_MARKUP
        )
    
    return ConversationHandler.END

# ==============================================================================
# 15. BROKER REGISTRATION HANDLERS
# ==============================================================================
async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not rate_limiter.is_allowed(update.effective_user.id):
        await safe_send_message(update, context, "⏳ እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።")
        return ConversationHandler.END
    
    context.user_data.clear()
    
    keyboard = [
        [InlineKeyboardButton("👨💼 ደላላ", callback_data="role_broker")],
        [InlineKeyboardButton("🚢 አስመጪ / አቅራቢ", callback_data="role_importer")],
        [InlineKeyboardButton("👤 ባለቤት / አቅራቢ", callback_data="role_owner")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await safe_send_message(
        update, context,
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
    
    context.user_data['broker_name'] = sanitize_input(update.message.text)
    await safe_send_message(update, context, "2️⃣ የስልክ ቁጥርዎን ያስገቡ፦")
    return BROKER_PHONE

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        reply_markup=build_indexed_keyboard(SUB_CITIES, "broker_sc_", columns=2)
    )
    return BROKER_SUBCITY

async def broker_reg_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    idx = int(query.data.replace("broker_sc_", ""))
    sub_city = SUB_CITIES[idx]
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
    
    if not update.message or not update.message.photo:
        await safe_send_message(
            update, context,
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
    
    await safe_send_message(
        update, context,
        f"📝 **የምዝገባ መረጃዎ፦**\n\n"
        f"👤 ስም: {name}\n"
        f"🎭 ሚና: {role}\n"
        f"📞 ስልክ: {phone}\n"
        f"📍 ክፍለ ከተማ: {sub_city}\n"
        f"🆔 Telegram ID: `{user.id}`\n\n"
        f"⏳ እባክዎ ይጠብቁ፣ እያስመዘገብን ነው...",
        parse_mode="Markdown"
    )
    
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
            reply_markup=MAIN_MARKUP
        )
        
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
                    InlineKeyboardButton("❌ ሰርዝ", callback_data=f"admin_reje_{user.id}")
                ],
                [InlineKeyboardButton("👤 ዝርዝር", callback_data=f"admin_view_{user.id}")]
            ])
            try:
                await context.bot.send_photo(
                    chat_id=Config.ADMIN_CHAT_ID_INT,
                    photo=photo_id,
                    caption=admin_msg,
                    parse_mode="Markdown",
                    reply_markup=admin_kbd
                )
                logger.info(f"Admin notification sent for broker {user.id}")
            except Exception as e:
                logger.error(f"Failed to send admin approval: {e}")
                await safe_send_message(
                    update, context,
                    "⚠️ ለአድሚን መላክ አልተቻለም፣ ነገር ግን ምዝገባዎ ተመዝግቧል።"
                )
    else:
        await safe_send_message(
            update, context,
            "❌ **ምዝገባውን ማጠናቀቅ አልተቻለም!**\n\n"
            "💡 እባክዎ የሚከተሉትን ያረጋግጡ፦\n"
            "• መረጃዎቹ ሙሉ መሆናቸውን\n"
            "• የበይነመረብ ግንኙነትዎን\n\n"
            "🔄 እንደገና ለመሞከር '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይጫኑ።",
            reply_markup=MAIN_MARKUP
        )
    
    return ConversationHandler.END

# ==============================================================================
# 16. BROKER RESPONSE HANDLERS
# ==============================================================================
async def broker_have_item_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        logger.error(f"Invalid callback data: {query.data}")
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
        reply_markup=HOME_ONLY_KEYBOARD
    )
    return BROKER_OFFER_TEXT

async def broker_offer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data['offer_text'] = sanitize_input(update.message.text)
    await safe_send_message(
        update, context,
        "📸 **የንብረቱን ፎቶ ይላኩ፦**\n(ፎቶ ከሌልዎት 'ፎቶ የለውም' ብለው ይጻፉ)"
    )
    return BROKER_OFFER_PHOTO

async def broker_offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    buyer_id = int(context.user_data.get('target_buyer_id', 0))
    req_id = context.user_data.get('target_req_id')
    offer_text = context.user_data.get('offer_text', '')
    broker_name = update.effective_user.first_name or "አቅራቢ"
    
    if not buyer_id or not req_id:
        await safe_send_message(update, context, "❌ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።")
        return ConversationHandler.END
    
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
            reply_markup=MAIN_MARKUP
        )
    except Exception as e:
        logger.error(f"Failed to send offer to buyer: {e}")
        await safe_send_message(
            update, context,
            "❌ መረጃውን ለፈላጊው መላክ አልተቻለም።",
            reply_markup=MAIN_MARKUP
        )
    
    return ConversationHandler.END

# ==============================================================================
# 17. VIEW REQUESTS
# ==============================================================================
async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    broker = BrokerRepository.get_by_chat_id(user_id)
    
    if not broker:
        await safe_send_message(
            update, context,
            "⛔ ይህን ገጽ ማየት የሚችሉት የተመዘገቡ አቅራቢዎች/ደላሎች ብቻ ናቸው!\n\n"
            "📝 እባክዎን መጀመሪያ '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይጫኑ።",
            reply_markup=MAIN_MARKUP
        )
        return
    
    if broker.get('status') != 'approved':
        await safe_send_message(
            update, context,
            "⏳ **ምዝገባዎ ገና በአድሚን አልጸደቀም!**\n\n"
            "⏳ ምዝገባዎ በአድሚን ሲረጋገጥ ማስታወቂያ ይደርስዎታል።\n"
            "📞 ለተጨማሪ መረጃ ድጋፍን ይጠቀሙ።",
            reply_markup=MAIN_MARKUP
        )
        return
    
    context.user_data['view_page'] = 0
    await show_requests_page(update, context)

async def show_requests_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        
        text = f"📋 **የፈላጊዎች ዝርዝር** (ገጽ {page+1}/{total_pages})\n\n"
        
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
            nav_buttons.append(InlineKeyboardButton("⬅️ ቀዳሚ", callback_data=f"page_{page-1}"))
        if offset + Config.ITEMS_PER_PAGE < total:
            nav_buttons.append(InlineKeyboardButton("➡️ ቀጣይ", callback_data=f"page_{page+1}"))
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
        logger.error(f"Error showing requests page: {e}")

# ==============================================================================
# 18. ADMIN HANDLERS
# ==============================================================================
async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                    text="🎉 **እንኳን ደስ አለዎት!** የምዝገባ ጥያቄዎ በአድሚን ጸድቋል።\n\n"
                         "📋 አሁን '📋 የፈላጊዎች ዝርዝር' በመጠቀም ጥያቄዎችን ማየት ይችላሉ።",
                    reply_markup=MAIN_MARKUP
                )
                logger.info(f"Broker approved: {target_id}")
            except Exception as e:
                logger.error(f"Could not notify approved user: {e}")
    
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
                    text="❌ የምዝገባ ጥያቄዎ ተሰርዟል።\n\n"
                         "ለተጨማሪ መረጃ እባክዎን አድሚንን ያግኙ።",
                    reply_markup=MAIN_MARKUP
                )
                logger.info(f"Broker rejected: {target_id}")
            except Exception as e:
                logger.error(f"Could not notify rejected user: {e}")
    
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
# 19. HELP COMMAND
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

🏠 **ዋና ገጽ:**
• ቀደም ሲል የነበረውን መልእክት ያጽዳል
• አዲስ ሜኑ ያመጣል
"""
    await safe_send_message(update, context, help_text, parse_mode="Markdown")

# ==============================================================================
# 20. MAIN APPLICATION
# ==============================================================================
def main():
    if not acquire_lock():
        print("❌ Another instance is running!")
        print(f"   Lock file: {LOCK_FILE}")
        print("   To force start: rm -f {LOCK_FILE}")
        sys.exit(1)
    
    try:
        init_db()
        init_connection_pool()
        
        threading.Thread(target=run_flask, daemon=True).start()
        logger.info(f"Flask server started on port {Config.PORT}")
        
        app = Application.builder().token(Config.BOT_TOKEN).build()
        
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
                SELLER_SUB: [CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_"), cancel_message_handler],
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
        
        logger.info("🚀 Adika Marketplace Bot started successfully!")
        
        print(f"✅ Bot started (PID: {os.getpid()})")
        
        app.run_polling()
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"❌ Fatal error: {e}")
        release_lock()
        sys.exit(1)
    finally:
        release_lock()

if __name__ == "__main__":
    main()
