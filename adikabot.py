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
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable ውስጥ አልተገኘም።")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

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
        
        # Listings Table
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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS brokers (
                    user_chat_id BIGINT PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    working_area TEXT NOT NULL,
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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS brokers (
                    user_chat_id INTEGER PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    working_area TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        logging.info("✅ Database initialized successfully")
    except Exception as e:
        logging.error(f"Database initialization error: {e}")
    finally:
        if conn:
            conn.close()

def is_broker_registered(user_chat_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT user_chat_id FROM brokers WHERE user_chat_id = {p}", (user_chat_id,))
        return cursor.fetchone() is not None
    except Exception as e:
        logging.error(f"Check broker error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def register_broker_db(user_chat_id, full_name, phone, area):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"""
            INSERT INTO brokers (user_chat_id, full_name, phone, working_area)
            VALUES ({p}, {p}, {p}, {p})
            ON CONFLICT (user_chat_id) DO UPDATE 
            SET full_name = EXCLUDED.full_name, phone = EXCLUDED.phone, working_area = EXCLUDED.working_area
        """, (user_chat_id, full_name, phone, area))
        return True
    except Exception as e:
        logging.error(f"Register broker error: {e}")
        return False
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
        else:
            cursor.execute(f"""
                INSERT INTO listings (user_chat_id, user_name, req_type, category, description)
                VALUES ({p}, {p}, {p}, {p}, {p})
            """, (user_chat_id, user_name, req_type, category, description))
            req_id = cursor.lastrowid
        return req_id
    except Exception as e:
        logging.error(f"Add listing error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_active_buyer_requests():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, category, description, created_at FROM listings WHERE req_type = 'BUY' ORDER BY id DESC LIMIT 10")
        return cursor.fetchall()
    except Exception as e:
        logging.error(f"Fetch requests error: {e}")
        return []
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 3. KEYBOARDS & CONVERSATION STATES
# ==============================================================================
MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ መመዝገብ", "📋 የፈላጊዎች ዝርዝር"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]

# Total 37 States
(
    FLOW_ROLE, FLOW_CAT,
    # Buyer Car
    BUY_CAR_MODEL, BUY_CAR_YEAR, BUY_CAR_BUDGET, BUY_CAR_PHONE,
    # Buyer House
    BUY_HOUSE_LOC, BUY_HOUSE_TYPE, BUY_HOUSE_BUDGET, BUY_HOUSE_PHONE,
    # Seller Car
    SELL_CAR_MODEL, SELL_CAR_YEAR, SELL_CAR_PRICE, SELL_CAR_NEG, SELL_CAR_PHONE, SELL_CAR_PHOTO,
    # Seller House
    SELL_HOUSE_LOC, SELL_HOUSE_TYPE, SELL_HOUSE_AREA, SELL_HOUSE_COND, SELL_HOUSE_PRICE, SELL_HOUSE_NEG, SELL_HOUSE_PHONE, SELL_HOUSE_PHOTO,
    # Broker Registration
    BROKER_NAME, BROKER_PHONE, BROKER_AREA,
    # Response Flow
    RESP_ROLE, 
    RESP_CAR_MODEL, RESP_CAR_YEAR, RESP_CAR_PRICE, RESP_CAR_NEG, RESP_CAR_PHONE, RESP_CAR_PHOTO,
    RESP_HOUSE_LOC, RESP_HOUSE_AREA, RESP_HOUSE_COND, RESP_HOUSE_PRICE, RESP_HOUSE_NEG, RESP_HOUSE_PHONE, RESP_HOUSE_PHOTO
) = range(37)

# ==============================================================================
# 4. CANCEL & START HANDLER
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    welcome_text = (
        "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
        "የሀገሪቱ ታላቁ የመኪና፣ የቤት እና የንብረት ገበያ ማዕከል።\n\n"
        "እባክዎን ከታች ካሉት አማራጮች አንዱን ይምረጡ፦"
    )
    reply_markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
    return ConversationHandler.END

async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🏠 ዋና ገጽ ሲነካ ሂደቱን በሙሉ ያቋርጣል"""
    return await start(update, context)

# ==============================================================================
# 5. BROKER REGISTRATION & REQUEST LISTS
# ==============================================================================
async def start_broker_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("📝 **የአቅራቢ/ደላላ የምዝገባ ፎርም**\n\nእባክዎን ሙሉ ስምዎን ያስገቡ፦", parse_mode="Markdown")
    return BROKER_NAME

async def broker_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['broker_name'] = update.message.text
    await update.message.reply_text("📞 **የስልክ ቁጥርዎን ያስገቡ፦**", parse_mode="Markdown")
    return BROKER_PHONE

async def broker_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['broker_phone'] = update.message.text
    await update.message.reply_text("📍 **ዋና የሚሰሩበትን አካባቢ ያስገቡ (ምሳሌ፦ ቦሌ፣ አያት፣ ገርጂ)፦**", parse_mode="Markdown")
    return BROKER_AREA

async def broker_area_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = context.user_data.get('broker_name')
    phone = context.user_data.get('broker_phone')
    area = update.message.text

    if register_broker_db(user.id, name, phone, area):
        await update.message.reply_text(
            f"✅ **በስኬት ተመዝግበዋል!**\n\n👤 **ስም:** {name}\n📞 **ስልክ:** {phone}\n📍 **አካባቢ:** {area}\n\nአሁን **'📋 የፈላጊዎች ዝርዝር'** ገጽን ማየት ይችላሉ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ ምዝገባው አልተሳካም። እባክዎ እንደገና ይሞክሩ።")
    return ConversationHandler.END

async def show_requests_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_broker_registered(user.id):
        await update.message.reply_text(
            "🔒 **ይህ ገጽ ለተመዘገቡ ደላሎች ብቻ የተፈቀደ ነው!**\n\nእባክዎን መጀመሪያ **'📝 እንደ አቅራቢ መመዝገብ'** የሚለውን ተጭነው ይመዝገቡ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="Markdown"
        )
        return

    requests = get_active_buyer_requests()
    if not requests:
        await update.message.reply_text("📭 በአሁኑ ሰዓት ምንም አዲስ የፈላጊዎች ጥያቄ የለም።")
        return

    msg = "📋 **የቅርብ ጊዜ የፈላጊዎች ዝርዝር (ለተመዘገቡ ደላሎች ብቻ)፦**\n\n"
    for req in requests:
        req_id, cat, desc, created = req
        c_icon = "🚗" if cat == "cat_car" else "🏠"
        msg += f"{c_icon} **ጥያቄ #REQ-{req_id}**\n{desc}\n────────────────\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

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
    await update.message.reply_text("👤 **እባክዎን ማንነትዎን ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return FLOW_ROLE

async def start_sell_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data['req_type'] = 'SELL'
    keyboard = [
        [InlineKeyboardButton("👤 የንብረቱ ባለቤት ነኝ", callback_data="role_self")],
        [InlineKeyboardButton("👨‍💼 ደላላ ነኝ (የደንበኛ ንብረት)", callback_data="role_broker")]
    ]
    await update.message.reply_text("👤 **እባክዎን ማንነትዎን ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return FLOW_ROLE

async def flow_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['user_role'] = "👤 ባለቤት" if query.data == "role_self" else "👨‍💼 ደላላ"

    keyboard = [
        [InlineKeyboardButton("🚗 መኪና (Automobile)", callback_data="cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ (Property)", callback_data="cat_house")],
    ]
    await query.edit_message_text("🏷️ **የንብረቱን ምድብ ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return FLOW_CAT

async def flow_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data
    context.user_data['category'] = cat
    req_type = context.user_data.get('req_type', 'BUY')

    if req_type == 'BUY':
        if cat == "cat_car":
            await query.edit_message_text("🚘 **የሚፈልጉትን የመኪና ሞዴል ያስገቡ፦**\n\n💡 *ምሳሌ፦* Toyota Vitz, Tucson...", parse_mode="Markdown")
            return BUY_CAR_MODEL
        else:
            loc_kbd = [
                [InlineKeyboardButton("ቦሌ", callback_data="loc_ቦሌ"), InlineKeyboardButton("ሲኤምሲ", callback_data="loc_ሲኤምሲ")],
                [InlineKeyboardButton("አያት", callback_data="loc_አያት"), InlineKeyboardButton("ገርጂ", callback_data="loc_ገርጂ")],
                [InlineKeyboardButton("ሳሪስ", callback_data="loc_ሳሪስ"), InlineKeyboardButton("ሌላ አካባቢ", callback_data="loc_ሌላ")]
            ]
            await query.edit_message_text("📍 **የሚፈልጉትን አካባቢ ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(loc_kbd), parse_mode="Markdown")
            return BUY_HOUSE_LOC
    else:
        if cat == "cat_car":
            await query.edit_message_text("🚘 **የመኪናውን ሞዴል ያስገቡ፦**\n\n💡 *ምሳሌ፦* Suzuki Desire, Vitz...", parse_mode="Markdown")
            return SELL_CAR_MODEL
        else:
            loc_kbd = [
                [InlineKeyboardButton("ቦሌ", callback_data="loc_ቦሌ"), InlineKeyboardButton("ሲኤምሲ", callback_data="loc_ሲኤምሲ")],
                [InlineKeyboardButton("አያት", callback_data="loc_አያት"), InlineKeyboardButton("ገርጂ", callback_data="loc_ገርጂ")],
                [InlineKeyboardButton("ሳሪስ", callback_data="loc_ሳሪስ"), InlineKeyboardButton("ሌላ አካባቢ", callback_data="loc_ሌላ")]
            ]
            await query.edit_message_text("📍 **የቤቱን/ቦታውን አካባቢ ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(loc_kbd), parse_mode="Markdown")
            return SELL_HOUSE_LOC

# --- BUYER CAR STEPS ---
async def buy_car_model_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_car_model'] = update.message.text
    await update.message.reply_text("📅 **የምርት ዘመን (ዓ.ም) ከስንት እስከ ስንት?**\n\n💡 *ምሳሌ፦* 2015 - 2020", parse_mode="Markdown")
    return BUY_CAR_YEAR

async def buy_car_year_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_car_year'] = update.message.text
    await update.message.reply_text("💰 **በጀት ከስንት እስከ ስንት?**\n\n💡 *ምሳሌ፦* 1.5 - 2.5 ሚሊዮን ብር", parse_mode="Markdown")
    return BUY_CAR_BUDGET

async def buy_car_budget_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_car_budget'] = update.message.text
    await update.message.reply_text("📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**", parse_mode="Markdown")
    return BUY_CAR_PHONE

async def buy_car_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_car_phone'] = update.message.text
    desc = (
        f"🚘 **ሞዴል:** {context.user_data.get('buy_car_model')}\n"
        f"📅 **የምርት ዘመን:** {context.user_data.get('buy_car_year')}\n"
        f"💰 **ባጀት:** {context.user_data.get('buy_car_budget')}\n"
        f"📞 **ስልክ:** {context.user_data.get('buy_car_phone')}"
    )
    return await finalize_listing(update, context, "cat_car", desc)

# --- BUYER HOUSE STEPS ---
async def buy_house_loc_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['buy_house_loc'] = query.data.replace("loc_", "")

    type_kbd = [
        [InlineKeyboardButton("🏡 ቪላ", callback_data="ht_ቪላ"), InlineKeyboardButton("🏢 ሰርቪስ", callback_data="ht_ሰርቪስ")],
        [InlineKeyboardButton("🏢 አፓርታማ", callback_data="ht_አፓርታማ"), InlineKeyboardButton("🏞️ መሬት/የጨረቃ", callback_data="ht_መሬት")],
        [InlineKeyboardButton("🏙️ ሪል እስቴት", callback_data="ht_ሪል እስቴት")]
    ]
    await query.edit_message_text("🏠 **የቤት/የቦታ አይነት ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(type_kbd), parse_mode="Markdown")
    return BUY_HOUSE_TYPE

async def buy_house_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['buy_house_type'] = query.data.replace("ht_", "")
    await query.edit_message_text("💰 **የተዘጋጀው ባጀት ከስንት እስከ ስንት?**", parse_mode="Markdown")
    return BUY_HOUSE_BUDGET

async def buy_house_budget_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_house_budget'] = update.message.text
    await update.message.reply_text("📞 **የስልክ ቁጥርዎን ያስገቡ፦**", parse_mode="Markdown")
    return BUY_HOUSE_PHONE

async def buy_house_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_house_phone'] = update.message.text
    desc = (
        f"📍 **አካባቢ:** {context.user_data.get('buy_house_loc')}\n"
        f"🏠 **የቤት አይነት:** {context.user_data.get('buy_house_type')}\n"
        f"💰 **ባጀት:** {context.user_data.get('buy_house_budget')}\n"
        f"📞 **ስልክ:** {context.user_data.get('buy_house_phone')}"
    )
    return await finalize_listing(update, context, "cat_house", desc)

# --- SELLER CAR STEPS ---
async def sell_car_model_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_car_model'] = update.message.text
    await update.message.reply_text("📅 **የምርት ዘመን (ዓ.ም) ያስገቡ፦**", parse_mode="Markdown")
    return SELL_CAR_YEAR

async def sell_car_year_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_car_year'] = update.message.text
    await update.message.reply_text("💰 **የመሸጫ ዋጋ ያስገቡ፦**", parse_mode="Markdown")
    return SELL_CAR_PRICE

async def sell_car_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_car_price'] = update.message.text
    neg_kbd = [
        [InlineKeyboardButton("🔄 ድርድር አለው", callback_data="neg_yes")],
        [InlineKeyboardButton("❌ ድርድር የለውም", callback_data="neg_no")]
    ]
    await update.message.reply_text("🤝 **ዋጋው ድርድር አለው?**", reply_markup=InlineKeyboardMarkup(neg_kbd), parse_mode="Markdown")
    return SELL_CAR_NEG

async def sell_car_neg_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['sell_car_neg'] = "ድርድር አለው" if query.data == "neg_yes" else "ድርድር የለውም"
    await query.edit_message_text("📞 **ስልክ ቁጥርዎን ያስገቡ፦**", parse_mode="Markdown")
    return SELL_CAR_PHONE

async def sell_car_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_car_phone'] = update.message.text
    await update.message.reply_text("📸 **የመኪናውን ፎቶ ያስገቡ፦**", parse_mode="Markdown")
    return SELL_CAR_PHOTO

async def sell_car_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return SELL_CAR_PHOTO

    desc = (
        f"🚘 **ሞዴል:** {context.user_data.get('sell_car_model')}\n"
        f"📅 **የምርት ዘመን:** {context.user_data.get('sell_car_year')}\n"
        f"💰 **ዋጋ:** {context.user_data.get('sell_car_price')} ({context.user_data.get('sell_car_neg')})\n"
        f"📞 **ስልክ:** {context.user_data.get('sell_car_phone')}"
    )
    return await finalize_listing(update, context, "cat_car", desc, photo_id=photo_id)

# --- SELLER HOUSE STEPS ---
async def sell_house_loc_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['sell_house_loc'] = query.data.replace("loc_", "")

    type_kbd = [
        [InlineKeyboardButton("🏡 ቪላ", callback_data="sht_ቪላ"), InlineKeyboardButton("🏢 ሰርቪስ", callback_data="sht_ሰርቪስ")],
        [InlineKeyboardButton("🏢 አፓርታማ", callback_data="sht_አፓርታማ"), InlineKeyboardButton("🏞️ መሬት/የጨረቃ", callback_data="sht_መሬት")],
        [InlineKeyboardButton("🏙️ ሪል እስቴት", callback_data="sht_ሪል እስቴት")]
    ]
    await query.edit_message_text("🏠 **የቤት/የቦታ አይነት ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(type_kbd), parse_mode="Markdown")
    return SELL_HOUSE_TYPE

async def sell_house_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['sell_house_type'] = query.data.replace("sht_", "")
    await query.edit_message_text("📐 **የቦታው/የቤቱ ስፋት (በካሬ ሜትር) ያስገቡ፦**", parse_mode="Markdown")
    return SELL_HOUSE_AREA

async def sell_house_area_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_house_area'] = update.message.text
    await update.message.reply_text("🏗️ **የቤቱ/የቦታው ሁኔታ ያስገቡ (ምሳሌ፦ ያለቀለት፣ ያላበቃ፣ ፕላስተር የለሽ)፦**", parse_mode="Markdown")
    return SELL_HOUSE_COND

async def sell_house_cond_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_house_cond'] = update.message.text
    await update.message.reply_text("💰 **የመሸጫ ዋጋ ያስገቡ፦**", parse_mode="Markdown")
    return SELL_HOUSE_PRICE

async def sell_house_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_house_price'] = update.message.text
    neg_kbd = [
        [InlineKeyboardButton("🔄 ድርድር አለው", callback_data="hneg_yes")],
        [InlineKeyboardButton("❌ ድርድር የለውም", callback_data="hneg_no")]
    ]
    await update.message.reply_text("🤝 **ዋጋው ድርድር አለው?**", reply_markup=InlineKeyboardMarkup(neg_kbd), parse_mode="Markdown")
    return SELL_HOUSE_NEG

async def sell_house_neg_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['sell_house_neg'] = "ድርድር አለው" if query.data == "hneg_yes" else "ድርድር የለውም"
    await query.edit_message_text("📞 **ስልክ ቁጥርዎን ያስገቡ፦**", parse_mode="Markdown")
    return SELL_HOUSE_PHONE

async def sell_house_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_house_phone'] = update.message.text
    await update.message.reply_text("📸 **የቤቱን/ንብረቱን ፎቶ ያስገቡ፦**", parse_mode="Markdown")
    return SELL_HOUSE_PHOTO

async def sell_house_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return SELL_HOUSE_PHOTO

    desc = (
        f"📍 **አካባቢ:** {context.user_data.get('sell_house_loc')}\n"
        f"🏠 **አይነት:** {context.user_data.get('sell_house_type')}\n"
        f"📐 **ስፋት:** {context.user_data.get('sell_house_area')} ካሬ\n"
        f"🏗️ **ሁኔታ:** {context.user_data.get('sell_house_cond')}\n"
        f"💰 **ዋጋ:** {context.user_data.get('sell_house_price')} ({context.user_data.get('sell_house_neg')})\n"
        f"📞 **ስልክ:** {context.user_data.get('sell_house_phone')}"
    )
    return await finalize_listing(update, context, "cat_house", desc, photo_id=photo_id)

# --- COMMON FINALIZE LISTING ---
async def finalize_listing(update: Update, context: ContextTypes.DEFAULT_TYPE, cat, formatted_desc, photo_id=None):
    user = update.effective_user
    req_type = context.user_data.get('req_type', 'BUY')
    role = context.user_data.get('user_role', 'ባለቤት')

    full_desc = f"[{role}]\n{formatted_desc}"
    req_id = add_listing(user.id, user.first_name, req_type, cat, full_desc)

    if req_id:
        title = "🔍 የገዢ ጥያቄ" if req_type == 'BUY' else "📢 የሻጭ ማስታወቂያ"
        action_btn_text = "✅ አለኝ (ንብረቱ አለኝ)" if req_type == 'BUY' else "✅ እፈልገዋለሁ (ደንበኛ አለኝ)"
        
        action_kbd = InlineKeyboardMarkup([[InlineKeyboardButton(action_btn_text, callback_data=f"item_resp_{req_id}_{user.id}_{cat}")]])

        reply_msg = f"✅ **{title}ዎ በስኬት ተመዝግቧል!** (#REQ-{req_id})\n\n👤 **ማንነት:** {role}\n{formatted_desc}\n\n🚀 ጥያቄዎ ለአቅራቢዎች ተልኳል፤ ምላሾች ሲኖሩ ይደርስዎታል።"
        
        if update.message:
            await update.message.reply_text(reply_msg, reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
        elif update.callback_query:
            await update.callback_query.message.reply_text(reply_msg, reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))

        if ADMIN_CHAT_ID:
            try:
                admin_msg = f"🔔 **አዲስ {title}!** (#REQ-{req_id})\n\n👤 **ላኪ:** {user.first_name} (@{user.username})\n🎭 **ማንነት:** {role}\n{formatted_desc}"
                if photo_id:
                    await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=photo_id, caption=admin_msg, reply_markup=action_kbd, parse_mode="Markdown")
                else:
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, reply_markup=action_kbd, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Admin notify error: {e}")
    return ConversationHandler.END

# ==============================================================================
# 7. RESPONSE FLOW (የምላሽ አሰጣጥ ፎርም)
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
        [InlineKeyboardButton("👤 ለራሴ እፈልጋለሁ / ንብረቱ የራሴ ነው", callback_data="resp_role_owner")],
        [InlineKeyboardButton("👨‍💼 ደላላ ነኝ ደንበኛ አለኝ", callback_data="resp_role_broker")]
    ]
    await query.message.reply_text("📋 **የምላሽ ሰጭ ማንነት፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return RESP_ROLE

async def resp_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['resp_role'] = "👤 ባለቤት" if query.data == "resp_role_owner" else "👨‍💼 ደላላ"
    
    target_cat = context.user_data.get('target_cat', 'cat_car')

    if target_cat == "cat_car":
        await query.edit_message_text("🚘 **የመኪናውን ሞዴል ያስገቡ፦**", parse_mode="Markdown")
        return RESP_CAR_MODEL
    else:
        loc_kbd = [
            [InlineKeyboardButton("ቦሌ", callback_data="rloc_ቦሌ"), InlineKeyboardButton("ሲኤምሲ", callback_data="rloc_ሲኤምሲ")],
            [InlineKeyboardButton("አያት", callback_data="rloc_አያት"), InlineKeyboardButton("ገርጂ", callback_data="rloc_ገርጂ")],
            [InlineKeyboardButton("ሳሪስ", callback_data="rloc_ሳሪስ"), InlineKeyboardButton("ሌላ አካባቢ", callback_data="rloc_ሌላ")]
        ]
        await query.edit_message_text("📍 **የቦታው/የቤቱ አካባቢ ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(loc_kbd), parse_mode="Markdown")
        return RESP_HOUSE_LOC

# --- CAR RESPONSE STEPS ---
async def resp_car_model_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_model'] = update.message.text
    await update.message.reply_text("📅 **የምርት ዘመን (ዓ.ም)፦**", parse_mode="Markdown")
    return RESP_CAR_YEAR

async def resp_car_year_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_year'] = update.message.text
    await update.message.reply_text("💰 **የመሸጫ/የመከራያ ዋጋ፦**", parse_mode="Markdown")
    return RESP_CAR_PRICE

async def resp_car_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_price'] = update.message.text
    neg_kbd = [
        [InlineKeyboardButton("🔄 ድርድር አለው", callback_data="rneg_yes")],
        [InlineKeyboardButton("❌ ድርድር የለውም", callback_data="rneg_no")]
    ]
    await update.message.reply_text("🤝 **ዋጋው ድርድር አለው?**", reply_markup=InlineKeyboardMarkup(neg_kbd), parse_mode="Markdown")
    return RESP_CAR_NEG

async def resp_car_neg_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['resp_neg'] = "ድርድር አለው" if query.data == "rneg_yes" else "ድርድር የለውም"
    await query.edit_message_text("📞 **ስልክ ቁጥርዎን ያስገቡ፦**", parse_mode="Markdown")
    return RESP_CAR_PHONE

async def resp_car_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_phone'] = update.message.text
    await update.message.reply_text("📸 **የመኪናውን ፎቶ ያስገቡ፦**", parse_mode="Markdown")
    return RESP_CAR_PHOTO

async def resp_car_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    responder = update.effective_user
    target_user_id = context.user_data.get('target_user_id')
    req_id = context.user_data.get('target_req_id')
    role = context.user_data.get('resp_role', 'አቅራቢ')
    
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return RESP_CAR_PHOTO

    formatted_caption = (
        f"🎉 **አዲስ የቀረበ የመኪና አማራጭ!** (#REQ-{req_id})\n\n"
        f"🎭 **የላኪው ሚና:** {role}\n"
        f"🚘 **ሞዴል:** {context.user_data.get('resp_model')}\n"
        f"📅 **የምርት ዘመን:** {context.user_data.get('resp_year')}\n"
        f"💰 **ዋጋ:** {context.user_data.get('resp_price')} ({context.user_data.get('resp_neg')})\n"
        f"📞 **ስልክ ቁጥር:** {context.user_data.get('resp_phone')}\n"
        f"👤 **ቴሌግራም:** @{responder.username if responder.username else responder.first_name}"
    )

    if target_user_id:
        try:
            await context.bot.send_photo(chat_id=target_user_id, photo=photo_id, caption=formatted_caption, parse_mode="Markdown")
            await update.message.reply_text("✅ **የመኪናው መረጃ እና ፎቶ ለጠያቂው በስኬት ተልኳል!**", reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
        except Exception as e:
            logging.error(f"Error sending response: {e}")
            await update.message.reply_text("❌ መረጃውን መላክ አልተቻለም።")

    return ConversationHandler.END

# --- HOUSE RESPONSE STEPS ---
async def resp_house_loc_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['resp_house_loc'] = query.data.replace("rloc_", "")
    await query.edit_message_text("📐 **የቦታው/የቤቱ ስፋት (በካሬ ሜትር)፦**", parse_mode="Markdown")
    return RESP_HOUSE_AREA

async def resp_house_area_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_house_area'] = update.message.text
    await update.message.reply_text("🏗️ **የቤቱ/የቦታው ሁኔታ ያስገቡ፦**", parse_mode="Markdown")
    return RESP_HOUSE_COND

async def resp_house_cond_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_house_cond'] = update.message.text
    await update.message.reply_text("💰 **ዋጋ ያስገቡ፦**", parse_mode="Markdown")
    return RESP_HOUSE_PRICE

async def resp_house_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_price'] = update.message.text
    neg_kbd = [
        [InlineKeyboardButton("🔄 ድርድር አለው", callback_data="rhneg_yes")],
        [InlineKeyboardButton("❌ ድርድር የለውም", callback_data="rhneg_no")]
    ]
    await update.message.reply_text("🤝 **ዋጋው ድርድር አለው?**", reply_markup=InlineKeyboardMarkup(neg_kbd), parse_mode="Markdown")
    return RESP_HOUSE_NEG

async def resp_house_neg_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['resp_neg'] = "ድርድር አለው" if query.data == "rhneg_yes" else "ድርድር የለውም"
    await query.edit_message_text("📞 **ስልክ ቁጥርዎን ያስገቡ፦**", parse_mode="Markdown")
    return RESP_HOUSE_PHONE

async def resp_house_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_phone'] = update.message.text
    await update.message.reply_text("📸 **የቤቱን/ንብረቱን ፎቶ ያስገቡ፦**", parse_mode="Markdown")
    return RESP_HOUSE_PHOTO

async def resp_house_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    responder = update.effective_user
    target_user_id = context.user_data.get('target_user_id')
    req_id = context.user_data.get('target_req_id')
    role = context.user_data.get('resp_role', 'አቅራቢ')
    
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return RESP_HOUSE_PHOTO

    formatted_caption = (
        f"🎉 **አዲስ የቀረበ የቤት/ንብረት አማራጭ!** (#REQ-{req_id})\n\n"
        f"🎭 **የላኪው ሚና:** {role}\n"
        f"📍 **አካባቢ:** {context.user_data.get('resp_house_loc')}\n"
        f"📐 **ስፋት:** {context.user_data.get('resp_house_area')} ካሬ\n"
        f"🏗️ **ሁኔታ:** {context.user_data.get('resp_house_cond')}\n"
        f"💰 **ዋጋ:** {context.user_data.get('resp_price')} ({context.user_data.get('resp_neg')})\n"
        f"📞 **ስልክ ቁጥር:** {context.user_data.get('resp_phone')}\n"
        f"👤 **ቴሌግራም:** @{responder.username if responder.username else responder.first_name}"
    )

    if target_user_id:
        try:
            await context.bot.send_photo(chat_id=target_user_id, photo=photo_id, caption=formatted_caption, parse_mode="Markdown")
            await update.message.reply_text("✅ **የቤት/ቦታው መረጃ እና ፎቶ ለጠያቂው በስኬት ተልኳል!**", reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
        except Exception as e:
            logging.error(f"Error sending response: {e}")
            await update.message.reply_text("❌ መረጃውን መላክ አልተቻለም።")

    return ConversationHandler.END

# ==============================================================================
# 8. MAIN FUNCTION
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    
    # Global Start & Request List Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), show_requests_list))

    # Cancel Handler for strict reset
    cancel_handler = MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), cancel_flow)

    # Broker Registration Conversation
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ መመዝገብ$"), start_broker_registration)],
        states={
            BROKER_NAME: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, broker_name_received)],
            BROKER_PHONE: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, broker_phone_received)],
            BROKER_AREA: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, broker_area_received)],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
    )

    # Response Conversation
    response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_item_response, pattern="^item_resp_")],
        states={
            RESP_ROLE: [cancel_handler, CallbackQueryHandler(resp_role_chosen, pattern="^resp_role_")],
            # Car Steps
            RESP_CAR_MODEL: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_model_received)],
            RESP_CAR_YEAR: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_year_received)],
            RESP_CAR_PRICE: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_price_received)],
            RESP_CAR_NEG: [cancel_handler, CallbackQueryHandler(resp_car_neg_chosen, pattern="^rneg_")],
            RESP_CAR_PHONE: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_phone_received)],
            RESP_CAR_PHOTO: [cancel_handler, MessageHandler(filters.PHOTO, resp_car_photo_received)],
            # House Steps
            RESP_HOUSE_LOC: [cancel_handler, CallbackQueryHandler(resp_house_loc_chosen, pattern="^rloc_")],
            RESP_HOUSE_AREA: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, resp_house_area_received)],
            RESP_HOUSE_COND: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, resp_house_cond_received)],
            RESP_HOUSE_PRICE: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, resp_house_price_received)],
            RESP_HOUSE_NEG: [cancel_handler, CallbackQueryHandler(resp_house_neg_chosen, pattern="^rhneg_")],
            RESP_HOUSE_PHONE: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, resp_house_phone_received)],
            RESP_HOUSE_PHOTO: [cancel_handler, MessageHandler(filters.PHOTO, resp_house_photo_received)],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
    )

    # Market Flow Conversation
    market_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(".*መግዛት.*"), start_buy_flow),
            MessageHandler(filters.Regex(".*መሸጥ.*"), start_sell_flow)
        ],
        states={
            FLOW_ROLE: [cancel_handler, CallbackQueryHandler(flow_role_chosen, pattern="^role_")],
            FLOW_CAT: [cancel_handler, CallbackQueryHandler(flow_category_chosen, pattern="^cat_")],
            
            # Buyer Car Steps
            BUY_CAR_MODEL: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, buy_car_model_received)],
            BUY_CAR_YEAR: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, buy_car_year_received)],
            BUY_CAR_BUDGET: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, buy_car_budget_received)],
            BUY_CAR_PHONE: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, buy_car_phone_received)],

            # Buyer House Steps
            BUY_HOUSE_LOC: [cancel_handler, CallbackQueryHandler(buy_house_loc_chosen, pattern="^loc_")],
            BUY_HOUSE_TYPE: [cancel_handler, CallbackQueryHandler(buy_house_type_chosen, pattern="^ht_")],
            BUY_HOUSE_BUDGET: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, buy_house_budget_received)],
            BUY_HOUSE_PHONE: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, buy_house_phone_received)],

            # Seller Car Steps
            SELL_CAR_MODEL: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_model_received)],
            SELL_CAR_YEAR: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_year_received)],
            SELL_CAR_PRICE: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_price_received)],
            SELL_CAR_NEG: [cancel_handler, CallbackQueryHandler(sell_car_neg_chosen, pattern="^neg_")],
            SELL_CAR_PHONE: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_phone_received)],
            SELL_CAR_PHOTO: [cancel_handler, MessageHandler(filters.PHOTO, sell_car_photo_received)],

            # Seller House Steps
            SELL_HOUSE_LOC: [cancel_handler, CallbackQueryHandler(sell_house_loc_chosen, pattern="^loc_")],
            SELL_HOUSE_TYPE: [cancel_handler, CallbackQueryHandler(sell_house_type_chosen, pattern="^sht_")],
            SELL_HOUSE_AREA: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, sell_house_area_received)],
            SELL_HOUSE_COND: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, sell_house_cond_received)],
            SELL_HOUSE_PRICE: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, sell_house_price_received)],
            SELL_HOUSE_NEG: [cancel_handler, CallbackQueryHandler(sell_house_neg_chosen, pattern="^hneg_")],
            SELL_HOUSE_PHONE: [cancel_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, sell_house_phone_received)],
            SELL_HOUSE_PHOTO: [cancel_handler, MessageHandler(filters.PHOTO, sell_house_photo_received)],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
    )

    app.add_handler(broker_conv)
    app.add_handler(response_conv)
    app.add_handler(market_conv)

    print("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()
