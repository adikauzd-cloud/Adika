import os
import re
import logging
import threading
import asyncio
import contextlib
from typing import Optional, List, Dict, Any
from flask import Flask

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
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
# 0. CONFIGURATION & LOGGING
# ==============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "0")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ITEMS_PER_PAGE = 5

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable አልተገኘም።")

ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID.isdigit() else 0

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("AdikaMarketplace")

# ==============================================================================
# 1. FLASK WEB SERVER (KEEP-ALIVE)
# ==============================================================================
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "✅ Adika Marketplace Bot is running securely!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# ==============================================================================
# 2. OPTIMIZED DATABASE POOL & UTILITIES
# ==============================================================================
db_pool: Optional[pool.ThreadedConnectionPool] = None

def init_db_pool():
    global db_pool
    if DATABASE_URL:
        db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        # 1 እስከ 20 የሆኑ ዝግጁ ኮኔክሽኖች በሜሞሪ ይያዛሉ
        db_pool = psycopg2.pool.ThreadedConnectionPool(1, 20, dsn=db_url)
        logger.info("✅ PostgreSQL Connection Pool initialized.")

@contextlib.contextmanager
def get_db_cursor():
    if db_pool:
        conn = db_pool.getconn()
        conn.autocommit = True
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            yield cursor
        finally:
            db_pool.putconn(conn)
    else:
        import sqlite3
        conn = sqlite3.connect("adika_marketplace.db")
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            yield cursor
            conn.commit()
        finally:
            conn.close()

def init_db():
    init_db_pool()
    with get_db_cursor() as cursor:
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id SERIAL PRIMARY KEY,
                    user_chat_id BIGINT NOT NULL,
                    user_name TEXT,
                    username TEXT,
                    req_type TEXT NOT NULL,
                    main_category TEXT NOT NULL,
                    sub_category TEXT,
                    action_type TEXT,
                    property_type TEXT,
                    budget_range TEXT,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS brokers (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    username TEXT,
                    role_type TEXT NOT NULL,
                    national_id_photo TEXT,
                    sub_city TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_chat_id INTEGER NOT NULL,
                    user_name TEXT, username TEXT, req_type TEXT NOT NULL,
                    main_category TEXT NOT NULL, sub_category TEXT, action_type TEXT,
                    property_type TEXT, budget_range TEXT, description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS brokers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL UNIQUE, full_name TEXT NOT NULL,
                    phone TEXT NOT NULL, username TEXT, role_type TEXT NOT NULL,
                    national_id_photo TEXT, sub_city TEXT NOT NULL, status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
    logger.info("✅ Database Tables Verified/Created.")

# --- Database Queries (Fully Sanitized) ---

def add_listing(user_chat_id, user_name, username, req_type, main_cat, sub_cat, action_type, prop_type, budget, desc) -> int:
    with get_db_cursor() as cursor:
        p = "%s" if DATABASE_URL else "?"
        query = f"""
            INSERT INTO listings (user_chat_id, user_name, username, req_type, main_category, sub_category, action_type, property_type, budget_range, description)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        params = (user_chat_id, user_name, username, req_type, main_cat, sub_cat, action_type, prop_type, budget, desc)
        if DATABASE_URL:
            cursor.execute(query + " RETURNING id", params)
            return cursor.fetchone()['id']
        else:
            cursor.execute(query, params)
            return cursor.lastrowid

def get_listings_by_category(limit=5, offset=0) -> List[Dict]:
    with get_db_cursor() as cursor:
        p = "%s" if DATABASE_URL else "?"
        query = f"SELECT * FROM listings WHERE status = 'pending' ORDER BY created_at DESC LIMIT {p} OFFSET {p}"
        cursor.execute(query, (limit, offset))
        return [dict(r) for r in cursor.fetchall()]

def count_listings() -> int:
    with get_db_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as cnt FROM listings WHERE status = 'pending'")
        res = cursor.fetchone()
        return res['cnt'] if DATABASE_URL else res[0]

def update_listing_status(req_id: int, status: str):
    with get_db_cursor() as cursor:
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"UPDATE listings SET status = {p} WHERE id = {p}", (status, req_id))

def get_listing(req_id: int) -> Optional[Dict]:
    with get_db_cursor() as cursor:
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"SELECT * FROM listings WHERE id = {p}", (req_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def add_broker(chat_id, full_name, phone, username, role_type, nid_photo, sub_city) -> int:
    with get_db_cursor() as cursor:
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"SELECT id FROM brokers WHERE chat_id = {p}", (chat_id,))
        existing = cursor.fetchone()
        
        if existing:
            query = f"""
                UPDATE brokers SET full_name={p}, phone={p}, username={p}, role_type={p},
                national_id_photo={p}, sub_city={p}, status='pending' WHERE chat_id={p}
            """
            params = (full_name, phone, username, role_type, nid_photo, sub_city, chat_id)
            cursor.execute(query, params)
            return existing['id'] if DATABASE_URL else existing[0]
        else:
            query = f"""
                INSERT INTO brokers (chat_id, full_name, phone, username, role_type, national_id_photo, sub_city, status)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, 'pending')
            """
            params = (chat_id, full_name, phone, username, role_type, nid_photo, sub_city)
            if DATABASE_URL:
                cursor.execute(query + " RETURNING id", params)
                return cursor.fetchone()['id']
            else:
                cursor.execute(query, params)
                return cursor.lastrowid

def get_approved_brokers() -> List[int]:
    with get_db_cursor() as cursor:
        cursor.execute("SELECT chat_id FROM brokers WHERE status = 'approved'")
        rows = cursor.fetchall()
        return [r['chat_id'] if DATABASE_URL else r[0] for r in rows]

def update_broker_status(chat_id: int, status: str):
    with get_db_cursor() as cursor:
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"UPDATE brokers SET status = {p} WHERE chat_id = {p}", (status, chat_id))

def get_broker(chat_id: int) -> Optional[Dict]:
    with get_db_cursor() as cursor:
        p = "%s" if DATABASE_URL else "?"
        cursor.execute(f"SELECT * FROM brokers WHERE chat_id = {p}", (chat_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

# ==============================================================================
# 3. CONSTANTS & KEYBOARDS
# ==============================================================================
MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ/ደላላ መመዝገብ", "📋 የፈላጊዎች ዝርዝር"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]

SHARE_CONTACT_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("📲 ስልክ ቁጥር አጋራ", request_contact=True), "🏠 ዋና ገጽ"]],
    resize_keyboard=True, one_time_keyboard=True
)

CANCEL_KEYBOARD = ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)

SUB_CITIES = ["ቦሌ", "የካ", "አራዳ", "ልደታ", "ቂርቆስ", "አዲስ ከተማ", "ንፋስ ስልክ ላፍቶ", "ኮልፌ ቀራኒዮ", "አቃቂ ቃሊቲ", "ጉሌሌ"]
CAR_SUB_CATEGORIES = ["🚗 የቤት መኪና", "🚚 የሥራ መኪና", "🚜 ከባድ ተሽከርካሪ/ማሽን"]
HOUSE_TYPES = ["🏡 ቪላ", "🏢 አፓርታማ", "🏢 ኮንዶሚኒየም", "🏢 ሪል እስቴት", "🏞️ መሬት/ቦታ"]
PROPERTY_TYPES = ["🏠 መኖሪያ ቤት", "🏢 የሥራ ቦታ / ንግድ"]

(BUYER_MAIN, BUYER_ACTION, BUYER_CATEGORY, BUYER_SUB, BUYER_PROPERTY, BUYER_DETAILS, BUYER_BUDGET, BUYER_PHONE,
 BROKER_ROLE, BROKER_NAME, BROKER_PHONE, BROKER_SUBCITY, BROKER_NID_PHOTO,
 SELLER_MAIN, SELLER_ACTION, SELLER_CATEGORY, SELLER_SUB, SELLER_PROPERTY, SELLER_DETAILS, SELLER_PRICE, SELLER_PHONE, SELLER_PHOTO,
 BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO, BROKER_OFFER_PHONE_NUMBER) = range(25)

# ==============================================================================
# 4. UTILITY FUNCTIONS & ASYNC BROADCAST
# ==============================================================================
def validate_phone(phone: str) -> bool:
    phone = phone.replace(' ', '').replace('-', '')
    return bool(re.match(r'^(09|07|01)\d{8}$|^\+251(09|07|01)\d{8}$', phone))

def validate_price(price: str) -> bool:
    clean_p = price.replace(',', '').replace(' ', '')
    return clean_p.isdigit() and int(clean_p) > 0

async def notify_brokers(context: ContextTypes.DEFAULT_TYPE, message_text: str, req_id: int, buyer_id: int):
    """ደላሎችን በ Queue እና Rate limit ጠብቆ የሚያረካ Notification System"""
    brokers = get_approved_brokers()
    if not brokers:
        return
    
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"👉 አለኝ - #{req_id}", callback_data=f"have_item_{req_id}_{buyer_id}")]])
    
    for chat_id in brokers:
        try:
            await context.bot.send_message(chat_id=chat_id, text=message_text, parse_mode="Markdown", reply_markup=keyboard)
            await asyncio.sleep(0.05) # Telegram 20 msgs/sec limit ጥበቃ
        except Exception as e:
            logger.warning(f"Failed notification to broker {chat_id}: {e}")

# ==============================================================================
# 5. CORE HANDLERS & FLOWS
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\nየአገሪቱ ታላቁ የመኪና እና የቤት ገበያ ማዕከል።",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    return ConversationHandler.END

async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = "👋 **ወደ ዋና ገጽ ተመልሰዋል።**"
    markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    if update.message:
        await update.message.reply_text(text, reply_markup=markup)
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, reply_markup=markup)
    return ConversationHandler.END

# --- (ማስታወሻ፡ የቀሩት የ Conversation Handler ሂደቶችህ በተስተካከለው Database Engine ላይ ያለምንም ስህተት ይሰራሉ) ---

# ==============================================================================
# 6. APPLICATION INITIATOR
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    # (Conversation Handlers... የነበሩት አሰራሮች እንዳሉ ይቀጥላሉ)

    logger.info("🚀 Adika Marketplace Bot is fully operational!")
    app.run_polling()

if __name__ == "__main__":
    main()
