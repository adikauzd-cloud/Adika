import logging
import os
import threading
import psycopg2
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
from datetime import datetime

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

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable ውስጥ አልተገኘም።")

ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID) if ADMIN_CHAT_ID else 0

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================================================================
# 2. DATABASE
# ==============================================================================
def get_db_connection():
    if DATABASE_URL:
        db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        return conn
    else:
        import sqlite3
        return sqlite3.connect("adika_marketplace.db")

def get_placeholder():
    return "%s" if DATABASE_URL else "?"

def init_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Listings table with enhanced fields
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
                    price TEXT,
                    negotiable TEXT,
                    contact_method TEXT,
                    contact_info TEXT,
                    status TEXT DEFAULT 'pending',
                    request_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
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
                    price TEXT,
                    negotiable TEXT,
                    contact_method TEXT,
                    contact_info TEXT,
                    status TEXT DEFAULT 'pending',
                    request_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        # Brokers table
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS brokers (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    location TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS brokers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    location TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        if DATABASE_URL:
            conn.commit()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    finally:
        if conn:
            conn.close()

# ========== LISTING FUNCTIONS ==========
def add_listing(user_chat_id, user_name, req_type, main_category, sub_category, action_type, 
                property_type, description, price, negotiable, contact_method, contact_info):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        prefix = "CAR" if main_category == "car" else "HSE"
        req_id = f"{prefix}-{user_chat_id}-{int(datetime.now().timestamp()) % 10000}"
        
        if DATABASE_URL:
            cursor.execute(f"""
                INSERT INTO listings 
                (user_chat_id, user_name, req_type, main_category, sub_category, action_type, 
                 property_type, description, price, negotiable, contact_method, contact_info, request_id)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}) RETURNING id
            """, (user_chat_id, user_name, req_type, main_category, sub_category, action_type, 
                  property_type, description, price, negotiable, contact_method, contact_info, req_id))
            listing_id = cursor.fetchone()[0]
            conn.commit()
        else:
            cursor.execute(f"""
                INSERT INTO listings 
                (user_chat_id, user_name, req_type, main_category, sub_category, action_type, 
                 property_type, description, price, negotiable, contact_method, contact_info, request_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_chat_id, user_name, req_type, main_category, sub_category, action_type, 
                  property_type, description, price, negotiable, contact_method, contact_info, req_id))
            listing_id = cursor.lastrowid
        
        return listing_id, req_id
    except Exception as e:
        logger.error(f"Add listing error: {e}")
        return None, None
    finally:
        if conn:
            conn.close()

def get_user_listings(user_chat_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM listings WHERE user_chat_id = {p} ORDER BY created_at DESC", (user_chat_id,))
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logger.error(f"Get user listings error: {e}")
        return []
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 3. KEYBOARDS & CONSTANTS
# ==============================================================================
MAIN_KEYBOARD = [
    ["🚗 መኪና (ለመግዛት / ለመሸጥ)"],
    ["🏠 ቤት/ቦታ (ለመግዛት / ለመሸጥ)"],
    ["📋 የእኔ ጥያቄዎች / ማስታወቂያዎች"],
    ["📞 እኛን ለማነጋገር", "🏠 ወደ ዋና ገጽ"]
]

HOUSE_TYPES = ["🏢 ኮንዶሚኒየም", "🏡 ቪላ / መኖሪያ ቤት", "🏬 ንግድ ቤት/ፎቅ", "📐 ባዶ ቦታ/መሬት"]

# ==============================================================================
# 4. CONVERSATION STATES
# ==============================================================================
CAR_BUYER_MODEL, CAR_BUYER_YEAR, CAR_BUYER_BUDGET, CAR_BUYER_CONTACT, CAR_BUYER_CONFIRM = range(5)
CAR_SELLER_MODEL, CAR_SELLER_YEAR_COND, CAR_SELLER_PRICE, CAR_SELLER_NEGO, CAR_SELLER_CONTACT, CAR_SELLER_CONFIRM = range(5, 11)
HOUSE_BUYER_TYPE, HOUSE_BUYER_LOCATION, HOUSE_BUYER_PRICE, HOUSE_BUYER_NEGO, HOUSE_BUYER_CONTACT, HOUSE_BUYER_CONFIRM = range(11, 17)
HOUSE_SELLER_TYPE, HOUSE_SELLER_LOCATION, HOUSE_SELLER_PRICE, HOUSE_SELLER_NEGO, HOUSE_SELLER_CONTACT, HOUSE_SELLER_CONFIRM = range(17, 23)

# ==============================================================================
# 5. START & CANCEL HANDLERS
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = (
        "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
        "🏢 **የሪል እስቴት እና የመኪና ደላላ አገልግሎት**\n\n"
        "በፍጥነት ይግዙ፣ ይሽጡ ወይም ያከራዩ።\n\n"
        "እባክዎን ከታች ካሉት አማራጮች ይምረጡ፦"
    )
    if update.message:
        await update.message.reply_text(
            welcome_text,
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    return ConversationHandler.END

async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await start(update, context)

# ==============================================================================
# 6. CATEGORY SELECTION MENUS
# ==============================================================================
async def car_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🛒 መኪና ለመግዛት", callback_data="car_buy_start")],
        [InlineKeyboardButton("🏷️ መኪና ለመሸጥ", callback_data="car_sell_start")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🚗 **የመኪና አገልግሎት ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def house_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🛒 ቤት/ቦታ ለመግዛት", callback_data="house_buy_start")],
        [InlineKeyboardButton("🏷️ ቤት/ቦታ ለመሸጥ", callback_data="house_sell_start")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🏠 **የቤት እና ቦታ አገልግሎት ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def my_listings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    listings = get_user_listings(user_id)
    if not listings:
        await update.message.reply_text("📋 ምንም የተመዘገበ ማስታወቂያ ወይም ጥያቄ የለዎትም።")
        return
    
    msg = "📋 **የእርስዎ ማስታወቂያዎች / ጥያቄዎች፦**\n\n"
    for item in listings[:5]:
        msg += f"🆔 **ID:** `{item[13] if len(item)>13 else item[0]}`\n"
        msg += f"📌 **ዓይነት:** {item[3]} ({item[2]})\n"
        msg += f"📝 **መግለጫ:** {item[7]}\n"
        msg += f"💰 **ዋጋ:** {item[8]}\n"
        msg += f" status: {item[12]}\n"
        msg += "-------------------------\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def contact_us(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📞 **እኛን ለማነጋገር፦**\n\n"
        "📱 ስልክ፦ 0911XXXXXX\n"
        "✈️ ቴሌግራም፦ @AdikaAdmin\n"
        "📍 አድራሻ፦ አዲስ አበባ፣ ኢትዮጵያ"
    )

# ==============================================================================
# 7. CAR BUYER FLOW
# ==============================================================================
async def car_buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    context.user_data['main_category'] = 'car'
    context.user_data['action_type'] = 'buy'
    
    await query.edit_message_text(
        "🚗 **መኪና ለመግዛት**\n\n"
        "1️⃣ እባክዎን የሚፈልጉትን የመኪና ዓይነት ወይም ሞዴል ያክሉ?\n"
        "💡 *ምሳሌ፦* Toyota Vitz, Hyundai Tucson, Ford...",
        parse_mode="Markdown"
    )
    return CAR_BUYER_MODEL

async def car_buyer_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['car_model'] = update.message.text
    await update.message.reply_text(
        "2️⃣ የምርት ዘመን ይምረጡ ወይም ያስገቡ (ከስንት እስከ ስንት)?\n"
        "💡 *ምሳሌ፦* 2015 - 2020",
        parse_mode="Markdown"
    )
    return CAR_BUYER_YEAR

async def car_buyer_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['car_year'] = update.message.text
    await update.message.reply_text(
        "3️⃣ መመደብ የሚችሉት የበጀት መጠን ስንት ነው?\n"
        "💡 *ምሳሌ፦* 2,000,000 - 3,000,000 ብር",
        parse_mode="Markdown"
    )
    return CAR_BUYER_BUDGET

async def car_buyer_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['budget'] = update.message.text
    
    keyboard = [
        [InlineKeyboardButton("📱 ስልክ ቁጥር ለማስገባት", callback_data="contact_phone")],
        [InlineKeyboardButton("✈️ በTelegram Username", callback_data="contact_username")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "4️⃣ የፍላጎትዎን መረጃ መዝግበናል።\n\n"
        "እርስዎን ለማነጋገር የትኛውን የመገናኛ መንገድ ይጠቀማሉ?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CAR_BUYER_CONTACT

async def car_buyer_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    method = query.data.replace("contact_", "")
    context.user_data['contact_method'] = "phone" if method == "phone" else "username"
    
    if method == "phone":
        await query.edit_message_text(
            "📱 **እባክዎን የስልክ ቁጥርዎን ያስገቡ፦**\n"
            "💡 *ምሳሌ፦* 0911XXXXXX",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            "✈️ **እባክዎን የቴሌግራም አድራሻዎን ያስገቡ፦**\n"
            "💡 *ምሳሌ፦* @yourusername",
            parse_mode="Markdown"
        )
    return CAR_BUYER_CONFIRM

async def car_buyer_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
        
    context.user_data['contact_info'] = update.message.text
    
    desc = (
        f"🚗 **መኪና ጥያቄ**\n\n"
        f"📌 ሞዴል: {context.user_data.get('car_model')}\n"
        f"📅 ዘመን: {context.user_data.get('car_year')}\n"
        f"💰 በጀት: {context.user_data.get('budget')}\n"
        f"📞 መገናኛ: {context.user_data.get('contact_method')} - {context.user_data.get('contact_info')}"
    )
    context.user_data['final_desc'] = desc
    
    keyboard = [
        [InlineKeyboardButton("✅ አረጋግጥ እና ላክ", callback_data="confirm_yes")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    
    await update.message.reply_text(
        f"📋 **እባክዎን መረጃዎቹን ያረጋግጡ**\n\n{desc}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CAR_BUYER_CONFIRM

# ==============================================================================
# 8. CAR SELLER FLOW
# ==============================================================================
async def car_seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    context.user_data['main_category'] = 'car'
    context.user_data['action_type'] = 'sell'
    
    await query.edit_message_text(
        "🚗 **መኪና ለመሸጥ**\n\n"
        "1️⃣ የሚሸጡትን መኪና ሞዴል እና የሰሪው ስም ያስገቡ\n"
        "💡 *ምሳሌ፦* Toyota Yaris Executive",
        parse_mode="Markdown"
    )
    return CAR_SELLER_MODEL

async def car_seller_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['car_model'] = update.message.text
    await update.message.reply_text(
        "2️⃣ የመኪናውን የምርት ዘመን (Year) እና ያገለገለበትን ሁኔታ ያስገቡ\n"
        "💡 *ምሳሌ፦* 2018፣ በኢትዮጵያ ያልተነዳ / ያገለገለ",
        parse_mode="Markdown"
    )
    return CAR_SELLER_YEAR_COND

async def car_seller_year_cond(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['car_year_cond'] = update.message.text
    await update.message.reply_text(
        "3️⃣ የመኪናው መሸጫ ዋጋ ስንት ነው?",
        parse_mode="Markdown"
    )
    return CAR_SELLER_PRICE

async def car_seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🤝 ድርድር አለው", callback_data="nego_yes")],
        [InlineKeyboardButton("🔒 ቋሚ ዋጋ ነው", callback_data="nego_no")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🔄 **የዋጋው ሁኔታ እንዴት ነው?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CAR_SELLER_NEGO

async def car_seller_nego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['negotiable'] = "🤝 ድርድር አለው" if query.data == "nego_yes" else "🔒 ቋሚ ዋጋ"
    
    keyboard = [
        [InlineKeyboardButton("📱 ስልክ ቁጥር ለማስገባት", callback_data="contact_phone")],
        [InlineKeyboardButton("✈️ በTelegram Username", callback_data="contact_username")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await query.edit_message_text(
        "4️⃣ **የመገናኛ አማራጭዎን ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CAR_SELLER_CONTACT

async def car_seller_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    method = query.data.replace("contact_", "")
    context.user_data['contact_method'] = "phone" if method == "phone" else "username"
    
    if method == "phone":
        await query.edit_message_text(
            "📱 **እባክዎን የስልክ ቁጥርዎን ያስገቡ፦**",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            "✈️ **እባክዎን የቴሌግራም አድራሻዎን ያስገቡ፦**",
            parse_mode="Markdown"
        )
    return CAR_SELLER_CONFIRM

async def car_seller_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
        
    context.user_data['contact_info'] = update.message.text
    
    desc = (
        f"🚗 **መኪና ለሽያጭ**\n\n"
        f"📌 ሞዴል: {context.user_data.get('car_model')}\n"
        f"📅 ዘመን/ሁኔታ: {context.user_data.get('car_year_cond')}\n"
        f"💰 ዋጋ: {context.user_data.get('price')}\n"
        f"🔄 {context.user_data.get('negotiable')}\n"
        f"📞 መገናኛ: {context.user_data.get('contact_method')} - {context.user_data.get('contact_info')}"
    )
    context.user_data['final_desc'] = desc
    
    keyboard = [
        [InlineKeyboardButton("✅ አረጋግጥ እና ላክ", callback_data="confirm_yes")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    
    await update.message.reply_text(
        f"📋 **እባክዎን መረጃዎቹን ያረጋግጡ**\n\n{desc}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CAR_SELLER_CONFIRM

# ==============================================================================
# 9. HOUSE BUYER FLOW
# ==============================================================================
async def house_buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    context.user_data['main_category'] = 'house'
    context.user_data['action_type'] = 'buy'
    
    keyboard = []
    for htype in HOUSE_TYPES:
        keyboard.append([InlineKeyboardButton(htype, callback_data=f"hbuy_type_{htype}")])
    keyboard.append([InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")])
    
    await query.edit_message_text(
        "🏠 **ቤት/ቦታ ለመግዛት**\n\n"
        "1️⃣ የሚፈልጉትን የቦታ/ንብረት አይነት ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_BUYER_TYPE

async def house_buyer_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['house_type'] = query.data.replace("hbuy_type_", "")
    context.user_data['property_type'] = "residential" if "ቪላ" in query.data or "ኮንዶ" in query.data else "commercial"
    
    await query.edit_message_text(
        f"🏠 **{context.user_data['house_type']}**\n\n"
        "2️⃣ ንብረቱ የሚገኝበትን ቦታ/አድራሻ ያስገቡ\n"
        "💡 *ምሳሌ፦* አዲስ አበባ፣ ቦሌ ክፍለ ከተማ፣ አትላስ አካባቢ",
        parse_mode="Markdown"
    )
    return HOUSE_BUYER_LOCATION

async def house_buyer_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['location'] = update.message.text
    await update.message.reply_text(
        "3️⃣ የንብረቱ ጠቅላላ ዋጋ ስንት ነው? (በብር)",
        parse_mode="Markdown"
    )
    return HOUSE_BUYER_PRICE

async def house_buyer_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🤝 ድርድር አለው", callback_data="nego_yes")],
        [InlineKeyboardButton("🔒 ቋሚ ዋጋ ነው", callback_data="nego_no")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🔄 **የዋጋው ሁኔታ እንዴት ነው?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_BUYER_NEGO

async def house_buyer_nego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['negotiable'] = "🤝 ድርድር አለው" if query.data == "nego_yes" else "🔒 ቋሚ ዋጋ"
    
    keyboard = [
        [InlineKeyboardButton("📱 ስልክ ቁጥር ለማስገባት", callback_data="contact_phone")],
        [InlineKeyboardButton("✈️ በTelegram Username", callback_data="contact_username")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await query.edit_message_text(
        "4️⃣ **የመገናኛ አማራጭዎን ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_BUYER_CONTACT

async def house_buyer_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    method = query.data.replace("contact_", "")
    context.user_data['contact_method'] = "phone" if method == "phone" else "username"
    
    if method == "phone":
        await query.edit_message_text(
            "📱 **እባክዎን የስልክ ቁጥርዎን ያስገቡ፦**",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            "✈️ **እባክዎን የቴሌግራም አድራሻዎን ያስገቡ፦**",
            parse_mode="Markdown"
        )
    return HOUSE_BUYER_CONFIRM

async def house_buyer_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
        
    context.user_data['contact_info'] = update.message.text
    
    desc = (
        f"🏠 **ቤት ጥያቄ**\n\n"
        f"🏠 አይነት: {context.user_data.get('house_type')}\n"
        f"📍 አካባቢ: {context.user_data.get('location')}\n"
        f"💰 ዋጋ: {context.user_data.get('price')}\n"
        f"🔄 {context.user_data.get('negotiable')}\n"
        f"📞 መገናኛ: {context.user_data.get('contact_method')} - {context.user_data.get('contact_info')}"
    )
    context.user_data['final_desc'] = desc
    
    keyboard = [
        [InlineKeyboardButton("✅ አረጋግጥ እና ላክ", callback_data="confirm_yes")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    
    await update.message.reply_text(
        f"📋 **እባክዎን መረጃዎቹን ያረጋግጡ**\n\n{desc}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_BUYER_CONFIRM

# ==============================================================================
# 10. HOUSE SELLER FLOW
# ==============================================================================
async def house_seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    context.user_data['main_category'] = 'house'
    context.user_data['action_type'] = 'sell'
    
    keyboard = []
    for htype in HOUSE_TYPES:
        keyboard.append([InlineKeyboardButton(htype, callback_data=f"hsell_type_{htype}")])
    keyboard.append([InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")])
    
    await query.edit_message_text(
        "🏠 **ቤት/ቦታ ለመሸጥ**\n\n"
        "1️⃣ የሚሸጡትን የቦታ/ንብረት አይነት ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_SELLER_TYPE

async def house_seller_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['house_type'] = query.data.replace("hsell_type_", "")
    context.user_data['property_type'] = "residential" if "ቪላ" in query.data or "ኮንዶ" in query.data else "commercial"
    
    await query.edit_message_text(
        f"🏠 **{context.user_data['house_type']}**\n\n"
        "2️⃣ ንብረቱ የሚገኝበትን ቦታ/አድራሻ ያስገቡ\n"
        "💡 *ምሳሌ፦* አዲስ አበባ፣ ቦሌ ክፍለ ከተማ፣ አትላስ አካባቢ",
        parse_mode="Markdown"
    )
    return HOUSE_SELLER_LOCATION

async def house_seller_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['location'] = update.message.text
    await update.message.reply_text(
        "3️⃣ የንብረቱ ጠቅላላ ዋጋ ስንት ነው? (በብር)",
        parse_mode="Markdown"
    )
    return HOUSE_SELLER_PRICE

async def house_seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("🤝 ድርድር አለው", callback_data="nego_yes")],
        [InlineKeyboardButton("🔒 ቋሚ ዋጋ ነው", callback_data="nego_no")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        "🔄 **የዋጋው ሁኔታ እንዴት ነው?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_SELLER_NEGO

async def house_seller_nego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    context.user_data['negotiable'] = "🤝 ድርድር አለው" if query.data == "nego_yes" else "🔒 ቋሚ ዋጋ"
    
    keyboard = [
        [InlineKeyboardButton("📱 ስልክ ቁጥር ለማስገባት", callback_data="contact_phone")],
        [InlineKeyboardButton("✈️ በTelegram Username", callback_data="contact_username")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    await query.edit_message_text(
        "4️⃣ **የመገናኛ አማራጭዎን ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_SELLER_CONTACT

async def house_seller_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    method = query.data.replace("contact_", "")
    context.user_data['contact_method'] = "phone" if method == "phone" else "username"
    
    if method == "phone":
        await query.edit_message_text(
            "📱 **እባክዎን የስልክ ቁጥርዎን ያስገቡ፦**",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            "✈️ **እባክዎን የቴሌግራም አድራሻዎን ያስገቡ፦**",
            parse_mode="Markdown"
        )
    return HOUSE_SELLER_CONFIRM

async def house_seller_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ወደ ዋና ገጽ":
        return await go_home(update, context)
        
    context.user_data['contact_info'] = update.message.text
    
    desc = (
        f"🏠 **ቤት ለሽያጭ**\n\n"
        f"🏠 አይነት: {context.user_data.get('house_type')}\n"
        f"📍 አካባቢ: {context.user_data.get('location')}\n"
        f"💰 ዋጋ: {context.user_data.get('price')}\n"
        f"🔄 {context.user_data.get('negotiable')}\n"
        f"📞 መገናኛ: {context.user_data.get('contact_method')} - {context.user_data.get('contact_info')}"
    )
    context.user_data['final_desc'] = desc
    
    keyboard = [
        [InlineKeyboardButton("✅ አረጋግጥ እና ላክ", callback_data="confirm_yes")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="flow_home")]
    ]
    
    await update.message.reply_text(
        f"📋 **እባክዎን መረጃዎቹን ያረጋግጡ**\n\n{desc}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return HOUSE_SELLER_CONFIRM

# ==============================================================================
# 11. CONFIRMATION HANDLER & SAVE TO DB
# ==============================================================================
async def confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "flow_home":
        return await go_home(update, context)
    
    await query.answer()
    user = update.effective_user
    
    req_type = context.user_data.get('req_type', 'BUY')
    main_cat = context.user_data.get('main_category', '')
    sub_cat = context.user_data.get('car_model') or context.user_data.get('house_type')
    action_type = context.user_data.get('action_type', '')
    prop_type = context.user_data.get('property_type', '')
    desc = context.user_data.get('final_desc', 'No Description')
    price = context.user_data.get('price') or context.user_data.get('budget', 'N/A')
    nego = context.user_data.get('negotiable', 'N/A')
    contact_method = context.user_data.get('contact_method', 'N/A')
    contact_info = context.user_data.get('contact_info', 'N/A')

    listing_id, req_id = add_listing(
        user.id, user.full_name, req_type, main_cat, sub_cat,
        action_type, prop_type, desc, price, nego, contact_method, contact_info
    )

    if req_id:
        success_text = (
            f"🎉 **መረጃዎ በስኬት ተመዝግቧል!**\n\n"
            f"🆔 **የጥያቄ መለያ ቁጥር (Request ID):** `{req_id}`\n\n"
            f"ቡድናችን መረጃውን ተመልክቶ በቅርብ ጊዜ ያነጋግርዎታል። አመሰግናለን!"
        )
        await query.edit_message_text(success_text, parse_mode="Markdown")

        # Notify Admin
        if ADMIN_CHAT_ID_INT != 0:
            try:
                admin_msg = (
                    f"🔔 **አዲስ ማስታወቂያ/ጥያቄ ደርሷል!**\n\n"
                    f"🆔 Request ID: `{req_id}`\n"
                    f"👤 ተጠቃሚ: {user.full_name} (@{user.username})\n"
                    f"📄 ዝርዝር፦\n{desc}"
                )
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID_INT, text=admin_msg, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Failed to send admin notification: {e}")
    else:
        await query.edit_message_text("❌ ይቅርታ፣ መረጃውን መመዝገብ አልተቻለም። እባክዎን በኋላ እንደገና ይሞክሩ።")

    context.user_data.clear()
    return ConversationHandler.END

# ==============================================================================
# 12. MAIN APPLICATION & HANDLER SETUP
# ==============================================================================
def main():
    init_db()

    # Flask background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    application = Application.builder().token(BOT_TOKEN).build()

    # Conversation Handlers
    car_buyer_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(car_buyer_start, pattern="^car_buy_start$")],
        states={
            CAR_BUYER_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_buyer_model)],
            CAR_BUYER_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_buyer_year)],
            CAR_BUYER_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_buyer_budget)],
            CAR_BUYER_CONTACT: [CallbackQueryHandler(car_buyer_contact, pattern="^(contact_|flow_home)")],
            CAR_BUYER_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, car_buyer_confirm),
                CallbackQueryHandler(confirm_handler, pattern="^(confirm_yes|flow_home)$")
            ],
        },
        fallbacks=[MessageHandler(filters.Regex("^🏠 ወደ ዋና ገጽ$"), go_home)],
        per_message=False
    )

    car_seller_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(car_seller_start, pattern="^car_sell_start$")],
        states={
            CAR_SELLER_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_seller_model)],
            CAR_SELLER_YEAR_COND: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_seller_year_cond)],
            CAR_SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, car_seller_price)],
            CAR_SELLER_NEGO: [CallbackQueryHandler(car_seller_nego, pattern="^(nego_|flow_home)")],
            CAR_SELLER_CONTACT: [CallbackQueryHandler(car_seller_contact, pattern="^(contact_|flow_home)")],
            CAR_SELLER_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, car_seller_confirm),
                CallbackQueryHandler(confirm_handler, pattern="^(confirm_yes|flow_home)$")
            ],
        },
        fallbacks=[MessageHandler(filters.Regex("^🏠 ወደ ዋና ገጽ$"), go_home)],
        per_message=False
    )

    house_buyer_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(house_buyer_start, pattern="^house_buy_start$")],
        states={
            HOUSE_BUYER_TYPE: [CallbackQueryHandler(house_buyer_type, pattern="^(hbuy_type_|flow_home)")],
            HOUSE_BUYER_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, house_buyer_location)],
            HOUSE_BUYER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, house_buyer_price)],
            HOUSE_BUYER_NEGO: [CallbackQueryHandler(house_buyer_nego, pattern="^(nego_|flow_home)")],
            HOUSE_BUYER_CONTACT: [CallbackQueryHandler(house_buyer_contact, pattern="^(contact_|flow_home)")],
            HOUSE_BUYER_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, house_buyer_confirm),
                CallbackQueryHandler(confirm_handler, pattern="^(confirm_yes|flow_home)$")
            ],
        },
        fallbacks=[MessageHandler(filters.Regex("^🏠 ወደ ዋና ገጽ$"), go_home)],
        per_message=False
    )

    house_seller_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(house_seller_start, pattern="^house_sell_start$")],
        states={
            HOUSE_SELLER_TYPE: [CallbackQueryHandler(house_seller_type, pattern="^(hsell_type_|flow_home)")],
            HOUSE_SELLER_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, house_seller_location)],
            HOUSE_SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, house_seller_price)],
            HOUSE_SELLER_NEGO: [CallbackQueryHandler(house_seller_nego, pattern="^(nego_|flow_home)")],
            HOUSE_SELLER_CONTACT: [CallbackQueryHandler(house_seller_contact, pattern="^(contact_|flow_home)")],
            HOUSE_SELLER_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, house_seller_confirm),
                CallbackQueryHandler(confirm_handler, pattern="^(confirm_yes|flow_home)$")
            ],
        },
        fallbacks=[MessageHandler(filters.Regex("^🏠 ወደ ዋና ገጽ$"), go_home)],
        per_message=False
    )

    # Register Main Commands and Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Regex("^🏠 ወደ ዋና ገጽ$"), go_home))
    application.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    
    application.add_handler(MessageHandler(filters.Regex("^🚗 መኪና \(ለመግዛት / ለመሸጥ\)$"), car_main_menu))
    application.add_handler(MessageHandler(filters.Regex("^🏠 ቤት/ቦታ \(ለመግዛት / ለመሸጥ\)$"), house_main_menu))
    application.add_handler(MessageHandler(filters.Regex("^📋 የእኔ ጥያቄዎች / ማስታወቂያዎች$"), my_listings))
    application.add_handler(MessageHandler(filters.Regex("^📞 እኛን ለማነጋገር$"), contact_us))

    # Register Conversation Handlers
    application.add_handler(car_buyer_conv)
    application.add_handler(car_seller_conv)
    application.add_handler(house_buyer_conv)
    application.add_handler(house_seller_conv)

    # Start Polling
    logger.info("🚀 Adika Marketplace Bot እየሰራ ይገኛል...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
