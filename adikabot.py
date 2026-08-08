import asyncio
import logging
import os
import threading
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from contextlib import contextmanager
from collections import defaultdict
import time

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
# 1. LOGGING
# ==============================================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logger.info(f"✅ Admin chat ID set to: {Config.ADMIN_CHAT_ID_INT}")

# ==============================================================================
# 2. DATABASE CONNECTION POOL
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
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Transaction failed: {e}")
        raise

# Helper to fetch single ID or value cross-platform (RealDictCursor vs SQLite Row)
def _extract_first_val(row):
    if not row:
        return None
    if isinstance(row, dict):
        return list(row.values())[0]
    return row[0]

# ==============================================================================
# 3. CACHE MANAGEMENT
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
# 4. RATE LIMITER
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
# 5. INPUT VALIDATION
# ==============================================================================
def validate_phone(phone: str) -> bool:
    phone = phone.replace(' ', '').replace('-', '')
    pattern = r'^(09|07|01)\d{8}$|^\+251(9|7|1)\d{8}$'
    return bool(re.match(pattern, phone))

def validate_price(price: str) -> bool:
    price = price.replace(',', '').replace(' ', '')
    return price.isdigit()

def validate_budget(budget: str) -> bool:
    budget = budget.replace(',', '').replace(' ', '')
    return budget.isdigit()

def sanitize_input(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'[<>"\'%;]', '', text.strip())

# ==============================================================================
# 6. CONSTANTS & KEYBOARDS
# ==============================================================================
SUB_CITIES = [
    "ቦሌ", "የካ", "አራዳ", "ልደታ",
    "ቂርቆስ", "አዲስ ከተማ", "ንፋስ ስልክ ላፍቶ",
    "ኮልፌ ቀራኒዮ", "አቃቂ ቃሊቲ", "ጉሌሌ", "ለሚ ኩራ",
]

CAR_SUB_CATEGORIES = ["🚗 ሴዳን", "🚙 SUV", "🚐 ሚኒባስ", "🚛 መኪና/ትራክ"]
HOUSE_TYPES = ["🏡 ቪላ", "🏢 አፓርታማ", "🏢 ኮንዶሚኒየም", "🏢 ሪል እስቴት", "🏞️ መሬት/ቦታ"]
COMMERCIAL_TYPES = ["🏢 ቢሮ", "🏪 ሱቅ", "🏭 ፋብሪካ/መጋዘን", "🅿️ ሌላ"]

MAIN_CATEGORIES = [("car", "🚗 መኪና"), ("house", "🏠 ቤት / ቦታ"), ("commercial", "🏢 የሥራ ቦታ / ንግድ")]

MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ/ደላላ መመዝገብ", "📋 የፈላጊዎች ዝርዝር"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"],
]
HOME_ONLY_KEYBOARD = ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
MAIN_MARKUP = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)

# ==============================================================================
# 7. DATABASE OPERATIONS
# ==============================================================================
class ListingRepository:
    @staticmethod
    def create(listing_data: Dict) -> Optional[int]:
        try:
            with get_db_connection() as conn:
                with transaction(conn):
                    cursor = conn.cursor()
                    
                    if Config.DATABASE_URL:
                        query = """
                            INSERT INTO listings 
                            (user_chat_id, user_name, req_type, main_category, sub_type,
                             action_type, description, price, phone, photo_file_id, budget, telegram_contact)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        """
                        cursor.execute(query, (
                            listing_data.get('user_chat_id'),
                            listing_data.get('user_name', ''),
                            listing_data.get('req_type', 'BUY'),
                            listing_data.get('main_category', ''),
                            listing_data.get('sub_type', 'N/A'),
                            listing_data.get('action_type', ''),
                            listing_data.get('description', ''),
                            listing_data.get('price'),
                            listing_data.get('phone', ''),
                            listing_data.get('photo_file_id'),
                            listing_data.get('budget'),
                            listing_data.get('telegram_contact')
                        ))
                        result = cursor.fetchone()
                        return _extract_first_val(result)
                    else:
                        query = """
                            INSERT INTO listings 
                            (user_chat_id, user_name, req_type, main_category, sub_type,
                             action_type, description, price, phone, photo_file_id, budget, telegram_contact)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """
                        cursor.execute(query, (
                            listing_data.get('user_chat_id'),
                            listing_data.get('user_name', ''),
                            listing_data.get('req_type', 'BUY'),
                            listing_data.get('main_category', ''),
                            listing_data.get('sub_type', 'N/A'),
                            listing_data.get('action_type', ''),
                            listing_data.get('description', ''),
                            listing_data.get('price'),
                            listing_data.get('phone', ''),
                            listing_data.get('photo_file_id'),
                            listing_data.get('budget'),
                            listing_data.get('telegram_contact')
                        ))
                        return cursor.lastrowid
        except Exception as e:
            logger.error(f"Failed to create listing: {e}")
            return None
    
    @staticmethod
    def get_pending(limit: int = 10, offset: int = 0) -> List[Dict]:
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
        cache_key = "listings_count_pending"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM listings WHERE status = 'pending'")
            count = _extract_first_val(cursor.fetchone()) or 0
            cache.set(cache_key, count)
            return count
    
    @staticmethod
    def update_status(listing_id: int, status: str) -> bool:
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
                    cache.invalidate()
                    return True
        except Exception as e:
            logger.error(f"Failed to update listing status: {e}")
            return False

class BrokerRepository:
    @staticmethod
    def create_or_update(broker_data: Dict) -> Optional[int]:
        with get_db_connection() as conn:
            with transaction(conn):
                cursor = conn.cursor()
                
                if Config.DATABASE_URL:
                    cursor.execute("SELECT id FROM brokers WHERE chat_id = %s", (broker_data.get('chat_id'),))
                else:
                    cursor.execute("SELECT id FROM brokers WHERE chat_id = ?", (broker_data.get('chat_id'),))
                
                existing = cursor.fetchone()
                existing_id = _extract_first_val(existing)
                
                if existing_id:
                    if Config.DATABASE_URL:
                        query = """
                            UPDATE brokers 
                            SET full_name = %s, phone = %s, telegram_id = %s, role_type = %s,
                                national_id_photo = %s, sub_city = %s, status = 'pending'
                            WHERE chat_id = %s
                            RETURNING id
                        """
                        cursor.execute(query, (
                            broker_data.get('full_name'),
                            broker_data.get('phone'),
                            broker_data.get('telegram_id'),
                            broker_data.get('role_type'),
                            broker_data.get('national_id_photo'),
                            broker_data.get('sub_city'),
                            broker_data.get('chat_id')
                        ))
                        broker_id = _extract_first_val(cursor.fetchone())
                    else:
                        query = """
                            UPDATE brokers 
                            SET full_name = ?, phone = ?, telegram_id = ?, role_type = ?,
                                national_id_photo = ?, sub_city = ?, status = 'pending'
                            WHERE chat_id = ?
                        """
                        cursor.execute(query, (
                            broker_data.get('full_name'),
                            broker_data.get('phone'),
                            broker_data.get('telegram_id'),
                            broker_data.get('role_type'),
                            broker_data.get('national_id_photo'),
                            broker_data.get('sub_city'),
                            broker_data.get('chat_id')
                        ))
                        broker_id = existing_id
                else:
                    if Config.DATABASE_URL:
                        query = """
                            INSERT INTO brokers 
                            (chat_id, full_name, phone, telegram_id, role_type, national_id_photo, sub_city, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
                            RETURNING id
                        """
                        cursor.execute(query, (
                            broker_data.get('chat_id'),
                            broker_data.get('full_name'),
                            broker_data.get('phone'),
                            broker_data.get('telegram_id'),
                            broker_data.get('role_type'),
                            broker_data.get('national_id_photo'),
                            broker_data.get('sub_city')
                        ))
                        broker_id = _extract_first_val(cursor.fetchone())
                    else:
                        query = """
                            INSERT INTO brokers 
                            (chat_id, full_name, phone, telegram_id, role_type, national_id_photo, sub_city, status)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                        """
                        cursor.execute(query, (
                            broker_data.get('chat_id'),
                            broker_data.get('full_name'),
                            broker_data.get('phone'),
                            broker_data.get('telegram_id'),
                            broker_data.get('role_type'),
                            broker_data.get('national_id_photo'),
                            broker_data.get('sub_city')
                        ))
                        broker_id = cursor.lastrowid
                
                cache.invalidate()
                return broker_id
    
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
            logger.info(f"📊 Found {len(result)} approved brokers")
            cache.set(cache_key, result)
            return result
    
    @staticmethod
    def get_all_pending() -> List[Dict]:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM brokers WHERE status = 'pending'")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    def get_by_chat_id(chat_id: int) -> Optional[Dict]:
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
                    cache.invalidate()
                    return True
        except Exception as e:
            logger.error(f"Failed to update broker status: {e}")
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
        'version': '3.0',
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
    
    response_code = 200 if status['status'] == 'healthy' else 503
    return jsonify(status), response_code

def run_flask():
    web_app.run(host="0.0.0.0", port=Config.PORT)

# ==============================================================================
# 9. DATABASE INITIALIZATION
# ==============================================================================
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
                        sub_type TEXT,
                        action_type TEXT,
                        description TEXT NOT NULL,
                        price TEXT,
                        phone TEXT,
                        photo_file_id TEXT,
                        budget TEXT,
                        telegram_contact TEXT,
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
                        telegram_id TEXT,
                        role_type TEXT NOT NULL,
                        national_id_photo TEXT,
                        sub_city TEXT NOT NULL,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS budget TEXT;")
                cursor.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS telegram_contact TEXT;")
                cursor.execute("ALTER TABLE brokers ADD COLUMN IF NOT EXISTS telegram_id TEXT;")
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
                        budget TEXT,
                        telegram_contact TEXT,
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
                        telegram_id TEXT,
                        role_type TEXT NOT NULL,
                        national_id_photo TEXT,
                        sub_city TEXT NOT NULL,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                cursor.execute("PRAGMA table_info(listings)")
                columns = [row[1] for row in cursor.fetchall()]
                if 'budget' not in columns:
                    cursor.execute("ALTER TABLE listings ADD COLUMN budget TEXT")
                if 'telegram_contact' not in columns:
                    cursor.execute("ALTER TABLE listings ADD COLUMN telegram_contact TEXT")
                
                cursor.execute("PRAGMA table_info(brokers)")
                b_columns = [row[1] for row in cursor.fetchall()]
                if 'telegram_id' not in b_columns:
                    cursor.execute("ALTER TABLE brokers ADD COLUMN telegram_id TEXT")
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at DESC)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_brokers_status ON brokers(status)")
            
            conn.commit()
            logger.info("✅ Database initialized successfully")
            
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise

# ==============================================================================
# 10. HELPER FUNCTIONS
# ==============================================================================
def build_indexed_keyboard(options: List[str], prefix: str, columns: int = 1, extra_home: bool = True):
    buttons = [InlineKeyboardButton(opt, callback_data=f"{prefix}{i}") for i, opt in enumerate(options)]
    keyboard = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    if extra_home:
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    return InlineKeyboardMarkup(keyboard)

def format_listing_for_broker(listing: Dict) -> str:
    listing_id = listing.get('id', '')
    main_cat = listing.get('main_category', '')
    sub_type = listing.get('sub_type', 'N/A')
    action_type = listing.get('action_type', '')
    description = listing.get('description', '')
    budget = listing.get('budget', 'N/A')
    phone = listing.get('phone', 'N/A')
    telegram = listing.get('telegram_contact', '')
    created_at = str(listing.get('created_at', ''))
    
    cat_emoji = {'car': '🚗', 'house': '🏠', 'commercial': '🏢'}
    emoji = cat_emoji.get(main_cat, '📌')
    
    contact_info = f"📞 ስልክ: {phone}"
    if telegram:
        contact_info += f"\n🆔 ቴሌግራም: {telegram}"
    
    return f"""
{emoji} **#{listing_id} - {main_cat.upper()}**

📋 **ዝርዝር መረጃ**
┌─────────────────────
│ 📌 ምድብ: {main_cat}
│ 🔹 ንኡስ: {sub_type}
│ 🔹 አይነት: {action_type}
│ 💰 በጀት: {budget} ብር
│ {contact_info}
│ 📅 ቀን: {created_at[:10] if created_at else 'N/A'}
└─────────────────────

📝 **መግለጫ:**
{description}
"""

def format_welcome_message() -> str:
    return """
👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏢 **የሀገሪቱ ታላቁ የመኪና፣ የቤት እና የንብረት ገበያ ማዕከል**

💡 **አጭር መመሪያ:**
• 🔍 ለመግዛት/መከራየት ፈልገዋል?
• 📢 ለመሸጥ/ማከራየት ፈልገዋል?
• 📝 እንደ ደላላ/አቅራቢ መመዝገብ ይፈልጋሉ?

📌 **እባክዎን ከታች ካሉት አማራጮች ይምረጡ!**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

async def notify_brokers(context: ContextTypes.DEFAULT_TYPE, message_text: str, req_id: int, buyer_id: int):
    approved_brokers = BrokerRepository.get_approved()
    logger.info(f"📢 Notifying {len(approved_brokers)} approved brokers about request #{req_id}")
    
    if not approved_brokers:
        logger.warning("⚠️ No approved brokers found to notify")
        return
    
    success_count = 0
    for b_id in approved_brokers:
        try:
            kbd = [[InlineKeyboardButton(f"✅ አለኝ - #{req_id}", callback_data=f"have_item_{req_id}_{buyer_id}")]]
            await context.bot.send_message(
                chat_id=b_id,
                text=message_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kbd),
            )
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"❌ Failed to send notification to broker {b_id}: {e}")
    
    logger.info(f"✅ Successfully notified {success_count}/{len(approved_brokers)} brokers")

async def safe_send_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, **kwargs):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if update.callback_query:
                await update.callback_query.message.reply_text(text, **kwargs)
            else:
                await update.message.reply_text(text, **kwargs)
            return True
        except Exception as e:
            logger.warning(f"Failed to send message (attempt {attempt + 1}): {e}")
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
    BUYER_MAIN, BUYER_SUB, BUYER_ACTION, BUYER_DETAILS, BUYER_BUDGET, BUYER_PHONE,
    SELLER_MAIN, SELLER_ACTION, SELLER_SUBTYPE, SELLER_DETAILS, SELLER_PRICE, SELLER_PHONE, SELLER_PHOTO,
    BROKER_ROLE, BROKER_NAME, BROKER_PHONE, BROKER_TELEGRAM_ID, BROKER_SUBCITY, BROKER_NID_PHOTO,
    BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO,
) = range(21)

# ==============================================================================
# 12. HANDLERS - START & HOME
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not rate_limiter.is_allowed(user_id):
        await update.message.reply_text("⏳ እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።")
        return ConversationHandler.END
    
    context.user_data.clear()
    welcome_text = format_welcome_message()
    await safe_send_message(update, context, welcome_text, parse_mode="Markdown", reply_markup=MAIN_MARKUP)
    return ConversationHandler.END

async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = """
🏠 **ወደ ዋና ገጽ ተመልሰዋል!**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 አሁን አዲስ ነገር መጀመር ይችላሉ።
📌 እባክዎን ከታች ካሉት አማራጮች ይምረጡ!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
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
    if not rate_limiter.is_allowed(update.effective_user.id):
        await safe_send_message(update, context, "⏳ እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።")
        return ConversationHandler.END
    
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    
    keyboard = [[InlineKeyboardButton(label, callback_data=f"flow_buy_cat_{code}")] for code, label in MAIN_CATEGORIES]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await safe_send_message(
        update, context,
        "🔍 **የሚፈልጉትን ምድብ ይምረጡ**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📌 እባክዎን የሚፈልጉትን የንብረት ዓይነት ይምረጡ:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
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
        options = CAR_SUB_CATEGORIES
    elif cat == "house":
        options = HOUSE_TYPES
    else:
        options = COMMERCIAL_TYPES
    
    keyboard = [[InlineKeyboardButton(opt, callback_data=f"flow_buy_sub_{i}")] for i, opt in enumerate(options)]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    cat_name = {"car": "መኪና", "house": "ቤት/ቦታ", "commercial": "የሥራ ቦታ"}.get(cat, "")
    await query.edit_message_text(
        f"📌 **የ{cat_name} ንኡስ ምድብ ይምረጡ**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔹 እባክዎን የሚፈልጉትን ዝርዝር አይነት ይምረጡ:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return BUYER_SUB

async def buyer_sub_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    idx = int(query.data.replace("flow_buy_sub_", ""))
    cat = context.user_data.get('main_category', '')
    
    if cat == "car":
        options = CAR_SUB_CATEGORIES
    elif cat == "house":
        options = HOUSE_TYPES
    else:
        options = COMMERCIAL_TYPES
    
    sub = options[idx] if idx < len(options) else "N/A"
    context.user_data['sub_type'] = sub
    
    keyboard = [
        [InlineKeyboardButton("🛍️ መግዛት", callback_data="flow_buy_action_buy")],
        [InlineKeyboardButton("🔑 መከራየት", callback_data="flow_buy_action_rent")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await query.edit_message_text(
        f"✅ **{sub}**\n\n"
        "❓ **የሚፈልጉትን የድርጊት አይነት ይምረጡ**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔹 መግዛት ነው ወይስ መከራየት?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BUYER_ACTION

async def buyer_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    action = "መግዛት" if "buy" in query.data else "መከራየት"
    context.user_data['action_type'] = action
    
    cat = context.user_data.get('main_category', '')
    example = ""
    if cat == "car":
        example = "💡 *ምሳሌ:* ቶዮታ ቪትዝ 2020፣ 60,000 ኪሜ የሄደ፣ ጥሩ ሁኔታ ላይ ያለ"
    elif cat == "house":
        example = "💡 *ምሳሌ:* ቦሌ አካባቢ 3 መኝታ ቤት፣ 150 ካሬ፣ የተጠናቀቀ"
    else:
        example = "💡 *ምሳሌ:* ሜክሲኮ አካባቢ የሽያጭ ቢሮ፣ 50 ካሬ"
    
    await query.edit_message_text(
        f"📝 **የንብረት ዝርዝር መግለጫ**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✍️ እባክዎን የሚፈልጉትን ንብረት በዝርዝር ይግለጹ:\n\n"
        f"{example}",
        parse_mode="Markdown"
    )
    return BUYER_DETAILS

async def buyer_details_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if len(text.strip()) < 5:
        await safe_send_message(
            update, context,
            "⚠️ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "እባክዎን ቢያንስ 5 ፊደላት ያለው ዝርዝር መግለጫ ያስገቡ。"
        )
        return BUYER_DETAILS
    
    context.user_data['description'] = sanitize_input(text)
    await safe_send_message(
        update, context,
        "💰 **በጀት (Budget)**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 እባክዎን ያለዎትን ከፍተኛ በጀት ያስገቡ:\n\n"
        "💡 *ምሳሌ:* 5,000,000 ብር\n"
        "📌 ቁጥር ብቻ ያስገቡ (ኮማ መጠቀም ይችላሉ)"
    )
    return BUYER_BUDGET

async def buyer_budget_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_budget(text):
        await safe_send_message(
            update, context,
            "⚠️ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "እባክዎን ትክክለኛ ቁጥር ያስገቡ።\n"
            "💡 ምሳሌ: 5,000,000"
        )
        return BUYER_BUDGET
    
    context.user_data['budget'] = text.replace(',', '').replace(' ', '')
    await safe_send_message(
        update, context,
        "📱 **የስልክ ቁጥር ወይም ቴሌግራም መለያ**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📞 እባክዎን እርስዎን የሚያገኙበትን መንገድ ይምረጡ:\n\n"
        "1️⃣ ስልክ ቁጥር ያስገቡ (ምሳሌ: 0911223344)\n"
        "2️⃣ ወይም ቴሌግራም መለያ ያስገቡ (ምሳሌ: @username)\n\n"
        "💡 ሁለቱንም ማስገባት ይችላሉ",
        reply_markup=HOME_ONLY_KEYBOARD
    )
    return BUYER_PHONE

async def buyer_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    is_phone = validate_phone(text)
    is_telegram = text.startswith('@') and len(text) > 1
    
    if not is_phone and not is_telegram:
        await safe_send_message(
            update, context,
            "⚠️ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "እባክዎን ትክክለኛ የስልክ ቁጥር ወይም ቴሌግራም መለያ ያስገቡ:\n"
            "📞 ስልክ: 0911223344 ወይም +251911223344\n"
            "🆔 ቴሌግራም: @username"
        )
        return BUYER_PHONE
    
    phone = text if is_phone else ""
    telegram = text if is_telegram else ""
    context.user_data['phone'] = phone
    context.user_data['telegram_contact'] = telegram
    
    await safe_send_message(
        update, context,
        "✅ **መረጃዎ ተቀብለናል!**\n\n"
        "⏳ እባክዎ ይጠብቁ፣ ጥያቄዎን እያስኬድን ነው...",
        reply_markup=HOME_ONLY_KEYBOARD
    )
    
    user = update.effective_user
    description = context.user_data.get('description', '')
    budget = context.user_data.get('budget', '')
    
    contact_info = ""
    if phone:
        contact_info += f"📞 ስልክ: {phone}\n"
    if telegram:
        contact_info += f"🆔 ቴሌግራም: {telegram}\n"
    
    listing_data = {
        'user_chat_id': user.id,
        'user_name': user.full_name or user.username or "ተጠቃሚ",
        'req_type': 'BUY',
        'main_category': context.user_data.get('main_category', ''),
        'sub_type': context.user_data.get('sub_type', 'N/A'),
        'action_type': context.user_data.get('action_type', ''),
        'description': description,
        'price': None,
        'phone': phone,
        'photo_file_id': None,
        'budget': budget,
        'telegram_contact': telegram
    }
    
    listing_id = ListingRepository.create(listing_data)
    
    if listing_id:
        notification_text = f"""
📢 **አዲስ የፍላጎት ጥያቄ (#REQ-{listing_id})**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 **ምድብ:** {listing_data['main_category']}
🔹 **ንኡስ ምድብ:** {listing_data['sub_type']}
🔹 **ዓይነት:** {listing_data['action_type']}
💰 **በጀት:** {budget} ብር
{contact_info}
👤 **ተጠቃሚ:** {user.full_name or user.username}

📝 **መግለጫ:**
{description}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ ይህን ጥያቄ መመለስ ከቻሉ 'አለኝ' የሚለውን ይጫኑ!
"""
        await notify_brokers(context, notification_text, listing_id, user.id)
        
        await safe_send_message(
            update, context,
            f"""
✅ **ጥያቄዎ በስኬት ተመዝግቧል!** 🎉

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 **የጥያቄ መረጃ:**
• 📌 ቁጥር: #{listing_id}
• 📅 ቀን: {datetime.now().strftime('%Y-%m-%d %H:%M')}
• 📊 ሁኔታ: በመጠበቅ ላይ

📌 ጥያቄዎ ለተረጋገጡ ደላሎች ተልኳል።
📞 ንብረቱ ያላቸው አቅራቢዎች በቅርቡ ያነጋግሩዎታል።
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
            reply_markup=MAIN_MARKUP
        )
    else:
        await safe_send_message(
            update, context,
            "❌ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "ጥያቄውን መመዝገብ አልተቻለም።\n"
            "💡 እባክዎ ቆይተው እንደገና ይሞክሩ።",
            reply_markup=MAIN_MARKUP
        )
    
    context.user_data.clear()
    return ConversationHandler.END

# ==============================================================================
# 14. HANDLERS - SELLER FLOW
# ==============================================================================
async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not rate_limiter.is_allowed(update.effective_user.id):
        await safe_send_message(update, context, "⏳ እባክዎ ትንሽ ቆይተው እንደገና ይሞክሩ።")
        return ConversationHandler.END
    
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    
    keyboard = [[InlineKeyboardButton(label, callback_data=f"flow_sell_cat_{code}")] for code, label in MAIN_CATEGORIES]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await safe_send_message(
        update, context,
        "📢 **አዲስ የሽያጭ/ኪራይ ማስታወቂያ**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📌 እባክዎን የሚሸጡትን ወይም የሚያከራዩትን ምድብ ይምረጡ:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
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
        options = CAR_SUB_CATEGORIES
    elif cat == "house":
        options = HOUSE_TYPES
    else:
        options = COMMERCIAL_TYPES
    
    keyboard = [[InlineKeyboardButton(opt, callback_data=f"flow_sell_sub_{i}")] for i, opt in enumerate(options)]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    cat_name = {"car": "መኪና", "house": "ቤት/ቦታ", "commercial": "የሥራ ቦታ"}.get(cat, "")
    await query.edit_message_text(
        f"📌 **የ{cat_name} ንኡስ ምድብ ይምረጡ**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔹 የሚሸጡትን ወይም የሚያከራዩትን ዝርዝር አይነት ይምረጡ:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return SELLER_ACTION

async def seller_sub_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    idx = int(query.data.replace("flow_sell_sub_", ""))
    cat = context.user_data.get('main_category', '')
    
    if cat == "car":
        options = CAR_SUB_CATEGORIES
    elif cat == "house":
        options = HOUSE_TYPES
    else:
        options = COMMERCIAL_TYPES
    
    sub = options[idx] if idx < len(options) else "N/A"
    context.user_data['sub_type'] = sub
    
    keyboard = [
        [InlineKeyboardButton("🛍️ መሸጥ", callback_data="flow_sell_action_sell")],
        [InlineKeyboardButton("🔑 ማከራየት", callback_data="flow_sell_action_rent")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await query.edit_message_text(
        f"✅ **{sub}**\n\n"
        "❓ **የድርጊት አይነት ይምረጡ**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔹 መሸጥ ነው ወይስ ማከራየት?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_SUBTYPE

async def seller_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    action = "መሸጥ" if "sell" in query.data else "ማከራየት"
    context.user_data['action_type'] = action
    
    cat = context.user_data.get('main_category', '')
    example = ""
    if cat == "car":
        example = "💡 *ምሳሌ:* ቶዮታ ቪትዝ 2020፣ 60,000 ኪሜ የሄደ፣ ጥሩ ሁኔታ ላይ ያለ"
    elif cat == "house":
        example = "💡 *ምሳሌ:* ቦሌ አካባቢ 3 መኝታ ቤት፣ 150 ካሬ፣ የተጠናቀቀ"
    else:
        example = "💡 *ምሳሌ:* ሜክሲኮ አካባቢ የሽያጭ ቢሮ፣ 50 ካሬ"
    
    await query.edit_message_text(
        f"📝 **የንብረት ዝርዝር መግለጫ**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✍️ እባክዎን የሚሸጡትን ወይም የሚያከራዩትን ንብረት በዝርዝር ይግለጹ:\n\n"
        f"{example}",
        parse_mode="Markdown"
    )
    return SELLER_DETAILS

async def seller_details_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if len(text.strip()) < 5:
        await safe_send_message(
            update, context,
            "⚠️ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "እባክዎን ቢያንስ 5 ፊደላት ያለው መግለጫ ያስገቡ。"
        )
        return SELLER_DETAILS
    
    context.user_data['description'] = sanitize_input(text)
    await safe_send_message(
        update, context,
        "💰 **ዋጋ**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 እባክዎን የሚሸጡበትን/ሚያከራዩበትን ዋጋ ያስገቡ:\n\n"
        "💡 *ምሳሌ:* 5,000,000 ብር\n"
        "📌 ቁጥር ብቻ ያስገቡ (ኮማ መጠቀም ይችላሉ)"
    )
    return SELLER_PRICE

async def seller_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_price(text):
        await safe_send_message(
            update, context,
            "⚠️ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "እባክዎን ትክክለኛ ዋጋ ያስገቡ (ቁጥር ብቻ)።\n"
            "💡 ምሳሌ: 5,000,000"
        )
        return SELLER_PRICE
    
    context.user_data['price'] = text.replace(',', '').replace(' ', '')
    await safe_send_message(
        update, context,
        "📱 **የስልክ ቁጥር ወይም ቴሌግራም መለያ**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📞 እባክዎን እርስዎን የሚያገኙበትን መንገድ ይምረጡ:\n\n"
        "1️⃣ ስልክ ቁጥር ያስገቡ (ምሳሌ: 0911223344)\n"
        "2️⃣ ወይም ቴሌግራም መለያ ያስገቡ (ምሳሌ: @username)\n\n"
        "💡 ሁለቱንም ማስገባት ይችላሉ"
    )
    return SELLER_PHONE

async def seller_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    is_phone = validate_phone(text)
    is_telegram = text.startswith('@') and len(text) > 1
    
    if not is_phone and not is_telegram:
        await safe_send_message(
            update, context,
            "⚠️ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "እባክዎን ትክክለኛ የስልክ ቁጥር ወይም ቴሌግራም መለያ ያስገቡ:\n"
            "📞 ስልክ: 0911223344 ወይም +251911223344\n"
            "🆔 ቴሌግራም: @username"
        )
        return SELLER_PHONE
    
    context.user_data['phone'] = text if is_phone else ""
    context.user_data['telegram_contact'] = text if is_telegram else ""
    
    await safe_send_message(
        update, context,
        "📸 **የንብረቱ ፎቶ**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🖼️ እባክዎን የንብረቱን ፎቶ ይላኩ:\n\n"
        "💡 ፎቶ ከሌለዎት 'ፎቶ የለውም' ብለው ይጻፉ"
    )
    return SELLER_PHOTO

async def seller_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text if update.message and update.message.text else None
    
    if text and text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    photo_id = None
    if update.message and update.message.photo:
        photo_id = update.message.photo[-1].file_id
    elif text and text.lower() == "ፎቶ የለውም":
        photo_id = None
    else:
        await safe_send_message(
            update, context,
            "⚠️ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "እባክዎን ፎቶ ይላኩ ወይም 'ፎቶ የለውም' ብለው ይጻፉ"
        )
        return SELLER_PHOTO
    
    user = update.effective_user
    description = context.user_data.get('description', '')
    price = context.user_data.get('price', '')
    phone = context.user_data.get('phone', '')
    telegram = context.user_data.get('telegram_contact', '')
    
    contact_info = ""
    if phone:
        contact_info += f"📞 ስልክ: {phone}\n"
    if telegram:
        contact_info += f"🆔 ቴሌግራም: {telegram}\n"
    
    full_description = f"{description}\n\n💰 ዋጋ: {price} ብር\n{contact_info}"
    
    listing_data = {
        'user_chat_id': user.id,
        'user_name': user.full_name or user.username or "ተጠቃሚ",
        'req_type': 'SELL',
        'main_category': context.user_data.get('main_category', ''),
        'sub_type': context.user_data.get('sub_type', 'N/A'),
        'action_type': context.user_data.get('action_type', ''),
        'description': full_description,
        'price': price,
        'phone': phone,
        'photo_file_id': photo_id,
        'budget': None,
        'telegram_contact': telegram
    }
    
    listing_id = ListingRepository.create(listing_data)
    
    if listing_id:
        await safe_send_message(
            update, context,
            f"""
✅ **ማስታወቂያዎ በስኬት ተመዝግቧል!** 🎉

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 **የማስታወቂያ መረጃ:**
• 📌 ቁጥር: #{listing_id}
• 📅 ቀን: {datetime.now().strftime('%Y-%m-%d %H:%M')}
• 📊 ሁኔታ: በመጠበቅ ላይ

📢 ማስታወቂያዎ ለተጠቃሚዎች ይታያል።
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
            reply_markup=MAIN_MARKUP
        )
        
        notification_text = f"""
📢 **አዲስ የሽያጭ/ኪራይ ማስታወቂያ! (#{listing_id})**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 **ምድብ:** {listing_data['main_category']}
🔹 **ንኡስ ምድብ:** {listing_data['sub_type']}
🔹 **ዓይነት:** {listing_data['action_type']}
💰 **ዋጋ:** {price} ብር
{contact_info}
👤 **አቅራቢ:** {listing_data['user_name']}

📝 **መግለጫ:**
{description}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ ለደላሎች: ይህ ማስታወቂያ ለፈላጊዎች ማሳወቅ ይችላሉ!
"""
        approved_brokers = BrokerRepository.get_approved()
        if approved_brokers:
            for b_id in approved_brokers:
                try:
                    await context.bot.send_message(
                        chat_id=b_id,
                        text=notification_text,
                        parse_mode="Markdown"
                    )
                    await asyncio.sleep(0.05)
                except Exception as e:
                    logger.error(f"Failed to send listing notification to broker {b_id}: {e}")
    else:
        await safe_send_message(
            update, context,
            "❌ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "ማስታወቂያውን መመዝገብ አልተቻለም።\n"
            "💡 እባክዎ እንደገና ይሞክሩ።",
            reply_markup=MAIN_MARKUP
        )
    
    context.user_data.clear()
    return ConversationHandler.END

# ==============================================================================
# 15. HANDLERS - BROKER REGISTRATION
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
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await safe_send_message(
        update, context,
        """
📝 **የአቅራቢ/ደላላ ምዝገባ**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔐 **አስፈላጊ መረጃ**
ይህ ምዝገባ ለሙያዊ አቅራቢዎች እና ደላሎች ብቻ ነው።

👤 **የምዝገባ ዓይነቶች:**
• 👨💼 ደላላ - ሽያጭ/ኪራይ የሚያመቻች
• 🚢 አስመጪ - ከውጭ የሚያስገባ
• 👤 ባለቤት - ንብረት ያለው

📌 **ማስታወሻ:**
ምዝገባዎ በአድሚን ከተረጋገጠ በኋላ ብቻ ጥያቄዎችን ማየት ይችላሉ!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return BROKER_ROLE

async def broker_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    role_map = {"role_broker": "ደላላ", "role_importer": "አስመጪ/አቅራቢ", "role_owner": "ባለቤት/አቅራቢ"}
    role = role_map.get(query.data, "አቅራቢ")
    context.user_data['broker_role'] = role
    
    await query.edit_message_text(
        f"👤 **ምዝገባ፦ {role}**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📝 **ደረጃ 1/6: ሙሉ ስም**\n\n"
        "✍️ እባክዎን ሙሉ ስምዎን ያስገቡ:"
    )
    return BROKER_NAME

async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data['broker_name'] = sanitize_input(update.message.text)
    await safe_send_message(
        update, context,
        "📞 **ምዝገባ፦ ደረጃ 2/6**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📱 እባክዎን የስልክ ቁጥርዎን ያስገቡ:\n\n"
        "💡 *ምሳሌ:* 0911223344"
    )
    return BROKER_PHONE

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(update.message.text):
        await safe_send_message(
            update, context,
            "⚠️ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "እባክዎን ትክክለኛ የስልክ ቁጥር ያስገቡ።\n"
            "💡 ምሳሌ: 0911223344"
        )
        return BROKER_PHONE
    
    context.user_data['broker_phone'] = update.message.text
    await safe_send_message(
        update, context,
        "🆔 **ምዝገባ፦ ደረጃ 3/6**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👤 እባክዎን የቴሌግራም ተጠቃሚ ስምዎን (@username) ያስገቡ:\n\n"
        "💡 *ምሳሌ:* @yourusername\n"
        "📌 ከሌለዎት 'አልኖረኝም' ብለው ይጻፉ"
    )
    return BROKER_TELEGRAM_ID

async def broker_reg_telegram_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    telegram_id = update.message.text
    if telegram_id.lower() == "አልኖረኝም":
        telegram_id = None
    else:
        telegram_id = sanitize_input(telegram_id)
    
    context.user_data['broker_telegram_id'] = telegram_id
    await safe_send_message(
        update, context,
        "📍 **ምዝገባ፦ ደረጃ 4/6**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🏙️ እባክዎን የሚሰሩበትን ክፍለ ከተማ ይምረጡ:",
        reply_markup=build_indexed_keyboard(SUB_CITIES, "broker_sc_", columns=2),
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
        "🆔 **ምዝገባ፦ ደረጃ 5/6**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📸 እባክዎን የፋይዳ (National ID) ወይም የነዋሪነት መታወቂያ ፎቶ ያንሱና ይላኩ:\n\n"
        "🔐 *ይህ ለማረጋገጫ ብቻ ነው*\n"
        "📌 ፎቶው ግልጽ እና ሙሉ መረጃ ያለው መሆን አለበት"
    )
    return BROKER_NID_PHOTO

async def broker_reg_nid_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    user = update.effective_user
    if not update.message or not update.message.photo:
        await safe_send_message(
            update, context,
            "❌ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "እባክዎ የመታወቂያዎን ፎቶ ይላኩ!\n\n"
            "📸 ፎቶውን ከቴሌግራም ፋይል አባሪ አማራጭ በመጠቀም ይላኩ።"
        )
        return BROKER_NID_PHOTO
    
    photo_id = update.message.photo[-1].file_id
    role = context.user_data.get('broker_role', 'አቅራቢ')
    name = context.user_data.get('broker_name', user.first_name)
    phone = context.user_data.get('broker_phone', '')
    telegram_id = context.user_data.get('broker_telegram_id', '')
    sub_city = context.user_data.get('broker_subcity', '')
    
    await safe_send_message(
        update, context,
        f"""
📋 **የምዝገባ መረጃ ማጠቃለያ**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👤 **ስም:** {name}
🎭 **ሚና:** {role}
📞 **ስልክ:** {phone}
🆔 **ቴሌግራም:** {telegram_id or 'አልተገለጸም'}
📍 **ክፍለ ከተማ:** {sub_city}
🆔 **Telegram ID:** `{user.id}`

⏳ እባክዎ ይጠብቁ፣ እያስመዘገብን ነው...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
        parse_mode="Markdown",
    )
    
    broker_data = {
        'chat_id': user.id,
        'full_name': name,
        'phone': phone,
        'telegram_id': telegram_id,
        'role_type': role,
        'sub_city': sub_city,
        'national_id_photo': photo_id
    }
    
    broker_id = BrokerRepository.create_or_update(broker_data)
    
    if broker_id:
        await safe_send_message(
            update, context,
            f"""
✅ **ምዝገባዎ በስኬት ተጠናቋል!** 🎉

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 **ምዝገባ ቁጥር:** #{broker_id}
👤 **ሚና:** {role}
📅 **ቀን:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
📊 **ሁኔታ:** በመጠበቅ ላይ (Pending)

⏳ አድሚኑ መረጃዎን ካረጋገጠ በኋላ ማስታወቂያ ይደርስዎታል።
📋 ምዝገባዎ ከጸደቀ በኋላ '📋 የፈላጊዎች ዝርዝር' ማየት ይችላሉ።
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
            reply_markup=MAIN_MARKUP,
        )
        
        if Config.ADMIN_CHAT_ID_INT != 0:
            admin_msg = f"""
🚨 **አዲስ የ{role} ምዝገባ ጥያቄ!**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👤 **ስም:** {name}
🎭 **ሚና:** {role}
📞 **ስልክ:** {phone}
🆔 **ቴሌግራም:** {telegram_id or 'አልተገለጸም'}
📍 **ክፍለ ከተማ:** {sub_city}
🆔 **Telegram ID:** `{user.id}`
📅 **ቀን:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

📸 **መታወቂያ ፎቶ ከላይ ተላኳል**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
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
            except Exception as e:
                logger.error(f"❌ Failed to send admin photo notification: {e}")
                try:
                    await context.bot.send_message(
                        chat_id=Config.ADMIN_CHAT_ID_INT,
                        text=admin_msg + f"\n\n📸 ፎቶ መላክ አልተቻለም።",
                        parse_mode="Markdown",
                        reply_markup=admin_kbd,
                    )
                except Exception as e2:
                    logger.error(f"❌ Failed to send admin text message: {e2}")
    else:
        await safe_send_message(
            update, context,
            "❌ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "ምዝገባውን ማጠናቀቅ አልተቻለም!\n\n"
            "💡 እባክዎ እንደገና ይሞክሩ።",
            reply_markup=MAIN_MARKUP,
        )
    
    return ConversationHandler.END

# ==============================================================================
# 16. HANDLERS - BROKER RESPONSE
# ==============================================================================
async def broker_have_item_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    broker = BrokerRepository.get_by_chat_id(user_id)
    
    if not broker or broker.get('status') != 'approved':
        await safe_send_message(
            update, context,
            "⛔ **ያልተፈቀደ ተግባር**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "ይህን ማድረግ የሚችሉት በአድሚን የተረጋገጡ ደላሎች/አቅራቢዎች ብቻ ናቸው!\n\n"
            "📝 መጀመሪያ ይመዝገቡ እና ማጽደቅ ይጠብቁ።"
        )
        return ConversationHandler.END
    
    parts = query.data.split('_')
    if len(parts) < 3:
        return ConversationHandler.END
    
    req_id = parts[2]
    buyer_id = parts[3] if len(parts) > 3 else None
    
    context.user_data['target_req_id'] = req_id
    context.user_data['target_buyer_id'] = buyer_id
    
    await safe_send_message(
        update, context,
        f"""
✅ **ለጥያቄ #{req_id} ምላሽ መስጠት**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✍️ እባክዎን ያለዎትን ንብረት ዝርዝር መረጃ ያስገቡ:

📌 **የሚከተሉትን ያካትቱ:**
• 🏷️ የንብረቱ አይነት
• 📍 አካባቢ
• 💰 ዋጋ
• 📞 የስልክ ቁጥር ወይም ቴሌግራም

💡 *ምሳሌ:* ቶዮታ ቪትዝ 2021፣ 30,000 KM የሄደ፣ ዋጋ 2.4 ሚሊዮን፣ ስልክ 0911...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
        reply_markup=HOME_ONLY_KEYBOARD,
    )
    return BROKER_OFFER_TEXT

async def broker_offer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data['offer_text'] = sanitize_input(update.message.text)
    await safe_send_message(
        update, context,
        "📸 **የንብረቱ ፎቶ**\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🖼️ እባክዎን የንብረቱን ፎቶ ይላኩ:\n\n"
        "💡 ፎቶ ከሌለዎት 'ፎቶ የለውም' ብለው ይጻፉ"
    )
    return BROKER_OFFER_PHOTO

async def broker_offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    buyer_id = int(context.user_data.get('target_buyer_id', 0))
    req_id = context.user_data.get('target_req_id')
    offer_text = context.user_data.get('offer_text', '')
    broker_name = update.effective_user.first_name or "አቅራቢ"
    
    if not buyer_id or not req_id:
        await safe_send_message(update, context, "❌ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።")
        return ConversationHandler.END
    
    ListingRepository.update_status(int(req_id), 'responded')
    
    message_to_buyer = f"""
🎉 **ለጥያቄዎ (#REQ-{req_id}) አዲስ አማራጭ ቀርቧል!**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👤 **አቅራቢ/ደላላ:** {broker_name}

📝 **የንብረቱ ዝርዝር:**
{offer_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 *ለተጨማሪ መረጃ ከላይ ያለውን መረጃ በመጠቀም ያነጋግሩ!*
"""
    
    try:
        if update.message and update.message.photo:
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
            f"""
✅ **መረጃዎ ለፈላጊው ተልኳል!** 📨

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 **የተላከው መረጃ:**
• 📌 ጥያቄ: #{req_id}
• 👤 ተቀባይ: {buyer_id}
• 📅 ቀን: {datetime.now().strftime('%Y-%m-%d %H:%M')}
• 📊 ሁኔታ: ተልኳል

📌 ጥያቄው ከ'📋 የፈላጊዎች ዝርዝር' ተወግዷል።
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
            reply_markup=MAIN_MARKUP,
        )
    except Exception as e:
        logger.error(f"Failed to send offer to buyer: {e}")
        await safe_send_message(
            update, context,
            "❌ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "መረጃውን ለፈላጊው መላክ አልተቻለም።\n"
            "💡 እባክዎ እንደገና ይሞክሩ።",
            reply_markup=MAIN_MARKUP,
        )
    
    return ConversationHandler.END

# ==============================================================================
# 17. HANDLERS - VIEW REQUESTS
# ==============================================================================
async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    broker = BrokerRepository.get_by_chat_id(user_id)
    
    if not broker:
        await safe_send_message(
            update, context,
            "⛔ **ያልተፈቀደ ተግባር**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "ይህን ገጽ ማየት የሚችሉት የተመዘገቡ አቅራቢዎች/ደላሎች ብቻ ናቸው!\n\n"
            "📝 እባክዎን መጀመሪያ '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይጫኑ።",
            reply_markup=MAIN_MARKUP,
        )
        return
    
    if broker.get('status') != 'approved':
        await safe_send_message(
            update, context,
            "⏳ **ምዝገባዎ ገና አልጸደቀም!**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⏳ ምዝገባዎ በአድሚን ሲረጋገጥ ማስታወቂያ ይደርስዎታል።\n"
            "📞 ለተጨማሪ መረጃ ድጋፍን ይጠቀሙ።",
            reply_markup=MAIN_MARKUP,
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
            text = """
📭 **ምንም ንቁ ጥያቄዎች የሉም**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💡 ሁሉም ጥያቄዎች ተመልሰዋል ወይም በሂደት ላይ ናቸው።
🔄 ቆይተው እንደገና ይሞክሩ።
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
            if update.message:
                await safe_send_message(update, context, text, reply_markup=MAIN_MARKUP)
            else:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(text)
            return
        
        text = f"""
📋 **የፈላጊዎች ዝርዝር**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📄 ገጽ {page + 1}/{total_pages}
📊 አጠቃላይ ጥያቄዎች: {total}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"""
        for listing in listings:
            text += format_listing_for_broker(listing) + "\n"
        
        keyboard = []
        for listing in listings:
            l_id = listing.get('id')
            u_id = listing.get('user_chat_id')
            keyboard.append([InlineKeyboardButton(f"✅ አለኝ - #{l_id}", callback_data=f"have_item_{l_id}_{u_id}")])
        
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ ቀዳሚ ገጽ", callback_data=f"page_{page - 1}"))
        if offset + Config.ITEMS_PER_PAGE < total:
            nav_buttons.append(InlineKeyboardButton("➡️ ቀጣይ ገጽ", callback_data=f"page_{page + 1}"))
        nav_buttons.append(InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home"))
        keyboard.append(nav_buttons)
        
        if update.message:
            await safe_send_message(
                update, context, text,
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
        await safe_send_message(
            update, context,
            "❌ **ስህተት**\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "ዝርዝሩን ማሳየት አልተቻለም።\n"
            "💡 እባክዎ እንደገና ይሞክሩ።"
        )

# ==============================================================================
# 18. HANDLERS - ADMIN
# ==============================================================================
async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data.startswith("admin_appr_"):
        target_id = int(data.replace("admin_appr_", ""))
        if BrokerRepository.update_status(target_id, 'approved'):
            await query.edit_message_caption(
                caption=(query.message.caption or "") + """

✅ **ሁኔታ: ጸድቋል (Approved)**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 ይህ አቅራቢ አሁን ጥያቄዎችን ማየት እና መመለስ ይችላል።
""",
                parse_mode="Markdown"
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="""
🎉 **እንኳን ደስ አለዎት!**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ የምዝገባ ጥያቄዎ በአድሚን ጸድቋል!

📋 አሁን '📋 የፈላጊዎች ዝርዝር' በመጠቀም ጥያቄዎችን ማየት ይችላሉ።
💡 ንብረት ያላቸውን ፈላጊዎች በመገናኘት ሽያጭ/ኪራይ ያመቻቹ!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
                    reply_markup=MAIN_MARKUP,
                )
            except Exception as e:
                logger.error(f"Failed to notify approved broker: {e}")
    
    elif data.startswith("admin_reje_"):
        target_id = int(data.replace("admin_reje_", ""))
        if BrokerRepository.update_status(target_id, 'rejected'):
            await query.edit_message_caption(
                caption=(query.message.caption or "") + """

❌ **ሁኔታ: ተሰርዟል (Rejected)**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 ይህ አቅራቢ አልጸደቀም።
""",
                parse_mode="Markdown"
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="""
❌ **የምዝገባ ጥያቄዎ ተሰርዟል**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📌 ለተጨማሪ መረጃ እባክዎን አድሚንን ያግኙ።
💡 የገቡት መረጃ ትክክል እንደሆነ በማረጋገጥ እንደገና መሞከር ይችላሉ።
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""",
                    reply_markup=MAIN_MARKUP,
                )
            except Exception as e:
                logger.error(f"Failed to notify rejected broker: {e}")
    
    elif data.startswith("admin_view_"):
        target_id = int(data.replace("admin_view_", ""))
        broker = BrokerRepository.get_by_chat_id(target_id)
        if broker:
            view_text = f"""
👤 **የአቅራቢው ዝርዝር መረጃ**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🆔 **ID:** {broker.get('id')}
👤 **ስም:** {broker.get('full_name')}
🎭 **ሚና:** {broker.get('role_type')}
📞 **ስልክ:** {broker.get('phone')}
🆔 **ቴሌግራም:** {broker.get('telegram_id') or 'አልተገለጸም'}
📍 **ክፍለ ከተማ:** {broker.get('sub_city')}
🆔 **Telegram ID:** {broker.get('chat_id')}
📅 **የተመዘገበ:** {broker.get('created_at')}
📊 **ሁኔታ:** {broker.get('status')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
            await query.message.reply_text(view_text, parse_mode="Markdown")

# ==============================================================================
# 19. HANDLERS - HELP
# ==============================================================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
❓ **የAdika Marketplace አጠቃቀም መመሪያ**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 **መግዛት ከፈለጉ:**
1. '🔍 መግዛት / መከራየት' ይምረጡ
2. ምድብ ይምረጡ (መኪና/ቤት/ንግድ)
3. ንኡስ ምድብ ይምረጡ
4. የድርጊት አይነት ይምረጡ
5. መረጃዎችን ይሙሉ

📢 **መሸጥ ከፈለጉ:**
1. '📢 መሸጥ / ማከራየት' ይምረጡ
2. ምድብ ይምረጡ
3. መረጃዎችን ይሙሉ

📝 **እንደ አቅራቢ ለመመዝገብ:**
1. '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይምረጡ
2. ሚናዎን ይምረጡ
3. መረጃዎችን ይሙሉ
4. የፋይዳ መታወቂያ ፎቶ ይላኩ
5. አስተዳዳሪ ማጽደቅ ይጠብቁ

📋 **የፈላጊዎች ዝርዝር:**
• ለተመዘገቡ እና ለተጸደቁ አቅራቢዎች ብቻ
• ንቁ ጥያቄዎችን በሙያዊ መልኩ ያሳያል

🏠 **ዋና ገጽ:**
• ቀደም ሲል የነበረውን ሂደት ያጽዳል
• አዲስ ነገር ለመጀመር ያስችላል
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    await safe_send_message(update, context, help_text, parse_mode="Markdown")

# ==============================================================================
# 20. MAIN APPLICATION
# ==============================================================================
def main():
    init_db()
    init_connection_pool()
    
    threading.Thread(target=run_flask, daemon=True).start()
    logger.info(f"Flask server started on port {Config.PORT}")
    
    app = Application.builder().token(Config.BOT_TOKEN).build()
    
    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)
    
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
        states={
            BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_|^flow_home$")],
            BUYER_SUB: [CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_|^flow_home$")],
            BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_|^flow_home$")],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details_received)],
            BUYER_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_budget_received)],
            BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone_received)],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_|^flow_home$")],
            SELLER_ACTION: [CallbackQueryHandler(seller_sub_chosen, pattern="^flow_sell_sub_|^flow_home$")],
            SELLER_SUBTYPE: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_|^flow_home$")],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details_received)],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price_received)],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone_received)],
            SELLER_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, seller_photo_received)],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ/ደላላ መመዝገብ$"), broker_reg_start)],
        states={
            BROKER_ROLE: [CallbackQueryHandler(broker_role_chosen, pattern="^role_|^flow_home$")],
            BROKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name)],
            BROKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone)],
            BROKER_TELEGRAM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_telegram_id)],
            BROKER_SUBCITY: [CallbackQueryHandler(broker_reg_subcity, pattern="^broker_sc_|^flow_home$")],
            BROKER_NID_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, broker_reg_nid_photo)],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    broker_response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broker_have_item_click, pattern="^have_item_")],
        states={
            BROKER_OFFER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text)],
            BROKER_OFFER_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, broker_offer_photo)],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    app.add_handler(CommandHandler("start", start))
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
    app.run_polling()

if __name__ == "__main__":
    main()
