
import asyncio
import html
import logging
import os
import threading
import traceback
import re
from typing import Optional, List, Dict, Any

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
# 0. FLASK WEB SERVER (health check / keep-alive)
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

try:
    ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID)
except ValueError:
    ADMIN_CHAT_ID_INT = 0

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
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"],
]
HOME_ONLY_KEYBOARD = ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
MAIN_MARKUP = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)

# ✅ የአዲስ አበባ 11 ክፍለ ከተሞች (ይፋዊ ዝርዝር - "ለሚ ኩራ" ን ጨምሮ)
SUB_CITIES = [
    "ቦሌ", "የካ", "አራዳ", "ልደታ",
    "ቂርቆስ", "አዲስ ከተማ", "ንፋስ ስልክ ላፍቶ",
    "ኮልፌ ቀራኒዮ", "አቃቂ ቃሊቲ", "ጉሌሌ", "ለሚ ኩራ",
]

CAR_SUB_CATEGORIES = ["🚗 የቤት መኪና", "🚚 የሥራ መኪና", "🚜 ከባድ ተሽከርካሪ/ማሽን"]
HOUSE_TYPES = ["🏡 ቪላ", "🏢 አፓርታማ", "🏢 ኮንዶሚኒየም", "🏢 ሪል እስቴት", "🏞️ መሬት/ቦታ"]
COMMERCIAL_TYPES = ["🏢 ቢሮ", "🏪 ሱቅ", "🏭 መጋዘን/ፋብሪካ", "🅿️ ሌላ የስራ ቦታ"]

MAIN_CATEGORIES = [("car", "🚗 መኪና"), ("house", "🏠 ቤት / ቦታ"), ("commercial", "🏢 የሥራ ቦታ / ንግድ")]

# ==============================================================================
# 3. DATABASE UTILITIES
# ==============================================================================
def get_db_connection():
    if DATABASE_URL:
        db_url = (
            DATABASE_URL.replace("postgres://", "postgresql://", 1)
            if DATABASE_URL.startswith("postgres://")
            else DATABASE_URL
        )
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect("adika_marketplace.db")
        conn.row_factory = sqlite3.Row
        return conn


def get_placeholder():
    return "%s" if DATABASE_URL else "?"


def init_db():
    """
    Creates tables if they don't exist yet. IMPORTANT: this no longer drops
    existing tables on every restart — previous versions of this bot wiped
    all listings and brokers on every deploy, which is destructive and has
    been fixed here.
    """
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
                    sub_type TEXT,
                    action_type TEXT,
                    description TEXT NOT NULL,
                    price TEXT,
                    phone TEXT,
                    photo_file_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
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
                );
            """)
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
                );
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
                );
            """)
            conn.commit()

        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    finally:
        if conn:
            conn.close()


# ========== LISTING DB OPERATIONS ==========
def add_listing(
    user_chat_id: int,
    user_name: str,
    req_type: str,
    main_category: str,
    sub_type: str,
    action_type: str,
    description: str,
    price: Optional[str] = None,
    phone: Optional[str] = None,
    photo_file_id: Optional[str] = None,
) -> Optional[int]:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        query = f"""
            INSERT INTO listings
                (user_chat_id, user_name, req_type, main_category, sub_type,
                 action_type, description, price, phone, photo_file_id)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        params = (
            user_chat_id, user_name, req_type, main_category, sub_type,
            action_type, description, price, phone, photo_file_id,
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
        logger.error(f"Add listing error: {e}")
        return None
    finally:
        if conn:
            conn.close()


def get_listings_by_category(limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
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


def count_listings() -> int:
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


# ========== BROKER DB OPERATIONS ==========
def add_broker(chat_id, full_name, phone, role_type, national_id_photo, sub_city) -> Optional[int]:
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
        logger.error(f"Add broker error: {e}")
        return None
    finally:
        if conn:
            conn.close()


def get_approved_brokers() -> List[int]:
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


def update_broker_status(chat_id, status) -> bool:
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


def get_broker(chat_id) -> Optional[Dict[str, Any]]:
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
# 4. CONVERSATION STATES
# ==============================================================================
(
    BUYER_MAIN, BUYER_ACTION, BUYER_SUBTYPE, BUYER_DETAILS, BUYER_PHONE,
    SELLER_MAIN, SELLER_ACTION, SELLER_SUBTYPE, SELLER_DETAILS, SELLER_PRICE, SELLER_PHONE, SELLER_PHOTO,
    BROKER_ROLE, BROKER_NAME, BROKER_PHONE, BROKER_SUBCITY, BROKER_NID_PHOTO,
    BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO,
) = range(19)

# ==============================================================================
# 5. HELPER FUNCTIONS
# ==============================================================================
def validate_phone(phone: str) -> bool:
    """
    Accepts local format (09xxxxxxxx / 07xxxxxxxx / 01xxxxxxxx) and
    international format (+2519xxxxxxxx / +2517xxxxxxxx / +2511xxxxxxxx).
    NOTE: the international form drops the leading 0 (e.g. +251911234567,
    NOT +2510911234567) — the previous regex incorrectly required the 0.
    """
    phone = phone.replace(' ', '').replace('-', '')
    pattern = r'^(09|07|01)\d{8}$|^\+251(9|7|1)\d{8}$'
    return bool(re.match(pattern, phone))


def validate_price(price: str) -> bool:
    price = price.replace(',', '').replace(' ', '')
    return price.isdigit()


def build_indexed_keyboard(options: List[str], prefix: str, columns: int = 1, extra_home: bool = True):
    """Builds an InlineKeyboardMarkup using INDEXES in callback_data (not raw
    text) so we never risk exceeding Telegram's 64-byte callback_data limit
    with long Amharic option strings."""
    buttons = [InlineKeyboardButton(opt, callback_data=f"{prefix}{i}") for i, opt in enumerate(options)]
    keyboard = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    if extra_home:
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    return InlineKeyboardMarkup(keyboard)


async def notify_brokers(context: ContextTypes.DEFAULT_TYPE, message_text: str, req_id: int, buyer_id: int):
    """Broadcasts a new buy request to all approved brokers, with a small
    delay between sends to stay well under Telegram's flood limits."""
    approved_brokers = get_approved_brokers()
    for b_id in approved_brokers:
        try:
            kbd = [[InlineKeyboardButton(f"👉 አለኝ - #{req_id}", callback_data=f"have_item_{req_id}_{buyer_id}")]]
            await context.bot.send_message(
                chat_id=b_id,
                text=message_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kbd),
            )
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to send notification to broker {b_id}: {e}")


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
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=MAIN_MARKUP)
    return ConversationHandler.END


async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = "👋 **ወደ ዋና ገጽ ተመልሰዋል!**\n\nእባክዎን አማራጭ ይምረጡ፦"

    if update.message:
        await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=MAIN_MARKUP)
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
# 7. BUYER FLOW (ፈላጊ)
# Flow order (consistent for car / house / commercial):
#   category -> action -> subtype -> details -> phone -> save
# ==============================================================================
async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'

    keyboard = [[InlineKeyboardButton(label, callback_data=f"flow_buy_cat_{code}")] for code, label in MAIN_CATEGORIES]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await update.message.reply_text(
        "🔍 **የሚፈልጉትን ምድብ ይምረጡ፦**",
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
    else:  # commercial
        await query.edit_message_text(
            "🏢 **የስራ ቦታው አይነት ይምረጡ፦**",
            reply_markup=build_indexed_keyboard(COMMERCIAL_TYPES, "flow_buy_type_"),
            parse_mode="Markdown",
        )
    return BUYER_SUBTYPE


async def buyer_subtype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['description'] = update.message.text
    await update.message.reply_text(
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**",
        parse_mode="Markdown",
        reply_markup=HOME_ONLY_KEYBOARD,
    )
    return BUYER_PHONE


async def buyer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    phone = update.message.text

    if phone == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    if not validate_phone(phone):
        await update.message.reply_text("❌ ስልክ ቁጥሩ ትክክል አይደለም! እባክዎ እንደገና ያስገቡ።\n(ምሳሌ፦ 0911223344 ወይም +251911223344)")
        return BUYER_PHONE

    main_cat = context.user_data.get('main_category', '')
    sub_type = context.user_data.get('sub_type', '')
    action_type = context.user_data.get('action_type', '')
    description = context.user_data.get('description', '')

    category_title = {"car": "🚗 አዲስ የመኪና ጥያቄ", "house": "🏠 አዲስ የቤት/ቦታ ጥያቄ", "commercial": "🏢 አዲስ የስራ ቦታ ጥያቄ"}.get(
        main_cat, "📌 አዲስ ጥያቄ"
    )

    full_desc = (
        f"📌 **{category_title}**\n"
        f"🔹 አይነት: {sub_type}\n"
        f"🔄 ፍላጎት: {action_type}\n"
        f"📝 ዝርዝር: {description}\n"
        f"📞 ስልክ: {phone}"
    )

    req_id = add_listing(
        user_chat_id=user.id, user_name=user.first_name, req_type='BUY',
        main_category=main_cat, sub_type=sub_type, action_type=action_type,
        description=full_desc, phone=phone,
    )

    if req_id:
        await update.message.reply_text(
            f"✅ **ጥያቄዎ በጥሩ ሁኔታ ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"📌 ጥያቄዎ ለተረጋገጡ ደላሎች የተላከ ሲሆን፣ ንብረቱ ያላቸው ደላሎች አማራጮችን ሲልኩልዎ እዚሁ ቴሌግራም ላይ ይደርስዎታል።",
            reply_markup=MAIN_MARKUP,
        )

        notification_text = (
            f"🔔 **{category_title}! (#REQ-{req_id})**\n\n"
            f"{full_desc}\n\n"
            f"👉 ይህ ንብረት በእጅዎ ካለ ከታች **'አለኝ'** የሚለውን በመጫን ለፈላጊው መረጃ ይላኩ!"
        )
        await notify_brokers(context, notification_text, req_id, user.id)
    else:
        await update.message.reply_text("❌ ጥያቄውን መመዝገብ አልተቻለም። እባክዎ እንደገና ይሞክሩ።", reply_markup=MAIN_MARKUP)

    return ConversationHandler.END


# ==============================================================================
# 8. BROKER RESPONSE FLOW (ደላላው "አለኝ" ሲል)
# ==============================================================================
async def broker_have_item_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    broker = get_broker(user_id)

    if not broker or broker.get('status') != 'approved':
        await query.message.reply_text("⛔ ይህን ማድረግ የሚችሉት በአድሚን የተረጋገጡ ደላሎች/አቅራቢዎች ብቻ ናቸው!")
        return ConversationHandler.END

    parts = query.data.split('_')
    req_id = parts[2]
    buyer_id = parts[3]

    context.user_data['target_req_id'] = req_id
    context.user_data['target_buyer_id'] = buyer_id

    await query.message.reply_text(
        f"✅ **ጥያቄ #{req_id}**\n\n"
        f"✍️ **ያለዎትን ንብረት ዝርዝር መረጃ እና ዋጋ ያስገቡ፦**\n"
        f"(ለምሳሌ፦ ቶዮታ ቪትዝ 2021፣ 30,000 KM የሄደ፣ ዋጋ 2.4 ሚሊዮን፣ ስልክ 0911...)",
        reply_markup=HOME_ONLY_KEYBOARD,
    )
    return BROKER_OFFER_TEXT


async def broker_offer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    context.user_data['offer_text'] = update.message.text
    await update.message.reply_text("📸 **የንብረቱን ፎቶ ይላኩ፦**\n(ፎቶ ከሌልዎት 'ፎቶ የለውም' ብለው ይጻፉ)")
    return BROKER_OFFER_PHOTO


async def broker_offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    buyer_id = int(context.user_data.get('target_buyer_id'))
    req_id = context.user_data.get('target_req_id')
    offer_text = context.user_data.get('offer_text')
    broker_name = update.effective_user.first_name

    update_listing_status(int(req_id), 'responded')

    message_to_buyer = (
        f"🎉 **ለጥያቄዎ (#REQ-{req_id}) አዲስ የቀረበ አማራጭ አለ!**\n\n"
        f"👤 **ደላላ/አቅራቢ፦** {broker_name}\n"
        f"📝 **የንብረቱ ዝርዝር፦**\n{offer_text}\n\n"
        f"💡 *ከፈለጉ ደውለው መገበያየት ይችላሉ!*"
    )

    try:
        if update.message.photo:
            photo_id = update.message.photo[-1].file_id
            await context.bot.send_photo(chat_id=buyer_id, photo=photo_id, caption=message_to_buyer, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=buyer_id, text=message_to_buyer, parse_mode="Markdown")

        await update.message.reply_text(
            "✅ **መረጃዎ ለፈላጊው በስኬት ተልኳል!**\n\n📌 ጥያቄው ከ'📋 የፈላጊዎች ዝርዝር' ተወግዷል።",
            reply_markup=MAIN_MARKUP,
        )
    except Exception as e:
        logger.error(f"Failed to send offer to buyer: {e}")
        await update.message.reply_text("❌ መረጃውን ለፈላጊው መላክ አልተቻለም።", reply_markup=MAIN_MARKUP)

    return ConversationHandler.END


# ==============================================================================
# 9. SELLER FLOW (መሸጥ / ማከራየት)
# Flow order mirrors the buyer flow exactly for consistency:
#   category -> action -> subtype -> details -> price -> phone -> photo -> save
# ==============================================================================
async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'

    keyboard = [[InlineKeyboardButton(label, callback_data=f"flow_sell_cat_{code}")] for code, label in MAIN_CATEGORIES]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await update.message.reply_text(
        "📢 **የሚሸጡትን ወይም የሚያከራዩትን ምድብ ይምረጡ፦**",
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
    else:  # commercial
        await query.edit_message_text(
            "🏢 **የስራ ቦታው አይነት ይምረጡ፦**",
            reply_markup=build_indexed_keyboard(COMMERCIAL_TYPES, "flow_sell_type_"),
            parse_mode="Markdown",
        )
    return SELLER_SUBTYPE


async def seller_subtype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['description'] = update.message.text
    await update.message.reply_text("💰 **የሚሸጡበትን/ሚያከራዩበትን ዋጋ ያስገቡ፦**", reply_markup=HOME_ONLY_KEYBOARD)
    return SELLER_PRICE


async def seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    if not validate_price(update.message.text):
        await update.message.reply_text("❌ እባክዎ ቁጥር ብቻ ያስገቡ።")
        return SELLER_PRICE

    context.user_data['price'] = update.message.text
    await update.message.reply_text("📞 **የስልክ ቁጥርዎን ያስገቡ፦**")
    return SELLER_PHONE


async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    if not validate_phone(update.message.text):
        await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ። (ምሳሌ፦ 0911223344 ወይም +251911223344)")
        return SELLER_PHONE

    context.user_data['phone'] = update.message.text
    await update.message.reply_text("📸 **የንብረቱን ፎቶ ይላኩ፦**")
    return SELLER_PHOTO


async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ፎቶ ይላኩ!")
        return SELLER_PHOTO

    main_cat = context.user_data.get('main_category')
    sub_type = context.user_data.get('sub_type', '')
    action_type = context.user_data.get('action_type', '')
    description = context.user_data.get('description', '')
    price = context.user_data.get('price', '')
    phone = context.user_data.get('phone', '')

    desc = (
        f"📢 **አዲስ የሽያጭ/ኪራይ ማስታወቂያ!**\n"
        f"🔹 አይነት: {sub_type}\n"
        f"🔄 ፍላጎት: {action_type}\n"
        f"📝 ዝርዝር: {description}\n"
        f"💰 ዋጋ: {price} ብር\n"
        f"📞 ስልክ: {phone}"
    )

    req_id = add_listing(
        user_chat_id=user.id, user_name=user.first_name, req_type='SELL',
        main_category=main_cat, sub_type=sub_type, action_type=action_type,
        description=desc, price=price, phone=phone, photo_file_id=photo_id,
    )

    if req_id:
        await update.message.reply_text("✅ **የማስታወቂያ ጥያቄዎ በስኬት ተመዝግቧል!**", reply_markup=MAIN_MARKUP)
    else:
        await update.message.reply_text("❌ ማስታወቂያውን መመዝገብ አልተቻለም። እባክዎ እንደገና ይሞክሩ።", reply_markup=MAIN_MARKUP)

    return ConversationHandler.END


# ==============================================================================
# 10. BROKER REGISTRATION
# ==============================================================================
async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    keyboard = [
        [InlineKeyboardButton("👨💼 ደላላ", callback_data="role_broker")],
        [InlineKeyboardButton("🚢 አስመጪ / አቅራቢ", callback_data="role_importer")],
        [InlineKeyboardButton("👤 ባለቤት / አቅራቢ", callback_data="role_owner")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await update.message.reply_text(
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
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['broker_name'] = update.message.text
    await update.message.reply_text("2️⃣ የስልክ ቁጥርዎን ያስገቡ፦")
    return BROKER_PHONE


async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    if not validate_phone(update.message.text):
        await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ። (ለምሳሌ፦ 0911223344)")
        return BROKER_PHONE

    context.user_data['broker_phone'] = update.message.text

    await update.message.reply_text(
        "3️⃣ የሚሰሩበትን ክፍለ ከተማ ይምረጡ፦",
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
        "4️⃣ **የፋይዳ (National ID) ወይም የነዋሪነት መታወቂያ ፎቶ ያንሱና ይላኩ፦**\n\n💡 *ይህ ለማረጋገጫ ብቻ ነው*"
    )
    return BROKER_NID_PHOTO


async def broker_reg_nid_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    user = update.effective_user

    if not update.message or not update.message.photo:
        await update.message.reply_text(
            "❌ **እባክዎ የመታወቂያዎን ፎቶ ይላኩ!**\n\n📸 ፎቶውን ከቴሌግራም ፋይል አባሪ አማራጭ በመጠቀም ይላኩ።\n✏️ ጽሁፍ አይቀበልም።"
        )
        return BROKER_NID_PHOTO

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
        parse_mode="Markdown",
    )

    broker_id = add_broker(user.id, name, phone, role, photo_id, sub_city)

    if broker_id:
        await update.message.reply_text(
            "✅ **ምዝገባዎ በስኬት ተጠናቋል!** 🎉\n\n"
            "⏳ አድሚኑ መረጃዎን ካረጋገጠ በኋላ ማስታወቂያ ይደርስዎታል።\n\n"
            "📋 ምዝገባዎ ከጸደቀ በኋላ '📋 የፈላጊዎች ዝርዝር' ማየት ይችላሉ።",
            reply_markup=MAIN_MARKUP,
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
                    InlineKeyboardButton("❌ ሰርዝ", callback_data=f"admin_reje_{user.id}"),
                ],
                [InlineKeyboardButton("👤 ዝርዝር", callback_data=f"admin_view_{user.id}")],
            ])
            try:
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID_INT, photo=photo_id, caption=admin_msg,
                    parse_mode="Markdown", reply_markup=admin_kbd,
                )
                logger.info(f"Admin notification sent for broker {user.id}")
            except Exception as e:
                logger.error(f"Failed to send admin approval message: {e}")
                await update.message.reply_text("⚠️ ለአድሚን መላክ አልተቻለም፣ ነገር ግን ምዝገባዎ ተመዝግቧል።")
        else:
            logger.warning("ADMIN_CHAT_ID is not set — broker approvals cannot be reviewed.")
    else:
        await update.message.reply_text(
            "❌ **ምዝገባውን ማጠናቀቅ አልተቻለም!**\n\n"
            "💡 እባክዎ የሚከተሉትን ያረጋግጡ፦\n"
            "• መረጃዎቹ ሙሉ መሆናቸውን\n"
            "• የበይነመረብ ግንኙነትዎን\n\n"
            "🔄 እንደገና ለመሞከር '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይጫኑ።",
            reply_markup=MAIN_MARKUP,
        )

    return ConversationHandler.END


# ==============================================================================
# 11. ADMIN APPROVAL HANDLER
# ==============================================================================
async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("admin_appr_"):
        target_id = int(data.replace("admin_appr_", ""))
        update_broker_status(target_id, 'approved')
        await query.edit_message_caption(
            caption=(query.message.caption or "") + "\n\n✅ **ሁኔታ፦ በስኬት ጸድቋል (Approved)**", parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="🎉 **እንኳን ደስ አለዎት!** የምዝገባ ጥያቄዎ በአድሚን ጸድቋል።\n\n📋 አሁን '📋 የፈላጊዎች ዝርዝር' በመጠቀም ጥያቄዎችን ማየት ይችላሉ።",
                reply_markup=MAIN_MARKUP,
            )
        except Exception as e:
            logger.error(f"Could not notify approved user: {e}")

    elif data.startswith("admin_reje_"):
        target_id = int(data.replace("admin_reje_", ""))
        update_broker_status(target_id, 'rejected')
        await query.edit_message_caption(
            caption=(query.message.caption or "") + "\n\n❌ **ሁኔታ፦ ተሰርዟል (Rejected)**", parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="❌ የምዝገባ ጥያቄዎ ተሰርዟል።\n\nለተጨማሪ መረጃ እባክዎን አድሚንን ያግኙ።",
                reply_markup=MAIN_MARKUP,
            )
        except Exception as e:
            logger.error(f"Could not notify rejected user: {e}")

    elif data.startswith("admin_view_"):
        target_id = int(data.replace("admin_view_", ""))
        broker = get_broker(target_id)
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
# 12. VIEW REQUESTS
# ==============================================================================
ITEMS_PER_PAGE = 5


async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    broker = get_broker(user_id)

    if not broker:
        await update.message.reply_text(
            "⛔ ይህን ገጽ ማየት የሚችሉት የተመዘገቡ አቅራቢዎች/ደላሎች ብቻ ናቸው!\n\n"
            "📝 እባክዎን መጀመሪያ '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይጫኑ።",
            reply_markup=MAIN_MARKUP,
        )
        return

    if broker.get('status') != 'approved':
        await update.message.reply_text(
            "⏳ **ምዝገባዎ ገና በአድሚን አልጸደቀም!**\n\n"
            "⏳ ምዝገባዎ በአድሚን ሲረጋገጥ ማስታወቂያ ይደርስዎታል።\n📞 ለተጨማሪ መረጃ ድጋፍን ይጠቀሙ።",
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
        offset = page * ITEMS_PER_PAGE

        listings = get_listings_by_category(limit=ITEMS_PER_PAGE, offset=offset)
        total = count_listings()
        total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

        if not listings:
            text = "📭 ምንም ንቁ ጥያቄዎች የሉም።"
            if update.message:
                await update.message.reply_text(text, reply_markup=MAIN_MARKUP)
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
        if offset + ITEMS_PER_PAGE < total:
            nav_buttons.append(InlineKeyboardButton("➡️ ቀጣይ", callback_data=f"page_{page + 1}"))
        nav_buttons.append(InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home"))
        keyboard.append(nav_buttons)

        if update.message:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            query = update.callback_query
            await query.answer()
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error in show_requests_page: {e}")


# ==============================================================================
# 13. GLOBAL ERROR HANDLER
# ==============================================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Logs the full traceback of any unhandled exception, notifies the admin
    (if configured), and lets the user know something went wrong instead of
    the bot silently hanging."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    # Notify the admin with details, but keep it under Telegram's message size limit.
    if ADMIN_CHAT_ID_INT != 0:
        update_str = update.to_dict() if isinstance(update, Update) else str(update)
        error_report = (
            "⚠️ <b>Bot Exception</b>\n\n"
            f"<pre>update = {html.escape(str(update_str))[:1500]}</pre>\n\n"
            f"<pre>{html.escape(tb_string)[-2500:]}</pre>"
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID_INT, text=error_report, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send error report to admin: {e}")

    # Let the user know without exposing internals.
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ ይቅርታ፣ ያልተጠበቀ ስህተት ተከስቷል። እባክዎ 🏠 ዋና ገጽ ተጭነው እንደገና ይሞክሩ።",
                reply_markup=MAIN_MARKUP,
            )
        except Exception as e:
            logger.error(f"Failed to notify user of error: {e}")


# ==============================================================================
# 14. HELP COMMAND
# ==============================================================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(help_text, parse_mode="Markdown")


# ==============================================================================
# 15. MAIN ENGINE
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    # Register the global error handler FIRST so every exception below is caught.
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", start))

    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)

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

    broker_response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broker_have_item_click, pattern="^have_item_")],
        states={
            BROKER_OFFER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text)],
            BROKER_OFFER_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, broker_offer_photo)],
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

    logger.info("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()


if __name__ == "__main__":
    main()
