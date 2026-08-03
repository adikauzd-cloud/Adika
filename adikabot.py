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

# ==============================================================================
# 3. KEYBOARDS & CONVERSATION STATES
# ==============================================================================
MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ መመዝገብ", "👤 መገለጫዬ"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]

# ==============================================================================
# 4. CONVERSATION STATES - FIXED
# ==============================================================================
# Market Flow States (Buyer & Seller)
FLOW_ROLE, FLOW_CAT = range(2)

# Buyer Car States
FLOW_CAR_TYPE, FLOW_CAR_PAYMENT, FLOW_CAR_DESC = range(2, 5)

# Buyer House States  
FLOW_HOUSE_TYPE, FLOW_HOUSE_ACTION, FLOW_HOUSE_PAYMENT, FLOW_HOUSE_DESC = range(5, 9)

# Buyer Commercial States
FLOW_COMMERCIAL_DESC = 9

# Seller Car States
SELL_MAKE, SELL_MODEL, SELL_PRICE, SELL_PAYMENT, SELL_PHONE, SELL_PHOTO = range(10, 16)

# Response Flow States
RESP_ROLE, RESP_CAR_MAKE, RESP_CAR_MODEL, RESP_HOUSE_DESC, RESP_PRICE, RESP_PHONE, RESP_PHOTO = range(16, 23)

# Total: 23 states

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

async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ ሂደቱ ተቋርጧል።",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    return ConversationHandler.END

# ==============================================================================
# 6. MARKET FLOW (BUYER & SELLER)
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

    # ========== SELLER FLOW ==========
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
            return FLOW_HOUSE_DESC

    # ========== BUYER FLOW ==========
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
        
    elif cat == "cat_house":
        keyboard = [
            [InlineKeyboardButton("🏡 ቪላ (Villa)", callback_data="htype_villa")],
            [InlineKeyboardButton("🏢 አፓርትመንት (Apartment)", callback_data="htype_apt")],
            [InlineKeyboardButton("🏢 ኮንዶሚኒየም (Condo)", callback_data="htype_condo")],
            [InlineKeyboardButton("🏞️ ባዶ ቦታ / መሬት (Plot)", callback_data="htype_land")]
        ]
        await query.edit_message_text(
            "🏠 **የሚፈልጉትን የቤት/ቦታ አይነት ይምረጡ፦**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return FLOW_HOUSE_TYPE
    else:  # Commercial
        await query.edit_message_text(
            "✍️ **የሚፈልጉትን የንግድ ቤት/ቢሮ ዝርዝር መረጃ ያስገቡ፦**\n\n"
            "💡 *ምሳሌ፦* «ቦሌ ዳቦ ማዕከል አካባቢ ለሱቅ የሚሆን ቤት»",
            parse_mode="Markdown"
        )
        return FLOW_COMMERCIAL_DESC

# ========== BUYER CAR FLOW ==========
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
    return FLOW_CAR_DESC

async def save_car_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    desc = update.message.text
    
    role = context.user_data.get('user_role', 'ባለቤት')
    car_type = context.user_data.get('car_type', 'መኪና')
    car_payment = context.user_data.get('car_payment', 'ካሽ')
    
    formatted_desc = f"🚘 **አይነት:** {car_type}\n💳 **ክፍያ:** {car_payment}\n📝 **ዝርዝር:** {desc}"
    full_desc = f"[{role}]\n{formatted_desc}"
    
    req_id = add_listing(user.id, user.first_name, 'BUY', 'cat_car', full_desc)
    
    if req_id:
        await update.message.reply_text(
            f"✅ **የገዢ ጥያቄዎ በስኬት ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"👤 **ማንነት:** {role}\n"
            f"{formatted_desc}\n\n"
            f"🚀 ጥያቄዎ ለደላሎች/አቅራቢዎች ተልኳል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID_INT:
            try:
                action_kbd = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ መልስ ስጥ", callback_data=f"item_resp_{req_id}_{user.id}_cat_car")]
                ])
                admin_msg = f"🔔 **አዲስ የመኪና ጥያቄ!** (#REQ-{req_id})\n\n👤 {user.first_name} (@{user.username})\n{formatted_desc}"
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID_INT,
                    text=admin_msg,
                    reply_markup=action_kbd,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    
    return ConversationHandler.END

# ========== BUYER HOUSE FLOW ==========
async def flow_house_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    h_map = {
        "htype_villa": "ቪላ",
        "htype_apt": "አፓርትመንት",
        "htype_condo": "ኮንዶሚኒየም",
        "htype_land": "ቦታ/መሬት"
    }
    context.user_data['house_type'] = h_map.get(query.data, "ቤት")

    keyboard = [
        [InlineKeyboardButton("🛍️ ለመግዛት", callback_data="hact_buy")],
        [InlineKeyboardButton("🔑 ለመከራየት", callback_data="hact_rent")]
    ]
    await query.edit_message_text(
        "❓ **መግዛት ነው ወይስ መከራየት የሚፈልጉት?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return FLOW_HOUSE_ACTION

async def flow_house_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['house_action'] = "ለመግዛት" if query.data == "hact_buy" else "ለመከራየት"

    keyboard = [
        [InlineKeyboardButton("💵 በካሽ (Cash)", callback_data="hpay_cash")],
        [InlineKeyboardButton("🏦 በባንክ ብድር", callback_data="hpay_bank")],
        [InlineKeyboardButton("🔄 ማናቸውም", callback_data="hpay_any")]
    ]
    await query.edit_message_text(
        "💳 **የመክፈያ መንገድ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return FLOW_HOUSE_PAYMENT

async def flow_house_payment_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    p_map = {"hpay_cash": "ካሽ", "hpay_bank": "ባንክ", "hpay_any": "ማናቸውም"}
    context.user_data['house_payment'] = p_map.get(query.data, "ካሽ")

    await query.edit_message_text(
        "✍️ **አሁን የሚፈልጉትን አካባቢ፣ የመኝታ ብዛት፣ ባጀት እና ስልክ ቁጥር ያስገቡ፦**\n\n"
        "💡 *ምሳሌ፦* «ቦሌ አካባቢ 2 መኝታ፣ ባጀት እስከ 10 ሚሊዮን ብር፣ ስልክ፡ 0911XXXXXX»",
        parse_mode="Markdown"
    )
    return FLOW_HOUSE_DESC

async def save_house_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    desc = update.message.text
    
    role = context.user_data.get('user_role', 'ባለቤት')
    house_type = context.user_data.get('house_type', 'ቤት')
    house_action = context.user_data.get('house_action', 'ለመግዛት')
    house_payment = context.user_data.get('house_payment', 'ካሽ')
    
    formatted_desc = f"🏠 **አይነት:** {house_type} ({house_action})\n💳 **ክፍያ:** {house_payment}\n📝 **ዝርዝር:** {desc}"
    full_desc = f"[{role}]\n{formatted_desc}"
    
    req_id = add_listing(user.id, user.first_name, 'BUY', 'cat_house', full_desc)
    
    if req_id:
        await update.message.reply_text(
            f"✅ **የገዢ ጥያቄዎ በስኬት ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"👤 **ማንነት:** {role}\n"
            f"{formatted_desc}\n\n"
            f"🚀 ጥያቄዎ ለደላሎች/አቅራቢዎች ተልኳል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID_INT:
            try:
                action_kbd = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ መልስ ስጥ", callback_data=f"item_resp_{req_id}_{user.id}_cat_house")]
                ])
                admin_msg = f"🔔 **አዲስ የቤት ጥያቄ!** (#REQ-{req_id})\n\n👤 {user.first_name} (@{user.username})\n{formatted_desc}"
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID_INT,
                    text=admin_msg,
                    reply_markup=action_kbd,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    
    return ConversationHandler.END

# ========== BUYER COMMERCIAL FLOW ==========
async def save_commercial_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    desc = update.message.text
    role = context.user_data.get('user_role', 'ባለቤት')
    
    full_desc = f"[{role}]\n🏢 **የንግድ ቤት:** {desc}"
    req_id = add_listing(user.id, user.first_name, 'BUY', 'cat_commercial', full_desc)
    
    if req_id:
        await update.message.reply_text(
            f"✅ **የገዢ ጥያቄዎ በስኬት ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"👤 **ማንነት:** {role}\n"
            f"📝 **ዝርዝር:** {desc}\n\n"
            f"🚀 ጥያቄዎ ለደላሎች/አቅራቢዎች ተልኳል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID_INT:
            try:
                action_kbd = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ መልስ ስጥ", callback_data=f"item_resp_{req_id}_{user.id}_cat_commercial")]
                ])
                admin_msg = f"🔔 **አዲስ የንግድ ቤት ጥያቄ!** (#REQ-{req_id})\n\n👤 {user.first_name} (@{user.username})\n📝 {desc}"
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID_INT,
                    text=admin_msg,
                    reply_markup=action_kbd,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    
    return ConversationHandler.END

# ==============================================================================
# 7. SELLER FLOW
# ==============================================================================
async def sell_car_make_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_make'] = update.message.text
    await update.message.reply_text(
        "🚘 **የመኪናውን ሞዴል እና የሰራበት ዓ.ም (Model & Year) ያስገቡ፦**",
        parse_mode="Markdown"
    )
    return SELL_MODEL

async def sell_car_model_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_model'] = update.message.text
    await update.message.reply_text(
        "💰 **የመሸጫ/የመከራያ ዋጋ ያስገቡ፦**",
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
        "📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**",
        parse_mode="Markdown"
    )
    return SELL_PHONE

async def sell_car_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_phone'] = update.message.text
    await update.message.reply_text(
        "📸 **በመጨረሻም የመኪናውን ፎቶ ያስገቡ፦**",
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

    formatted_desc = f"🚘 **መኪና:** {make}\n🏷️ **ሞዴል:** {model}\n💰 **ዋጋ:** {price}\n💳 **ክፍያ:** {payment}\n📞 **ስልክ:** {phone}"
    req_id = add_listing(user.id, user.first_name, 'SELL', 'cat_car', f"[{role}]\n{formatted_desc}")

    if req_id:
        await update.message.reply_text(
            f"✅ **ማስታወቂያዎ በስኬት ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"👤 **ማንነት:** {role}\n{formatted_desc}",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )

        if ADMIN_CHAT_ID_INT:
            try:
                action_kbd = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ እፈልገዋለሁ", callback_data=f"item_resp_{req_id}_{user.id}_cat_car")]
                ])
                admin_msg = f"🔔 **አዲስ የሻጭ ማስታወቂያ!** (#REQ-{req_id})\n\n👤 {user.first_name} (@{user.username})\n{formatted_desc}"
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID_INT,
                    photo=photo_id,
                    caption=admin_msg,
                    reply_markup=action_kbd,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Admin notify error: {e}")
    return ConversationHandler.END

# ==============================================================================
# 8. RESPONSE FLOW
# ==============================================================================
async def start_item_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    
    context.user_data.clear()
    context.user_data['target_req_id'] = parts[2]
    context.user_data['target_user_id'] = int(parts[3])
    context.user_data['target_cat'] = parts[4] if len(parts) > 4 else "cat_car"

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
    
    target_cat = context.user_data.get('target_cat', 'cat_car')

    if target_cat == "cat_car":
        await query.edit_message_text(
            "🚘 **የመኪናው ስም (Make/Brand)፦**\n\n💡 *ምሳሌ፦* Toyota, Hyundai, Suzuki...",
            parse_mode="Markdown"
        )
        return RESP_CAR_MAKE
    else:
        await query.edit_message_text(
            "🏠 **የቤቱን/ቦታውን አድራሻ እና ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቦሌ አትላስ አካባቢ፣ ባለ 2 መኝታ አፓርትመንት...",
            parse_mode="Markdown"
        )
        return RESP_HOUSE_DESC

async def resp_car_make_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_make'] = update.message.text
    await update.message.reply_text(
        "🚘 **የመኪናው ሞዴል እና የሰራበት ዓ.ም (Model & Year)፦**",
        parse_mode="Markdown"
    )
    return RESP_CAR_MODEL

async def resp_car_model_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_model'] = update.message.text
    await update.message.reply_text(
        "💰 **የመሸጫ/የመከራያ ዋጋ፦**",
        parse_mode="Markdown"
    )
    return RESP_PRICE

async def resp_house_desc_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_house_desc'] = update.message.text
    await update.message.reply_text(
        "💰 **የቤቱ/የቦታው ዋጋ፦**",
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
        "📸 **በመጨረሻም የንብረቱን ፎቶ ያስገቡ፦**",
        parse_mode="Markdown"
    )
    return RESP_PHOTO

async def resp_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    responder = update.effective_user
    target_user_id = context.user_data.get('target_user_id')
    req_id = context.user_data.get('target_req_id')
    target_cat = context.user_data.get('target_cat', 'cat_car')
    
    role = context.user_data.get('resp_role', 'አቅራቢ')
    price = context.user_data.get('resp_price', 'N/A')
    phone = context.user_data.get('resp_phone', 'N/A')
    photo_id = update.message.photo[-1].file_id if update.message.photo else None

    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return RESP_PHOTO

    if target_cat == "cat_car":
        make = context.user_data.get('resp_make', 'N/A')
        model = context.user_data.get('resp_model', 'N/A')
        detail_str = f"🚘 **ስም:** {make}\n🏷️ **ሞዴል:** {model}"
    else:
        house_desc = context.user_data.get('resp_house_desc', 'N/A')
        detail_str = f"🏠 **ዝርዝር:** {house_desc}"

    formatted_caption = (
        f"🎉 **አዲስ አማራጭ!** (#REQ-{req_id})\n\n"
        f"🎭 **ሚና:** {role}\n"
        f"{detail_str}\n"
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
                "✅ **መረጃዎች ለጠያቂው ተልከዋል!**",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        except Exception as e:
            logger.error(f"Error sending response: {e}")
            await update.message.reply_text("❌ መላክ አልተቻለም።")

    return ConversationHandler.END

# ==============================================================================
# 9. MAIN FUNCTION
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))

    # Response Flow
    response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_item_response, pattern="^item_resp_")],
        states={
            RESP_ROLE: [CallbackQueryHandler(resp_role_chosen, pattern="^resp_role_")],
            RESP_CAR_MAKE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_make_received)],
            RESP_CAR_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_model_received)],
            RESP_HOUSE_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_house_desc_received)],
            RESP_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_price_received)],
            RESP_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_phone_received)],
            RESP_PHOTO: [MessageHandler(filters.PHOTO, resp_photo_received)],
        },
        fallbacks=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex(".*(ዋና ገጽ|መግዛት|መሸጥ).*"), cancel_flow)
        ],
        allow_reentry=True,
    )

    # Market Flow (Buyer & Seller)
    market_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(".*መግዛት.*"), start_buy_flow),
            MessageHandler(filters.Regex(".*መሸጥ.*"), start_sell_flow)
        ],
        states={
            FLOW_ROLE: [CallbackQueryHandler(flow_role_chosen, pattern="^role_")],
            FLOW_CAT: [CallbackQueryHandler(flow_category_chosen, pattern="^cat_")],
            
            # Buyer Car Steps
            FLOW_CAR_TYPE: [CallbackQueryHandler(flow_car_type_chosen, pattern="^cartype_")],
            FLOW_CAR_PAYMENT: [CallbackQueryHandler(flow_car_payment_chosen, pattern="^pay_")],
            FLOW_CAR_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_car_request)],
            
            # Buyer House Steps
            FLOW_HOUSE_TYPE: [CallbackQueryHandler(flow_house_type_chosen, pattern="^htype_")],
            FLOW_HOUSE_ACTION: [CallbackQueryHandler(flow_house_action_chosen, pattern="^hact_")],
            FLOW_HOUSE_PAYMENT: [CallbackQueryHandler(flow_house_payment_chosen, pattern="^hpay_")],
            FLOW_HOUSE_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_house_request)],
            
            # Buyer Commercial Steps
            FLOW_COMMERCIAL_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_commercial_request)],
            
            # Seller Car Steps
            SELL_MAKE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_make_received)],
            SELL_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_model_received)],
            SELL_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_price_received)],
            SELL_PAYMENT: [CallbackQueryHandler(sell_car_payment_chosen, pattern="^spay_")],
            SELL_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_phone_received)],
            SELL_PHOTO: [MessageHandler(filters.PHOTO, sell_car_photo_received)],
        },
        fallbacks=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex(".*(ዋና ገጽ|መግዛት|መሸጥ).*"), cancel_flow)
        ],
        allow_reentry=True,
    )

    app.add_handler(response_conv)
    app.add_handler(market_conv)

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Update {update} caused error: {context.error}", exc_info=True)

    app.add_error_handler(error_handler)

    logger.info("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()