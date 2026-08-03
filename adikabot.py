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
# 2. DATABASE INITIALIZATION
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
        
        # Brokers/Vendors table
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vendors (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL UNIQUE,
                    vendor_type TEXT NOT NULL,
                    document_id TEXT,
                    is_verified INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vendors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL UNIQUE,
                    vendor_type TEXT NOT NULL,
                    document_id TEXT,
                    is_verified INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        # Listings table
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id SERIAL PRIMARY KEY,
                    user_chat_id BIGINT NOT NULL,
                    user_name TEXT,
                    req_type TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
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
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
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

# ========== VENDOR FUNCTIONS ==========
def add_vendor(chat_id, full_name, phone, vendor_type, document_id=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        if DATABASE_URL:
            cursor.execute(f"""
                INSERT INTO vendors (chat_id, full_name, phone, vendor_type, document_id)
                VALUES ({p}, {p}, {p}, {p}, {p}) RETURNING id
            """, (chat_id, full_name, phone, vendor_type, document_id))
            vendor_id = cursor.fetchone()[0]
            conn.commit()
        else:
            cursor.execute(f"""
                INSERT INTO vendors (chat_id, full_name, phone, vendor_type, document_id)
                VALUES (?, ?, ?, ?, ?)
            """, (chat_id, full_name, phone, vendor_type, document_id))
            vendor_id = cursor.lastrowid
        return vendor_id
    except Exception as e:
        logger.error(f"Add vendor error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_vendor(chat_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM vendors WHERE chat_id = {p} AND is_active = 1", (chat_id,))
        row = cursor.fetchone()
        return row
    except Exception as e:
        logger.error(f"Get vendor error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def verify_vendor(vendor_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"UPDATE vendors SET is_verified = 1 WHERE id = {p}", (vendor_id,))
        if DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Verify vendor error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_all_vendors():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vendors WHERE is_active = 1 ORDER BY registered_at DESC")
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logger.error(f"Get vendors error: {e}")
        return []
    finally:
        if conn:
            conn.close()

# ========== LISTING FUNCTIONS ==========
def add_listing(user_chat_id, user_name, req_type, category, description):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        if DATABASE_URL:
            cursor.execute(f"""
                INSERT INTO listings (user_chat_id, user_name, req_type, category, description)
                VALUES ({p}, {p}, {p}, {p}, {p}) RETURNING id
            """, (user_chat_id, user_name, req_type, category, description))
            req_id = cursor.fetchone()[0]
            conn.commit()
        else:
            cursor.execute(f"""
                INSERT INTO listings (user_chat_id, user_name, req_type, category, description)
                VALUES (?, ?, ?, ?, ?)
            """, (user_chat_id, user_name, req_type, category, description))
            req_id = cursor.lastrowid
        return req_id
    except Exception as e:
        logger.error(f"Add listing error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_all_listings():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM listings WHERE status = 'pending' ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logger.error(f"Get listings error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_listing(req_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM listings WHERE id = {p}", (req_id,))
        row = cursor.fetchone()
        return row
    except Exception as e:
        logger.error(f"Get listing error: {e}")
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
        if DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Update listing error: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 3. KEYBOARDS & CONSTANTS
# ==============================================================================
MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ መመዝገብ", "📋 የፈላጊዎች ዝርዝር"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]

LOCATIONS = ["ቦሌ", "ሲኤምሲ", "ሳሪስ", "አያት", "ገርጂ", "ካዛንችስ", "መገናኛ", "ቃሊቲ", "ልደታ", "አራዳ"]

VENDOR_TYPES = ["🏢 ሪል እስቴት አልሚ", "🏪 የመኪና መሸጫ", "👨‍💼 ደላላ", "👤 የግል ባለቤት"]

# ==============================================================================
# 4. CONVERSATION STATES
# ==============================================================================
# Market Flow States
FLOW_ROLE, FLOW_CAT, FLOW_CAR_TYPE, FLOW_CAR_PAYMENT, FLOW_DESC = range(5)
SELL_MAKE, SELL_MODEL, SELL_PRICE, SELL_PAYMENT, SELL_PHONE, SELL_PHOTO = range(5, 11)

# Response Flow States
RESP_ROLE, RESP_CAR_MAKE, RESP_CAR_MODEL, RESP_PRICE, RESP_PHONE, RESP_PHOTO = range(11, 17)

# Vendor Registration States
VENDOR_NAME, VENDOR_PHONE, VENDOR_TYPE, VENDOR_DOCUMENT = range(17, 21)

# ==============================================================================
# 5. GENERAL HANDLERS
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    """ሂደቱን ትቶ ወደ ዋና ገጽ ይመልሳል"""
    context.user_data.clear()
    await update.message.reply_text(
        "🏠 ወደ ዋና ገጽ ተመልሰሃል።",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    return ConversationHandler.END

async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ ሂደቱ ተቋርጧል።",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    return ConversationHandler.END

# ==============================================================================
# 6. HELP
# ==============================================================================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
❓ **እንዴት እንደሚጠቀሙ**

🔍 **መግዛት ከፈለጉ:**
• '🔍 መግዛት / መከራየት' ይምረጡ
• መኪና ወይም ቤት ይምረጡ
• መረጃ ይሙሉ
• ጥያቄዎ ለደላሎች ይላካል

📢 **መሸጥ ከፈለጉ:**
• '📢 መሸጥ / ማከራየት' ይምረጡ
• መረጃ ይሙሉ
• ማስታወቂያዎ ይታተማል

📝 **እንደ አቅራቢ ለመመዝገብ:**
• '📝 እንደ አቅራቢ መመዝገብ' ይምረጡ
• መረጃ ይሙሉ
• '📋 የፈላጊዎች ዝርዝር' ማየት ይችላሉ
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ==============================================================================
# 7. VENDOR REGISTRATION
# ==============================================================================
async def vendor_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    existing = get_vendor(user_id)
    if existing:
        await update.message.reply_text(
            "✅ አስቀድመው እንደ አቅራቢ ተመዝግበዋል!\n\n"
            f"👤 {existing[2]}\n"
            f"📞 {existing[3]}\n"
            f"🏷️ {existing[4]}\n"
            f"📊 {'✅ የተረጋገጠ' if existing[6] else '⏳ በመጠበቅ ላይ'}",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return ConversationHandler.END
    
    await update.message.reply_text(
        "📝 **እንደ አቅራቢ/ደላላ መመዝገብ**\n\n"
        "1️⃣ ሙሉ ስምዎን ያስገቡ፦",
        parse_mode="Markdown"
    )
    return VENDOR_NAME

async def vendor_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['vendor_name'] = update.message.text
    await update.message.reply_text(
        "2️⃣ የስልክ ቁጥርዎን ያስገቡ፦",
        parse_mode="Markdown"
    )
    return VENDOR_PHONE

async def vendor_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['vendor_phone'] = update.message.text
    
    keyboard = []
    for vtype in VENDOR_TYPES:
        keyboard.append([InlineKeyboardButton(vtype, callback_data=f"vendor_type_{vtype}")])
    
    await update.message.reply_text(
        "3️⃣ የአቅራቢነት አይነት ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return VENDOR_TYPE

async def vendor_reg_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    vendor_type = query.data.replace("vendor_type_", "")
    context.user_data['vendor_type'] = vendor_type
    
    await query.edit_message_text(
        f"✅ አይነት: {vendor_type}\n\n"
        "4️⃣ የፈቃድ/የምስክር ወረቀት ፎቶ ይላኩ (ካለ)፦\n"
        "💡 *(ካልሆነ 'የለም' ብለው ይላኩ)*",
        parse_mode="Markdown"
    )
    return VENDOR_DOCUMENT

async def vendor_reg_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    document_id = None
    
    if update.message.photo:
        document_id = update.message.photo[-1].file_id
    elif update.message.text and update.message.text.lower() != "የለም":
        document_id = update.message.text
    
    vendor_id = add_vendor(
        user.id,
        context.user_data['vendor_name'],
        context.user_data['vendor_phone'],
        context.user_data['vendor_type'],
        document_id
    )
    
    if vendor_id:
        await update.message.reply_text(
            f"✅ **በስኬት ተመዝግበዋል!**\n\n"
            f"👤 {context.user_data['vendor_name']}\n"
            f"📞 {context.user_data['vendor_phone']}\n"
            f"🏷️ {context.user_data['vendor_type']}\n\n"
            f"⏳ አካውንትዎ እየተረጋገጠ ነው...",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID_INT:
            try:
                admin_keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ ፈቅድ", callback_data=f"verify_vendor_{vendor_id}")]
                ])
                admin_msg = f"🔔 **አዲስ አቅራቢ!**\n\n👤 {context.user_data['vendor_name']}\n📞 {context.user_data['vendor_phone']}\n🏷️ {context.user_data['vendor_type']}\n🆔 {vendor_id}"
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID_INT,
                    text=admin_msg,
                    reply_markup=admin_keyboard,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    else:
        await update.message.reply_text("❌ ምዝገባ አልተሳካም።")
    
    return ConversationHandler.END

# ==============================================================================
# 8. VIEW REQUESTS (FOR VENDORS ONLY)
# ==============================================================================
async def view_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    vendor = get_vendor(user_id)
    if not vendor:
        await update.message.reply_text(
            "⛔ ይህን ገጽ ማየት የሚችሉት የተመዘገቡ አቅራቢዎች/ደላሎች ብቻ ናቸው!\n\n"
            "📝 እባክዎን መጀመሪያ '📝 እንደ አቅራቢ መመዝገብ' የሚለውን ተጭነው ይመዝገቡ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    listings = get_all_listings()
    
    if not listings:
        await update.message.reply_text(
            "📭 ምንም ንቁ ጥያቄዎች የሉም።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    text = "📋 **የፈላጊዎች ዝርዝር**\n\n"
    for listing in listings:
        req_id, chat_id, name, req_type, category, desc, status, created = listing
        icon = "🚗" if category == "cat_car" else "🏠"
        text += f"{icon} **#{req_id}** - {desc[:80]}...\n"
        text += f"📅 {created}\n"
        text += "────────────────────\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ==============================================================================
# 9. BUYER FLOW
# ==============================================================================
async def start_buy_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'BUY'
    keyboard = [
        [InlineKeyboardButton("👤 ለራሴ የምፈልግ ገዢ ነኝ", callback_data="role_self")],
        [InlineKeyboardButton("👨‍💼 ደላላ ነኝ (ለደንበኛዬ)", callback_data="role_broker")]
    ]
    await update.message.reply_text(
        "👤 **እባክዎን ማንነትዎን ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return FLOW_ROLE

async def flow_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['user_role'] = "👤 ባለቤት" if query.data == "role_self" else "👨‍💼 ደላላ"

    keyboard = [
        [InlineKeyboardButton("🚗 መኪና (Automobile)", callback_data="cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ (Property)", callback_data="cat_house")],
        [InlineKeyboardButton("🏢 ንግድ ቤት / ቢሮ (Commercial)", callback_data="cat_commercial")],
    ]
    await query.edit_message_text(
        "🏷️ **የንብረቱን ምድብ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return FLOW_CAT

async def flow_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data
    context.user_data['category'] = cat
    req_type = context.user_data.get('req_type', 'BUY')

    if req_type == 'SELL':
        if cat == "cat_car":
            await query.edit_message_text(
                "🚘 **የመኪናውን ስም (Make/Brand) ያስገቡ፦**\n\n💡 *ምሳሌ፦* Toyota, Hyundai, Suzuki...",
                parse_mode="Markdown"
            )
            return SELL_MAKE
        else:
            await query.edit_message_text(
                "✍️ **የንብረቱን/የቤቱን ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* «ቦሌ አትላስ አካባቢ 3 መኝታ ያለው ቪላ ቤት»",
                parse_mode="Markdown"
            )
            return FLOW_DESC

    # BUYER FLOW
    if cat == "cat_car":
        keyboard = [
            [InlineKeyboardButton("🚘 የቤት መኪና (Automobile)", callback_data="cartype_personal")],
            [InlineKeyboardButton("🚚 የጭነት / የንግድ መኪና", callback_data="cartype_commercial")],
            [InlineKeyboardButton("🚜 ከባድ ማሽን / የሥራ መኪና", callback_data="cartype_heavy")]
        ]
        await query.edit_message_text(
            "🚘 **የሚፈልጉትን የመኪና አይነት ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return FLOW_CAR_TYPE
    else:
        await query.edit_message_text(
            "✍️ **የሚፈልጉትን ዕቃ/ቤት ዝርዝር መረጃ ያስገቡ፦**\n\n"
            "💡 *ምሳሌ፦* «ቦሌ አካባቢ 2 መኝታ ቤት ኪራይ እስከ 40,000 ብር»",
            parse_mode="Markdown"
        )
        return FLOW_DESC

async def flow_car_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    types_map = {
        "cartype_personal": "የቤት መኪና",
        "cartype_commercial": "የጭነት/የንግድ",
        "cartype_heavy": "ከባድ ማሽን"
    }
    context.user_data['car_type'] = types_map.get(query.data, "መኪና")

    keyboard = [
        [InlineKeyboardButton("💵 በካሽ (Cash)", callback_data="pay_cash")],
        [InlineKeyboardButton("🏦 በባንክ ብድር / ሊዚንግ", callback_data="pay_bank")],
        [InlineKeyboardButton("🔄 በሁለቱም ይቻላል", callback_data="pay_any")]
    ]
    await query.edit_message_text(
        "💳 **የመክፈያ መንገድዎን ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return FLOW_CAR_PAYMENT

async def flow_car_payment_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pay_map = {"pay_cash": "ካሽ", "pay_bank": "ባንክ ብድር", "pay_any": "ማናቸውም"}
    context.user_data['car_payment'] = pay_map.get(query.data, "ካሽ")

    await query.edit_message_text(
        "✍️ **አሁን የመኪናውን ሞዴል፣ የባጀት መጠን እና የስልክ ቁጥርዎን ጽፈው ይላኩ፦**\n\n"
        "💡 *ምሳሌ፦* «ሱዙኪ ዲዛየር 2022፣ እስከ 2.5 ሚሊዮን ብር፣ ስልክ፡ 0911XXXXXX»",
        parse_mode="Markdown"
    )
    return FLOW_DESC

# ==============================================================================
# 10. SELLER FLOW
# ==============================================================================
async def start_sell_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    keyboard = [
        [InlineKeyboardButton("👤 የንብረቱ ባለቤት ነኝ", callback_data="role_self")],
        [InlineKeyboardButton("👨‍💼 ደላላ ነኝ (የደንበኛ ንብረት)", callback_data="role_broker")]
    ]
    await update.message.reply_text(
        "👤 **እባክዎን ማንነትዎን ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return FLOW_ROLE

async def sell_car_make_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_make'] = update.message.text
    await update.message.reply_text(
        "🚘 **የመኪናውን ሞዴል እና የሰራበት ዓ.ም (Model & Year) ያስገቡ፦**\n\n💡 *ምሳሌ፦* Vitz 2018, Tucson 2022...",
        parse_mode="Markdown"
    )
    return SELL_MODEL

async def sell_car_model_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_model'] = update.message.text
    await update.message.reply_text(
        "💰 **የመሸጫ/የመከራያ ዋጋ ያስገቡ፦**\n\n💡 *ምሳሌ፦* 2,500,000 ብር",
        parse_mode="Markdown"
    )
    return SELL_PRICE

async def sell_car_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("💵 በካሽ (Cash)", callback_data="spay_cash")],
        [InlineKeyboardButton("🏦 በባንክ ብድር / ሊዚንግ", callback_data="spay_bank")],
        [InlineKeyboardButton("🔄 በሁለቱም ይቻላል", callback_data="spay_any")]
    ]
    await update.message.reply_text(
        "💳 **የመክፈያ መንገድ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SELL_PAYMENT

async def sell_car_payment_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pay_map = {"spay_cash": "ካሽ", "spay_bank": "ባንክ ብድር", "spay_any": "ማናቸውም"}
    context.user_data['sell_payment'] = pay_map.get(query.data, "ካሽ")

    await query.edit_message_text(
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**\n\n💡 *ምሳሌ፦* 0911XXXXXX",
        parse_mode="Markdown"
    )
    return SELL_PHONE

async def sell_car_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_phone'] = update.message.text
    await update.message.reply_text(
        "📸 **በመጨረሻም የመኪናውን/ንብረቱን ፎቶ ያስገቡ፦**\n\n💡 *(አንድ ግልጽ ፎቶ ይላኩ)*",
        parse_mode="Markdown"
    )
    return SELL_PHOTO

async def sell_car_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    role = context.user_data.get('user_role', 'ባለቤት')
    make = context.user_data.get('sell_make', 'N/A')
    model = context.user_data.get('sell_model', 'N/A')
    price = context.user_data.get('sell_price', 'N/A')
    payment = context.user_data.get('sell_payment', 'ካሽ')
    phone = context.user_data.get('sell_phone', 'N/A')

    photo_id = update.message.photo[-1].file_id if update.message.photo else None

    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return SELL_PHOTO

    formatted_desc = (
        f"🚘 **መኪና:** {make}\n"
        f"🏷️ **ሞዴል:** {model}\n"
        f"💰 **ዋጋ:** {price}\n"
        f"💳 **ክፍያ:** {payment}\n"
        f"📞 **ስልክ:** {phone}"
    )

    req_id = add_listing(user.id, user.first_name, 'SELL', 'cat_car', f"[{role}]\n{formatted_desc}")

    if req_id:
        action_kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ እፈልገዋለሁ", callback_data=f"item_want_{req_id}_{user.id}")]
        ])

        await update.message.reply_text(
            f"✅ **ማስታወቂያዎ በስኬት ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"👤 **ማንነት:** {role}\n"
            f"{formatted_desc}\n\n"
            "🚀 ማስታወቂያዎ ለገዢዎች/ደላሎች ተልኳል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )

        if ADMIN_CHAT_ID_INT:
            try:
                admin_msg = f"🔔 **አዲስ የሻጭ ማስታወቂያ!** (#REQ-{req_id})\n\n👤 {user.first_name} (@{user.username})\n🎭 {role}\n{formatted_desc}"
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID_INT,
                    photo=photo_id,
                    caption=admin_msg,
                    reply_markup=action_kbd,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    else:
        await update.message.reply_text("❌ ጥያቄውን ማስመዝገብ አልተቻለም።")

    return ConversationHandler.END

# ==============================================================================
# 11. SAVE LISTING REQUEST
# ==============================================================================
async def save_listing_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    req_type = context.user_data.get('req_type', 'BUY')
    cat = context.user_data.get('category', 'cat_car')
    role = context.user_data.get('user_role', 'ባለቤት')

    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    desc = update.message.caption if photo_id else update.message.text

    if not desc:
        await update.message.reply_text("❌ እባክዎ አስፈላጊውን መረጃ በጽሁፍ ያስገቡ!")
        return FLOW_DESC

    car_info = ""
    if cat == "cat_car" and req_type == 'BUY':
        c_type = context.user_data.get('car_type', 'መኪና')
        c_pay = context.user_data.get('car_payment', 'ካሽ')
        car_info = f"🚘 **አይነት:** {c_type}\n💳 **ክፍያ:** {c_pay}\n"

    full_desc = f"[{role}]\n{car_info}{desc}"
    req_id = add_listing(user.id, user.first_name, req_type, cat, full_desc)

    if req_id:
        title = "🔍 የገዢ ጥያቄ"
        action_kbd = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ አለኝ", callback_data=f"item_have_{req_id}_{user.id}")]
        ])

        await update.message.reply_text(
            f"✅ **{title}ዎ በስኬት ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"👤 **ማንነት:** {role}\n"
            f"{car_info}"
            f"📝 **ዝርዝር:** {desc}\n\n"
            "🚀 ጥያቄዎ ለአቅራቢዎች ተልኳል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID_INT:
            try:
                admin_msg = f"🔔 **አዲስ {title}!** (#REQ-{req_id})\n\n👤 {user.first_name} (@{user.username})\n🎭 {role}\n{car_info}📝 {desc}"
                if photo_id:
                    await context.bot.send_photo(
                        chat_id=ADMIN_CHAT_ID_INT,
                        photo=photo_id,
                        caption=admin_msg,
                        reply_markup=action_kbd,
                        parse_mode="Markdown"
                    )
                else:
                    await context.bot.send_message(
                        chat_id=ADMIN_CHAT_ID_INT,
                        text=admin_msg,
                        reply_markup=action_kbd,
                        parse_mode="Markdown"
                    )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    else:
        await update.message.reply_text("❌ ጥያቄውን ማስመዝገብ አልተቻለም።")
    return ConversationHandler.END

# ==============================================================================
# 12. RESPONSE FLOW
# ==============================================================================
async def start_item_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    
    context.user_data.clear()
    context.user_data['target_req_id'] = parts[2]
    context.user_data['target_user_id'] = int(parts[3])

    keyboard = [
        [InlineKeyboardButton("👤 የንብረቱ ባለቤት ነኝ", callback_data="resp_role_owner")],
        [InlineKeyboardButton("👨‍💼 ደላላ ነኝ", callback_data="resp_role_broker")]
    ]
    await query.message.reply_text(
        "📋 **የምላሽ ሰጭ ማንነት፦**\n\nእባክዎን ማንነትዎን ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return RESP_ROLE

async def resp_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['resp_role'] = "👤 ባለቤት" if query.data == "resp_role_owner" else "👨‍💼 ደላላ"
    await query.edit_message_text(
        "🚘 **የመኪናው/ንብረቱ ስም (Make/Brand)፦**\n\n💡 *ምሳሌ፦* Toyota, Hyundai, Suzuki...",
        parse_mode="Markdown"
    )
    return RESP_CAR_MAKE

async def resp_car_make_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_make'] = update.message.text
    await update.message.reply_text(
        "🚘 **የመኪናው ሞዴል እና የሰራበት ዓ.ም (Model & Year)፦**\n\n💡 *ምሳሌ፦* Vitz 2018, Tucson 2022...",
        parse_mode="Markdown"
    )
    return RESP_CAR_MODEL

async def resp_car_model_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_model'] = update.message.text
    await update.message.reply_text(
        "💰 **የመሸጫ/የመከራያ ዋጋ፦**\n\n💡 *ምሳሌ፦* 2,500,000 ብር",
        parse_mode="Markdown"
    )
    return RESP_PRICE

async def resp_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_price'] = update.message.text
    await update.message.reply_text(
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**",
        parse_mode="Markdown"
    )
    return RESP_PHONE

async def resp_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_phone'] = update.message.text
    await update.message.reply_text(
        "📸 **በመጨረሻም የንብረቱን/የመኪናውን ፎቶ ያስገቡ፦**",
        parse_mode="Markdown"
    )
    return RESP_PHOTO

async def resp_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    responder = update.effective_user
    target_user_id = context.user_data.get('target_user_id')
    req_id = context.user_data.get('target_req_id')
    
    role = context.user_data.get('resp_role', 'አቅራቢ')
    make = context.user_data.get('resp_make', 'N/A')
    model = context.user_data.get('resp_model', 'N/A')
    price = context.user_data.get('resp_price', 'N/A')
    phone = context.user_data.get('resp_phone', 'N/A')
    photo_id = update.message.photo[-1].file_id if update.message.photo else None

    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return RESP_PHOTO

    formatted_caption = (
        f"🎉 **አዲስ አማራጭ!** (#REQ-{req_id})\n\n"
        f"🎭 **ሚና:** {role}\n"
        f"🚘 **ስም:** {make}\n"
        f"🏷️ **ሞዴል:** {model}\n"
        f"💰 **ዋጋ:** {price}\n"
        f"📞 **ስልክ:** {phone}\n"
        f"👤 @{responder.username if responder.username else responder.first_name}"
    )

    if target_user_id:
        try:
            await context.bot.send_photo(
                chat_id=target_user_id,
                photo=photo_id,
                caption=formatted_caption,
                parse_mode="Markdown"
            )
            await update.message.reply_text(
                "✅ **መረጃዎች ለፈላጊው ተልከዋል!**",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
            update_listing_status(int(req_id), 'responded')
        except Exception as e:
            logger.error(f"Error sending response: {e}")
            await update.message.reply_text("❌ መላክ አልተቻለም።")

    return ConversationHandler.END

# ==============================================================================
# 13. ADMIN VERIFY VENDOR
# ==============================================================================
async def admin_verify_vendor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    vendor_id = int(query.data.split("_")[2])
    if verify_vendor(vendor_id):
        await query.edit_message_text("✅ አቅራቢው ተረጋግጧል!")
    else:
        await query.edit_message_text("❌ ማረጋገጥ አልተቻለም።")

# ==============================================================================
# 14. MAIN FUNCTION
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))

    # Cancel Handler
    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)

    # ===== RESPONSE CONVERSATION =====
    response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_item_response, pattern="^item_(have|want)_")],
        states={
            RESP_ROLE: [CallbackQueryHandler(resp_role_chosen, pattern="^resp_role_"), cancel_message_handler],
            RESP_CAR_MAKE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_make_received), cancel_message_handler],
            RESP_CAR_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_model_received), cancel_message_handler],
            RESP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_price_received), cancel_message_handler],
            RESP_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_phone_received), cancel_message_handler],
            RESP_PHOTO: [MessageHandler(filters.PHOTO, resp_photo_received), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== MARKET CONVERSATION =====
    market_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), start_buy_flow),
            MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), start_sell_flow)
        ],
        states={
            FLOW_ROLE: [CallbackQueryHandler(flow_role_chosen, pattern="^role_"), cancel_message_handler],
            FLOW_CAT: [CallbackQueryHandler(flow_category_chosen, pattern="^cat_"), cancel_message_handler],
            FLOW_CAR_TYPE: [CallbackQueryHandler(flow_car_type_chosen, pattern="^cartype_"), cancel_message_handler],
            FLOW_CAR_PAYMENT: [CallbackQueryHandler(flow_car_payment_chosen, pattern="^pay_"), cancel_message_handler],
            FLOW_DESC: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, save_listing_request), cancel_message_handler],
            SELL_MAKE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_make_received), cancel_message_handler],
            SELL_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_model_received), cancel_message_handler],
            SELL_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_price_received), cancel_message_handler],
            SELL_PAYMENT: [CallbackQueryHandler(sell_car_payment_chosen, pattern="^spay_"), cancel_message_handler],
            SELL_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_phone_received), cancel_message_handler],
            SELL_PHOTO: [MessageHandler(filters.PHOTO, sell_car_photo_received), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== VENDOR REGISTRATION =====
    vendor_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ መመዝገብ$"), vendor_reg_start)],
        states={
            VENDOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, vendor_reg_name), cancel_message_handler],
            VENDOR_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, vendor_reg_phone), cancel_message_handler],
            VENDOR_TYPE: [CallbackQueryHandler(vendor_reg_type, pattern="^vendor_type_"), cancel_message_handler],
            VENDOR_DOCUMENT: [MessageHandler(filters.PHOTO | filters.TEXT & ~filters.COMMAND, vendor_reg_document), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ===== OTHER HANDLERS =====
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(MessageHandler(cancel_filter, go_home))
    
    # ===== ADMIN VERIFY =====
    app.add_handler(CallbackQueryHandler(admin_verify_vendor, pattern="^verify_vendor_"))

    # ===== ADD CONVERSATIONS =====
    app.add_handler(response_conv)
    app.add_handler(market_conv)
    app.add_handler(vendor_conv)

    # ===== ERROR HANDLER =====
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} caused error: {context.error}", exc_info=True)

    app.add_error_handler(error_handler)

    logger.info("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()
