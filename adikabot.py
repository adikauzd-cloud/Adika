# ==============================================================================
# ADIKA MARKETPLACE BOT - CLEAN VERSION
# ==============================================================================

import logging
import os
import re
import asyncio
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

import psycopg2
from psycopg2.extras import RealDictCursor
import sqlite3

from flask import Flask, request, jsonify, render_template_string

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
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
# 1. CONFIGURATION & LOGGING
# ==============================================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "0")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable ውስጥ አልተገኘም።")

ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 0
DB_FILE = "adika_marketplace.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Global bot application (for Flask notifications)
bot_app: Optional[Application] = None

# ==============================================================================
# 2. FLASK WEB SERVER & WEBAPP
# ==============================================================================

web_app = Flask(__name__)

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
            <button type="submit" id="submitBtn" class="w-full bg-blue-600 text-white p-2 rounded font-bold">መረጃውን ይላኩ</button>
        </form>
        <p id="statusMsg" class="text-center mt-4 text-sm hidden"></p>
    </div>
    <script>
        let tg = window.Telegram.WebApp;
        tg.expand();
        tg.ready();

        document.getElementById('listingForm').onsubmit = async (e) => {
            e.preventDefault();
            const btn = document.getElementById('submitBtn');
            const status = document.getElementById('statusMsg');
            btn.disabled = true;
            btn.innerText = "እየተላከ ነው...";
            status.classList.add('hidden');

            const data = {
                user_id: tg.initDataUnsafe.user ? tg.initDataUnsafe.user.id : "unknown",
                category: document.getElementById('category').value,
                price: document.getElementById('price').value,
                description: document.getElementById('description').value,
                phone: document.getElementById('phone').value
            };

            try {
                const res = await fetch('/api/submit-listing', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                });
                const result = await res.json();

                if (result.status === "success") {
                    status.innerText = "✅ በስኬት ተመዝግቧል! ቁጥር: #" + result.req_id;
                    status.classList.remove('hidden');
                    status.classList.add('text-green-600');
                    setTimeout(() => tg.close(), 1800);
                } else {
                    status.innerText = "❌ " + (result.message || "ስህተት ተከስቷል");
                    status.classList.remove('hidden');
                    status.classList.add('text-red-600');
                    btn.disabled = false;
                    btn.innerText = "መረጃውን ይላኩ";
                }
            } catch (err) {
                status.innerText = "❌ የኔትወርክ ስህተት። እንደገና ይሞክሩ።";
                status.classList.remove('hidden');
                status.classList.add('text-red-600');
                btn.disabled = false;
                btn.innerText = "መረጃውን ይላኩ";
            }
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
        <h2 class="text-xl font-bold mb-4 text-center">የሚፈልጉትን ንብረት ይግለጹ</h2>
        <form id="buyerForm" class="space-y-4">
            <select id="category" class="w-full p-2 border rounded">
                <option value="መኪና">መኪና</option>
                <option value="ቤት">ቤት</option>
            </select>
            <input type="text" id="budget" placeholder="ባጀት (በብር)" class="w-full p-2 border rounded" required>
            <textarea id="details" placeholder="ዝርዝር ፍላጎት" class="w-full p-2 border rounded" required></textarea>
            <input type="tel" id="phone" placeholder="ስልክ ቁጥር" class="w-full p-2 border rounded" required>
            <button type="submit" id="submitBtn" class="w-full bg-green-600 text-white p-2 rounded font-bold">ጥያቄውን ይላኩ</button>
        </form>
        <p id="statusMsg" class="text-center mt-4 text-sm hidden"></p>
    </div>
    <script>
        let tg = window.Telegram.WebApp;
        tg.expand();
        tg.ready();

        document.getElementById('buyerForm').onsubmit = async (e) => {
            e.preventDefault();
            const btn = document.getElementById('submitBtn');
            const status = document.getElementById('statusMsg');
            btn.disabled = true;
            btn.innerText = "እየተላከ ነው...";
            status.classList.add('hidden');

            const data = {
                user_id: tg.initDataUnsafe.user ? tg.initDataUnsafe.user.id : "unknown",
                category: document.getElementById('category').value,
                budget: document.getElementById('budget').value,
                details: document.getElementById('details').value,
                phone: document.getElementById('phone').value
            };

            try {
                const res = await fetch('/api/submit-request', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                });
                const result = await res.json();

                if (result.status === "success") {
                    status.innerText = "✅ ጥያቄዎ ተመዝግቧል! ቁጥር: #" + result.req_id;
                    status.classList.remove('hidden');
                    status.classList.add('text-green-600');
                    setTimeout(() => tg.close(), 1800);
                } else {
                    status.innerText = "❌ " + (result.message || "ስህተት ተከስቷል");
                    status.classList.remove('hidden');
                    status.classList.add('text-red-600');
                    btn.disabled = false;
                    btn.innerText = "ጥያቄውን ይላኩ";
                }
            } catch (err) {
                status.innerText = "❌ የኔትወርክ ስህተት። እንደገና ይሞክሩ።";
                status.classList.remove('hidden');
                status.classList.add('text-red-600');
                btn.disabled = false;
                btn.innerText = "ጥያቄውን ይላኩ";
            }
        };
    </script>
</body>
</html>
"""

@web_app.route('/')
def home():
    return "✅ Adika Marketplace Bot በስኬት እየሰራ ይገኛል!", 200

@web_app.route('/seller-form')
def webapp_seller_form():
    return render_template_string(SELLER_FORM_HTML)

@web_app.route('/buyer-form')
def webapp_buyer_form():
    return render_template_string(BUYER_FORM_HTML)


def _send_notification_safe(notification_text: str, req_id: int, buyer_id: int):
    """ከ Flask ውስጥ በአስተማማኝ መንገድ ለደላሎች ማሳወቂያ መላክ"""
    if not bot_app:
        logger.warning("bot_app is None – cannot send notification")
        return

    try:
        async def _notify():
            await notify_brokers(bot_app.bot, notification_text, req_id, buyer_id)

        # አዲስ event loop በተለየ thread
        def run_in_thread():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_notify())
                loop.close()
                logger.info(f"✅ Notification sent for req_id={req_id}")
            except Exception as e:
                logger.error(f"❌ Notification thread error: {e}", exc_info=True)

        t = threading.Thread(target=run_in_thread, daemon=True)
        t.start()

    except Exception as e:
        logger.error(f"❌ Failed to start notification thread: {e}", exc_info=True)


@web_app.route('/api/submit-listing', methods=['POST'])
def submit_listing():
    try:
        data = request.json or {}
        user_id = data.get('user_id')
        category = data.get('category', 'መኪና')
        price = data.get('price', '')
        description = data.get('description', '')
        phone = data.get('phone', '')

        logger.info(f"📥 Seller WebApp data: {data}")

        if not user_id or user_id == "unknown":
            return jsonify({"status": "error", "message": "User ID አልተገኘም። Telegram ውስጥ ክፈት።"}), 400

        full_desc = (
            f"📢 **አዲስ የሽያጭ/ኪራይ ማስታወቂያ (WebApp)**\n"
            f"📌 ምድብ: {category}\n"
            f"💰 ዋጋ: {price} ብር\n"
            f"📝 መግለጫ: {description}\n"
            f"📞 ስልክ: {phone}"
        )

        req_id = add_listing(
            user_chat_id=int(user_id) if str(user_id).isdigit() else 0,
            user_name="WebApp User",
            req_type="SELL",
            main_category=category,
            sub_category="",
            action_type="መሸጥ",
            property_type="",
            description=full_desc,
            price=str(price),
            phone=str(phone),
        )

        if req_id:
            logger.info(f"✅ Seller listing saved ID={req_id}")

            # ለደላሎች ማሳወቂያ
            notification_text = (
                f"📢 **አዲስ የሽያጭ ማስታወቂያ! (#SELL-{req_id})**\n\n"
                f"{full_desc}"
            )
            _send_notification_safe(notification_text, req_id, int(user_id))

            return jsonify({"status": "success", "req_id": req_id})
        else:
            return jsonify({"status": "error", "message": "Database ውስጥ ማስቀመጥ አልተቻለም።"}), 500

    except Exception as e:
        logger.error(f"❌ submit_listing error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Server Error: {str(e)}"}), 500


@web_app.route('/api/submit-request', methods=['POST'])
def submit_request():
    try:
        data = request.json or {}
        user_id = data.get('user_id')
        category = data.get('category', 'መኪና')
        budget = data.get('budget', '')
        details = data.get('details', '')
        phone = data.get('phone', '')

        logger.info(f"📥 Buyer WebApp data: {data}")

        if not user_id or user_id == "unknown":
            return jsonify({"status": "error", "message": "User ID አልተገኘም። Telegram ውስጥ ክፈት።"}), 400

        full_desc = (
            f"📌 **አዲስ የ{category} ጥያቄ (WebApp)**\n"
            f"💰 በጀት: {budget} ብር\n"
            f"📝 ዝርዝር: {details}\n"
            f"📞 ስልክ: {phone}"
        )

        req_id = add_listing(
            user_chat_id=int(user_id) if str(user_id).isdigit() else 0,
            user_name="WebApp User",
            req_type="BUY",
            main_category=category,
            sub_category="",
            action_type="መግዛት",
            property_type="",
            description=full_desc,
            price=str(budget),
            phone=str(phone),
        )

        if req_id:
            logger.info(f"✅ Buyer request saved ID={req_id}")

            # ለደላሎች ማሳወቂያ
            notification_text = (
                f"🔔 **አዲስ የ{category} ጥያቄ! (#REQ-{req_id})**\n\n"
                f"{full_desc}\n\n"
                f"👉 ይህ ንብረት በእጅዎ ካለ **'አለኝ'** የሚለውን ይጫኑ!"
            )
            _send_notification_safe(notification_text, req_id, int(user_id))

            return jsonify({"status": "success", "req_id": req_id})
        else:
            return jsonify({"status": "error", "message": "Database ውስጥ ማስቀመጥ አልተቻለም።"}), 500

    except Exception as e:
        logger.error(f"❌ submit_request error: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Server Error: {str(e)}"}), 500


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port, use_reloader=False)
# ==============================================================================
# 2. DATABASE MANAGEMENT
# ==============================================================================

DB_NAME = "adika_marketplace.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. የሽያጭ/ኪራይ መረጃዎች ሰንጠረዥ (Updated Seller/Listings Table)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_chat_id INTEGER,
            user_name TEXT,
            username TEXT,
            req_type TEXT,            -- SELL / RENT
            main_category TEXT,       -- house / car / business
            sub_category TEXT,
            condition TEXT,           -- Brand New / Good / Needs Repair
            location TEXT,            -- Sub-city / Specific location
            price TEXT,
            is_negotiable INTEGER DEFAULT 1, -- 1=የሚደራደር, 0=የማይደራደር
            is_urgent INTEGER DEFAULT 0,     -- 1=አስቸኳይ, 0=መደበኛ
            contact_type TEXT,        -- phone / telegram
            contact_value TEXT,       -- Phone number or Telegram @username
            description TEXT,
            photo_id TEXT,
            status TEXT DEFAULT 'ACTIVE',    -- ACTIVE / SOLD / DELETED
            is_verified INTEGER DEFAULT 0,  -- 1=Verified, 0=Unverified
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 2. የገዢዎች መረጃ ሰንጠረዥ (የነበረው ሳይነካ ይቀጥላል)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS buyer_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_chat_id INTEGER,
            user_name TEXT,
            username TEXT,
            req_type TEXT,
            main_category TEXT,
            sub_category TEXT,
            action_type TEXT,
            property_type TEXT,
            description TEXT,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()


# ==============================================================================
# 4. DATABASE OPERATIONS
# ==============================================================================

def add_listing(user_chat_id, user_name, req_type, main_category, sub_category,
                action_type, property_type, description, price=None, phone=None, photo_id=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()

        # አሮጌ table ካለ አዲስ columns ለመጨመር መሞከር
        try:
            if DATABASE_URL:
                cursor.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS price TEXT;")
                cursor.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS phone TEXT;")
                cursor.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS photo_id TEXT;")
            else:
                # SQLite
                try:
                    cursor.execute("ALTER TABLE listings ADD COLUMN price TEXT;")
                except:
                    pass
                try:
                    cursor.execute("ALTER TABLE listings ADD COLUMN phone TEXT;")
                except:
                    pass
                try:
                    cursor.execute("ALTER TABLE listings ADD COLUMN photo_id TEXT;")
                except:
                    pass
                conn.commit()
        except Exception as alter_err:
            logger.warning(f"ALTER TABLE warning (may already exist): {alter_err}")

        query = f"""
            INSERT INTO listings 
            (user_chat_id, user_name, req_type, main_category, sub_category, 
             action_type, property_type, description, price, phone, photo_id, status)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, 'pending')
        """
        params = (
            user_chat_id, 
            user_name, 
            req_type, 
            main_category, 
            sub_category or "",
            action_type or "", 
            property_type or "", 
            description, 
            price or "", 
            phone or "", 
            photo_id
        )

        if DATABASE_URL:
            cursor.execute(query + " RETURNING id", params)
            row = cursor.fetchone()
            if row is None:
                logger.error("RETURNING id returned None")
                return None
            req_id = row["id"] if isinstance(row, dict) else row[0]
        else:
            cursor.execute(query, params)
            req_id = cursor.lastrowid
            conn.commit()

        logger.info(f"✅ Listing added successfully with ID: {req_id}")
        return req_id

    except Exception as e:
        logger.error(f"❌ Add listing error: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()

def get_listing_by_id(listing_id: int):
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

def get_listings_by_category(limit=10, offset=0, req_type=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()

        if req_type:
            query = f"SELECT * FROM listings WHERE status = 'pending' AND req_type = {p} ORDER BY created_at DESC LIMIT {p} OFFSET {p}"
            cursor.execute(query, (req_type, limit, offset))
        else:
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

def count_listings(req_type=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if req_type:
            p = get_placeholder()
            cursor.execute(f"SELECT COUNT(*) FROM listings WHERE status = 'pending' AND req_type = {p}", (req_type,))
        else:
            cursor.execute("SELECT COUNT(*) FROM listings WHERE status = 'pending'")
        row = cursor.fetchone()
        return row[0] if not isinstance(row, dict) else list(row.values())[0]
    except Exception as e:
        logger.error(f"Count listings error: {e}")
        return 0
    finally:
        if conn:
            conn.close()

def update_listing_status(req_id: int, status: str) -> bool:
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

def get_public_marketplace_items(main_category=None, limit=10, offset=0):
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
                    WHERE chat_id = {p} RETURNING id
                """
                cursor.execute(query, (full_name, phone, role_type, national_id_photo, sub_city, chat_id))
                row = cursor.fetchone()
                broker_id = row["id"] if isinstance(row, dict) else row[0]
            else:
                query = """
                    UPDATE brokers 
                    SET full_name = ?, phone = ?, role_type = ?,
                        national_id_photo = ?, sub_city = ?, status = 'pending'
                    WHERE chat_id = ?
                """
                cursor.execute(query, (full_name, phone, role_type, national_id_photo, sub_city, chat_id))
                broker_id = existing[0] if not isinstance(existing, dict) else existing["id"]
                conn.commit()
        else:
            if DATABASE_URL:
                query = f"""
                    INSERT INTO brokers (chat_id, full_name, phone, role_type, national_id_photo, sub_city, status)
                    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, 'pending') RETURNING id
                """
                cursor.execute(query, (chat_id, full_name, phone, role_type, national_id_photo, sub_city))
                row = cursor.fetchone()
                broker_id = row["id"] if isinstance(row, dict) else row[0]
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

def get_broker(chat_id: int):
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
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"UPDATE brokers SET status = {p} WHERE chat_id = {p}", (status.lower(), chat_id))
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Update broker status error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_approved_brokers():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM brokers WHERE status = 'approved'")
        rows = cursor.fetchall()
        return [dict(row)["chat_id"] if isinstance(row, dict) else row[0] for row in rows]
    except Exception as e:
        logger.error(f"Get approved brokers error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_approved_brokers_directory(sub_city=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()

        if sub_city and sub_city != "ሁሉም":
            query = f"""
                SELECT full_name, phone, role_type, sub_city, rating 
                FROM brokers WHERE status = 'approved' AND sub_city = {p}
                ORDER BY rating DESC
            """
            cursor.execute(query, (sub_city,))
        else:
            query = """
                SELECT full_name, phone, role_type, sub_city, rating 
                FROM brokers WHERE status = 'approved' ORDER BY rating DESC
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
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"""
            INSERT INTO broker_offers (request_id, broker_id, description, photo_id)
            VALUES ({p}, {p}, {p}, {p})
        """, (request_id, broker_id, description, photo_id))
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Save broker offer error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def add_broker_rating(broker_chat_id, user_chat_id, stars):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()

        cursor.execute(
            f"INSERT INTO ratings (broker_chat_id, user_chat_id, stars) VALUES ({p}, {p}, {p})",
            (broker_chat_id, user_chat_id, stars)
        )

        cursor.execute(
            f"SELECT AVG(stars), COUNT(*) FROM ratings WHERE broker_chat_id = {p}",
            (broker_chat_id,)
        )
        result = cursor.fetchone()
        avg_stars = result[0] if not isinstance(result, dict) else list(result.values())[0]
        total_count = result[1] if not isinstance(result, dict) else list(result.values())[1]

        cursor.execute(
            f"UPDATE brokers SET rating = {p}, total_ratings = {p} WHERE chat_id = {p}",
            (round(float(avg_stars or 5.0), 1), total_count, broker_chat_id)
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
# 5. CONSTANTS & KEYBOARDS
# ==============================================================================

# 1. ለደላሎች የሚላከው ካርድ ቁልፎች (#2 & #21)
def build_broker_card_keyboard(listing_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤝 ገዢ/ተከራይ አለኝ", callback_data=f"broker_has_client_{listing_id}"),
            InlineKeyboardButton("👤 ለራሴ እፈልገዋለሁ", callback_data=f"broker_for_self_{listing_id}")
        ],
        [
            InlineKeyboardButton("🚨 ሪፖርት አድርግ", callback_data=f"report_listing_{listing_id}")
        ]
    ])

# 2. ሻጭ ከመለጠፉ በፊት የሚያየው ማረጋገጫ (#3)
def build_seller_confirmation_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ አረጋግጥ እና ለጥፍ", callback_data="seller_confirm_post"),
            InlineKeyboardButton("❌ ሰርዝ", callback_data="seller_cancel_post")
        ]
    ])

# 3. የባለቤት ዕቃ አስተዳደር ቁልፍ (#7)
def build_owner_manage_keyboard(listing_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ ተሸጧል / ተከራይቷል", callback_data=f"mark_sold_{listing_id}"),
            InlineKeyboardButton("🗑 ከአየር ላይ አውርድ", callback_data=f"delete_listing_{listing_id}")
        ]
    ])

# 4. የሻጭ ካርድ ዲዛይን አዘጋጅ (#5, #8, #10, #13, #14)
def format_seller_card(data: dict) -> str:
    urgent_badge = "⚡ **[አስቸኳይ ሽያጭ]**\n" if data.get('is_urgent') else ""
    verified_badge = " ✔️ *Verified Listing*" if data.get('is_verified') else ""
    negotiable_text = "የሚደራደር" if data.get('is_negotiable') else "የማይደራደር"
    
    contact_type = data.get('contact_type', 'phone')
    contact_val = data.get('contact_value', '')
    contact_display = f"📞 `{contact_val}`" if contact_type == 'phone' else f"✈️ @{contact_val.replace('@', '')}"

    card_text = (
        f"{urgent_badge}"
        f"📌 **{data.get('main_category', '').upper()} - {data.get('sub_category', '')}**{verified_badge}\n\n"
        f"⚙️ **ሁኔታ፦** {data.get('condition', 'ያልተገለጸ')}\n"
        f"📍 **ክፍለ-ከተማ/ቦታ፦** {data.get('location', 'ያልተጠቀሰ')}\n"
        f"💵 **ዋጋ፦** {data.get('price')} ብር ({negotiable_text})\n\n"
        f"📝 **ዝርዝር መረጃ፦**\n{data.get('description', '')}\n\n"
        f"🔗 **መገናኛ፦** {contact_display}"
    )
    return card_text

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

def format_buyer_card(req: dict) -> str:
    req_id = req.get('id', 'N/A')
    main_cat = req.get('main_category', '')
    action_type = req.get('action_type', '')
    sub_cat = req.get('sub_category', 'ያልተጠቀሰ')
    prop_type = req.get('property_type', 'ያልተጠቀሰ')
    desc = req.get('description', '')
    phone = req.get('phone', 'መረጃው አልተያያዘም')

    icon = "🚗" if main_cat in ["መኪና", "car", "CAR"] else "🏠"

    return (
        f"{icon} **[ፈላጊ - #{req_id}]**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📌 **ዘርፍ፦** {main_cat} ({action_type})\n"
        f"🏷️ **ዓይነት፦** {sub_cat} | {prop_type}\n"
        f"📝 **ዝርዝር ፍላጎት፦**\n_{desc}_\n\n"
        f"📞 **የፈላጊው ስልክ፦** `{phone}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 *ደላላ ከሆኑና ይህ ንብረት በእጅዎ ካለ ከታች ያለውን አዝራር ይጫኑ።*"
    )

def format_seller_card(item: dict) -> str:
    item_id = item.get('id', 'N/A')
    main_cat = item.get('main_category', '')
    action_type = item.get('action_type', '')
    sub_cat = item.get('sub_category', '-')
    desc = item.get('description', '')
    price = item.get('price', 'በድርድር')
    phone = item.get('phone', '-')

    icon = "🚗" if main_cat in ["መኪና", "car", "CAR"] else "🏠"
    tag = "🔴 ለሽያጭ" if action_type in ["መሸጥ", "SELL"] else "🔵 ለኪራይ"

    return (
        f"{icon} **[ለገበያ የቀረበ - #{item_id}]** {tag}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 **አይነት፦** {main_cat} ({sub_cat})\n"
        f"💰 **ዋጋ፦** `{price}`\n\n"
        f"📋 **መግለጫ፦**\n_{desc}_\n\n"
        f"📞 **የባለቤቱ/አቅራቢው ስልክ፦** `{phone}`\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"✨ *ለበለጠ መረጃ በስልክ ቁጥሩ በቀጥታ ይደውሉ።*"
    )

def format_broker_profile(b: dict) -> str:
    stars = "⭐" * int(float(b.get('rating', 5)))
    return (
        f"👤 **ስም፦** {b.get('full_name')}\n"
        f"🎭 **ሚና፦** {b.get('role_type')}\n"
        f"📍 **ክፍለ ከተማ፦** {b.get('sub_city')}\n"
        f"📞 **ስልክ፦** `{b.get('phone')}`\n"
        f"ደረጃ፦ {b.get('rating', 5.0)}/5.0 {stars}\n"
        f"───────────────────"
    )

def get_nav_buttons(back_callback: str = None) -> list:
    buttons = []
    if back_callback:
        buttons.append(InlineKeyboardButton("⬅️ ተመለስ", callback_data=back_callback))
    buttons.append(InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home"))
    return buttons

def build_request_keyboard(req_id: int, back_callback: str = None) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🗑️ ጥያቄውን አጥፋ", callback_data=f"delete_req_{req_id}")],
        get_nav_buttons(back_callback),
    ]
    return InlineKeyboardMarkup(keyboard)

async def notify_brokers(bot, message_text: str, req_id: int, buyer_id: int):
    approved_brokers = get_approved_brokers()
    if not approved_brokers:
        logger.info("No approved brokers found to notify")
        return

    for b_id in approved_brokers:
        try:
            kbd = [[InlineKeyboardButton(f"👉 አለኝ - #{req_id}", callback_data=f"have_item_{req_id}_{buyer_id}")]]
            await bot.send_message(
                chat_id=b_id,
                text=message_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kbd)
            )
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to send notification to broker {b_id}: {e}")
# ==============================================================================
# CONVERSATION STATES
# ==============================================================================

(
    BUYER_MAIN, 
    BUYER_SUB, 
    BUYER_ACTION, 
    BUYER_HTYPE, 
    BUYER_PROPERTY, 
    BUYER_DETAILS, 
    BUYER_PHONE
) = range(10, 17)

(
    SELLER_MAIN, 
    SELLER_SUB,
    SELLER_SUBCAT, 
    SELLER_ACTION, 
    SELLER_PROPERTY,
    SELLER_CONDITION, 
    SELLER_LOCATION, 
    SELLER_PRICE, 
    SELLER_NEGOTIABLE, 
    SELLER_URGENT, 
    SELLER_DESC, 
    SELLER_CONTACT_TYPE, 
    SELLER_CONTACT_VAL, 
    SELLER_PHOTO, 
    SELLER_CONFIRM
) = range(100, 115)


# ==============================================================================
# 7. SELLER HANDLERS & CONVERSATION
# ==============================================================================

# State Definitions (ለሻጭ ብቻ)
(
    SELLER_MAIN, SELLER_SUBCAT, SELLER_CONDITION, 
    SELLER_LOCATION, SELLER_PRICE, SELLER_NEGOTIABLE, 
    SELLER_URGENT, SELLER_DESC, SELLER_CONTACT_TYPE, 
    SELLER_CONTACT_VAL, SELLER_PHOTO, SELLER_CONFIRM
) = range(100, 112)

# 1. ንኡስ ምድብ እና የጽሁፍ ማስተካከያ (#6)
async def seller_subcat_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['sub_category'] = query.data.replace("sell_sub_", "")
    
    keyboard = [
        [InlineKeyboardButton("✨ አዲስ (Brand New)", callback_data="cond_Brand New")],
        [InlineKeyboardButton("👍 በጥሩ ሁኔታ ላይ ያለ", callback_data="cond_Good")],
        [InlineKeyboardButton("🛠 ጥገና የሚፈልግ", callback_data="cond_Needs Repair")],
    ]
    
    prompt_text = "🚗 **የመኪና አይነት/ሞዴል ይምረጡ፦**" if context.user_data.get('main_category') == "car" else "⚙️ **የንብረቱ/ዕቃው ሁኔታ ምን ይመስላል?**"
    
    await query.edit_message_text(
        prompt_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_CONDITION

# 2. የንብረት ሁኔታ ከተመረጠ በኋላ አድራሻ/ቦታ መቀበል (#9)
async def seller_condition_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['condition'] = query.data.replace("cond_", "")
    
    await query.edit_message_text(
        "📍 **ንብረቱ የሚገኝበትን ክፍለ-ከተማ ወይም ልዩ ቦታ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቦሌ / ካዛንችስ",
        parse_mode="Markdown"
    )
    return SELLER_LOCATION

# 3. አድራሻ ሲገባ ዋጋ መጠየቅ
async def seller_location_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['location'] = update.message.text.strip()
    await update.message.reply_text("💵 **የመሸጫ/የመኪራያ ዋጋ በብር ያስገቡ፦**")
    return SELLER_PRICE

# 4. ዋጋ ሲገባ የድርድር ሁኔታ መጠየቅ (#8)
async def seller_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['price'] = update.message.text.strip()
    
    keyboard = [
        [
            InlineKeyboardButton("💰 የሚደራደር", callback_data="neg_1"),
            InlineKeyboardButton("🔒 የማይደራደር", callback_data="neg_0")
        ]
    ]
    await update.message.reply_text(
        "💵 **የዋጋ ሁኔታ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_NEGOTIABLE

# 5. የአስቸኳይ ሽያጭ ጥያቄ (#14)
async def seller_negotiable_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['is_negotiable'] = 1 if query.data == "neg_1" else 0
    
    keyboard = [
        [
            InlineKeyboardButton("⚡ አዎ (አስቸኳይ ሽያጭ)", callback_data="urg_1"),
            InlineKeyboardButton("🔹 መደበኛ ሽያጭ", callback_data="urg_0")
        ]
    ]
    await query.edit_message_text(
        "🚨 **ማስታወቂያው የ «አስቸኳይ ሽያጭ» ባጅ እንዲኖረው ይፈልጋሉ?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_URGENT

# 6. ዝርዝር መግለጫ መጠየቅ
async def seller_urgent_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['is_urgent'] = 1 if query.data == "urg_1" else 0
    
    await query.edit_message_text(
        "📝 **የንብረቱን/ዕቃውን ዝርዝር መረጃ ያስገቡ፦**",
        parse_mode="Markdown"
    )
    return SELLER_DESC

# 7. የመገናኛ ምርጫ መጠየቅ (#5)
async def seller_desc_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['description'] = update.message.text.strip()
    
    keyboard = [
        [
            InlineKeyboardButton("📞 በስልክ ቁጥር", callback_data="contact_phone"),
            InlineKeyboardButton("✈️ በቴሌግራም (@username)", callback_data="contact_telegram")
        ]
    ]
    await update.message.reply_text(
        "📞 **ገዢዎች በምን እንዲያገኙዎት ይፈልጋሉ?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELLER_CONTACT_TYPE

# 8. የመገናኛ መረጃ መቀበል (#5)
async def seller_contact_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    choice = query.data.replace("contact_", "")
    context.user_data['contact_type'] = choice
    
    if choice == "phone":
        await query.edit_message_text("📞 **እባክዎን ስልክ ቁጥርዎን ያስገቡ፦** (ምሳሌ፦ 0911223344)")
    else:
        user = update.effective_user
        if user.username:
            context.user_data['contact_value'] = user.username
            await query.edit_message_text(f"✅ የመረጡት ቴሌግራም አድራሻ፦ @{user.username}\n\n🖼 **አሁን የንብረቱን ፎቶ ይላኩ፦**")
            return SELLER_PHOTO
        else:
            await query.edit_message_text("✍️ **እባክዎን የቴሌግራም username ዎን ያስገቡ፦** (ምሳሌ፦ @myusername)")
            
    return SELLER_CONTACT_VAL

async def seller_contact_val_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['contact_value'] = update.message.text.strip().replace("@", "")
    await update.message.reply_text("🖼 **አሁን የንብረቱን ፎቶ ይላኩ፦**")
    return SELLER_PHOTO

# 9. ፎቶ መቀበል እና ቅድመ-እይታ ከነ ማረጋገጫ ቁልፎች ማሳየት (#1, #3)
async def seller_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data['photo_id'] = update.message.photo[-1].file_id
    else:
        context.user_data['photo_id'] = None

    card_preview = format_seller_card(context.user_data)
    preview_text = f"📋 **የማስታወቂያዎ ቅድመ-እይታ፦**\n\n{card_preview}\n\nእባክዎን መረጃውን አረጋግጠው ይልቀቁት፦"

    if context.user_data.get('photo_id'):
        await update.message.reply_photo(
            photo=context.user_data['photo_id'],
            caption=preview_text,
            reply_markup=build_seller_confirmation_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            preview_text,
            reply_markup=build_seller_confirmation_keyboard(),
            parse_mode="Markdown"
        )
    return SELLER_CONFIRM

# 10. ማረጋገጫ እና መለጠፍ / መሰረዝ (#3, #28)
async def seller_confirm_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "seller_cancel_post":
        await query.edit_message_caption("❌ **ማስታወቂያው ተሰርዟል።**") if query.message.photo else await query.edit_message_text("❌ **ማስታወቂያው ተሰርዟል።**")
        context.user_data.clear()
        return ConversationHandler.END

    user = update.effective_user
    listing_id = save_seller_listing(user.id, user.full_name, user.username, context.user_data)
    
    if listing_id:
        context.user_data['id'] = listing_id
        
        await query.edit_message_caption(
            caption=f"✅ **ማስታወቂያዎ በስኬት ተለጥፏል! (#LIST-{listing_id})**\n\n{format_seller_card(context.user_data)}",
            reply_markup=build_owner_manage_keyboard(listing_id),
            parse_mode="Markdown"
        ) if query.message.photo else await query.edit_message_text(
            text=f"✅ **ማስታወቂያዎ በስኬት ተለጥፏል! (#LIST-{listing_id})**\n\n{format_seller_card(context.user_data)}",
            reply_markup=build_owner_manage_keyboard(listing_id),
            parse_mode="Markdown"
        )
        
        await notify_brokers_new_listing(context.bot, context.user_data)
        await post_to_channel(context.bot, context.user_data)
    else:
        await query.message.reply_text("❌ **ስህተት ተከስቷል። እባክዎን እንደገና ይሞክሩ።**")

    context.user_data.clear()
    return ConversationHandler.END

# ==============================================================================
# 8. START & HOME HANDLERS
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
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=welcome_text,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    return ConversationHandler.END

# ==============================================================================
# 9. BUYER FLOW
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
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    phone = update.message.text.strip()
    if not validate_phone(phone):
        await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ። (ለምሳሌ፦ 0911223344)")
        return BUYER_PHONE

    context.user_data["phone"] = phone
    user = update.effective_user
    user_data = context.user_data

    desc = user_data.get('description', '')
    if user_data.get('property_subtype'):
        desc = f"🏠 {user_data.get('property_subtype')}\n{desc}"

    req_id = add_listing(
        user_chat_id=user.id,
        user_name=user.first_name or "User",
        req_type="BUY",
        main_category=user_data.get('main_category', ''),
        sub_category=user_data.get('sub_category', ''),
        action_type=user_data.get('action_type', 'መግዛት'),
        property_type=user_data.get('property_type', ''),
        description=desc,
        phone=phone,
    )

    if req_id:
        reply_markup = build_request_keyboard(req_id, back_callback="flow_home")
        await update.message.reply_text(
            f"✅ **ጥያቄዎ በስኬት ተመዝግቧል!**\n\n"
            f"🆔 **የጥያቄ ቁጥር:** #{req_id}\n"
            f"📞 **ስልክ:** {phone}\n\n"
            f"አቅራቢዎች ወይም ደላሎች ጥያቄዎን አይተው መልስ ይሰጡዎታል።",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

        # Notify brokers
        notification_text = (
            f"🔔 **አዲስ ጥያቄ! (#REQ-{req_id})**\n\n"
            f"{desc}\n\n"
            f"📞 ስልክ: {phone}\n\n"
            f"👉 ይህ ንብረት በእጅዎ ካለ **'አለኝ'** የሚለውን ይጫኑ!"
        )
        await notify_brokers(context.bot, notification_text, req_id, user.id)
    else:
        await update.message.reply_text("❌ መረጃውን መመዝገብ አልተቻለም። እባክዎ እንደገና ይሞክሩ።")

    context.user_data.clear()
    return ConversationHandler.END

# ==============================================================================
# 10. SELLER FLOW
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
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ይላኩ (ወይም 'ዝለል' የሚለውን ይጻፉ)፦**",
        parse_mode="Markdown"
    )
    return SELLER_PHOTO

async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    photo_id = update.message.photo[-1].file_id if update.message.photo else None

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
        user_chat_id=user.id,
        user_name=user.first_name or "User",
        req_type="SELL",
        main_category=context.user_data.get('main_category'),
        sub_category=context.user_data.get('sub_category', ''),
        action_type=context.user_data.get('action_type'),
        property_type=context.user_data.get('property_type', ''),
        description=desc,
        price=context.user_data.get('price'),
        phone=context.user_data.get('phone'),
        photo_id=photo_id,
    )

    if req_id:
        await update.message.reply_text(
            "✅ **ማስታወቂያዎ በስኬት ተመዝግቧል!** 🎉\n\n"
            "📌 ማስታወቂያዎ ለደላሎች ተልኳል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )

        notification_text = (
            f"📢 **አዲስ የሽያጭ/ኪራይ ማስታወቂያ!**\n\n"
            f"{desc}\n\n"
            f"👉 ይህን ማስታወቂያ ለፈላጊዎች ማሳወቅ ይችላሉ!"
        )
        await notify_brokers(context.bot, notification_text, req_id, user.id)
    else:
        await update.message.reply_text(
            "❌ ማስታወቂያውን መመዝገብ አልተቻለም።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )

    context.user_data.clear()
    return ConversationHandler.END

# ==============================================================================
# 11. BROKER REGISTRATION
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

    await query.edit_message_text(
        f"👤 **ምዝገባ፦ {role}**\n\n1️⃣ ሙሉ ስምዎን ያስገቡ፦",
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
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    user = update.effective_user
    photo_id = update.message.photo[-1].file_id if update.message.photo else None

    if not photo_id:
        await update.message.reply_text("❌ እባክዎ የመታወቂያ ፎቶ ይላኩ።")
        return BROKER_NID_PHOTO

    role = context.user_data.get('broker_role', 'አቅራቢ')
    name = context.user_data.get('broker_name', user.first_name)
    phone = context.user_data.get('broker_phone', '')
    sub_city = context.user_data.get('broker_subcity', '')

    broker_id = add_broker(user.id, name, phone, role, photo_id, sub_city)

    if broker_id:
        await update.message.reply_text(
            "✅ **ምዝገባዎ በስኬት ተጠናቋል!** 🎉\n\n"
            "⏳ አድሚኑ መረጃዎን ካረጋገጠ በኋላ ማስታወቂያ ይደርስዎታል።",
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
                logger.error(f"Failed to send admin approval message: {e}")
    else:
        await update.message.reply_text(
            "❌ **ምዝገባውን ማጠናቀቅ አልተቻለም!** እባክዎ እንደገና ይሞክሩ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )

    context.user_data.clear()
    return ConversationHandler.END

# ==============================================================================
# 12. BROKER OFFER FLOW
# ==============================================================================

async def broker_have_item_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if len(parts) < 3:
        await query.message.reply_text("❌ የተሳሳተ መረጃ ተላኳል።")
        return ConversationHandler.END

    req_id = parts[2]
    buyer_id = parts[3] if len(parts) >= 4 else None

    if not buyer_id:
        listing = get_listing_by_id(int(req_id)) if req_id.isdigit() else None
        if listing:
            buyer_id = listing.get('user_chat_id')

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
        photo_id = None
        if update.message.photo:
            photo_id = update.message.photo[-1].file_id
        elif update.message.text and update.message.text != "ፎቶ የለውም":
            pass

        save_broker_offer(int(req_id), broker_user.id, offer_text, photo_id)

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
            "✅ **መረጃዎ ለፈላጊው በስኬት ተልኳል!**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to send offer to buyer {buyer_id}: {e}")
        await update.message.reply_text(
            "❌ መረጃውን ለፈላጊው መላክ አልተቻለም።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )

    context.user_data.clear()
    return ConversationHandler.END

async def nohave_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    broker = get_broker(user_id)

    if not broker or broker.get('status') != 'approved':
        await query.answer("⛔ ይህን ማድረግ የሚችሉት በአድሚን የተረጋገጡ ደላሎች/አቅራቢዎች ብቻ ናቸው!", show_alert=True)
        return

    parts = query.data.split('_')
    req_id = parts[-1] if parts else "?"
    await query.answer(f"ℹ️ ጥያቄ #{req_id} አልፎታል።", show_alert=False)

    await query.message.reply_text(
        f"ℹ️ **ጥያቄ #{req_id} አልፎታል።**\n\n"
        f"💡 ሌላ አዲስ ጥያቄ ለማየት '📋 የፈላጊዎች ዝርዝር' የሚለውን ይጫኑ።",
        parse_mode="Markdown"
    )

# ==============================================================================
# 13. VIEW REQUESTS / MARKETPLACE / DIRECTORY
# ==============================================================================

async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID_INT)
    broker = get_broker(user_id)

    if not is_admin and not broker:
        await update.message.reply_text(
            "⛔ ይህን ገጽ ማየት የሚችሉት የተመዘገቡ አቅራቢዎች/ደላሎች ወይም አድሚን ብቻ ናቸው!\n\n"
            "📝 እባክዎን መጀመሪያ '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይጫኑ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return

    if not is_admin and broker.get('status') != 'approved':
        await update.message.reply_text(
            "⏳ **ምዝገባዎ ገና በአድሚን አልጸደቀም!**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        return

    listings = get_listings_by_category(limit=20, offset=0, req_type="BUY")
    total = count_listings(req_type="BUY")

    if not listings:
        await update.message.reply_text(
            "📭 **ምንም ንቁ ጥያቄዎች የሉም**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        return

    broker_name = "👑 አድሚን" if is_admin else (broker.get('full_name') if broker else "ደላላ")

    await update.message.reply_text(
        f"<b>📋 የፈላጊዎች ዝርዝር</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>{broker_name}</b>\n"
        f"🔔 <b>ጠቅላላ፡</b> {total} ጥያቄዎች",
        parse_mode="HTML"
    )

    for listing in listings:
        req_id = listing.get('id')
        user_chat_id = listing.get('user_chat_id')
        card_text = format_buyer_card(listing)

        keyboard_buttons = [
            InlineKeyboardButton(f"✅ አለኝ #{req_id}", callback_data=f"have_item_{req_id}_{user_chat_id}")
        ]
        if is_admin:
            keyboard_buttons.append(
                InlineKeyboardButton(f"❌ Delete #{req_id}", callback_data=f"delete_req_{req_id}")
            )
        else:
            keyboard_buttons.append(
                InlineKeyboardButton(f"❌ አልፎኛል #{req_id}", callback_data=f"nohave_item_{req_id}")
            )

        await update.message.reply_text(
            card_text,
            reply_markup=InlineKeyboardMarkup([keyboard_buttons]),
            parse_mode="Markdown"
        )

async def view_public_marketplace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = get_public_marketplace_items(limit=10)

    if not items:
        await update.message.reply_text(
            "📭 **በአሁኑ ሰዓት ለሽያጭ/ኪራይ የቀረቡ ንብረቶች የሉም።**",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        "🛍️ **ለሽያጭ እና ለኪራይ የቀረቡ ንብረቶች ዝርዝር፦**",
        parse_mode="Markdown"
    )

    for item in items:
        card_text = format_seller_card(item)
        photo_id = item.get('photo_id')

        if photo_id:
            try:
                await update.message.reply_photo(photo=photo_id, caption=card_text, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(card_text, parse_mode="Markdown")
        else:
            await update.message.reply_text(card_text, parse_mode="Markdown")

async def view_brokers_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        msg += format_broker_profile(b) + "\n\n"

    await query.edit_message_text(msg, parse_mode="Markdown")

# ==============================================================================
# 14. ADMIN HANDLERS
# ==============================================================================

async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if update.effective_user.id != ADMIN_CHAT_ID_INT:
        await query.answer("⛔ ይህን ማድረግ የሚችሉት አድሚን ብቻ ናቸው!", show_alert=True)
        return

    if data.startswith("admin_appr_"):
        broker_telegram_id = int(data.replace("admin_appr_", ""))
        success = update_broker_status(broker_telegram_id, "approved")
        if success:
            try:
                await query.edit_message_caption(
                    caption=f"{query.message.caption}\n\n✅ **ሁኔታ፦ ተፀድቋል (Approved)**",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    chat_id=broker_telegram_id,
                    text=(
                        "🎉 **እንኳን ደስ አለዎት!**\n\n"
                        "የደላላ/አቅራቢ ምዝገባዎ በአድሚን ፀድቋል።\n"
                        "አሁን '📋 የፈላጊዎች ዝርዝር' በመጫን መስራት መጀመር ይችላሉ።"
                    ),
                    reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify approved broker: {e}")
        else:
            await query.message.reply_text("❌ የደላላውን ሁኔታ መቀየር አልተቻለም።")

    elif data.startswith("admin_reje_"):
        broker_telegram_id = int(data.replace("admin_reje_", ""))
        success = update_broker_status(broker_telegram_id, "rejected")
        if success:
            try:
                await query.edit_message_caption(
                    caption=f"{query.message.caption}\n\n❌ **ሁኔታ፦ ተሰርዟል (Rejected)**",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    chat_id=broker_telegram_id,
                    text="❌ **የምዝገባ ጥያቄዎ ውድቅ ተደርጓል!** እባክዎ እንደገና ይመዝገቡ።",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify rejected broker: {e}")

async def delete_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID_INT)

    parts = query.data.split('_')
    if len(parts) < 3:
        await query.message.reply_text("❌ የተሳሳተ መረጃ ተላኳል።")
        return

    req_id = int(parts[-1])
    listing = get_listing_by_id(req_id)

    if not listing:
        await query.message.reply_text("❌ ጥያቄው አልተገኘም።")
        return

    if not is_admin and listing.get('user_chat_id') != user_id:
        await query.message.reply_text("⛔ ይህን ጥያቄ የማጥፋት ፈቃድ የለዎትም!")
        return

    success = update_listing_status(req_id, "deleted")
    if success:
        try:
            await query.edit_message_text(
                f"🗑️ **ጥያቄ #{req_id} በስኬት ተሰርዟል።**",
                parse_mode="Markdown"
            )
        except Exception:
            await query.message.reply_text(
                f"🗑️ **ጥያቄ #{req_id} በስኬት ተሰርዟል።**",
                parse_mode="Markdown"
            )
    else:
        await query.message.reply_text("❌ ጥያቄውን ማጥፋት አልተቻለም።")

# ==============================================================================
# 15. SUPPORT HANDLER
# ==============================================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📞 **አዲካ ማርኬትፕሌስ - የደንበኞች ድጋፍ**\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "❓ **ቦቱን እንዴት መጠቀም ይቻላል?**\n\n"
        "1️⃣ **መግዛት / መከራየት፦** የሚፈልጉትን ቤት ወይም መኪና ፍላጎት ይመዝግቡ።\n"
        "2️⃣ **መሸጥ / ማከራየት፦** የሚሸጡትን ንብረት መረጃ እና ፎቶ በመጫን ለገበያ ያቅርቡ።\n"
        "3️⃣ **የደላሎች ማውጫ፦** በየክፍለ ከተማው የተረጋገጡ ደላሎችን ይመልከቱ።\n\n"
        "📲 **ለተጨማሪ ጥያቄ፦** ከአስተዳዳሪው ጋር ይገናኙ።"
    )

    keyboard = [
        [InlineKeyboardButton("💬 ከአስተዳዳሪው ጋር ይወያዩ", url="https://t.me/Adika_Admin")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]

    if update.message:
        await update.message.reply_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ==============================================================================
# 16. MAIN ENGINE
# ==============================================================================

def main():
    global bot_app

    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    bot_app = app

    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_handler = MessageHandler(cancel_filter, go_home)

    # Buyer Conversation
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
        states={
            BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_handler],
            BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_"), cancel_handler],
            BUYER_SUB: [CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_"), cancel_handler],
            BUYER_PROPERTY: [CallbackQueryHandler(buyer_property_chosen, pattern="^flow_buy_prop_"), cancel_handler],
            BUYER_HTYPE: [CallbackQueryHandler(buyer_htype_chosen, pattern="^flow_buy_htype_"), cancel_handler],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details), cancel_handler],
            BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone), cancel_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    # Seller Conversation
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_"), cancel_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_handler],
            SELLER_SUB: [CallbackQueryHandler(seller_sub_chosen, pattern="^flow_sell_sub_"), cancel_handler],
            SELLER_PROPERTY: [CallbackQueryHandler(seller_property_chosen, pattern="^flow_sell_prop_"), cancel_handler],
            SELLER_HTYPE: [CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_"), cancel_handler],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details), cancel_handler],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price), cancel_handler],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone), cancel_handler],
            SELLER_PHOTO: [
                MessageHandler(filters.PHOTO, seller_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_photo),
                cancel_handler
            ],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    # Broker Registration
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ/ደላላ መመዝገብ$"), broker_reg_start)],
        states={
            BROKER_ROLE: [CallbackQueryHandler(broker_role_chosen, pattern="^role_"), cancel_handler],
            BROKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name), cancel_handler],
            BROKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone), cancel_handler],
            BROKER_SUBCITY: [CallbackQueryHandler(broker_reg_subcity, pattern="^broker_sc_"), cancel_handler],
            BROKER_NID_PHOTO: [MessageHandler(filters.PHOTO, broker_reg_nid_photo), cancel_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    # Broker Offer Response
    broker_response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broker_have_item_click, pattern="^have_item_")],
        states={
            BROKER_OFFER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text), cancel_handler],
            BROKER_OFFER_PHOTO: [
                MessageHandler(filters.PHOTO, broker_offer_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_photo),
                cancel_handler
            ],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    # Register handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(broker_response_conv)

    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
    app.add_handler(MessageHandler(filters.Regex(r"^🛍️ የገበያ ቦታ \(የሚሸጡ\)$"), view_public_marketplace))
    app.add_handler(MessageHandler(filters.Regex("^👥 የደላሎች/አቅራቢዎች ማውጫ$"), view_brokers_directory))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(cancel_handler)

    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(admin_approval_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(delete_request_callback, pattern=r"^delete_req_"))
    app.add_handler(CallbackQueryHandler(nohave_item_callback, pattern="^nohave_item_"))
    app.add_handler(CallbackQueryHandler(filter_brokers_by_subcity_callback, pattern="^dir_sc_"))

    logger.info("🚀 Adika Marketplace Bot በስኬት ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()
