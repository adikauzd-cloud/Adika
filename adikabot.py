
import logging
import os
import re
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List

# Database Libraries
import psycopg2
from psycopg2.extras import RealDictCursor

# Flask Web Server
from flask import Flask, render_template_string, request, jsonify

# Telegram Libraries
from telegram import (
    Update, ReplyKeyboardMarkup, InlineKeyboardButton, 
    InlineKeyboardMarkup, WebAppInfo
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "0")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_FILE = "adika_marketplace.db"

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable not set!")

ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 0

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================================================================
# 2. CONSTANTS & KEYBOARDS
# ==============================================================================

MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["🛍️ የገበያ ቦታ (የሚሸጡ)", "📋 የፈላጊዎች ዝርዝር"],
    ["👥 የደላሎች/አቅራቢዎች ማውጫ", "📝 እንደ አቅራቢ/ደላላ መመዝገብ"],
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
# 3. CONVERSATION STATES (ሁሉም በአንድ ቦታ)
# ==============================================================================

(
    BUYER_MAIN, BUYER_ACTION, BUYER_SUB, BUYER_PROPERTY, 
    BUYER_DETAILS, BUYER_PHONE, BUYER_HTYPE,
    SELLER_MAIN, SELLER_ACTION, SELLER_SUB, SELLER_PROPERTY,
    SELLER_DETAILS, SELLER_PRICE, SELLER_PHONE, SELLER_PHOTO, SELLER_HTYPE,
    BROKER_ROLE, BROKER_NAME, BROKER_PHONE, BROKER_SUBCITY, BROKER_NID_PHOTO,
    BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO
) = range(23)

# ==============================================================================
# 4. DATABASE CONNECTION (የተዋሃደ - አንድ ጊዜ ብቻ)
# ==============================================================================

def get_db_connection():
    """የተዋሃደ የዳታቤዝ ግንኙነት ፈንክሽን"""
    if DATABASE_URL:
        cleaned_url = DATABASE_URL.strip().strip('"').strip("'")
        if cleaned_url.startswith("postgres://"):
            cleaned_url = cleaned_url.replace("postgres://", "postgresql://", 1)
        try:
            conn = psycopg2.connect(cleaned_url, cursor_factory=RealDictCursor)
            conn.autocommit = True
            return conn
        except Exception as e:
            logger.error(f"❌ PostgreSQL connection failed: {e}")
            raise
    else:
        import sqlite3
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_FILE)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

def get_placeholder():
    """SQL placeholder - PostgreSQL ወይም SQLite ለይቶ ለማወቅ"""
    return "%s" if DATABASE_URL else "?"

# ==============================================================================
# 5. DATABASE INITIALIZATION (የተዋሃደ)
# ==============================================================================

def init_db():
    """የዳታቤዝ ሰንጠረዦችን መፍጠር - አንድ ጊዜ ብቻ"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Common tables for both PostgreSQL and SQLite
        tables = """
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
                price TEXT,
                phone TEXT,
                photo_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS brokers (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL UNIQUE,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                role_type TEXT NOT NULL,
                national_id_photo TEXT,
                sub_city TEXT NOT NULL,
                rating REAL DEFAULT 5.0,
                total_ratings INT DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS ratings (
                id SERIAL PRIMARY KEY,
                broker_chat_id BIGINT NOT NULL,
                user_chat_id BIGINT NOT NULL,
                stars INT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS broker_offers (
                id SERIAL PRIMARY KEY,
                request_id INTEGER NOT NULL,
                broker_id BIGINT NOT NULL,
                description TEXT,
                photo_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """
        
        # SQLite doesn't support SERIAL, so we need to adapt
        if not DATABASE_URL:
            tables = tables.replace("SERIAL", "INTEGER")
            tables = tables.replace("BIGINT", "INTEGER")
        
        cursor.execute(tables)
        
        if not DATABASE_URL:
            conn.commit()
            
        logger.info("✅ Database initialized successfully")
        
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        if conn and not DATABASE_URL:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 6. DATABASE OPERATIONS (የተዋሃዱ - ድግግሞሽ የለም)
# ==============================================================================

def add_broker(chat_id: int, full_name: str, phone: str, role_type: str, 
               national_id_photo: str, sub_city: str) -> Optional[int]:
    """ደላላ መመዝገብ - የተዋሃደ"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        # Check if exists
        cursor.execute(f"SELECT id FROM brokers WHERE chat_id = {p}", (chat_id,))
        existing = cursor.fetchone()
        
        if existing:
            query = f"""
                UPDATE brokers 
                SET full_name = {p}, phone = {p}, role_type = {p}, 
                    national_id_photo = {p}, sub_city = {p}, status = 'pending'
                WHERE chat_id = {p}
                RETURNING id
            """ if DATABASE_URL else """
                UPDATE brokers 
                SET full_name = ?, phone = ?, role_type = ?, 
                    national_id_photo = ?, sub_city = ?, status = 'pending'
                WHERE chat_id = ?
            """
            params = (full_name, phone, role_type, national_id_photo, sub_city, chat_id)
            cursor.execute(query, params)
            broker_id = existing[0] if not DATABASE_URL else cursor.fetchone()[0]
        else:
            query = f"""
                INSERT INTO brokers (chat_id, full_name, phone, role_type, national_id_photo, sub_city, status)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, 'pending')
                RETURNING id
            """ if DATABASE_URL else """
                INSERT INTO brokers (chat_id, full_name, phone, role_type, national_id_photo, sub_city, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """
            params = (chat_id, full_name, phone, role_type, national_id_photo, sub_city)
            cursor.execute(query, params)
            broker_id = cursor.lastrowid if not DATABASE_URL else cursor.fetchone()[0]
        
        if not DATABASE_URL:
            conn.commit()
            
        return broker_id
    except Exception as e:
        logger.error(f"Add broker error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_broker(chat_id: int) -> Optional[Dict]:
    """ደላላ መረጃ ማውጣት"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
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

def update_broker_status(chat_id: int, status: str) -> bool:
    """የደላላ ሁኔታ ማሻሻል"""
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

def get_approved_brokers() -> List[int]:
    """የተረጋገጡ ደላሎችን ዝርዝር ማውጣት"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM brokers WHERE status = 'approved'")
        rows = cursor.fetchall()
        return [dict(row)['chat_id'] for row in rows]
    except Exception as e:
        logger.error(f"Get approved brokers error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def add_listing(user_chat_id: int, user_name: str, req_type: str, 
                main_category: str, sub_category: str, action_type: str,
                property_type: str, description: str, price: str = None,
                phone: str = None, photo_id: str = None) -> Optional[int]:
    """አዲስ ጥያቄ/ማስታወቂያ መመዝገብ"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        query = f"""
            INSERT INTO listings 
            (user_chat_id, user_name, req_type, main_category, sub_category, 
             action_type, property_type, description, price, phone, photo_id)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            RETURNING id
        """ if DATABASE_URL else """
            INSERT INTO listings 
            (user_chat_id, user_name, req_type, main_category, sub_category, 
             action_type, property_type, description, price, phone, photo_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        params = (user_chat_id, user_name, req_type, main_category, sub_category,
                  action_type, property_type, description, price, phone, photo_id)
        
        cursor.execute(query, params)
        
        if DATABASE_URL:
            listing_id = cursor.fetchone()[0]
        else:
            listing_id = cursor.lastrowid
            conn.commit()
            
        return listing_id
    except Exception as e:
        logger.error(f"Add listing error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_listings_by_category(limit: int = 10, offset: int = 0, req_type: str = None) -> List[Dict]:
    """ጥያቄዎችን በምድብ ማውጣት"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        if req_type:
            query = f"""
                SELECT * FROM listings 
                WHERE status = 'pending' AND req_type = {p}
                ORDER BY created_at DESC LIMIT {p} OFFSET {p}
            """
            cursor.execute(query, (req_type, limit, offset))
        else:
            query = f"""
                SELECT * FROM listings 
                WHERE status = 'pending'
                ORDER BY created_at DESC LIMIT {p} OFFSET {p}
            """
            cursor.execute(query, (limit, offset))
            
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Get listings error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def count_listings(req_type: str = None) -> int:
    """ጠቅላላ ጥያቄዎችን መቁጠር"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if req_type:
            cursor.execute("SELECT COUNT(*) FROM listings WHERE status = 'pending' AND req_type = %s", (req_type,))
        else:
            cursor.execute("SELECT COUNT(*) FROM listings WHERE status = 'pending'")
        return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Count listings error: {e}")
        return 0
    finally:
        if conn:
            conn.close()

def get_listing_by_id(listing_id: int) -> Optional[Dict]:
    """በID ጥያቄ ማውጣት"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
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

def update_listing_status(listing_id: int, status: str) -> bool:
    """የጥያቄ ሁኔታ ማሻሻል"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"UPDATE listings SET status = {p} WHERE id = {p}", (status, listing_id))
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Update listing error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_public_marketplace_items(main_category: str = None, limit: int = 10, offset: int = 0) -> List[Dict]:
    """ለገበያ የቀረቡ ንብረቶችን ማውጣት"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        if main_category:
            query = f"""
                SELECT * FROM listings 
                WHERE req_type = 'SELL' AND status = 'pending' AND main_category = {p}
                ORDER BY created_at DESC LIMIT {p} OFFSET {p}
            """
            cursor.execute(query, (main_category, limit, offset))
        else:
            query = f"""
                SELECT * FROM listings 
                WHERE req_type = 'SELL' AND status = 'pending'
                ORDER BY created_at DESC LIMIT {p} OFFSET {p}
            """
            cursor.execute(query, (limit, offset))
            
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Get public marketplace items error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_approved_brokers_directory(sub_city: str = None) -> List[Dict]:
    """የተረጋገጡ ደላሎችን ዝርዝር በክፍለ ከተማ ማውጣት"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        if sub_city and sub_city != "ሁሉም":
            query = f"""
                SELECT full_name, phone, role_type, sub_city, rating, total_ratings 
                FROM brokers WHERE status = 'approved' AND sub_city = {p}
                ORDER BY rating DESC
            """
            cursor.execute(query, (sub_city,))
        else:
            query = """
                SELECT full_name, phone, role_type, sub_city, rating, total_ratings 
                FROM brokers WHERE status = 'approved'
                ORDER BY rating DESC
            """
            cursor.execute(query)
            
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Get approved brokers directory error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def save_broker_offer(request_id: int, broker_id: int, description: str, photo_id: str = None) -> bool:
    """የደላላ አማራጭ መመዝገብ"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        query = f"""
            INSERT INTO broker_offers (request_id, broker_id, description, photo_id)
            VALUES ({p}, {p}, {p}, {p})
        """ if DATABASE_URL else """
            INSERT INTO broker_offers (request_id, broker_id, description, photo_id)
            VALUES (?, ?, ?, ?)
        """
        
        cursor.execute(query, (request_id, broker_id, description, photo_id))
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Save broker offer error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def add_broker_rating(broker_chat_id: int, user_chat_id: int, stars: int) -> bool:
    """ለደላላ ደረጃ መስጠት"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        # Add rating
        cursor.execute(
            f"INSERT INTO ratings (broker_chat_id, user_chat_id, stars) VALUES ({p}, {p}, {p})",
            (broker_chat_id, user_chat_id, stars)
        )
        
        # Update average
        cursor.execute(
            f"SELECT AVG(stars), COUNT(*) FROM ratings WHERE broker_chat_id = {p}",
            (broker_chat_id,)
        )
        avg_stars, total_count = cursor.fetchone()
        
        cursor.execute(
            f"UPDATE brokers SET rating = {p}, total_ratings = {p} WHERE chat_id = {p}",
            (round(float(avg_stars), 1), total_count, broker_chat_id)
        )
        
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Add broker rating error: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 7. VALIDATION FUNCTIONS (የተዋሃዱ)
# ==============================================================================

def validate_phone(phone: str) -> bool:
    """የስልክ ቁጥር ማረጋገጫ"""
    phone = phone.replace(' ', '').replace('-', '')
    pattern = r'^(09|07|01)\d{8}$|^\+251(9|7|1)\d{8}$'
    return bool(re.match(pattern, phone))

def validate_price(price: str) -> bool:
    """የዋጋ ማረጋገጫ"""
    price = price.replace(',', '').replace(' ', '')
    return price.isdigit()

def format_buyer_card(req: Dict) -> str:
    """የፈላጊ ካርድ ፎርማት"""
    emoji = "🚗" if req.get('main_category') == "መኪና" else "🏠"
    return f"""
{emoji} **ጥያቄ #{req.get('id', 'N/A')}**
━━━━━━━━━━━━━━━━━━━
📌 **ዘርፍ፦** {req.get('main_category', 'N/A')}
🏷️ **አይነት፦** {req.get('sub_category', 'N/A')}
🔄 **ድርጊት፦** {req.get('action_type', 'N/A')}
📝 **ዝርዝር፦** {req.get('description', 'N/A')[:200]}
📞 **ስልክ፦** `{req.get('phone', 'N/A')}`
📅 **ቀን፦** {str(req.get('created_at', ''))[:10]}
━━━━━━━━━━━━━━━━━━━
"""

def format_seller_card(item: Dict) -> str:
    """የሻጭ ካርድ ፎርማት"""
    emoji = "🚗" if item.get('main_category') == "መኪና" else "🏠"
    status = "🟢 ለሽያጭ" if item.get('action_type') == "መሸጥ" else "🔵 ለኪራይ"
    return f"""
{emoji} **ማስታወቂያ #{item.get('id', 'N/A')}** {status}
━━━━━━━━━━━━━━━━━━━
📦 **አይነት፦** {item.get('main_category', 'N/A')} ({item.get('sub_category', 'N/A')})
💰 **ዋጋ፦** `{item.get('price', 'N/A')}`
📝 **መግለጫ፦** {item.get('description', 'N/A')[:200]}
📞 **ስልክ፦** `{item.get('phone', 'N/A')}`
━━━━━━━━━━━━━━━━━━━
"""

def format_broker_profile(broker: Dict) -> str:
    """የደላላ ፕሮፋይል ፎርማት"""
    stars = "⭐" * min(5, int(broker.get('rating', 5)))
    return f"""
👤 **{broker.get('full_name', 'N/A')}**
├─ 🎭 ሚና፦ {broker.get('role_type', 'N/A')}
├─ 📍 ክፍለ ከተማ፦ {broker.get('sub_city', 'N/A')}
├─ 📞 ስልክ፦ `{broker.get('phone', 'N/A')}`
├─ ⭐ ደረጃ፦ {broker.get('rating', 5):.1f}/5.0 {stars}
└─ 🏆 ግምገማዎች፦ {broker.get('total_ratings', 0)}
"""

# ==============================================================================
# 8. WEBAPP TEMPLATES (የተለዩ)
# ==============================================================================

SELLER_FORM_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 p-4">
    <div class="max-w-md mx-auto bg-white p-6 rounded-xl shadow-md">
        <h2 class="text-xl font-bold mb-4 text-center">ንብረት ለገበያ ያቅርቡ</h2>
        <form id="listingForm" class="space-y-4">
            <select id="category" class="w-full p-2 border rounded">
                <option value="መኪና">መኪና</option>
                <option value="ቤት">ቤት</option>
            </select>
            <input type="text" id="price" placeholder="ዋጋ (በብር)" class="w-full p-2 border rounded" required>
            <textarea id="description" placeholder="ዝርዝር መግለጫ" class="w-full p-2 border rounded" required></textarea>
            <input type="tel" id="phone" placeholder="ስልክ ቁጥር" class="w-full p-2 border rounded" required>
            <button type="submit" class="w-full bg-blue-600 text-white p-2 rounded font-bold">መረጃውን ይላኩ</button>
        </form>
    </div>
    <script>
        let tg = window.Telegram.WebApp;
        tg.expand();
        document.getElementById('listingForm').onsubmit = (e) => {
            e.preventDefault();
            const data = {
                user_id: tg.initDataUnsafe.user ? tg.initDataUnsafe.user.id : "unknown",
                category: document.getElementById('category').value,
                price: document.getElementById('price').value,
                description: document.getElementById('description').value,
                phone: document.getElementById('phone').value
            };
            fetch('/api/submit-listing', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            }).then(() => tg.close());
        };
    </script>
</body>
</html>
"""

BUYER_FORM_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 p-4">
    <div class="max-w-md mx-auto bg-white p-6 rounded-xl shadow-md">
        <h2 class="text-xl font-bold mb-4 text-center">የሚፈልጉትን ንብረት ይዘርዝሩ</h2>
        <form id="buyerForm" class="space-y-4">
            <select id="category" class="w-full p-2 border rounded">
                <option value="መኪና">መኪና</option>
                <option value="ቤት">ቤት</option>
            </select>
            <input type="text" id="budget" placeholder="ባጀት (በብር)" class="w-full p-2 border rounded" required>
            <textarea id="details" placeholder="ዝርዝር ፍላጎት" class="w-full p-2 border rounded" required></textarea>
            <input type="tel" id="phone" placeholder="ስልክ ቁጥር" class="w-full p-2 border rounded" required>
            <button type="submit" class="w-full bg-green-600 text-white p-2 rounded font-bold">ጥያቄውን ይላኩ</button>
        </form>
    </div>
    <script>
        let tg = window.Telegram.WebApp;
        tg.expand();
        document.getElementById('buyerForm').onsubmit = (e) => {
            e.preventDefault();
            const data = {
                user_id: tg.initDataUnsafe.user ? tg.initDataUnsafe.user.id : "unknown",
                category: document.getElementById('category').value,
                budget: document.getElementById('budget').value,
                details: document.getElementById('details').value,
                phone: document.getElementById('phone').value
            };
            fetch('/api/submit-request', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            }).then(() => tg.close());
        };
    </script>
</body>
</html>
"""

# ==============================================================================
# 9. FLASK WEB SERVER
# ==============================================================================

web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "✅ Adika Marketplace Bot is running!", 200

@web_app.route('/seller-form')
def webapp_seller_form():
    return render_template_string(SELLER_FORM_HTML)

@web_app.route('/buyer-form')
def webapp_buyer_form():
    return render_template_string(BUYER_FORM_HTML)

@web_app.route('/api/submit-listing', methods=['POST'])
def submit_listing():
    data = request.json
    logger.info(f"New Listing Received: {data}")
    return jsonify({"status": "success"})

@web_app.route('/api/submit-request', methods=['POST'])
def submit_request():
    data = request.json
    logger.info(f"New Buyer Request Received: {data}")
    return jsonify({"status": "success"})

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# ==============================================================================
# 10. BROKER NOTIFICATION
# ==============================================================================

async def notify_brokers(context: ContextTypes.DEFAULT_TYPE, message_text: str, 
                          req_id: int, buyer_id: int):
    """ለተረጋገጡ ደላሎች ማሳወቂያ መላክ"""
    approved_brokers = get_approved_brokers()
    if not approved_brokers:
        logger.info("No approved brokers found to notify")
        return
    
    for b_id in approved_brokers:
        try:
            keyboard = [[
                InlineKeyboardButton(f"👉 አለኝ - #{req_id}", 
                                    callback_data=f"have_item_{req_id}_{buyer_id}")
            ]]
            await context.bot.send_message(
                chat_id=b_id,
                text=message_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to send notification to broker {b_id}: {e}")

# ==============================================================================
# 11. BOT HANDLERS - START & HOME
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = """
👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**

የሀገሪቱ ታላቁ የመኪና፣ የቤት እና የንብረት ገበያ ማዕከል።

እባክዎን ከታች ካሉት አማራጮች አንዱን ይምረጡ፦
"""
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
# 12. BUYER HANDLERS (የተስተካከሉ)
# ==============================================================================

async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    
    web_app_url = "https://adika-vrkk.onrender.com/buyer-form"
    
    keyboard = [
        [InlineKeyboardButton("🌐 በፎርም በፍጥነት ለመሙላት", web_app=WebAppInfo(url=web_app_url))],
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
        f"✅ {sub}\n\n❓ **የድርጊት አይነት ይምረጡ፦**",
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
            "✍️ **የሚፈልጉትን መኪና ዝርዝር መረጃ ያስገቡ፦**\n\n💡 ምሳሌ፦ ቶዮታ ቪትዝ 2020፣ ባጀት እስከ 2.5 ሚሊዮን ብር",
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
    return BUYER_HTYPE

async def buyer_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    htype = query.data.replace("flow_buy_htype_", "")
    context.user_data['property_subtype'] = htype
    
    await query.edit_message_text(
        f"🏠 **{htype}**\n\n✍️ **የሚፈልጉትን ቤት/ቦታ ዝርዝር መረጃ ያስገቡ፦**",
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
    
    full_desc = f"""
📌 **አዲስ የ{main_cat} ጥያቄ**
🔹 አይነት: {prop_subtype if prop_subtype else sub_cat}
🔄 ፍላጎት: {action_type}
📝 ዝርዝር: {description}
📞 ስልክ: {phone}
"""
    
    req_id = add_listing(
        user.id, user.first_name, 'BUY', main_cat, sub_cat, 
        action_type, prop_subtype, full_desc, phone=phone
    )
    
    if req_id:
        await update.message.reply_text(
            f"✅ **ጥያቄዎ ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"📌 ጥያቄዎ ለተረጋገጡ ደላሎች ተልኳል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        notification_text = f"""
🔔 **አዲስ የ{main_cat} ጥያቄ! (#REQ-{req_id})**

{full_desc}

👉 ይህ ንብረት በእጅዎ ካለ 'አለኝ' የሚለውን በመጫን መረጃ ይላኩ!
"""
        await notify_brokers(context, notification_text, req_id, user.id)
    else:
        await update.message.reply_text("❌ ጥያቄውን መመዝገብ አልተቻለም።")

    return ConversationHandler.END

# ==============================================================================
# 13. SELLER HANDLERS (የተስተካከሉ)
# ==============================================================================

async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    
    web_app_url = "https://adika-vrkk.onrender.com/seller-form"
    
    keyboard = [
        [InlineKeyboardButton("🌐 በፎርም በፍጥነት ለመሙላት", web_app=WebAppInfo(url=web_app_url))],
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
            "✍️ **የመኪናውን ዝርዝር መረጃ ያስገቡ፦**\n\n💡 ምሳሌ፦ ቶዮታ ቪትዝ 2020፣ 60,000 ኪሜ የሄደ",
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
    return SELLER_HTYPE

async def seller_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    htype = query.data.replace("flow_sell_htype_", "")
    context.user_data['property_subtype'] = htype
    
    await query.edit_message_text(
        f"🏠 **{htype}**\n\n✍️ **የቤቱን/ቦታውን ዝርዝር መረጃ ያስገቡ፦**",
        parse_mode="Markdown"
    )
    return SELLER_DETAILS

async def seller_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['description'] = update.message.text
    await update.message.reply_text(
        "💰 **የሚሸጡበትን/ሚያከራዩበትን ዋጋ ያስገቡ፦**", 
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
        parse_mode="Markdown"
    )
    return SELLER_PRICE

async def seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_price(update.message.text):
        await update.message.reply_text("❌ እባክዎ ቁጥር ብቻ ያስገቡ።")
        return SELLER_PRICE
    
    context.user_data['price'] = update.message.text
    await update.message.reply_text("📞 **የስልክ ቁጥርዎን ያስገቡ፦**", parse_mode="Markdown")
    return SELLER_PHONE

async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(update.message.text):
        await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ።")
        return SELLER_PHONE
    
    context.user_data['phone'] = update.message.text
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ይላኩ (ወይም 'ዝለል' ይጻፉ)፦**", 
        parse_mode="Markdown"
    )
    return SELLER_PHOTO

async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
        
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    
    if not photo_id and update.message.text != "ዝለል":
        await update.message.reply_text("📸 ፎቶ አልተላከም። ያለ ፎቶ ማስታወቂያዎን እንመዘግባለን...")
    
    description = f"🏠 {context.user_data.get('property_subtype', '')}\n{context.user_data.get('description', '')}"
    
    full_desc = f"""
📢 **አዲስ የሽያጭ/ኪራይ ማስታወቂያ!**
🔄 አይነት: {context.user_data.get('action_type')}
📝 ዝርዝር: {description}
💰 ዋጋ: {context.user_data.get('price')} ብር
📞 ስልክ: {context.user_data.get('phone')}
"""
    
    req_id = add_listing(
        user.id, user.first_name, 'SELL',
        context.user_data.get('main_category'),
        context.user_data.get('sub_category', ''),
        context.user_data.get('action_type'),
        context.user_data.get('property_type', ''),
        full_desc,
        price=context.user_data.get('price'),
        phone=context.user_data.get('phone'),
        photo_id=photo_id
    )
    
    if req_id:
        await update.message.reply_text(
            "✅ **ማስታወቂያዎ ተመዝግቧል!** 🎉",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    else:
        await update.message.reply_text(
            "❌ ማስታወቂያውን መመዝገብ አልተቻለም።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 14. BROKER REGISTRATION HANDLERS
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
    context.user_data['broker_role'] = role_map.get(query.data, "አቅራቢ")
    
    await query.edit_message_text(
        f"👤 **ምዝገባ፦ {context.user_data['broker_role']}**\n\n1️⃣ ሙሉ ስምዎን ያስገቡ፦",
        parse_mode="Markdown"
    )
    return BROKER_NAME

async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['broker_name'] = update.message.text
    await update.message.reply_text("2️⃣ **የስልክ ቁጥርዎን ያስገቡ፦**", parse_mode="Markdown")
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
    await update.message.reply_text(
        "3️⃣ **የሚሰሩበትን ክፍለ ከተማ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return BROKER_SUBCITY

async def broker_reg_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    sub_city = query.data.replace("broker_sc_", "")
    context.user_data['broker_subcity'] = sub_city
    
    await query.edit_message_text(
        "4️⃣ **የፋይዳ ወይም የነዋሪነት መታወቂያ ፎቶ ይላኩ፦**",
        parse_mode="Markdown"
    )
    return BROKER_NID_PHOTO

async def broker_reg_nid_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    user = update.effective_user
    
    if not update.message or not update.message.photo:
        await update.message.reply_text("❌ **እባክዎ የመታወቂያዎን ፎቶ ይላኩ!**", parse_mode="Markdown")
        return BROKER_NID_PHOTO
        
    existing_broker = get_broker(user.id)
    if existing_broker:
        await update.message.reply_text(
            f"ℹ️ **አስቀድመው ተመዝግበዋል!**\n👤 {existing_broker.get('full_name')}",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
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
            "✅ **ምዝገባዎ ተጠናቋል!** 🎉\n\n⏳ አድሚኑ ካረጋገጠ በኋላ ማስታወቂያ ይደርስዎታል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        
        if ADMIN_CHAT_ID_INT != 0:
            admin_msg = f"""
🚨 **አዲስ የ{role} ምዝገባ!**

👤 ስም: {name}
🎭 ሚና: {role}
📞 ስልክ: {phone}
📍 ክፍለ ከተማ: {sub_city}
🆔 Telegram ID: `{user.id}`
"""
            admin_kbd = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ አጽድቅ", callback_data=f"admin_appr_{user.id}"),
                    InlineKeyboardButton("❌ ሰርዝ", callback_data=f"admin_reje_{user.id}")
                ]
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
                logger.error(f"Failed to send admin notification: {e}")
    else:
        await update.message.reply_text(
            "❌ **ምዝገባውን ማጠናቀቅ አልተቻለም!**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        
    return ConversationHandler.END

# ==============================================================================
# 15. BROKER OFFER HANDLERS
# ==============================================================================

async def broker_have_item_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    broker = get_broker(user_id)
    
    if not broker or broker.get('status') != 'approved':
        await query.message.reply_text(
            "⛔ ይህን ማድረግ የሚችሉት የተረጋገጡ ደላሎች ብቻ ናቸው!",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
        
    parts = query.data.split('_')
    if len(parts) < 2:
        await query.message.reply_text("❌ የተሳሳተ መረጃ ተላኳል።")
        return ConversationHandler.END
        
    req_id = int(parts[1])
    buyer_id = parts[2] if len(parts) >= 3 else None
    
    if not buyer_id:
        listing = get_listing_by_id(req_id)
        buyer_id = listing.get('user_chat_id') if listing else None

    if not buyer_id:
        await query.message.reply_text("❌ የፈላጊው መረጃ አልተገኘም።")
        return ConversationHandler.END
    
    context.user_data['target_req_id'] = req_id
    context.user_data['target_buyer_id'] = int(buyer_id)
    
    await query.message.reply_text(
        f"✅ **ጥያቄ #{req_id}**\n\n✍️ **ያለዎትን ንብረት ዝርዝር ያስገቡ፦**",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
        parse_mode="Markdown"
    )
    return BROKER_OFFER_TEXT

async def broker_offer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['offer_text'] = text
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ይላኩ (ወይም 'ፎቶ የለውም')፦**",
        reply_markup=ReplyKeyboardMarkup([["ፎቶ የለውም"], ["🏠 ዋና ገጽ"]], resize_keyboard=True),
        parse_mode="Markdown"
    )
    return BROKER_OFFER_PHOTO

async def broker_offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    buyer_id = context.user_data.get('target_buyer_id')
    req_id = context.user_data.get('target_req_id')
    offer_text = context.user_data.get('offer_text')
    
    if not buyer_id or not req_id or not offer_text:
        await update.message.reply_text(
            "❌ የሂደት ስህተት ተከሰተ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return ConversationHandler.END
        
    broker_user = update.effective_user
    broker = get_broker(broker_user.id)
    broker_phone = broker.get('phone', 'N/A') if broker else 'N/A'
    
    message_to_buyer = f"""
🎉 **ለጥያቄዎ (#REQ-{req_id}) አዲስ አማራጭ አለ!**

👤 ደላላ: {broker_user.first_name}
📞 ስልክ: {broker_phone}
📝 ዝርዝር:
{offer_text}

💡 ደውለው መገበያየት ይችላሉ!
"""
    
    try:
        photo_id = update.message.photo[-1].file_id if update.message.photo else None
        save_broker_offer(req_id, broker_user.id, offer_text, photo_id)

        if photo_id:
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
            "✅ **መረጃዎ ለፈላጊው ተልኳል!**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send offer: {e}")
        await update.message.reply_text(
            "❌ መረጃውን መላክ አልተቻለም።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 16. VIEW REQUESTS HANDLER
# ==============================================================================

async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID_INT)
    broker = get_broker(user_id)
    
    if not is_admin and not broker:
        await update.message.reply_text(
            "⛔ ይህን ማየት የሚችሉት የተመዘገቡ ደላሎች ወይም አድሚን ብቻ ናቸው!",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    if not is_admin and broker.get('status') != 'approved':
        await update.message.reply_text(
            "⏳ **ምዝገባዎ ገና አልጸደቀም!**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        return
    
    listings = get_listings_by_category(limit=50, offset=0)
    
    if not listings:
        await update.message.reply_text(
            "📭 **ምንም ንቁ ጥያቄዎች የሉም**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        return
    
    for listing in listings:
        req_id = listing.get('id')
        user_chat_id = listing.get('user_chat_id')
        card_text = format_buyer_card(listing)
        
        keyboard = [[
            InlineKeyboardButton(f"✅ አለኝ #{req_id}", callback_data=f"have_item_{req_id}_{user_chat_id}")
        ]]
        if is_admin:
            keyboard[0].append(InlineKeyboardButton(f"❌ Delete #{req_id}", callback_data=f"delete_item_{req_id}"))
        else:
            keyboard[0].append(InlineKeyboardButton(f"❌ አልፎኛል #{req_id}", callback_data=f"nohave_item_{req_id}"))
            
        await update.message.reply_text(
            card_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

# ==============================================================================
# 17. PUBLIC MARKETPLACE & BROKER DIRECTORY
# ==============================================================================

async def view_public_marketplace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = get_public_marketplace_items(limit=10)
    if not items:
        await update.message.reply_text("📭 በአሁኑ ሰዓት ለሽያጭ የቀረቡ ንብረቶች የሉም።")
        return
    
    for item in items:
        card_text = format_seller_card(item)
        photo_id = item.get('photo_id')
        if photo_id:
            try:
                await update.message.reply_photo(photo=photo_id, caption=card_text, parse_mode="Markdown")
            except:
                await update.message.reply_text(card_text, parse_mode="Markdown")
        else:
            await update.message.reply_text(card_text, parse_mode="Markdown")

async def view_brokers_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(sc, callback_data=f"dir_sc_{sc}")] for sc in SUB_CITIES]
    keyboard.append([InlineKeyboardButton("🌐 ሁሉም", callback_data="dir_sc_ሁሉም")])
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await update.message.reply_text(
        "📍 **የደላሎች ማውጫ**\n\nክፍለ ከተማ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def filter_brokers_by_subcity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub_city = query.data.replace("dir_sc_", "")
    brokers = get_approved_brokers_directory(sub_city=sub_city)
    
    if not brokers:
        await query.edit_message_text(f"📭 በ{sub_city} የተመዘገቡ ደላሎች የሉም።")
        return
    
    msg = f"📋 **የተረጋገጡ ደላሎች ({sub_city})**\n━━━━━━━━━━━━━━━━━━━\n\n"
    for b in brokers:
        msg += format_broker_profile(b) + "\n"
    await query.edit_message_text(msg, parse_mode="Markdown")

# ==============================================================================
# 18. ADMIN HANDLERS
# ==============================================================================

async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if update.effective_user.id != ADMIN_CHAT_ID_INT:
        await query.answer("⛔ አድሚን ብቻ!", show_alert=True)
        return
    
    data = query.data
    broker_id = int(data.split("_")[2])
    
    if data.startswith("admin_appr_"):
        success = update_broker_status(broker_id, "approved")
        if success:
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\n✅ ተፀድቋል!",
                parse_mode="Markdown"
            )
            try:
                await context.bot.send_message(
                    chat_id=broker_id,
                    text="🎉 **ምዝገባዎ ተፀድቋል!**\nአሁን '📋 የፈላጊዎች ዝርዝር' መጠቀም ይችላሉ።",
                    parse_mode="Markdown",
                    reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
                )
            except Exception as e:
                logger.error(f"Failed to notify broker: {e}")
    elif data.startswith("admin_reje_"):
        success = update_broker_status(broker_id, "rejected")
        if success:
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\n❌ ተሰርዟል!",
                parse_mode="Markdown"
            )
            try:
                await context.bot.send_message(
                    chat_id=broker_id,
                    text="❌ ምዝገባዎ ውድቅ ተደርጓል። እባክዎ በትክክለኛ መረጃ እንደገና ይሞክሩ።",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify broker: {e}")

async def delete_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID_INT)
    req_id = int(query.data.split("_")[2])
    
    listing = get_listing_by_id(req_id)
    if not listing:
        await query.message.reply_text("❌ ጥያቄው አልተገኘም።")
        return
    
    if not is_admin and listing.get('user_chat_id') != user_id:
        await query.message.reply_text("⛔ ይህን የማጥፋት ፈቃድ የለዎትም!")
        return
    
    success = update_listing_status(req_id, 'deleted')
    if success:
        await query.edit_message_text(
            f"🗑️ **ጥያቄ #{req_id} ተሰርዟል**\n👤 {update.effective_user.first_name}",
            parse_mode="Markdown"
        )

async def nohave_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    req_id = query.data.split("_")[2]
    await query.message.reply_text(f"ℹ️ **ጥያቄ #{req_id} አልፎታል።**", parse_mode="Markdown")

# ==============================================================================
# 19. SUPPORT HANDLER
# ==============================================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📞 **Adika Marketplace - ድጋፍ**

❓ **እንዴት መጠቀም?**

1️⃣ **መግዛት/መከራየት** - ፍላጎትዎን ይመዝግቡ
2️⃣ **መሸጥ/ማከራየት** - ንብረትዎን ያስተዋውቁ
3️⃣ **የደላሎች ማውጫ** - የተረጋገጡ ደላሎችን ይፈልጉ

📲 ለተጨማሪ እርዳታ አድሚንን ያግኙ።
"""
    keyboard = [[InlineKeyboardButton("💬 አድሚን", url="https://t.me/Adika_Admin")]]
    await update.message.reply_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ==============================================================================
# 20. MAIN ENGINE
# ==============================================================================

def main():
    """ዋና የBot አስኬጀር"""
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Common cancel handler
    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)
    
    # Buyer Conversation
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
        states={
            BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_message_handler],
            BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_"), cancel_message_handler],
            BUYER_SUB: [CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_"), cancel_message_handler],
            BUYER_PROPERTY: [CallbackQueryHandler(buyer_property_chosen, pattern="^flow_buy_prop_"), cancel_message_handler],
            BUYER_HTYPE: [CallbackQueryHandler(buyer_htype_chosen, pattern="^flow_buy_htype_"), cancel_message_handler],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details), cancel_message_handler],
            BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    # Seller Conversation
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_"), cancel_message_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_message_handler],
            SELLER_SUB: [CallbackQueryHandler(seller_sub_chosen, pattern="^flow_sell_sub_"), cancel_message_handler],
            SELLER_PROPERTY: [CallbackQueryHandler(seller_property_chosen, pattern="^flow_sell_prop_"), cancel_message_handler],
            SELLER_HTYPE: [CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_"), cancel_message_handler],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details), cancel_message_handler],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price), cancel_message_handler],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone), cancel_message_handler],
            SELLER_PHOTO: [MessageHandler(filters.PHOTO | filters.TEXT, seller_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    # Broker Registration Conversation
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ/ደላላ መመዝገብ$"), broker_reg_start)],
        states={
            BROKER_ROLE: [CallbackQueryHandler(broker_role_chosen, pattern="^role_"), cancel_message_handler],
            BROKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name), cancel_message_handler],
            BROKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone), cancel_message_handler],
            BROKER_SUBCITY: [CallbackQueryHandler(broker_reg_subcity, pattern="^broker_sc_"), cancel_message_handler],
            BROKER_NID_PHOTO: [MessageHandler(filters.PHOTO | filters.TEXT, broker_reg_nid_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    # Broker Response Conversation
    broker_response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broker_have_item_click, pattern="^have_item_")],
        states={
            BROKER_OFFER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text), cancel_message_handler],
            BROKER_OFFER_PHOTO: [MessageHandler(filters.PHOTO | filters.TEXT, broker_offer_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )
    
    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(broker_response_conv)
    
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
    app.add_handler(MessageHandler(filters.Regex("^🛍️ የገበያ ቦታ"), view_public_marketplace))
    app.add_handler(MessageHandler(filters.Regex("^👥 የደላሎች"), view_brokers_directory))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(cancel_message_handler)
    
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(admin_approval_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(delete_request_callback, pattern="^delete_item_"))
    app.add_handler(CallbackQueryHandler(nohave_item_callback, pattern="^nohave_item_"))
    app.add_handler(CallbackQueryHandler(filter_brokers_by_subcity_callback, pattern="^dir_sc_"))
    
    logger.info("🚀 Adika Marketplace Bot started successfully!")
    app.run_polling()

if __name__ == "__main__":
    main()