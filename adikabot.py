import logging
import os
import threading
import re
import asyncio  # ✅ ይህን ይጨምሩ
from typing import Optional, List, Dict, Any
from datetime import datetime  # ✅ date አያስፈልግም
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template_string, request, jsonify  # ✅ render_template_string, request, jsonify ተጨምረዋል
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
# 0. FLASK WEB SERVER & WEBAPP ROUTES
# ==============================================================================
import os
import asyncio
from flask import Flask, request, jsonify, render_template_string

web_app = Flask(__name__)

# SELLER WEBAPP HTML TEMPLATE
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

# BUYER WEBAPP HTML TEMPLATE
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

@web_app.route('/')
def home():
    return "✅ Adika Marketplace Bot በስኬት እየሰራ ይገኛል!", 200

@web_app.route('/seller-form', endpoint='webapp_seller_form')
def webapp_seller_form():
    return render_template_string(SELLER_FORM_HTML)

@web_app.route('/buyer-form', endpoint='webapp_buyer_form')
def webapp_buyer_form():
    return render_template_string(BUYER_FORM_HTML)

@web_app.route('/api/submit-listing', methods=['POST'])
def submit_listing():
    data = request.json
    print(f"New Listing Received: {data}")
    return jsonify({"status": "success"})
@web_app.route('/api/submit-request', methods=['POST'], endpoint='api_submit_request')
def api_submit_request():
    data = request.json
    user_id = data.get('user_id')
    category = data.get('category', 'መኪና')
    budget = data.get('budget', '')
    details = data.get('details', '')
    phone = data.get('phone', '')

    if not user_id or user_id == "unknown":
        return jsonify({"status": "error", "message": "User ID አልተገኘም"}), 400

    full_desc = (
        f"📌 **አዲስ የ{category} ጥያቄ (በ WebApp የተሞላ)**\n"
        f"💰 በጀት: {budget} ብር\n"
        f"📝 ዝርዝር: {details}\n"
        f"📞 ስልክ: {phone}"
    )

    req_id = add_listing(user_id, "WebApp User", 'BUY', category, '', 'መግዛት', '', full_desc)

    if req_id:
        notification_text = (
            f"🔔 **አዲስ የ{category} ጥያቄ! (#REQ-{req_id})**\n\n"
            f"{full_desc}\n\n"
            f"👉 ይህ ንብረት በእጅዎ ካለ ከታች **'አለኝ'** የሚለውን በመጫን ለፈላጊው መረጃ ይላኩ!"
        )
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(notify_brokers(bot_app, notification_text, req_id, user_id))
            loop.close()
        except Exception as e:
            print(f"Error notifying brokers: {e}")

        return jsonify({"status": "success", "req_id": req_id})
    
    return jsonify({"status": "error", "message": "መረጃውን መመዝገብ አልተቻለም"}), 500

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)
# ==============================================================================
# BUYER WEBAPP FORM & ROUTE
# ==============================================================================
BUYER_FORM_HTML = """
<!DOCTYPE html>
<html>
<head>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 p-4">
    <div class="max-w-md mx-auto bg-white p-6 rounded-xl shadow-md">
        <h2 class="text-xl font-bold mb-4 text-center">የሚፈልጉትን ንብረት ይግለጹ</h2>
        <form id="buyerForm" class="space-y-4">
            <select id="category" class="w-full p-2 border rounded">
                <option value="መኪና">መኪና</option>
                <option value="ቤት">ቤት</option>
            </select>
            <input type="text" id="budget" placeholder="የተመደበ በጀት (በብር)" class="w-full p-2 border rounded" required>
            <textarea id="details" placeholder="የሚፈልጉት ንብረት ዝርዝር መግለጫ" class="w-full p-2 border rounded" required></textarea>
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

@web_app.route('/buyer-form')
def buyer_form():
    return render_template_string(BUYER_FORM_HTML)

@web_app.route('/api/submit-request', methods=['POST'])
def submit_request():
    data = request.json
    print(f"New Buyer Request Received: {data}")
    return jsonify({"status": "success"})
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

import os
import re
import logging
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_FILE = "adika_marketplace.db"

# ==============================================================================
# 2. CONSTANTS & KEYBOARDS
# ==============================================================================

MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["🛍️ የገበያ ቦታ (የሚሸጡ)", "📋 የፈላጊዎች ዝርዝር"],
    ["👥 የደላሎች/አቅራቢዎች ማውጫ", "📝 እንደ አቅራቢ/ደላላ መመዝገብ"],
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
# HELPER FUNCTIONS
# ==============================================================================

def validate_phone(phone: str) -> bool:
    """Validate Ethiopian phone number formats (09..., 07..., +251...)"""
    pattern = r"^(?:\+251|0)[79]\d{8}$"
    return bool(re.match(pattern, phone.strip()))


def get_db_connection():
    """Create and return connection for PostgreSQL (if URL exists) or SQLite"""
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        conn.autocommit = True
        return conn
    else:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn
        
async def delete_request_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """ጥያቄን ለማጥፋት - ለባለቤቱ እና ለአድሚን ብቻ"""
    query = update.callback_query
    await query.answer()

    req_id_str = query.data.replace("delete_req_", "")
    if not req_id_str.isdigit():
        await query.message.reply_text("❌ የተሳሳተ የጥያቄ መታወቂያ (ID)።")
        return

    req_id = int(req_id_str)
    listing = get_listing_by_id(req_id)

    if not listing:
        await query.message.reply_text("❌ ጥያቄው አልተገኘም ወይም አስቀድሞ ተሰርዟል።")
        return

    user_id = query.from_user.id
    is_owner = listing.get("user_chat_id") == user_id
    is_admin = user_id == ADMIN_CHAT_ID_INT

    if not (is_owner or is_admin):
        await query.answer(
            "⛔ ይህን ጥያቄ ለማጥፋት ፈቃድ የለዎትም!", show_alert=True
        )
        return

    success = update_listing_status(req_id, "deleted")
    if success:
        try:
            await query.edit_message_text(
                f"🗑️ **ጥያቄ #{req_id} በስኬት ተሰርዟል።**",
                parse_mode="Markdown",
            )
        except Exception:
            await query.message.reply_text(
                f"🗑️ **ጥያቄ #{req_id} በስኬት ተሰርዟል።**",
                parse_mode="Markdown",
            )
    else:
        await query.message.reply_text(
            "❌ ጥያቄውን ማጥፋት አልተቻለም። እባክዎ እንደገና ይሞክሩ።"
        )
# ==============================================================================
# SECTION 1: DATABASE INITIALIZATION
# ==============================================================================

def init_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if DATABASE_URL:
            # PostgreSQL Tables
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
            """)
        else:
            # SQLite Tables
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
                    price TEXT,
                    phone TEXT,
                    photo_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS brokers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    role_type TEXT NOT NULL,
                    national_id_photo TEXT,
                    sub_city TEXT NOT NULL,
                    rating REAL DEFAULT 5.0,
                    total_ratings INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker_chat_id INTEGER NOT NULL,
                    user_chat_id INTEGER NOT NULL,
                    stars INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS broker_offers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id INTEGER NOT NULL,
                    broker_id INTEGER NOT NULL,
                    description TEXT,
                    photo_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
            
        logging.info("✅ Adika Database initialized with Ratings and Marketplace Support")
        
    except Exception as e:
        logging.error(f"❌ Database initialization error: {e}")
        if conn and not DATABASE_URL:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# ==============================================================================
# SECTION 3: DATABASE UTILITIES & OPERATIONS
# ==============================================================================

def add_broker(chat_id: int, full_name: str, phone: str, role_type: str, national_id_photo: str, sub_city: str):
    """Insert or update a broker record"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if DATABASE_URL:
            cursor.execute("""
                INSERT INTO brokers (chat_id, full_name, phone, role_type, national_id_photo, sub_city, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                ON CONFLICT (chat_id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    phone = EXCLUDED.phone,
                    role_type = EXCLUDED.role_type,
                    national_id_photo = EXCLUDED.national_id_photo,
                    sub_city = EXCLUDED.sub_city,
                    status = 'pending';
            """, (chat_id, full_name, phone, role_type, national_id_photo, sub_city))
        else:
            cursor.execute("""
                INSERT INTO brokers (chat_id, full_name, phone, role_type, national_id_photo, sub_city, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                ON CONFLICT(chat_id) DO UPDATE SET
                    full_name = excluded.full_name,
                    phone = excluded.phone,
                    role_type = excluded.role_type,
                    national_id_photo = excluded.national_id_photo,
                    sub_city = excluded.sub_city,
                    status = 'pending';
            """, (chat_id, full_name, phone, role_type, national_id_photo, sub_city))
            conn.commit()
        return True
    except Exception as e:
        logging.error(f"Database error in add_broker: {e}")
        return False
    finally:
        if conn:
            conn.close()


def get_broker(chat_id: int):
    """Fetch broker details by chat_id"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM brokers WHERE chat_id = %s" if DATABASE_URL else "SELECT * FROM brokers WHERE chat_id = ?"
        cursor.execute(query, (chat_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logging.error(f"Database error in get_broker: {e}")
        return None
    finally:
        if conn:
            conn.close()


def update_broker_status(chat_id: int, status: str) -> bool:
    """Update approval status of a broker ('approved', 'rejected', 'pending')"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("UPDATE brokers SET status = %s WHERE chat_id = %s", (status.lower(), chat_id))
        else:
            cursor.execute("UPDATE brokers SET status = ? WHERE chat_id = ?", (status.lower(), chat_id))
            conn.commit()
        return True
    except Exception as e:
        logging.error(f"Database error in update_broker_status: {e}")
        return False
    finally:
        if conn:
            conn.close()


def save_broker_offer(request_id: int, broker_id: int, description: str, photo_id: str = None) -> bool:
    """Save a broker's response/offer for a listing request"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("""
                INSERT INTO broker_offers (request_id, broker_id, description, photo_id)
                VALUES (%s, %s, %s, %s)
            """, (request_id, broker_id, description, photo_id))
        else:
            cursor.execute("""
                INSERT INTO broker_offers (request_id, broker_id, description, photo_id)
                VALUES (?, ?, ?, ?)
            """, (request_id, broker_id, description, photo_id))
            conn.commit()
        return True
    except Exception as e:
        logging.error(f"Database error in save_broker_offer: {e}")
        return False
    finally:
        if conn:
            conn.close()


def get_listing_by_id(listing_id: int):
    """Fetch a single listing by its ID"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM listings WHERE id = %s" if DATABASE_URL else "SELECT * FROM listings WHERE id = ?"
        cursor.execute(query, (listing_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        logging.error(f"Database error in get_listing_by_id: {e}")
        return None
    finally:
        if conn:
            conn.close()
# ==============================================================================
# SECTION 1: BUYER REQUEST CARD FORMATTER
# ==============================================================================
def format_buyer_card(req: dict) -> str:
    """የፈላጊዎችን ጥያቄ በፅዳት አዘጋጅቶ የሚያቀርብ ፈንክሽን"""
    req_id = req.get('id', 'N/A')
    main_cat = req.get('main_category', '')
    action_type = req.get('action_type', '')
    sub_cat = req.get('sub_category', 'ያልተጠቀሰ')
    prop_type = req.get('property_type', 'ያልተጠቀሰ')
    desc = req.get('description', '')
    phone = req.get('phone', 'መረጃው አልተያያዘም')
    
    icon = "🚗" if main_cat == "መኪና" else "🏠"
    
    card = (
        f"{icon} **[ፈላጊ - #{req_id}]**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📌 **ዘርፍ፦** {main_cat} ({action_type})\n"
        f"🏷️ **ዓይነት፦** {sub_cat} | {prop_type}\n"
        f"📝 **ዝርዝር ፍላጎት፦**\n_{desc}_\n\n"
        f"📞 **የፈላጊው ስልክ፦** `{phone}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 *ደላላ ከሆኑና ይህ ንብረት በእጅዎ ካለ ከታች ያለውን አዝራር ይጫኑ።*"
    )
    return card
# ==============================================================================
# SECTION 2: SELLER ITEM CARD FORMATTER
# ==============================================================================
def format_seller_card(item: dict) -> str:
    """ለሽያጭ/ኪራይ የቀረበን ንብረት አደራጅቶ የሚያቀርብ ፈንክሽን"""
    item_id = item.get('id', 'N/A')
    main_cat = item.get('main_category', '')
    action_type = item.get('action_type', '')
    sub_cat = item.get('sub_category', '-')
    desc = item.get('description', '')
    price = item.get('price', 'በድርድር')
    phone = item.get('phone', '-')
    
    icon = "🚗" if main_cat == "መኪና" else "🏠"
    tag = "🔴 ለሽያጭ" if action_type == "መሸጥ" else "🔵 ለኪራይ"
    
    card = (
        f"{icon} **[ለገበያ የቀረበ - #{item_id}]** {tag}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 **አይነት፦** {main_cat} ({sub_cat})\n"
        f"💰 **ዋጋ፦** `{price}`\n\n"
        f"📋 **መግለጫ፦**\n_{desc}_\n\n"
        f"📞 **የባለቤቱ/አቅራቢው ስልክ፦** `{phone}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"✨ *ለበለጠ መረጃ በስልክ ቁጥሩ በቀጥታ ይደውሉ።*"
    )
    return card
# ==============================================================================
# ==============================================================================
# UPDATED SECTION 3: HANDLERS USING NEW CARD FORMATTERS
# ==============================================================================
async def view_public_marketplace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """የሚሸጡ ንብረቶችን በአዲሱ የካርድ ዲዛይን የሚያሳይ"""
    items = get_public_marketplace_items(limit=10)
    
    if not items:
        await update.message.reply_text("📭 በአሁኑ ሰዓት ለሽያጭ/ኪራይ የቀረቡ ንብረቶች የሉም።")
        return

    await update.message.reply_text("🛍️ **ለሽያጭ እና ለኪራይ የቀረቡ ንብረቶች ዝርዝር፦**", parse_mode="Markdown")
    
    for item in items:
        card_text = format_seller_card(item)  # አዲሱን የካርድ ዲዛይን አገናኘነው
        photo_id = item.get('photo_id')
        
        if photo_id:
            try:
                await update.message.reply_photo(photo=photo_id, caption=card_text, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(card_text, parse_mode="Markdown")
        else:
            await update.message.reply_text(card_text, parse_mode="Markdown")

async def filter_brokers_by_subcity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """የደላሎችን ዝርዝር በአዲሱ የፕሮፋይል ካርድ ዲዛይን የሚያሳይ"""
    query = update.callback_query
    await query.answer()
    
    sub_city = query.data.replace("dir_sc_", "")
    brokers = get_approved_brokers_directory(sub_city=sub_city)
    
    if not brokers:
        await query.edit_message_text(f"📭 በ{sub_city} ክፍለ ከተማ የተመዘገቡ ደላሎች አልተገኙም።")
        return

    msg = f"📋 **የተረጋገጡ ደላሎች ዝርዝር ({sub_city})፦**\n━━━━━━━━━━━━━━━━━━━\n\n"
    for b in brokers:
        msg += format_broker_profile(b) + "\n\n"  # አዲሱን የደላላ ፕሮፋይል ዲዛይን አገናኘነው
        
    await query.edit_message_text(msg, parse_mode="Markdown")

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ==============================================================================
# SECTION 4: INLINE NAVIGATION & PAGINATION HELPERS
# ==============================================================================


def get_nav_buttons(back_callback: str = None) -> list:
    buttons = []
    if back_callback:
        buttons.append(
            InlineKeyboardButton("⬅️ ተመለስ", callback_data=back_callback)
        )
    buttons.append(
        InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")
    )
    return buttons


def build_request_keyboard(
    req_id: int, back_callback: str = None
) -> InlineKeyboardMarkup:
    """የጥያቄ ዝርዝር ማሳያ ቁልፎችን ከነ ማጥፊያው አዘጋጅቶ ይመልሳል"""
    keyboard = [
        [
            InlineKeyboardButton(
                "🗑️ ጥያቄውን አጥፋ", callback_data=f"delete_req_{req_id}"
            )
        ],
        get_nav_buttons(back_callback),
    ]
    return InlineKeyboardMarkup(keyboard)


def build_pagination_keyboard(
    current_page: int, total_pages: int, prefix: str
) -> InlineKeyboardMarkup:
    nav_row = []

    if current_page > 1:
        nav_row.append(
            InlineKeyboardButton(
                "◀️ ቀዳሚ", callback_data=f"{prefix}_page_{current_page - 1}"
            )
        )

    nav_row.append(
        InlineKeyboardButton(
            f"📄 {current_page}/{total_pages}", callback_data="ignore"
        )
    )

    if current_page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                "ቀጣይ ▶️", callback_data=f"{prefix}_page_{current_page + 1}"
            )
        )

    keyboard = [nav_row, get_nav_buttons()]
    return InlineKeyboardMarkup(keyboard)
# ==============================================================================
# SECTION 5: MARKETPLACE PAGINATION CALLBACK
# ==============================================================================
async def marketplace_pagination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """የገበያ ቦታ ገጾችን የሚያላቅቅ Handler"""
    query = update.callback_query
    await query.answer()
    
    # ከ callback_data ላይ የገጽ ቁጥሩን መለየት (ለምሳሌ: market_page_2)
    try:
        page = int(query.data.split("_")[-1])
    except ValueError:
        page = 1
        
    items_per_page = 5
    offset = (page - 1) * items_per_page
    
    items = get_public_marketplace_items(limit=items_per_page, offset=offset)
    
    if not items:
        await query.edit_message_text("📭 በዚህ ገጽ ላይ ምንም ንብረት አልተገኘም።")
        return

    await query.message.reply_text(f"🛍️ **ለሽያጭ/ኪራይ የቀረቡ (ገጽ {page})፦**", parse_mode="Markdown")
    
    for item in items:
        card_text = format_seller_card(item)
        photo_id = item.get('photo_id')
        
        if photo_id:
            try:
                await query.message.reply_photo(photo=photo_id, caption=card_text, parse_mode="Markdown")
            except Exception:
                await query.message.reply_text(card_text, parse_mode="Markdown")
        else:
            await query.message.reply_text(card_text, parse_mode="Markdown")

# 1. DATABASE CONNECTION
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

# 2. DATABASE INITIALIZATION
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
                    description TEXT NOT NULL,
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
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

# 3. REGISTER BROKER
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

# 4. GET BROKER
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

# 5. UPDATE BROKER STATUS
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

# 6. GET APPROVED BROKERS
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

# 7. ADD LISTING
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

# 8. GET LISTINGS
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
        logging.error(f"Get listings error: {e}")
        return []
    finally:
        if conn:
            conn.close()

# 9. COUNT LISTINGS
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

# 10. GET LISTING BY ID
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

# 11. UPDATE LISTING STATUS
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
# SECTION 2: NEW DATABASE UTILITIES
# ==============================================================================
def get_public_marketplace_items(main_category=None, limit=10, offset=0):
    """የሚሸጡ ወይም የሚያከራዩ ንብረቶችን ለተጠቃሚዎች ለማሳየት የሚያወጣ ፈንክሽን"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor) if DATABASE_URL else conn.cursor()
        p = get_placeholder()
        
        if main_category:
            query = f"SELECT * FROM listings WHERE req_type = 'SELL' AND status = 'pending' AND main_category = {p} ORDER BY created_at DESC LIMIT {p} OFFSET {p}"
            cursor.execute(query, (main_category, limit, offset))
        else:
            query = f"SELECT * FROM listings WHERE req_type = 'SELL' AND status = 'pending' ORDER BY created_at DESC LIMIT {p} OFFSET {p}"
            cursor.execute(query, (limit, offset))
            
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Get public marketplace items error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_approved_brokers_directory(sub_city=None):
    """የተረጋገጡ ደላሎችን በክፍለ ከተማ እና በRating ለይቶ የሚያወጣ ፈንክሽን"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor) if DATABASE_URL else conn.cursor()
        p = get_placeholder()
        
        if sub_city and sub_city != "ሁሉም":
            query = f"SELECT full_name, phone, role_type, sub_city, rating FROM brokers WHERE status = 'approved' AND sub_city = {p} ORDER BY rating DESC"
            cursor.execute(query, (sub_city,))
        else:
            query = "SELECT full_name, phone, role_type, sub_city, rating FROM brokers WHERE status = 'approved' ORDER BY rating DESC"
            cursor.execute(query)
            
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Get approved brokers directory error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def add_broker_rating(broker_chat_id, user_chat_id, stars):
    """ለደላላ Rating መስጫ እና አማካኝ ማሰሊያ ፈንክሽን"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        # 1. Add new rating entry
        cursor.execute(
            f"INSERT INTO ratings (broker_chat_id, user_chat_id, stars) VALUES ({p}, {p}, {p})",
            (broker_chat_id, user_chat_id, stars)
        )
        
        # 2. Recalculate average rating
        cursor.execute(
            f"SELECT AVG(stars), COUNT(*) FROM ratings WHERE broker_chat_id = {p}",
            (broker_chat_id,)
        )
        avg_stars, total_count = cursor.fetchone()
        
        # 3. Update broker table
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
# SECTION 3: PUBLIC MARKETPLACE & BROKER DIRECTORY HANDLERS
# ==============================================================================
async def view_public_marketplace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ተጠቃሚዎች የሚሸጡ ንብረቶችንና መኪኖችን የሚያዩበት ክፍል"""
    items = get_public_marketplace_items(limit=10)
    
    if not items:
        await update.message.reply_text(
            "📭 **በአሁኑ ሰዓት ለሽያጭ/ኪራይ የቀረቡ ንብረቶች የሉም።**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return

    await update.message.reply_text("🛍️ **ለሽያጭ እና ለኪራይ የቀረቡ ንብረቶች ዝርዝር፦**", parse_mode="Markdown")
    
    for item in items:
        desc = item.get('description', '')
        photo_id = item.get('photo_id')
        
        if photo_id:
            try:
                await update.message.reply_photo(photo=photo_id, caption=desc, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(desc, parse_mode="Markdown")
        else:
            await update.message.reply_text(desc, parse_mode="Markdown")

async def view_brokers_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """የተመዘገቡ አቅራቢዎችን እና ደላሎችን ዝርዝር የሚያሳይ ክፍል"""
    keyboard = [[InlineKeyboardButton(sc, callback_data=f"dir_sc_{sc}")] for sc in SUB_CITIES]
    keyboard.append([InlineKeyboardButton("🌐 የሁሉም ክፍለ ከተሞች", callback_data="dir_sc_ሁሉም")])
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await update.message.reply_text(
        "📍 **የደላሎችና አቅራቢዎች ማውጫ**\n\nእባክዎን ማየት የሚፈልጉበትን ክፍለ ከተማ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def filter_brokers_by_subcity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    sub_city = query.data.replace("dir_sc_", "")
    brokers = get_approved_brokers_directory(sub_city=sub_city)
    
    if not brokers:
        await query.edit_message_text(f"📭 በ{sub_city} ክፍለ ከተማ የተመዘገቡ ደላሎች አልተገኙም።")
        return

    msg = f"📋 **የተረጋገጡ ደላሎች ዝርዝር ({sub_city})፦**\n━━━━━━━━━━━━━━━━━━━\n\n"
    for b in brokers:
        stars = "⭐" * int(b['rating'])
        msg += (
            f"👤 **ስም፦** {b['full_name']}\n"
            f"🎭 **ሚና፦** {b['role_type']}\n"
            f"📍 **ክፍለ ከተማ፦** {b['sub_city']}\n"
            f"📞 **ስልክ፦** `{b['phone']}`\n"
            f" ደረጃ፦ {b['rating']}/5.0 {stars}\n"
            f"───────────────────\n"
        )
        
    await query.edit_message_text(msg, parse_mode="Markdown")

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

import logging
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters,
)

logger = logging.getLogger(__name__)

# State Constants
BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO = range(2)


# ==============================================================================
# 7. BUYER FLOW (ፈላጊ) - የተሻሻለ (Web App Integration)
# ==============================================================================

async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    
    web_app_url = "https://adika-vrkk.onrender.com/buyer-form"
    
    keyboard = [
        [InlineKeyboardButton("🌐 በፎርም በፍጥነት ለመሙላት (WebApp)", web_app=WebAppInfo(url=web_app_url))],
        [InlineKeyboardButton("🚗 መኪና", callback_data="flow_buy_cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ", callback_data="flow_buy_cat_house")],
        [InlineKeyboardButton("🏢 የሥራ ቦታ / ንግድ", callback_data="flow_buy_cat_commercial")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🔍 **የሚፈልጉትን ምድብ ይምረጡ፦**\n\n"
        "💡 *በአንድ ገጽ ላይ በቀላሉ ለመሙላት 'በፎርም በፍጥነት ለመሙላት' የሚለውን አዝራር መጠቀም ይችላሉ።*",
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
    return BUYER_HTYPE


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
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
)

logger = logging.getLogger(__name__)

# State Constants
BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO = range(2)

# ==============================================================================
# 11. BROKER OFFER FLOW (የደላሎች "አለኝ" ምላሽ ሂደት)
# ==============================================================================

async def broker_have_item_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broker clicking 'Have Item' / 'አለኝ' button"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    broker = get_broker(user_id)
    
    if not broker or broker.get('status') != 'approved':
        await query.message.reply_text(
            "⛔ **ይህን ማድረግ የሚችሉት በአድሚን የተረጋገጡ ደላሎች/አቅራቢዎች ብቻ ናቸው!**",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
        
    parts = query.data.split('_')
    if len(parts) < 2:
        await query.message.reply_text("❌ የተሳሳተ መረጃ ተላኳል።")
        return ConversationHandler.END
        
    req_id = parts[1]
    
    # buyer_id ከ callback_data ካለ ወይም ከ database መውሰድ
    buyer_id = parts[2] if len(parts) >= 3 else None
    if not buyer_id:
        listing = get_listing_by_id(int(req_id)) if req_id.isdigit() else None
        if listing:
            buyer_id = listing.get('user_chat_id') or listing.get('user_id')

    if not buyer_id:
        await query.message.reply_text("❌ የፈላጊው መረጃ አልተገኘም።")
        return ConversationHandler.END
    
    context.user_data['target_req_id'] = req_id
    context.user_data['target_buyer_id'] = buyer_id
    
    await query.message.reply_text(
        f"✅ **ጥያቄ #{req_id}**\n\n"
        f"✍️ **ያለዎትን ንብረት ዝርዝር መረጃ እና ዋጋ ያስገቡ፦**\n"
        f"(ለምሳሌ፦ ቶዮታ ቪትዝ 2021፣ 30,000 KM የሄደ፣ ዋጋ 2.4 ሚሊዮን፣ ስልክ 0911...)",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
        parse_mode="Markdown"
    )
    return BROKER_OFFER_TEXT


async def broker_offer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive offer description text from broker"""
    text = update.message.text
    
    if text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
        
    context.user_data['offer_text'] = text
    
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ይላኩ፦**\n\n(ፎቶ ከሌልዎት 'ፎቶ የለውም' ብለው ይጻፉ)",
        reply_markup=ReplyKeyboardMarkup([["ፎቶ የለውም"], ["🏠 ዋና ገጽ"]], resize_keyboard=True),
        parse_mode="Markdown"
    )
    return BROKER_OFFER_PHOTO


async def broker_offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive offer photo (or text skip) and deliver offer to buyer"""
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    raw_buyer_id = context.user_data.get('target_buyer_id')
    req_id = context.user_data.get('target_req_id')
    offer_text = context.user_data.get('offer_text')
    
    if not raw_buyer_id or not req_id or not offer_text:
        await update.message.reply_text(
            "❌ የሂደት ስህተት ተከሰቷል። እባክዎ እንደገና ይሞክሩ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return ConversationHandler.END
        
    buyer_id = int(raw_buyer_id)
    broker_user = update.effective_user
    broker_name = broker_user.first_name or "ደላላ/አቅራቢ"
    
    broker = get_broker(broker_user.id)
    broker_phone = broker.get('phone', 'አልተጠቀሰም') if broker else 'አልተጠቀሰም'
    
    message_to_buyer = (
        f"🎉 **ለጥያቄዎ (#REQ-{req_id}) አዲስ የቀረበ አማራጭ አለ!**\n\n"
        f"👤 **ደላላ/አቅራቢ፦** {broker_name}\n"
        f"📞 **ስልክ፦** {broker_phone}\n"
        f"📝 **የንብረቱ ዝርዝር፦**\n{offer_text}\n\n"
        f"💡 *ከፈለጉ ደውለው መገበያየት ይችላሉ!*"
    )
    
    try:
        photo_id = update.message.photo[-1].file_id if (update.message and update.message.photo) else None
        
        # ኦፈሩን በዳታቤዝ ውስጥ መዝግቦ መያዝ
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
            "✅ **መረጃዎ ለፈላጊው በስኬት ተልኳል!**\n\n"
            "📌 ጥያቄው በ'📋 የፈላጊዎች ዝርዝር' ውስጥ እንደበፊቱ ይቀመጣል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send offer to buyer {buyer_id}: {e}")
        await update.message.reply_text(
            "❌ መረጃውን ለፈላጊው መላክ አልተቻለም።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
    context.user_data.pop('target_req_id', None)
    context.user_data.pop('target_buyer_id', None)
    context.user_data.pop('offer_text', None)
    
    return ConversationHandler.END


async def nohave_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Not Have' button click - broker doesn't have the item"""
    query = update.callback_query
    
    user_id = query.from_user.id
    broker = get_broker(user_id)
    
    if not broker or broker.get('status') != 'approved':
        await query.answer("⛔ ይህን ማድረግ የሚችሉት በአድሚን የተረጋገጡ ደላሎች/አቅራቢዎች ብቻ ናቸው!", show_alert=True)
        return

    parts = query.data.split('_')
    if len(parts) < 2:
        await query.answer("❌ የተሳሳተ መረጃ ተላኳል።", show_alert=True)
        return

    req_id = parts[1]
    await query.answer(f"ℹ️ ጥያቄ #{req_id} አልፎታል።", show_alert=False)

    formatted_req_id = f"#{int(req_id):04d}" if req_id.isdigit() else f"#{req_id}"

    await query.message.reply_text(
        f"ℹ️ **ጥያቄ {formatted_req_id} አልፎታል።**\n\n"
        f"💡 ሌላ አዲስ ጥያቄ ለማየት '📋 የፈላጊዎች ዝርዝር' የሚለውን ይጫኑ።",
        parse_mode="Markdown"
    )
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update, WebAppInfo
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    CommandHandler,
    filters,
)

logger = logging.getLogger(__name__)

# State Constants
(
    BROKER_ROLE,
    BROKER_NAME,
    BROKER_PHONE,
    BROKER_SUBCITY,
    BROKER_NID_PHOTO,
    BROKER_OFFER_TEXT,
    BROKER_OFFER_PHOTO,
) = range(7)


# ==============================================================================
# 9. SELLER FLOW (መሸጥ / ማከራየት) - የተስተካከለ
# ==============================================================================

async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    
    web_app_url = "https://adika-vrkk.onrender.com/seller-form"
    
    keyboard = [
        [InlineKeyboardButton("🌐 በፎርም በፍጥነት ለመሙላት (WebApp)", web_app=WebAppInfo(url=web_app_url))],
        [InlineKeyboardButton("🚗 መኪና", callback_data="flow_sell_cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ", callback_data="flow_sell_cat_house")],
        [InlineKeyboardButton("🏢 የሥራ ቦታ / ንግድ", callback_data="flow_sell_cat_commercial")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "📢 **የሚሸጡትን ወይም የሚያከራዩትን ምድብ ይምረጡ፦**\n\n"
        "💡 *በአንድ ገጽ ላይ በቀላሉ ለመሙላት 'በፎርም በፍጥነት ለመሙላት' የሚለውን አዝራር መጠቀም ይችላሉ።*",
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
    return SELLER_HTYPE


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
    await update.message.reply_text("📸 **የንብረቱን ፎቶ ይላኩ (ወይም 'ዝለል' የሚለውን ይጻፉ)፦**", parse_mode="Markdown")
    return SELLER_PHOTO


async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
        
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    
    if not photo_id:
        await update.message.reply_text("📸 **ፎቶ አልተላከም**\n\nያለ ፎቶ ማስታወቂያዎን በመመዝገብ ላይ ይገኛል...")
    
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
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        
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
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
    
    return ConversationHandler.END
# ==============================================================================
# 10. BROKER REGISTRATION (የተስተካከለ)
# ==============================================================================

async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start broker/supplier registration process"""
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
    """Handle role selection callback"""
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
    
    await query.edit_message_text(
        f"👤 **ምዝገባ፦ {role}**\n\n1️⃣ ሙሉ ስምዎን ያስገቡ፦",
        parse_mode="Markdown"
    )
    return BROKER_NAME


async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive broker full name"""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
        
    context.user_data['broker_name'] = update.message.text
    await update.message.reply_text(
        "2️⃣ **የስልክ ቁጥርዎን ያስገቡ፦**",
        parse_mode="Markdown"
    )
    return BROKER_PHONE


async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive broker phone number"""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(update.message.text):
        await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ። (ለምሳሌ፦ 0911223344)")
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
    """Handle subcity selection callback"""
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    sub_city = query.data.replace("broker_sc_", "")
    context.user_data['broker_subcity'] = sub_city
    
    await query.edit_message_text(
        "4️⃣ **የፋይዳ (National ID) ወይም የነዋሪነት መታወቂያ ፎቶ ያንሱና ይላኩ፦**\n\n"
        "💡 *ይህ ለማረጋገጫ ብቻ ነው*",
        parse_mode="Markdown"
    )
    return BROKER_NID_PHOTO


async def broker_reg_nid_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive ID photo and submit registration"""
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    user = update.effective_user
    
    if not update.message or not update.message.photo:
        await update.message.reply_text(
            "❌ **እባክዎ የመታወቂያዎን ፎቶ ይላኩ!**\n\n"
            "📸 ፎቶውን ከቴሌግራም ፋይል አባሪ አማራጭ በመጠቀም ይላኩ።\n"
            "✏️ ጽሁፍ አይቀበልም።",
            parse_mode="Markdown"
        )
        return BROKER_NID_PHOTO
        
    existing_broker = get_broker(user.id)
    if existing_broker:
        await update.message.reply_text(
            "ℹ️ **አስቀድመው ተመዝግበዋል!**\n\n"
            f"👤 ስም: {existing_broker.get('full_name')}\n"
            f"📊 ሁኔታ: {existing_broker.get('status')}\n\n"
            "📌 ለውጥ ለማድረግ እባክዎን አድሚንን ያግኙ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        return ConversationHandler.END
        
    photo_id = update.message.photo[-1].file_id
    role = context.user_data.get('broker_role', 'አቅራቢ')
    name = context.user_data.get('broker_name', user.first_name)
    phone = context.user_data.get('broker_phone', '')
    sub_city = context.user_data.get('broker_subcity', '')
    
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
    
    broker_id = add_broker(user.id, name, phone, role, photo_id, sub_city)
    
    if broker_id:
        await update.message.reply_text(
            "✅ **ምዝገባዎ በስኬት ተጠናቋል!** 🎉\n\n"
            "⏳ አድሚኑ መረጃዎን ካረጋገጠ በኋላ ማስታወቂያ ይደርስዎታል።\n\n"
            "📋 ምዝገባዎ ከጸደቀ በኋላ '📋 የፈላጊዎች ዝርዝር' ማየት ይችላሉ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        
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
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        
    return ConversationHandler.END


# ==============================================================================
# CONVERSATION HANDLERS & REGISTRATIONS SETUP
# ==============================================================================

# 1. Broker Offer Flow ConversationHandler
broker_offer_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(broker_have_item_click, pattern=r"^have_item_")
    ],
    states={
        BROKER_OFFER_TEXT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text)
        ],
        BROKER_OFFER_PHOTO: [
            MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), broker_offer_photo)
        ],
    },
    fallbacks=[
        MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), go_home),
        CommandHandler("cancel", go_home),
    ],
    per_message=False,
)

# 2. Broker Registration ConversationHandler
broker_reg_conv_handler = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^📝 እንደ አቅራቢ/ደላላ መመዝገብ$"), broker_reg_start)
    ],
    states={
        BROKER_ROLE: [
            CallbackQueryHandler(broker_role_chosen, pattern=r"^role_"),
            CallbackQueryHandler(go_home, pattern=r"^flow_home$")
        ],
        BROKER_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name)
        ],
        BROKER_PHONE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone)
        ],
        BROKER_SUBCITY: [
            CallbackQueryHandler(broker_reg_subcity, pattern=r"^broker_sc_"),
            CallbackQueryHandler(go_home, pattern=r"^flow_home$")
        ],
        BROKER_NID_PHOTO: [
            MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, broker_reg_nid_photo)
        ],
    },
    fallbacks=[
        MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), go_home),
        CommandHandler("cancel", go_home),
    ],
    per_message=False,
)

# 3. App Dispatcher Registration Function
def register_broker_handlers(application):
    """Register all broker-related handlers to application"""
    application.add_handler(broker_reg_conv_handler)
    application.add_handler(broker_offer_conv_handler)
    application.add_handler(
        CallbackQueryHandler(nohave_item_callback, pattern=r"^nohave_item_")
    )
# ==============================================================================
# 11. ADMIN APPROVAL HANDLERS (የአድሚን ማፅደቂያ እና ማኔጅመንት)
# ==============================================================================

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes


async def admin_approve_broker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve a broker registration request"""
    query = update.callback_query
    await query.answer()

    # Security check: Admin only
    if update.effective_user.id != ADMIN_CHAT_ID_INT:
        await query.answer("⛔ ይህን ማድረግ የሚችሉት አድሚን ብቻ ናቸው!", show_alert=True)
        return

    broker_telegram_id = int(query.data.replace("admin_appr_", ""))

    # Update broker status in database
    success = update_broker_status(broker_telegram_id, status="approved")

    if success:
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n✅ **ሁኔታ፦ ተፀድቋል (Approved)**",
            parse_mode="Markdown",
        )

        # Notify the broker
        try:
            await context.bot.send_message(
                chat_id=broker_telegram_id,
                text=(
                    "🎉 **እንኳን ደስ አለዎት!**\n\n"
                    "የደላላ/አቅራቢ ምዝገባዎ በአድሚን ፀድቋል።\n"
                    "አሁን '📋 የፈላጊዎች ዝርዝር' በመጫን መስራት መጀመር ይችላሉ።"
                ),
                reply_markup=ReplyKeyboardMarkup(
                    MAIN_KEYBOARD, resize_keyboard=True
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(
                f"Failed to send approval notification to {broker_telegram_id}: {e}"
            )
    else:
        await query.message.reply_text("❌ የደላላውን ሁኔታ መቀየር አልተቻለም።")


async def admin_reject_broker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reject a broker registration request"""
    query = update.callback_query
    await query.answer()

    # Security check: Admin only
    if update.effective_user.id != ADMIN_CHAT_ID_INT:
        await query.answer("⛔ ይህን ማድረግ የሚችሉት አድሚን ብቻ ናቸው!", show_alert=True)
        return

    broker_telegram_id = int(query.data.replace("admin_reje_", ""))

    # Update status in database
    success = update_broker_status(broker_telegram_id, status="rejected")

    if success:
        await query.edit_message_caption(
            caption=f"{query.message.caption}\n\n❌ **ሁኔታ፦ ተሰርዟል (Rejected)**",
            parse_mode="Markdown",
        )

        # Notify the broker
        try:
            await context.bot.send_message(
                chat_id=broker_telegram_id,
                text=(
                    "❌ **የምዝገባ ጥያቄዎ ውድቅ ተደርጓል!**\n\n"
                    "እባክዎን ትክክለኛ መረጃ እና መታወቂያ በመጠቀም እንደገና ይመዝገቡ።"
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(
                f"Failed to send rejection notification to {broker_telegram_id}: {e}"
            )
    else:
        await query.message.reply_text("❌ የደላላውን ሁኔታ መቀየር አልተቻለም።")


async def admin_view_broker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View detailed info of a broker"""
    query = update.callback_query
    await query.answer()

    # Security check: Admin only
    if update.effective_user.id != ADMIN_CHAT_ID_INT:
        await query.answer("⛔ ይህን ማድረግ የሚችሉት አድሚን ብቻ ናቸው!", show_alert=True)
        return

    broker_telegram_id = int(query.data.replace("admin_view_", ""))
    broker_info = get_broker(broker_telegram_id)

    if broker_info:
        msg = (
            f"👤 <b>የአቅራቢ/ደላላ ዝርዝር መረጃ</b>\n\n"
            f"• <b>ስም:</b> {broker_info.get('full_name', 'N/A')}\n"
            f"• <b>ሚና:</b> {broker_info.get('role', 'N/A')}\n"
            f"• <b>ስልክ:</b> {broker_info.get('phone', 'N/A')}\n"
            f"• <b>ክፍለ ከተማ:</b> {broker_info.get('sub_city', 'N/A')}\n"
            f"• <b>ሁኔታ:</b> {broker_info.get('status', 'N/A')}\n"
            f"• <b>Telegram ID:</b> <code>{broker_telegram_id}</code>"
        )
        await query.message.reply_text(msg, parse_mode="HTML")
    else:
        await query.message.reply_text("❌ የደላላው መረጃ አልተገኘም።")


async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Master callback router for admin approval actions (^admin_)"""
    query = update.callback_query
    data = query.data

    if data.startswith("admin_appr_"):
        await admin_approve_broker(update, context)
    elif data.startswith("admin_reje_"):
        await admin_reject_broker(update, context)
    elif data.startswith("admin_view_"):
        await admin_view_broker(update, context)


def register_admin_approval_handlers(application):
    """Register admin approval callback handlers"""
    application.add_handler(
        CallbackQueryHandler(admin_approval_callback, pattern=r"^admin_")
    )
# ==============================================================================
# 12.5 DELETE REQUEST HANDLER (አዲስ ተጨምሯል)
# ==============================================================================
async def delete_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ጥያቄን ለማጥፋት - ለባለቤቱ እና ለአድሚን ብቻ"""
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
            f"🗑️ **ጥያቄ #{req_id} ተሰርዟል**\n\n"
            f"👤 በ: {update.effective_user.first_name}\n"
            f"📅 ቀን: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="Markdown"
        )
        
        await query.message.reply_text(
            f"✅ **ጥያቄ #{req_id} በስኬት ተሰርዟል!**\n\n"
            f"📌 ጥያቄው ከ'📋 የፈላጊዎች ዝርዝር' ተወግዷል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    else:
        await query.message.reply_text("❌ ጥያቄውን ማጥፋት አልተቻለም።")

# ==============================================================================
# 12. VIEW REQUESTS - MAIN HANDLER & SEARCH
# ==============================================================================

import re
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler


async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main handler for viewing requests - checks permissions and shows all requests"""
    user_id = update.effective_user.id
    
    # Check if user is admin
    is_admin = (user_id == ADMIN_CHAT_ID_INT)
    
    # Check if user is a registered broker
    broker = get_broker(user_id)
    
    # If not admin and not broker, deny access
    if not is_admin and not broker:
        await update.message.reply_text(
            "⛔ ይህን ገጽ ማየት የሚችሉት የተመዘገቡ አቅራቢዎች/ደላሎች ወይም አድሚን ብቻ ናቸው!\n\n"
            "📝 እባክዎን መጀመሪያ '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይጫኑ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    # If broker but not approved
    if not is_admin and broker.get('status') != 'approved':
        await update.message.reply_text(
            "⏳ **ምዝገባዎ ገና በአድሚን አልጸደቀም!**\n\n"
            "⏳ ምዝገባዎ በአድሚን ሲረጋገጥ ማስታወቂያ ይደርስዎታል።\n"
            "📞 ለተጨማሪ መረጃ ድጋፍን ይጠቀሙ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        return
    
    # Get all pending requests
    try:
        listings = get_listings_by_category(limit=50, offset=0)
        total = count_listings()
    except Exception as e:
        logger.error(f"Database error: {e}")
        await update.message.reply_text(
            "❌ የውሂብ ጎታ ስህተት! እባክዎ እንደገና ይሞክሩ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    if not listings:
        await update.message.reply_text(
            "📭 **ምንም ንቁ ጥያቄዎች የሉም**\n\n"
            "💡 ሁሉም ጥያቄዎች ተመልሰዋል ወይም በሂደት ላይ ናቸው።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        return
    
    # Get user info
    if is_admin:
        broker_name = "👑 አድሚን"
    else:
        broker_data = get_broker(user_id)
        broker_name = broker_data.get('full_name', 'ደላላ') if broker_data else 'ደላላ'
    
    # Build summary
    summary_text = (
        f"<b>📋 የፈላጊዎች ዝርዝር</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>{broker_name}</b>\n"
        f"🔔 <b>ጠቅላላ፡</b> {total} ጥያቄዎች\n"
        f"⏳ <b>ምላሽ የሚጠብቁ፡</b> {total}"
    )
    await update.message.reply_text(summary_text, parse_mode="HTML")
    
    # Send each request individually with its own buttons
    for listing in listings:
        req_id = listing.get('id')
        description = listing.get('description', '')
        main_cat = str(listing.get('main_category', '')).upper()
        action_type = listing.get('action_type', 'N/A')
        created_at = listing.get('created_at', '')
        user_chat_id = listing.get('user_chat_id') or listing.get('user_id')
        
        # Extract data from description using regex
        phone_match = re.search(r'📞 ስልክ:\s*([\d+]+)', description)
        budget_match = re.search(r'(?:ባጀት|ዋጋ):\s*([\d,]+)', description)
        location_match = re.search(r'አካባቢ:\s*([^\n]+)', description)
        
        # Get sub type
        sub_type_match = re.search(r'🔹 አይነት:\s*([^\n]+)', description)
        sub_type = sub_type_match.group(1) if sub_type_match else listing.get('sub_category', 'N/A')
        
        # Format date
        if created_at:
            try:
                if isinstance(created_at, datetime):
                    date_str = created_at.strftime('%Y-%m-%d')
                else:
                    date_str = str(created_at)[:10]
            except Exception:
                date_str = 'N/A'
        else:
            date_str = 'N/A'
        
        # Determine deal type label
        if "ሽያጭ" in action_type or "መሸጥ" in action_type:
            price_val = budget_match.group(1) if budget_match else 'አልተጠቀሰም'
            price_label = f"💰 <b>ዋጋ፡</b> {price_val}"
        else:
            price_val = budget_match.group(1) if budget_match else 'አልተጠቀሰም'
            price_label = f"💰 <b>በጀት፡</b> {price_val}"
        
        # Get category emoji
        if main_cat == "CAR":
            cat_emoji = "🚗"
            cat_name = "መኪና"
        elif main_cat == "HOUSE":
            cat_emoji = "🏠"
            cat_name = "ቤት/ቦታ"
        else:
            cat_emoji = "📌"
            cat_name = main_cat if main_cat else "ጠቅላላ"
        
        # Build card
        phone_val = phone_match.group(1) if phone_match else 'N/A'
        loc_val = location_match.group(1) if location_match else 'አልተጠቀሰም'
        
        card_text = (
            f"⏳ <b>#{req_id}. {cat_emoji} {cat_name}</b>\n"
            f"📌 <b>አይነት፡</b> {sub_type}\n"
            f"🔄 <b>ድርጊት፡</b> {action_type}\n"
            f"{price_label}\n"
            f"📍 <b>አካባቢ፡</b> {loc_val}\n"
            f"👤 <b>ስልክ፡</b> <code>{phone_val}</code>\n"
            f"📅 <b>ቀን፡</b> {date_str}"
        )
        
        # Build inline keyboard buttons
        keyboard_buttons = [
            InlineKeyboardButton(f"✅ አለኝ #{req_id}", callback_data=f"have_item_{req_id}_{user_chat_id}")
        ]
        
        # Add delete button if admin
        if is_admin:
            keyboard_buttons.append(
                InlineKeyboardButton(f"❌ Delete #{req_id}", callback_data=f"delete_item_{req_id}")
            )
        else:
            keyboard_buttons.append(
                InlineKeyboardButton(f"❌ አልፎኛል #{req_id}", callback_data=f"nohave_item_{req_id}")
            )
            
        keyboard = InlineKeyboardMarkup([keyboard_buttons])
        
        # Send message
        await update.message.reply_text(
            card_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    
    # Send home button at the end
    home_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ])
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━━━━\n"
        "📌 ለማየት የሚፈልጉትን ጥያቄ ይምረጡ።",
        reply_markup=home_keyboard,
        parse_mode="HTML"
    )
# ==============================================================================
# 12.1 DELETE REQUEST HANDLER (የተስተካከለ)
# ==============================================================================
async def delete_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle delete request - only owner or admin can delete"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID_INT)
    
    # Extract request ID from callback data
    parts = query.data.split('_')
    if len(parts) < 3:
        await query.message.reply_text("❌ የተሳሳተ መረጃ ተላኳል።")
        return
    
    req_id = int(parts[2])
    
    # Get listing details
    listing = get_listing_by_id(req_id)
    
    if not listing:
        await query.message.reply_text("❌ ጥያቄው አልተገኘም።")
        return
    
    # Check permission: only admin or the user who created the request
    if not is_admin and listing.get('user_chat_id') != user_id:
        await query.message.reply_text("⛔ ይህን ጥያቄ የማጥፋት ፈቃድ የለዎትም!")
        return
    
    # Delete the request
    success = update_listing_status(req_id, 'deleted')
    
    if success:
        # Update the message to show it's deleted
        await query.edit_message_text(
            f"🗑️ **ጥያቄ #{req_id:04d} ተሰርዟል**\n\n"
            f"👤 በ: {update.effective_user.first_name}\n"
            f"📅 ቀን: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode="Markdown"
        )
        
        # Send confirmation
        await query.message.reply_text(
            f"✅ **ጥያቄ #{req_id:04d} በስኬት ተሰርዟል!**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    else:
        await query.message.reply_text("❌ ጥያቄውን ማጥፋት አልተቻለም።")

import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

ITEMS_PER_PAGE = 5

# ==============================================================================
# 12.2 HAVE ITEM HANDLER
# ==============================================================================
async def have_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Have' button click - broker has the item"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    broker = get_broker(user_id)
    
    if not broker or broker.get('status') != 'approved':
        await query.message.reply_text("⛔ ይህን ማድረግ የሚችሉት የተረጋገጡ ደላሎች/አቅራቢዎች ብቻ ናቸው!")
        return
    
    # Extract request ID from callback data
    parts = query.data.split('_')
    if len(parts) < 2:
        await query.message.reply_text("❌ የተሳሳተ መረጃ ተላኳል።")
        return
    
    req_id = int(parts[1])
    
    # Get listing details
    listing = get_listing_by_id(req_id)
    
    if not listing:
        await query.message.reply_text("❌ ጥያቄው አልተገኘም።")
        return
    
    # Store in context for the next step
    context.user_data['target_req_id'] = req_id
    context.user_data['target_buyer_id'] = listing.get('user_chat_id')
    
    await query.message.reply_text(
        f"✅ **ጥያቄ #{req_id:04d}**\n\n"
        f"✍️ **ያለዎትን ንብረት ዝርዝር መረጃ እና ዋጋ ያስገቡ፦**\n"
        f"(ለምሳሌ፦ ቶዮታ ቪትዝ 2021፣ 30,000 KM የሄደ፣ ዋጋ 2.4 ሚሊዮን፣ ስልክ 0911...)",
        parse_mode="Markdown"
    )
    return BROKER_OFFER_TEXT


def format_request_card(req):
    """Format a single request as a clean professional card"""
    req_id = req.get("id")
    req_type = req.get("category", '').upper()
    action = req.get("action", 'N/A')
    phone = req.get("phone", 'N/A')
    date = req.get("date", 'N/A')
    budget = req.get("budget", "አልተጠቀሰም")
    details = req.get("details", "-")

    if req_type == "HOUSE":
        sub_type = req.get("sub_type", "ቤት/ቦታ")
        location = req.get("location", "አልተጠቀሰም")
        return (
            f"🏠 **#{req_id} {sub_type}** ({action})\n"
            f"📍 አካባቢ: {location}\n"
            f"💰 በጀት: {budget}\n"
            f"📞 {phone} | 📅 {date}\n"
            f"📝 ተጨማሪ: {details}\n"
        )
    elif req_type == "CAR":
        model = req.get("model", "የቤት መኪና")
        return (
            f"🚗 **#{req_id} {model}** ({action})\n"
            f"💰 በጀት: {budget}\n"
            f"📞 {phone} | 📅 {date}\n"
            f"📝 ተጨማሪ: {details}\n"
        )
    else:
        return (
            f"📌 **#{req_id}** ({action})\n"
            f"📞 {phone} | 📅 {date}\n"
            f"📝 {details}\n"
        )


def build_requests_message(user_name, requests_list, page, total_pages, total_count=0):
    """Build the complete requests message"""
    total = total_count if total_count > 0 else len(requests_list)
    header = f"📋 **የፈላጊዎች ዝርዝር** | 👤 {user_name}\n"
    header += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    header += f"🔹 ገጽ {page}/{total_pages} (ጠቅላላ፡ {total} ጥያቄዎች)\n\n"
    
    body = "\n".join([format_request_card(req) for req in requests_list])
    return header + body


def build_request_buttons(requests_list, page, total_pages):
    """Build inline keyboard with action buttons for each request"""
    keyboard = []
    
    # Each request gets its own row with Have/Not Have buttons
    for req in requests_list:
        req_id = req.get("id")
        icon = "🏠" if req.get("category") == "HOUSE" else "🚗" if req.get("category") == "CAR" else "📌"
        row = [
            InlineKeyboardButton(f"{icon} #{req_id} አለኝ", callback_data=f"have_{req_id}"),
            InlineKeyboardButton(f"❌ #{req_id} የለኝም", callback_data=f"nohave_{req_id}")
        ]
        keyboard.append(row)
    
    # Pagination row
    pagination_row = []
    if page > 1:
        pagination_row.append(InlineKeyboardButton("◀️ ፊተኛ", callback_data=f"page_{page-1}"))
    else:
        pagination_row.append(InlineKeyboardButton("⏹", callback_data="none"))
    
    pagination_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="none"))
    
    if page < total_pages:
        pagination_row.append(InlineKeyboardButton("ቀጣይ ▶️", callback_data=f"page_{page+1}"))
    else:
        pagination_row.append(InlineKeyboardButton("⏹", callback_data="none"))
    
    keyboard.append(pagination_row)
    
    # Home button
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    return InlineKeyboardMarkup(keyboard)


async def show_requests_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display requests with clean UI"""
    try:
        # Handle page navigation
        if update.callback_query and update.callback_query.data.startswith("page_"):
            page = int(update.callback_query.data.replace("page_", ""))
            context.user_data['view_page'] = page
            query = update.callback_query
            await query.answer()
        else:
            page = context.user_data.get('view_page', 1)
        
        offset = (page - 1) * ITEMS_PER_PAGE
        
        # Get listings from database
        try:
            listings = get_listings_by_category(limit=ITEMS_PER_PAGE, offset=offset)
            total = count_listings()
        except Exception as e:
            logger.error(f"Database error: {e}")
            error_text = "❌ የውሂብ ጎታ ስህተት! እባክዎ እንደገና ይሞክሩ።"
            if update.message:
                await update.message.reply_text(error_text, parse_mode="Markdown")
            elif update.callback_query:
                await update.callback_query.edit_message_text(error_text, parse_mode="Markdown")
            return
        
        total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        
        # Ensure page is within bounds
        if page > total_pages:
            page = total_pages
            context.user_data['view_page'] = page
            offset = (page - 1) * ITEMS_PER_PAGE
            listings = get_listings_by_category(limit=ITEMS_PER_PAGE, offset=offset)
        
        if not listings:
            text = """
📭 **ምንም ንቁ ጥያቄዎች የሉም**

━━━━━━━━━━━━━━━━━━━━━━
💡 ሁሉም ጥያቄዎች ተመልሰዋል ወይም በሂደት ላይ ናቸው።
🔄 ቆይተው እንደገና ይሞክሩ።
"""
            if update.message:
                await update.message.reply_text(text, parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
            elif update.callback_query:
                await update.callback_query.edit_message_text(text, parse_mode="Markdown")
            return
        
        # Get user info
        user_id = update.effective_user.id
        is_admin = (user_id == ADMIN_CHAT_ID_INT)
        
        if is_admin:
            broker_name = "👑 አድሚን"
        else:
            broker_data = get_broker(user_id)
            broker_name = broker_data.get('full_name', 'ደላላ') if broker_data else 'ደላላ'
        
        # Convert listings to request format
        requests_list = []
        for listing in listings:
            description = listing.get('description', '')
            
            # Extract data from description
            phone_match = re.search(r'📞 ስልክ:\s*([\d\+]+)', description)
            budget_match = re.search(r'ባጀት:\s*([\d,]+)', description) or re.search(r'ዋጋ:\s*([\d,]+)', description)
            location_match = re.search(r'አካባቢ:\s*([^\n]+)', description)
            
            # Get action type
            action_match = re.search(r'🔄 ፍላጎት:\s*([^\n]+)', description)
            action = action_match.group(1) if action_match else listing.get('action_type', 'N/A')
            
            # Get sub type
            sub_type_match = re.search(r'🔹 አይነት:\s*([^\n]+)', description)
            sub_type = sub_type_match.group(1) if sub_type_match else listing.get('sub_category', 'N/A')
            
            # Get model for car
            model_match = re.search(r'🚗\s*([^\n]+)', description)
            model = model_match.group(1) if model_match else 'የቤት መኪና'
            
            # Clean details
            clean_desc = description
            clean_desc = re.sub(r'📞 ስልክ:\s*[\d\+]+', '', clean_desc)
            clean_desc = re.sub(r'ባጀት:\s*[\d,]+', '', clean_desc)
            clean_desc = re.sub(r'ዋጋ:\s*[\d,]+', '', clean_desc)
            clean_desc = re.sub(r'አካባቢ:\s*[^\n]+', '', clean_desc)
            clean_desc = re.sub(r'📌\s*\*\*.*?\*\*', '', clean_desc)
            clean_desc = re.sub(r'🔹\s*አይነት:\s*[^\n]+', '', clean_desc)
            clean_desc = re.sub(r'🔄\s*ፍላጎት:\s*[^\n]+', '', clean_desc)
            clean_desc = re.sub(r'🚗\s*[^\n]+', '', clean_desc)
            clean_desc = clean_desc.strip()
            
            if len(clean_desc) > 100:
                clean_desc = clean_desc[:100] + "..."
            
            req = {
                'id': listing.get('id'),
                'category': listing.get('main_category', '').upper(),
                'action': action,
                'phone': phone_match.group(1) if phone_match else 'N/A',
                'date': str(listing.get('created_at', ''))[:10] if listing.get('created_at') else 'N/A',
                'budget': budget_match.group(1) if budget_match else 'አልተጠቀሰም',
                'details': clean_desc if clean_desc else '-',
                'sub_type': sub_type,
                'location': location_match.group(1) if location_match else 'አልተጠቀሰም',
                'model': model,
                'user_chat_id': listing.get('user_chat_id')
            }
            requests_list.append(req)
        
        # Build message and keyboard
        message = build_requests_message(broker_name, requests_list, page, total_pages, total_count=total)
        keyboard = build_request_buttons(requests_list, page, total_pages)
        
        # Send or edit message
        if update.message:
            await update.message.reply_text(
                message,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        elif update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logger.error(f"Error in show_requests_page: {e}", exc_info=True)
        error_text = """
❌ **ስህተት!**

━━━━━━━━━━━━━━━━━━━━━━
ዝርዝሩን ማሳየት አልተቻለም።
💡 እባክዎ እንደገና ይሞክሩ።
"""
        if update.message:
            await update.message.reply_text(error_text, parse_mode="Markdown")
        elif update.callback_query:
            await update.callback_query.edit_message_text(error_text, parse_mode="Markdown")
# ==============================================================================
# SECTION: CUSTOMER SUPPORT HANDLER
# ==============================================================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """የደንበኞች ድጋፍ እና መመሪያ መስጫ ክፍል"""
    help_text = (
        "📞 **አዲካ ማርኬትፕሌስ - የደንበኞች ድጋፍ**\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "❓ **ቦቱን እንዴት መጠቀም ይቻላል?**\n\n"
        "1️⃣ **መግዛት / መከራየት፦** የሚፈልጉትን ቤት ወይም መኪና ፍላጎት ይመዝግቡ። ጥያቄዎ ለተመዘገቡ ደላሎች ይደርሳል።\n"
        "2️⃣ **መሸጥ / ማከራየት፦** የሚሸጡትን ንብረት መረጃ እና ፎቶ በመጫን ለገበያ ያቅርቡ።\n"
        "3️⃣ **የደላሎች ማውጫ፦** በየክፍለ ከተማው የተረጋገጡ ደላሎችን እና የደረጃ (Rating) መረጃቸውን ይመልከቱ።\n\n"
        "📲 **ለተጨማሪ ጥያቄ ወይም ድጋፍ፦**\n"
        "ከታች ያለውን አዝራር በመጫን ከአስተዳዳሪው ጋር በቀጥታ መነጋገር ይችላሉ።"
    )
    
    keyboard = [
        [InlineKeyboardButton("💬 ከአስተዳዳሪው ጋር ይወያዩ (Admin)", url="https://t.me/Adika_Admin")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(help_text, reply_markup=reply_markup, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode="Markdown")

# ==============================================================================
# SECTION 14: MAIN ENGINE (የተስተካከለ እና የተቀናጀ)
# ==============================================================================

import logging
import threading
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
)

logger = logging.getLogger(__name__)


def main():
    """Main function to initialize database, start web server, and run the bot."""
    # 1. Database Initialization & Flask Thread
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    # 2. Application Builder
    app = Application.builder().token(BOT_TOKEN).build()
application.add_handler(
    CallbackQueryHandler(delete_request_callback, pattern=r"^delete_req_")
)
    # Shared Cancel Handler
    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)

    # 3. Conversation Handlers

    # 3.1. Buyer Conversation Handler
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
        states={
            BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_message_handler],
            BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_"), cancel_message_handler],
            BUYER_SUB: [
                CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_"),
                CallbackQueryHandler(buyer_htype_chosen, pattern="^flow_buy_htype_"),
                cancel_message_handler,
            ],
            BUYER_PROPERTY: [CallbackQueryHandler(buyer_property_chosen, pattern="^flow_buy_prop_"), cancel_message_handler],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details), cancel_message_handler],
            BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # 3.2. Seller Conversation Handler
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_"), cancel_message_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_message_handler],
            SELLER_SUB: [
                CallbackQueryHandler(seller_sub_chosen, pattern="^flow_sell_sub_"),
                CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_"),
                cancel_message_handler,
            ],
            SELLER_PROPERTY: [CallbackQueryHandler(seller_property_chosen, pattern="^flow_sell_prop_"), cancel_message_handler],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details), cancel_message_handler],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price), cancel_message_handler],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone), cancel_message_handler],
            SELLER_PHOTO: [MessageHandler(filters.PHOTO, seller_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # 3.3. Broker Registration Conversation Handler
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

    # 3.4. Broker Response Conversation Handler
    broker_response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broker_have_item_click, pattern="^have_item_")],
        states={
            BROKER_OFFER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text), cancel_message_handler],
            BROKER_OFFER_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, broker_offer_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # 4. Register Commands
    app.add_handler(CommandHandler("start", start))

    # 5. Register Conversation Handlers First
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(broker_response_conv)

    # 6. Register Message Handlers (Main Navigation)
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
    app.add_handler(MessageHandler(filters.Regex("^🛍️ የገበያ ቦታ \(የሚሸጡ\)$"), view_public_marketplace))
    app.add_handler(MessageHandler(filters.Regex("^👥 የደላሎች/አቅራቢዎች ማውጫ$"), view_brokers_directory))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(cancel_message_handler)

    # 7. Register Callback Query Handlers
    app.add_handler(CallbackQueryHandler(show_requests_page, pattern="^page_"))
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(admin_approval_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(delete_request_callback, pattern="^delete_item_"))
    app.add_handler(CallbackQueryHandler(nohave_item_callback, pattern="^nohave_item_"))
    app.add_handler(CallbackQueryHandler(filter_brokers_by_subcity_callback, pattern="^dir_sc_"))
    app.add_handler(CallbackQueryHandler(marketplace_pagination_callback, pattern="^market_page_"))

    # 8. Start Bot Engine
    logger.info("🚀 Adika Marketplace Bot በስኬት ተጀምሯል...")
    app.run_polling()


if __name__ == "__main__":
    main()
