import logging
import os
import threading
import re
import asyncio
import contextlib
from typing import Optional, List, Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton
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
# 0. FLASK WEB SERVER
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
ITEMS_PER_PAGE = 5

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable ውስጥ አልተገኘም።")

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
    ["📝 እንደ አቅራቢ/ደላላ መመዝገብ", "📋 የፈላጊዎች ዝርዝር"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]

SHARE_CONTACT_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("📲 ስልክ ቁጥር አጋራ", request_contact=True), "🏠 ዋና ገጽ"]],
    resize_keyboard=True,
    one_time_keyboard=True
)

CANCEL_KEYBOARD = ReplyKeyboardMarkup(
    [["🏠 ዋና ገጽ"]],
    resize_keyboard=True
)

SUB_CITIES = [
    "ቦሌ", "የካ", "አራዳ", "ልደታ", 
    "ቂርቆስ", "አዲስ ከተማ", "ንፋስ ስልክ ላፍቶ", 
    "ኮልፌ ቀራኒዮ", "አቃቂ ቃሊቲ", "ጉሌሌ", "ላምበርት/የካ"
]

CAR_SUB_CATEGORIES = ["🚗 የቤት መኪና", "🚚 የሥራ መኪና", "🚜 ከባድ ተሽከርካሪ/ማሽን"]
HOUSE_TYPES = ["🏡 ቪላ", "🏢 አፓርታማ", "🏢 ኮንዶሚኒየም", "🏢 ሪል እስቴት", "🏞️ መሬት/ቦታ"]
PROPERTY_TYPES = ["🏠 መኖሪያ ቤት", "🏢 የሥራ ቦታ / ንግድ"]

# ==============================================================================
# 3. CONVERSATION STATES
# ==============================================================================
(
    BUYER_MAIN, 
    BUYER_ACTION, 
    BUYER_CATEGORY, 
    BUYER_SUB, 
    BUYER_PROPERTY, 
    BUYER_DETAILS, 
    BUYER_BUDGET,      
    BUYER_PHONE,       
    BROKER_ROLE, 
    BROKER_NAME, 
    BROKER_PHONE, 
    BROKER_SUBCITY, 
    BROKER_NID_PHOTO,
    SELLER_MAIN, 
    SELLER_ACTION, 
    SELLER_CATEGORY, 
    SELLER_SUB, 
    SELLER_PROPERTY, 
    SELLER_DETAILS, 
    SELLER_PRICE, 
    SELLER_PHONE, 
    SELLER_PHOTO,
    BROKER_OFFER_TEXT, 
    BROKER_OFFER_PHOTO, 
    BROKER_OFFER_PHONE_NUMBER
) = range(25)

# ==============================================================================
# 4. DATABASE UTILITIES
# ==============================================================================
def get_db_connection():
    if DATABASE_URL:
        db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
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

@contextlib.contextmanager
def get_db_cursor():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor) if DATABASE_URL else conn.cursor()
        yield cursor, conn
    finally:
        if conn:
            conn.close()

def init_db():
    with get_db_cursor() as (cursor, conn):
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
            conn.commit()
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_chat_id INTEGER NOT NULL,
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
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL UNIQUE,
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
            conn.commit()
    logger.info("✅ Database initialized successfully")

def add_listing(user_chat_id, user_name, username, req_type, main_category, sub_category, action_type, property_type, budget_range, description):
    with get_db_cursor() as (cursor, conn):
        p = get_placeholder()
        query = f"""
            INSERT INTO listings (user_chat_id, user_name, username, req_type, main_category, sub_category, action_type, property_type, budget_range, description)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        params = (user_chat_id, user_name, username, req_type, main_category, sub_category, action_type, property_type, budget_range, description)
        
        if DATABASE_URL:
            cursor.execute(query + " RETURNING id", params)
            return cursor.fetchone()[0]
        else:
            cursor.execute(query, params)
            conn.commit()
            return cursor.lastrowid

def get_listings_by_category(limit=10, offset=0):
    with get_db_cursor() as (cursor, conn):
        p = get_placeholder()
        query = f"SELECT * FROM listings WHERE status = 'pending' ORDER BY created_at DESC LIMIT {p} OFFSET {p}"
        cursor.execute(query, (limit, offset))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def count_listings():
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT COUNT(*) FROM listings WHERE status = 'pending'")
        return cursor.fetchone()[0]

def update_listing_status(req_id, status):
    with get_db_cursor() as (cursor, conn):
        p = get_placeholder()
        cursor.execute(f"UPDATE listings SET status = {p} WHERE id = {p}", (status, req_id))
        if not DATABASE_URL:
            conn.commit()
        return True

def get_listing(req_id):
    with get_db_cursor() as (cursor, conn):
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM listings WHERE id = {p}", (req_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def add_broker(chat_id, full_name, phone, username, role_type, national_id_photo, sub_city):
    with get_db_cursor() as (cursor, conn):
        p = get_placeholder()
        cursor.execute(f"SELECT id FROM brokers WHERE chat_id = {p}", (chat_id,))
        existing = cursor.fetchone()
        
        if existing:
            if DATABASE_URL:
                query = f"""
                    UPDATE brokers 
                    SET full_name = {p}, phone = {p}, username = {p}, role_type = {p}, 
                        national_id_photo = {p}, sub_city = {p}, status = 'pending'
                    WHERE chat_id = {p}
                    RETURNING id
                """
                cursor.execute(query, (full_name, phone, username, role_type, national_id_photo, sub_city, chat_id))
                return cursor.fetchone()[0]
            else:
                query = """
                    UPDATE brokers 
                    SET full_name = ?, phone = ?, username = ?, role_type = ?, 
                        national_id_photo = ?, sub_city = ?, status = 'pending'
                    WHERE chat_id = ?
                """
                cursor.execute(query, (full_name, phone, username, role_type, national_id_photo, sub_city, chat_id))
                conn.commit()
                return existing[0]
        else:
            if DATABASE_URL:
                query = f"""
                    INSERT INTO brokers (chat_id, full_name, phone, username, role_type, national_id_photo, sub_city, status)
                    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, 'pending')
                    RETURNING id
                """
                cursor.execute(query, (chat_id, full_name, phone, username, role_type, national_id_photo, sub_city))
                return cursor.fetchone()[0]
            else:
                query = """
                    INSERT INTO brokers (chat_id, full_name, phone, username, role_type, national_id_photo, sub_city, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                """
                cursor.execute(query, (chat_id, full_name, phone, username, role_type, national_id_photo, sub_city))
                conn.commit()
                return cursor.lastrowid

def get_approved_brokers():
    with get_db_cursor() as (cursor, conn):
        cursor.execute("SELECT chat_id FROM brokers WHERE status = 'approved'")
        rows = cursor.fetchall()
        return [dict(row)['chat_id'] for row in rows]

def update_broker_status(chat_id, status):
    with get_db_cursor() as (cursor, conn):
        p = get_placeholder()
        cursor.execute(f"UPDATE brokers SET status = {p} WHERE chat_id = {p}", (status, chat_id))
        if not DATABASE_URL:
            conn.commit()
        return True

def get_broker(chat_id):
    with get_db_cursor() as (cursor, conn):
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM brokers WHERE chat_id = {p}", (chat_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

# ==============================================================================
# 5. HELPER FUNCTIONS
# ==============================================================================
def validate_phone(phone: str) -> bool:
    phone = phone.replace(' ', '').replace('-', '')
    pattern = r'^(09|07|01)\d{8}$|^\+251(09|07|01)\d{8}$'
    return bool(re.match(pattern, phone))

def validate_price(price: str) -> bool:
    price = price.replace(',', '').replace(' ', '')
    return price.isdigit() and int(price) > 0

def validate_budget(budget: str) -> bool:
    budget = budget.replace(',', '').strip()
    if not budget:
        return False
    if budget.replace(' ', '').isdigit() and int(budget.replace(' ', '')) > 0:
        return True
    return True  # Accept any reasonable input

async def send_batched_messages(context, chat_ids: List[int], text: str, reply_markup=None, delay: float = 0.5):
    semaphore = asyncio.Semaphore(5)
    
    async def send_single(chat_id):
        async with semaphore:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
                await asyncio.sleep(delay)
            except Exception as e:
                logger.error(f"Failed to send to {chat_id}: {e}")
    
    tasks = [send_single(cid) for cid in chat_ids]
    await asyncio.gather(*tasks, return_exceptions=True)

async def notify_brokers(context, message_text: str, req_id: int, buyer_id: int):
    approved_brokers = get_approved_brokers()
    if not approved_brokers:
        return
    
    keyboard = [[InlineKeyboardButton(f"👉 አለኝ - #{req_id}", callback_data=f"have_item_{req_id}_{buyer_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    batch_size = 30
    for i in range(0, len(approved_brokers), batch_size):
        batch = approved_brokers[i:i+batch_size]
        await send_batched_messages(context, batch, message_text, reply_markup, delay=0.5)
        await asyncio.sleep(2)

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

# ==============================================================================
# 7. BUYER FLOW (ፈላጊ)
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
            "🚗 **የሚፈልጉት መኪና ዝርዝር መረጃ ያስገቡ፦**\n\n"
            "💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020፣ አውቶማቲክ፣ ከ50,000 ኪሎ ሜትር በታች",
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
        f"🏠 **{htype}**\n\n"
        "✍️ **የሚፈልጉትን ቤት/ቦታ ዝርዝር መረጃ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* ቦሌ አትላስ አካባቢ 3 መኝታ ቤት፣ ከፍተኛ ጥገና ያላስፈለገ",
        parse_mode="Markdown"
    )
    return BUYER_DETAILS

async def buyer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['description'] = update.message.text
    
    await update.message.reply_text(
        "💰 **የበጀት ግምትዎን ያስገቡ፦**\n\n"
        "💡 *ምሳሌዎች፦*\n"
        "• ቁጥር ብቻ: `2,500,000`\n"
        "• ከ... እስከ...: `ከ2,000,000 እስከ 3,000,000`\n"
        "• ከ...: `ከ2,000,000`\n"
        "• እስከ...: `እስከ 3,000,000`",
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
        "📞 **እርስዎን የሚያገኙበትን መረጃ ያስገቡ፦**\n\n"
        "📲 የስልክ ቁጥርዎን መላክ ወይም የቴሌግራም Usernameዎን (@username) ማስገባት ይችላሉ።\n\n"
        "💡 ለቀላል ግቤት '📲 ስልክ ቁጥር አጋራ' ባተን ይጠቀሙ።",
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
        phone = update.message.contact.phone_number
        contact_info = f"📞 {phone}"
    else:
        text = update.message.text.strip()
        if text.startswith('@'):
            contact_info = f"👤 {text}"
        elif validate_phone(text):
            contact_info = f"📞 {text}"
        else:
            await update.message.reply_text(
                "❌ እባክዎ ትክክለኛ የስልክ ቁጥር ወይም Username ያስገቡ።\n\n"
                "💡 ለምሳሌ፦\n"
                "• ስልክ: `0911223344`\n"
                "• Username: `@username`",
                parse_mode="Markdown",
                reply_markup=SHARE_CONTACT_KEYBOARD
            )
            return BUYER_PHONE
    
    main_cat = context.user_data.get('main_category', '')
    sub_cat = context.user_data.get('sub_category', '')
    action_type = context.user_data.get('action_type', '')
    prop_subtype = context.user_data.get('property_subtype', '')
    description = context.user_data.get('description', '')
    budget = context.user_data.get('budget', '')
    
    category_title = "🚗 አዲስ የመኪና ጥያቄ" if main_cat == "car" else "🏠 አዲስ የቤት/ቦታ ጥያቄ"
    user_name = f"{user.first_name} {user.last_name or ''}".strip()
    
    full_desc = (
        f"📌 **{category_title}**\n"
        f"🔹 አይነት: {prop_subtype if prop_subtype else sub_cat}\n"
        f"🔄 ፍላጎት: {action_type}\n"
        f"📝 ዝርዝር: {description}\n"
        f"💰 በጀት: {budget}\n"
        f"{contact_info}"
    )
    
    req_id = add_listing(user.id, user_name, username, 'BUY', main_cat, sub_cat, action_type, prop_subtype, budget, full_desc)
    
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

    return ConversationHandler.END

# ==============================================================================
# 8. BROKER RESPONSE FLOW
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
    
    listing = get_listing(req_id)
    if not listing or listing.get('status') != 'pending':
        await query.message.reply_text(
            "⛔ **ይህ ጥያቄ አስቀድሞ ተመልሷል!**\n\n"
            f"📌 ጥያቄ #{req_id} ሌላ አቅራቢ መልሶለታል።"
        )
        return ConversationHandler.END
    
    context.user_data['target_req_id'] = req_id
    context.user_data['target_buyer_id'] = buyer_id
    
    await query.message.reply_text(
        f"✅ **ጥያቄ #{req_id}**\n\n"
        f"✍️ **ያለዎትን ንብረት ዝርዝር መረጃ እና ዋጋ ያስገቡ፦**\n"
        f"(ለምሳሌ፦ ቶዮታ ቪትዝ 2021፣ 30,000 KM የሄደ፣ ዋጋ 2.4 ሚሊዮን...)",
        reply_markup=CANCEL_KEYBOARD
    )
    return BROKER_OFFER_TEXT

async def broker_offer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
        
    context.user_data['offer_text'] = update.message.text
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ይላኩ፦**\n(ፎቶ ከሌልዎት 'ፎቶ የለውም' ብለው ይጻፉ)",
        reply_markup=CANCEL_KEYBOARD
    )
    return BROKER_OFFER_PHOTO

async def broker_offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_id = None
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
    elif update.message.text and update.message.text.lower() == 'ፎቶ የለውም':
        photo_id = None
    elif update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith('image/'):
        photo_id = update.message.document.file_id
    else:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ ወይም 'ፎቶ የለውም' ይጻፉ።")
        return BROKER_OFFER_PHOTO
    
    context.user_data['offer_photo'] = photo_id
    
    await update.message.reply_text(
        "📞 **እርስዎን ለማግኘት የስልክ ቁጥርዎን ያስገቡ፦**\n\n"
        "💡 ለቀላል ግቤት '📲 ስልክ ቁጥር አጋራ' ባተን መጠቀም ይችላሉ።",
        reply_markup=SHARE_CONTACT_KEYBOARD
    )
    return BROKER_OFFER_PHONE_NUMBER

async def broker_offer_phone_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buyer_id = int(context.user_data.get('target_buyer_id'))
    req_id = context.user_data.get('target_req_id')
    offer_text = context.user_data.get('offer_text')
    photo_id = context.user_data.get('offer_photo')
    broker_name = update.effective_user.first_name
    broker_username = update.effective_user.username or ""
    
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if update.message.contact:
        broker_phone = update.message.contact.phone_number
    else:
        broker_phone = update.message.text
        if not validate_phone(broker_phone):
            await update.message.reply_text(
                "❌ ትክክለኛ የስልክ ቁጥር ያስገቡ።",
                reply_markup=SHARE_CONTACT_KEYBOARD
            )
            return BROKER_OFFER_PHONE_NUMBER
    
    update_listing_status(int(req_id), 'responded')
    
    username_text = f"👤 @{broker_username}" if broker_username else f"👤 {broker_name}"
    
    message_to_buyer = (
        f"🎉 **ለጥያቄዎ (#REQ-{req_id}) አዲስ የቀረበ አማራጭ አለ!**\n\n"
        f"{username_text}\n"
        f"📝 **የንብረቱ ዝርዝር፦**\n{offer_text}\n\n"
        f"📞 **ለመግባቢያ ስልክ፦** {broker_phone}\n\n"
        f"💡 *ከፈለጉ ደውለው መገበያየት ይችላሉ!*"
    )
    
    try:
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
            "📌 ጥያቄው ከ'📋 የፈላጊዎች ዝርዝር' ተወግዷል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    except Exception as e:
        logger.error(f"Failed to send offer to buyer: {e}")
        await update.message.reply_text("❌ መረጃውን ለፈላጊው መላክ አልተቻለም።", reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
        
    return ConversationHandler.END

# ==============================================================================
# 9. SELLER FLOW (ሻጭ)
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
        await query.edit_message_text(
            "🚗 **የመኪናውን ዝርዝር መረጃ ያስገቡ፦**\n\n"
            "💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020፣ አውቶማቲክ፣ 45,000 KM የሄደ",
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
    return SELLER_SUB

async def seller_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    htype = query.data.replace("flow_sell_htype_", "")
    context.user_data['property_subtype'] = htype
    
    await query.edit_message_text(
        f"🏠 **{htype}**\n\n"
        "✍️ **የቤቱን/ቦታውን ዝርዝር መረጃ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* ቦሌ አትላስ አካባቢ 3 መኝታ ቤት፣ ከፍተኛ ጥገና ያላስፈለገ",
        parse_mode="Markdown"
    )
    return SELLER_DETAILS

async def seller_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['description'] = update.message.text
    await update.message.reply_text(
        "💰 **የሚሸጡበትን/ሚያከራዩበትን ዋጋ ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* 2,500,000",
        parse_mode="Markdown",
        reply_markup=CANCEL_KEYBOARD
    )
    return SELLER_PRICE

async def seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_price(update.message.text):
        await update.message.reply_text(
            "❌ እባክዎ ትክክለኛ ቁጥር ያስገቡ።\n\n"
            "💡 ለምሳሌ፦ `2500000` ወይም `2,500,000`",
            parse_mode="Markdown"
        )
        return SELLER_PRICE
    
    context.user_data['price'] = update.message.text
    await update.message.reply_text(
        "📞 **የስልክ ቁጥርዎን ያስገቡ፦**\n\n"
        "💡 ለቀላል ግቤት '📲 ስልክ ቁጥር አጋራ' ባተን መጠቀም ይችላሉ።",
        reply_markup=SHARE_CONTACT_KEYBOARD
    )
    return SELLER_PHONE

async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text
    
    if not validate_phone(phone):
        await update.message.reply_text(
            "❌ ትክክለኛ የስልክ ቁጥር ያስገቡ።\n\n"
            "💡 ለምሳሌ፦ `0911223344`",
            reply_markup=SHARE_CONTACT_KEYBOARD
        )
        return SELLER_PHONE
    
    context.user_data['phone'] = phone
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ይላኩ፦**\n\n"
        "💡 *አንድ ፎቶ ብቻ ይላኩ*",
        reply_markup=CANCEL_KEYBOARD
    )
    return SELLER_PHOTO

async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    username = user.username or ""
    user_name = f"{user.first_name} {user.last_name or ''}".strip()
    
    # Handle photo
    if not update.message.photo:
        await update.message.reply_text(
            "❌ እባክዎ ፎቶ ይላኩ!",
            reply_markup=CANCEL_KEYBOARD
        )
        return SELLER_PHOTO
    
    photo_id = update.message.photo[-1].file_id
    
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
        user_name, 
        username, 
        'SELL', 
        context.user_data.get('main_category', ''), 
        context.user_data.get('sub_category', ''), 
        context.user_data.get('action_type', ''), 
        context.user_data.get('property_type', ''), 
        '', 
        desc
    )
    
    if req_id:
        await update.message.reply_text(
            "✅ **የማስታወቂያ ጥያቄዎ በስኬት ተመዝግቧል!** 🎉\n\n"
            f"📌 ማስታወቂያዎ ለደላሎች ተልኳል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    else:
        await update.message.reply_text(
            "❌ ማስታወቂያውን ማስመዝገብ አልተቻለም። እባክዎ እንደገና ይሞክሩ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 10. BROKER REGISTRATION
# ==============================================================================
async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    
    keyboard = [
        [InlineKeyboardButton("👨‍💼 ደላላ", callback_data="role_broker")],
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
    
    await query.edit_message_text(f"👤 **ምዝገባ፦ {role}**\n\n1️⃣ ሙሉ ስምዎን ያስገቡ፦")
    return BROKER_NAME

async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['broker_name'] = update.message.text
    await update.message.reply_text(
        "2️⃣ የስልክ ቁጥርዎን ያስገቡ፦\n\n💡 ለቀላል ግቤት '📲 ስልክ ቁጥር አጋራ' ባተን መጠቀም ይችላሉ።",
        reply_markup=SHARE_CONTACT_KEYBOARD
    )
    return BROKER_PHONE

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text
    
    if not validate_phone(phone):
        await update.message.reply_text(
            "❌ ትክክለኛ የስልክ ቁጥር ያስገቡ።\n\n"
            "💡 ለቀላል ግቤት '📲 ስልክ ቁጥር አጋራ' ባተን መጠቀም ይችላሉ።",
            reply_markup=SHARE_CONTACT_KEYBOARD
        )
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
    sub_city = query.data.replace("broker_sc_", "")
    context.user_data['broker_subcity'] = sub_city
    
    await query.edit_message_text(
        "4️⃣ **የፋይዳ (National ID) ወይም የነዋሪነት መታወቂያ ፎቶ ያንሱና ይላኩ፦**\n\n"
        "💡 *ፎቶውን እንደ ፎቶ ወይም ፋይል መላክ ይችላሉ*"
    )
    return BROKER_NID_PHOTO

async def broker_reg_nid_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    user = update.effective_user
    username = user.username or ""
    
    photo_id = None
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
    elif update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith('image/'):
        photo_id = update.message.document.file_id
    else:
        await update.message.reply_text(
            "❌ **እባክዎ የመታወቂያዎን ፎቶ ይላኩ!**\n\n"
            "📸 ፎቶውን እንደ:\n"
            "• ፎቶ (Photo)\n"
            "• ፋይል (Document)\n"
            "በመላክ ይችላሉ።"
        )
        return BROKER_NID_PHOTO
        
    role = context.user_data.get('broker_role', 'አቅራቢ')
    name = context.user_data.get('broker_name', user.first_name)
    phone = context.user_data.get('broker_phone', '')
    sub_city = context.user_data.get('broker_subcity', '')
    
    broker_id = add_broker(user.id, name, phone, username, role, photo_id, sub_city)
    
    if broker_id:
        await update.message.reply_text(
            "✅ **ምዝገባዎ በስኬት ተጠናቋል!** 🎉\n\n"
            "⏳ አድሚኑ መረጃዎን ካረጋገጠ በኋላ ማስታወቂያ ይደርስዎታል።\n\n"
            "📋 ምዝገባዎ ከጸደቀ በኋላ '📋 የፈላጊዎች ዝርዝር' ማየት ይችላሉ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID_INT:
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
                await update.message.reply_text("⚠️ ለአድሚን መላክ አልተቻለም፣ ነገር ግን ምዝገባዎ ተመዝግቧል።")
    else:
        await update.message.reply_text(
            "❌ **ምዝገባውን ማጠናቀቅ አልተቻለም!**\n\n"
            "💡 እባክዎ የሚከተሉትን ያረጋግጡ፦\n"
            "• መረጃዎቹ ሙሉ መሆናቸውን\n"
            "• የበይነመረብ ግንኙነትዎን\n\n"
            "🔄 እንደገና ለመሞከር '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይጫኑ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
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
            caption=query.message.caption + "\n\n✅ **ሁኔታ፦ በስኬት ጸድቋል (Approved)**",
            parse_mode="Markdown"
        )
        
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="🎉 **እንኳን ደስ አለዎት!** የምዝገባ ጥያቄዎ በአድሚን ጸድቋል።\n\n"
                     "📋 አሁን '📋 የፈላጊዎች ዝርዝር' በመጠቀም ጥያቄዎችን ማየት ይችላሉ።",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        except Exception as e:
            logger.error(f"Could not notify approved user: {e}")
            
    elif data.startswith("admin_reje_"):
        target_id = int(data.replace("admin_reje_", ""))
        update_broker_status(target_id, 'rejected')
        
        await query.edit_message_caption(
            caption=query.message.caption + "\n\n❌ **ሁኔታ፦ ተሰርዟል (Rejected)**",
            parse_mode="Markdown"
        )
        
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="❌ የምዝገባ ጥያቄዎ ተሰርዟል።\n\nለተጨማሪ መረጃ እባክዎን አድሚንን ያግኙ።",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
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
async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    broker = get_broker(user_id)
    
    if not broker:
        await update.message.reply_text(
            "⛔ ይህን ገጽ ማየት የሚችሉት የተመዘገቡ አቅራቢዎች/ደላሎች ብቻ ናቸው!\n\n"
            "📝 እባክዎን መጀመሪያ '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይጫኑ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    if broker.get('status') != 'approved':
        await update.message.reply_text(
            "⏳ **ምዝገባዎ ገና በአድሚን አልጸደቀም!**\n\n"
            "⏳ ምዝገባዎ በአድሚን ሲረጋገጥ ማስታወቂያ ይደርስዎታል።\n"
            "📞 ለተጨማሪ መረጃ ድጋፍን ይጠቀሙ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    context.user_data['view_page'] = 0
    await show_requests_page(update, context)

async def show_requests_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        page = context.user_data.get('view_page', 0)
        offset = page * ITEMS_PER_PAGE
        
        listings = get_listings_by_category(limit=ITEMS_PER_PAGE, offset=offset)
        total = count_listings()
        total_pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        
        if not listings:
            text = "📭 ምንም ንቁ ጥያቄዎች የሉም።"
            if update.message:
                await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
            else:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(text)
            return
        
        text = f"📋 **የፈላጊዎች ዝርዝር** (ገጽ {page+1}/{total_pages})\n\n"
        
        for listing in listings:
            listing_id = listing.get('id', '')
            description = listing.get('description', '')
            username = listing.get('username', '')
            if username:
                text += f"━━━━━━━━━━━━━━━━━━━━\n📌 **#{listing_id}** @{username}\n{description}\n"
            else:
                text += f"━━━━━━━━━━━━━━━━━━━━\n📌 **#{listing_id}**\n{description}\n"
        
        keyboard = []
        for listing in listings:
            l_id = listing.get('id')
            u_id = listing.get('user_chat_id')
            keyboard.append([InlineKeyboardButton(f"👉 አለኝ - #{l_id}", callback_data=f"have_item_{l_id}_{u_id}")])
        
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ ቀዳሚ", callback_data=f"page_{page-1}"))
        if offset + ITEMS_PER_PAGE < total:
            nav_buttons.append(InlineKeyboardButton("➡️ ቀጣይ", callback_data=f"page_{page+1}"))
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
# 13. HELP COMMAND
# ==============================================================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
❓ **እንዴት እንደሚጠቀሙ**

🔍 **መግዛት ከፈለጉ:**
• '🔍 መግዛት / መከራየት' ይምረጡ
• ምድብ ይምረጡ (መኪና/ቤት/ንግድ)
• ንኡስ ምድብ ይምረጡ
• ዝርዝር መረጃ ያስገቡ
• የበጀት ግምት ያስገቡ
• ስልክ ወይም Username ያስገቡ

📢 **መሸጥ ከፈለጉ:**
• '📢 መሸጥ / ማከራየት' ይምረጡ
• ምድብ ይምረጡ
• ዝርዝር መረጃ ያስገቡ
• ዋጋ ያስገቡ
• ስልክ ያስገቡ
• ፎቶ ይላኩ

📝 **እንደ አቅራቢ ለመመዝገብ:**
• '📝 እንደ አቅራቢ/ደላላ መመዝገብ' ይምረጡ
• ሚናዎን ይምረጡ
• የፋይዳ መታወቂያ ፎቶ ይላኩ
• አስተዳዳሪ ማጽደቅ ይጠብቁ

📋 **የፈላጊዎች ዝርዝር:**
• ለተመዘገቡ እና ለተጸደቁ አቅራቢዎች ብቻ
• ንቁ ጥያቄዎችን ያሳያል
• በገጽ ይከፋፈላል

🏠 **ዋና ገጽ:**
• ቀደም ሲል የነበረውን መልእክት ያጽዳል
• አዲስ ሜኑ ያመጣል

📲 **ስልክ ቁጥር:**
• '📲 ስልክ ቁጥር አጋራ' ባተን በመጠቀም በቀላሉ ማጋራት ይችላሉ
• ወይም በጽሁፍ መጻፍ ይችላሉ
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ==============================================================================
# 14. MAIN ENGINE
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))

    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)

    # ===== BUYER CONVERSATION =====
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
        states={
            BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_message_handler],
            BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_"), cancel_message_handler],
            BUYER_CATEGORY: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_message_handler],
            BUYER_SUB: [CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_"), CallbackQueryHandler(buyer_htype_chosen, pattern="^flow_buy_htype_"), cancel_message_handler],
            BUYER_PROPERTY: [CallbackQueryHandler(buyer_property_chosen, pattern="^flow_buy_prop_"), cancel_message_handler],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details), cancel_message_handler],
            BUYER_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_budget), cancel_message_handler],
            BUYER_PHONE: [MessageHandler((filters.TEXT | filters.CONTACT) & ~filters.COMMAND, buyer_phone), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== SELLER CONVERSATION =====
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_"), cancel_message_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_message_handler],
            SELLER_SUB: [CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_"), cancel_message_handler],
            SELLER_PROPERTY: [CallbackQueryHandler(seller_property_chosen, pattern="^flow_sell_prop_"), cancel_message_handler],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details), cancel_message_handler],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price), cancel_message_handler],
            SELLER_PHONE: [MessageHandler((filters.TEXT | filters.CONTACT) & ~filters.COMMAND, seller_phone), cancel_message_handler],
            SELLER_PHOTO: [MessageHandler(filters.PHOTO, seller_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== BROKER REGISTRATION =====
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ/ደላላ መመዝገብ$"), broker_reg_start)],
        states={
            BROKER_ROLE: [CallbackQueryHandler(broker_role_chosen, pattern="^role_"), cancel_message_handler],
            BROKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name), cancel_message_handler],
            BROKER_PHONE: [MessageHandler((filters.TEXT | filters.CONTACT) & ~filters.COMMAND, broker_reg_phone), cancel_message_handler],
            BROKER_SUBCITY: [CallbackQueryHandler(broker_reg_subcity, pattern="^broker_sc_"), cancel_message_handler],
            BROKER_NID_PHOTO: [MessageHandler((filters.PHOTO | filters.Document.IMAGE | filters.TEXT) & ~filters.COMMAND, broker_reg_nid_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== BROKER RESPONSE =====
    broker_response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broker_have_item_click, pattern="^have_item_")],
        states={
            BROKER_OFFER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text), cancel_message_handler],
            BROKER_OFFER_PHOTO: [MessageHandler((filters.PHOTO | filters.Document.IMAGE | filters.TEXT) & ~filters.COMMAND, broker_offer_photo), cancel_message_handler],
            BROKER_OFFER_PHONE_NUMBER: [MessageHandler((filters.TEXT | filters.CONTACT) & ~filters.COMMAND, broker_offer_phone_number), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== OTHER HANDLERS =====
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(MessageHandler(cancel_filter, go_home))
    app.add_handler(CallbackQueryHandler(show_requests_page, pattern="^page_"))
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(admin_approval_callback, pattern="^admin_"))

    # ===== ADD CONVERSATIONS =====
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(broker_response_conv)

    # ===== ERROR HANDLER =====
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} caused error: {context.error}", exc_info=True)

    app.add_error_handler(error_handler)

    logger.info("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()