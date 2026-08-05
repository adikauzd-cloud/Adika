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
# 4. UTILITIES & HANDLERS
# ==============================================================================
def validate_phone(phone: str) -> bool:
    phone = phone.replace(' ', '').replace('-', '')
    return bool(re.match(r'^(09|07|01)\d{8}$|^\+251(09|07|01)\d{8}$', phone))

def validate_price(price: str) -> bool:
    clean_p = price.replace(',', '').replace(' ', '')
    return clean_p.isdigit() and int(clean_p) > 0

async def notify_brokers(context: ContextTypes.DEFAULT_TYPE, message_text: str, req_id: int, buyer_id: int):
    brokers = get_approved_brokers()
    if not brokers:
        return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"👉 አለኝ - #{req_id}", callback_data=f"have_item_{req_id}_{buyer_id}")]])
    for chat_id in brokers:
        try:
            await context.bot.send_message(chat_id=chat_id, text=message_text, parse_mode="Markdown", reply_markup=keyboard)
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning(f"Failed notification to broker {chat_id}: {e}")

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
    text = "👋 **ወደ ዋና ገጽ ተመልሰዋል።**\n\nእባክዎን አማራጭ ይምረጡ፦"
    markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=markup)
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.delete_message()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=text,
            parse_mode="Markdown",
            reply_markup=markup
        )
    return ConversationHandler.END

# ==============================================================================
# 5. BUYER FLOW
# ==============================================================================
async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "🚗 **የሚፈልጉት መኪና ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020፣ አውቶማቲክ",
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
        f"🏠 **{htype}**\n\n✍️ **የሚፈልጉትን ቤት/ቦታ ዝርዝር መረጃ ያስገቡ፦**",
        parse_mode="Markdown"
    )
    return BUYER_DETAILS

async def buyer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['description'] = update.message.text
    await update.message.reply_text(
        "💰 **የበጀት ግምትዎን ያስገቡ፦**",
        parse_mode="Markdown",
        reply_markup=CANCEL_KEYBOARD
    )
    return BUYER_BUDGET

async def buyer_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    budget = update.message.text
    if budget == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['budget'] = budget
    await update.message.reply_text(
        "📞 **እርስዎን የሚያገኙበትን ስልክ ቁጥር ወይም Telegram ID ያስገቡ፦**",
        parse_mode="Markdown",
        reply_markup=SHARE_CONTACT_KEYBOARD
    )
    return BUYER_PHONE

async def buyer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username or ""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if update.message.contact:
        contact_info = f"📞 {update.message.contact.phone_number}"
    else:
        text = update.message.text.strip()
        contact_info = f"📞 {text}" if validate_phone(text) or text.startswith('@') else None

    if not contact_info:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ የስልክ ቁጥር ያስገቡ።", reply_markup=SHARE_CONTACT_KEYBOARD)
        return BUYER_PHONE
    
    main_cat = context.user_data.get('main_category', '')
    sub_cat = context.user_data.get('sub_category', '')
    action_type = context.user_data.get('action_type', '')
    prop_subtype = context.user_data.get('property_subtype', '')
    description = context.user_data.get('description', '')
    budget = context.user_data.get('budget', '')
    
    category_title = "🚗 አዲስ የመኪና ጥያቄ" if main_cat == "car" else "🏠 አዲስ የቤት/ቦታ ጥያቄ"
    user_name = f"{user.first_name} {user.last_name or ''}".strip()
    
    full_desc = f"📌 **{category_title}**\n🔹 አይነት: {prop_subtype or sub_cat}\n🔄 ፍላጎት: {action_type}\n📝 ዝርዝር: {description}\n💰 በጀት: {budget}\n{contact_info}"
    
    req_id = add_listing(user.id, user_name, username, 'BUY', main_cat, sub_cat, action_type, prop_subtype, budget, full_desc)
    
    if req_id:
        await update.message.reply_text(
            f"✅ **ጥያቄዎ በጥሩ ሁኔታ ተመዝግቧል!** (#REQ-{req_id})",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        notification_text = f"🔔 **{category_title}! (#REQ-{req_id})**\n\n{full_desc}\n\n👉 ይህ ንብረት በእጅዎ ካለ ከታች **'አለኝ'** የሚለውን ይጫኑ!"
        await notify_brokers(context, notification_text, req_id, user.id)

    return ConversationHandler.END

# ==============================================================================
# 6. SELLER FLOW
# ==============================================================================
async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    keyboard = [
        [InlineKeyboardButton("🚗 መኪና", callback_data="flow_sell_cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ", callback_data="flow_sell_cat_house")],
        [InlineKeyboardButton("🏢 የሥራ ቦታ / ንግድ", callback_data="flow_sell_cat_commercial")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text("📢 **የሚሸጡትን/ሚያከራዩትን ምድብ ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
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
    await query.edit_message_text("❓ **የድርጊት አይነት ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return SELLER_ACTION

async def seller_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    await query.answer()
    action = query.data.replace("flow_sell_action_", "")
    context.user_data['action_type'] = "መሸጥ" if action == "sell" else "ማከራየት"
    
    if context.user_data.get('main_category') == "car":
        await query.edit_message_text("🚗 **የመኪናውን ዝርዝር መረጃ ያስገቡ፦**", parse_mode="Markdown")
        return SELLER_DETAILS
    else:
        keyboard = [[InlineKeyboardButton(ptype, callback_data=f"flow_sell_prop_{ptype}")] for ptype in PROPERTY_TYPES]
        keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
        await query.edit_message_text("🏠 **የንብረት አይነት ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
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
    await query.edit_message_text("🏠 **የቤቱ አይነት ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return SELLER_SUB

async def seller_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    await query.answer()
    htype = query.data.replace("flow_sell_htype_", "")
    context.user_data['property_subtype'] = htype
    await query.edit_message_text(f"🏠 **{htype}**\n\n✍️ **የቤቱን/ቦታውን ዝርዝር መረጃ ያስገቡ፦**", parse_mode="Markdown")
    return SELLER_DETAILS

async def seller_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['description'] = update.message.text
    await update.message.reply_text("💰 **የሚሸጡበትን/ሚያከራዩበትን ዋጋ ያስገቡ፦**", parse_mode="Markdown", reply_markup=CANCEL_KEYBOARD)
    return SELLER_PRICE

async def seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    if not validate_price(update.message.text):
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ቁጥር ያስገቡ።")
        return SELLER_PRICE
    context.user_data['price'] = update.message.text
    await update.message.reply_text("📞 **የስልክ ቁጥርዎን ያስገቡ፦**", reply_markup=SHARE_CONTACT_KEYBOARD)
    return SELLER_PHONE

async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    phone = update.message.contact.phone_number if update.message.contact else update.message.text
    if not validate_phone(phone):
        await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ።", reply_markup=SHARE_CONTACT_KEYBOARD)
        return SELLER_PHONE
    context.user_data['phone'] = phone
    await update.message.reply_text("📸 **የንብረቱን ፎቶ ይላኩ፦**", reply_markup=CANCEL_KEYBOARD)
    return SELLER_PHOTO

async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    user = update.effective_user
    if not update.message.photo:
        await update.message.reply_text("❌ እባክዎ ፎቶ ይላኩ!", reply_markup=CANCEL_KEYBOARD)
        return SELLER_PHOTO
    
    desc = f"📢 **አዲስ ማስታወቂያ!**\n🔄 አይነት: {context.user_data.get('action_type')}\n📝 ዝርዝር: {context.user_data.get('description')}\n💰 ዋጋ: {context.user_data.get('price')} ብር\n📞 ስልክ: {context.user_data.get('phone')}"
    req_id = add_listing(user.id, user.first_name, user.username or "", 'SELL', context.user_data.get('main_category', ''), '', context.user_data.get('action_type', ''), '', '', desc)
    
    if req_id:
        await update.message.reply_text("✅ **የማስታወቂያ ጥያቄዎ በስኬት ተመዝግቧል!** 🎉", reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
    return ConversationHandler.END

# ==============================================================================
# 7. BROKER REGISTRATION
# ==============================================================================
async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("👨‍💼 ደላላ", callback_data="role_broker")],
        [InlineKeyboardButton("🚢 አስመጪ / አቅራቢ", callback_data="role_importer")],
        [InlineKeyboardButton("👤 ባለቤት / አቅራቢ", callback_data="role_owner")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text("📝 **የምዝገባ አይነት ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return BROKER_ROLE

async def broker_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    await query.answer()
    role_map = {"role_broker": "ደላላ", "role_importer": "አስመጪ/አቅራቢ", "role_owner": "ባለቤት/አቅራቢ"}
    context.user_data['broker_role'] = role_map.get(query.data, "አቅራቢ")
    await query.edit_message_text(f"👤 **ምዝገባ፦ {context.user_data['broker_role']}**\n\n1️⃣ ሙሉ ስምዎን ያስገቡ፦")
    return BROKER_NAME

async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['broker_name'] = update.message.text
    await update.message.reply_text("2️⃣ የስልክ ቁጥርዎን ያስገቡ፦", reply_markup=SHARE_CONTACT_KEYBOARD)
    return BROKER_PHONE

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    phone = update.message.contact.phone_number if update.message.contact else update.message.text
    if not validate_phone(phone):
        await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ።", reply_markup=SHARE_CONTACT_KEYBOARD)
        return BROKER_PHONE
    context.user_data['broker_phone'] = phone
    keyboard = [[InlineKeyboardButton(sc, callback_data=f"broker_sc_{sc}")] for sc in SUB_CITIES]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await update.message.reply_text("3️⃣ የሚሰሩበትን ክፍለ ከተማ ይምረጡ፦", reply_markup=InlineKeyboardMarkup(keyboard))
    return BROKER_SUBCITY

async def broker_reg_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    await query.answer()
    context.user_data['broker_subcity'] = query.data.replace("broker_sc_", "")
    await query.edit_message_text("4️⃣ **የፋይዳ (National ID) ፎቶ ይላኩ፦**")
    return BROKER_NID_PHOTO

async def broker_reg_nid_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    user = update.effective_user
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ የመታወቂያዎን ፎቶ ይላኩ!")
        return BROKER_NID_PHOTO
        
    broker_id = add_broker(user.id, context.user_data.get('broker_name', user.first_name), context.user_data.get('broker_phone', ''), user.username or "", context.user_data.get('broker_role', 'ደላላ'), photo_id, context.user_data.get('broker_subcity', ''))
    if broker_id:
        await update.message.reply_text("✅ **ምዝገባዎ በስኬት ተጠናቋል!** 🎉\n\nአድሚኑ መረጃዎን ካረጋገጠ በኋላ ቦቱ ይከፈትልዎታል።", reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
    return ConversationHandler.END

# ==============================================================================
# 8. OTHER HANDLERS & HELP
# ==============================================================================
async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    broker = get_broker(update.effective_user.id)
    if not broker or broker.get('status') != 'approved':
        await update.message.reply_text("⛔ ይህን ገጽ ማየት የሚችሉት የተጸደቁ ደላሎች ብቻ ናቸው!", reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
        return
    context.user_data['view_page'] = 0
    await show_requests_page(update, context)

async def show_requests_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    page = context.user_data.get('view_page', 0)
    listings = get_listings_by_category(limit=ITEMS_PER_PAGE, offset=page * ITEMS_PER_PAGE)
    if not listings:
        await (update.message.reply_text if update.message else update.callback_query.message.reply_text)("📭 ምንም ንቁ ጥያቄዎች የሉም።", reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
        return
    text = f"📋 **የፈላጊዎች ዝርዝር**\n\n" + "\n".join([f"📌 **#{l['id']}**\n{l['description']}\n" for l in listings])
    keyboard = [[InlineKeyboardButton(f"👉 አለኝ - #{l['id']}", callback_data=f"have_item_{l['id']}_{l['user_chat_id']}")] for l in listings]
    keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ **እገዛ እና ድጋፍ**\n\nለማንኛውም ጥያቄ አድሚኑን ያግኙ።", parse_mode="Markdown")

# ==============================================================================
# 9. MAIN APPLICATION INITIATOR
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    # Universal Cancel/Home Filter (ቋሚ ገጽ ማደሻ)
    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_handler = MessageHandler(cancel_filter, go_home)

    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
        states={
            BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_handler],
            BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_"), cancel_handler],
            BUYER_SUB: [CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_"), CallbackQueryHandler(buyer_htype_chosen, pattern="^flow_buy_htype_"), cancel_handler],
            BUYER_PROPERTY: [CallbackQueryHandler(buyer_property_chosen, pattern="^flow_buy_prop_"), cancel_handler],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details), cancel_handler],
            BUYER_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_budget), cancel_handler],
            BUYER_PHONE: [MessageHandler((filters.TEXT | filters.CONTACT) & ~filters.COMMAND, buyer_phone), cancel_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler, CallbackQueryHandler(go_home, pattern="^flow_home$")],
        allow_reentry=True,
    )

    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_"), cancel_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_handler],
            SELLER_SUB: [CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_"), cancel_handler],
            SELLER_PROPERTY: [CallbackQueryHandler(seller_property_chosen, pattern="^flow_sell_prop_"), cancel_handler],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details), cancel_handler],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price), cancel_handler],
            SELLER_PHONE: [MessageHandler((filters.TEXT | filters.CONTACT) & ~filters.COMMAND, seller_phone), cancel_handler],
            SELLER_PHOTO: [MessageHandler(filters.PHOTO, seller_photo), cancel_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler, CallbackQueryHandler(go_home, pattern="^flow_home$")],
        allow_reentry=True,
    )

    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ/ደላላ መመዝገብ$"), broker_reg_start)],
        states={
            BROKER_ROLE: [CallbackQueryHandler(broker_role_chosen, pattern="^role_"), cancel_handler],
            BROKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name), cancel_handler],
            BROKER_PHONE: [MessageHandler((filters.TEXT | filters.CONTACT) & ~filters.COMMAND, broker_reg_phone), cancel_handler],
            BROKER_SUBCITY: [CallbackQueryHandler(broker_reg_subcity, pattern="^broker_sc_"), cancel_handler],
            BROKER_NID_PHOTO: [MessageHandler((filters.PHOTO | filters.Document.IMAGE | filters.TEXT) & ~filters.COMMAND, broker_reg_nid_photo), cancel_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler, CallbackQueryHandler(go_home, pattern="^flow_home$")],
        allow_reentry=True,
    )

    # Handlers Registration
    app.add_handler(CommandHandler("start", start))
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(MessageHandler(cancel_filter, go_home))
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))

    logger.info("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()
