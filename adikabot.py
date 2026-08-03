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
        logging.info("✅ Database initialized successfully")
    except Exception as e:
        logging.error(f"Database initialization error: {e}")
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

# ==============================================================================
# 3. KEYBOARDS & CONVERSATION STATES
# ==============================================================================
MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ መመዝገብ", "👤 መገለጫዬ"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]

# States for Market Flow (Buyer & Seller)
(
    FLOW_ROLE, FLOW_CAT, 
    BUY_CAR_TYPE, BUY_CAR_MODEL, BUY_CAR_BUDGET, BUY_CAR_PAY, BUY_CAR_PHONE,
    BUY_HOUSE_TYPE, BUY_HOUSE_ACT, BUY_HOUSE_LOC, BUY_HOUSE_BUDGET, BUY_HOUSE_PAY, BUY_HOUSE_PHONE,
    SELL_CAR_MAKE, SELL_CAR_MODEL, SELL_CAR_PRICE, SELL_CAR_PAY, SELL_CAR_PHONE, SELL_CAR_PHOTO,
    GENERIC_DESC
) = range(20)

# States for Response Flow
(
    RESP_ROLE, 
    RESP_CAR_MAKE, RESP_CAR_MODEL, RESP_CAR_PRICE, RESP_CAR_PHONE, RESP_CAR_PHOTO,
    RESP_HOUSE_DESC, RESP_HOUSE_PRICE, RESP_HOUSE_PHONE, RESP_HOUSE_PHOTO
) = range(20, 30)

# ==============================================================================
# 4. GENERAL HANDLERS
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

async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ማንኛውም የዋና ገጽ ጥያቄ ሲመጣ የቀደመውን ሂደቶች በሙሉ ያቋርጣል"""
    return await start(update, context)

# ==============================================================================
# 5. MARKET FLOW (BUYER & SELLER)
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
        [InlineKeyboardButton("🏢 ንግድ ቤት / ቢሮ (Commercial)", callback_data="cat_commercial")],
    ]
    await query.edit_message_text("🏷️ **የንብረቱን ምድብ ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return FLOW_CAT

async def flow_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat = query.data
    context.user_data['category'] = cat
    req_type = context.user_data.get('req_type', 'BUY')

    if req_type == 'SELL':
        if cat == "cat_car":
            await query.edit_message_text("🚘 **የመኪናውን ስም (Make/Brand) ያስገቡ፦**\n\n💡 *ምሳሌ፦* Toyota, Hyundai, Suzuki...", parse_mode="Markdown")
            return SELL_CAR_MAKE
        else:
            await query.edit_message_text("✍️ **የንብረቱን/የቤቱን ዝርዝር መረጃ እና ስልክ ቁጥር ያስገቡ፦**", parse_mode="Markdown")
            return GENERIC_DESC
    else:
        # BUYER FLOW STEP BY STEP
        if cat == "cat_car":
            keyboard = [
                [InlineKeyboardButton("🚘 የቤት መኪና (Automobile)", callback_data="bcartype_personal")],
                [InlineKeyboardButton("🚚 የጭነት / የንግድ መኪና", callback_data="bcartype_commercial")],
                [InlineKeyboardButton("🚜 ከባድ ማሽን / የሥራ መኪና", callback_data="bcartype_heavy")]
            ]
            await query.edit_message_text("🚘 **የሚፈልጉትን የመኪና አይነት ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return BUY_CAR_TYPE

        elif cat == "cat_house":
            keyboard = [
                [InlineKeyboardButton("🏡 ቪላ (Villa)", callback_data="bhtype_villa")],
                [InlineKeyboardButton("🏢 አፓርትመንት (Apartment)", callback_data="bhtype_apt")],
                [InlineKeyboardButton("🏢 ኮንዶሚኒየም (Condo)", callback_data="bhtype_condo")],
                [InlineKeyboardButton("🏞️ ባዶ ቦታ / መሬት (Plot)", callback_data="bhtype_land")]
            ]
            await query.edit_message_text("🏠 **የሚፈልጉትን የቤት/ቦታ አይነት ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return BUY_HOUSE_TYPE
        else:
            await query.edit_message_text("✍️ **የሚፈልጉትን የንግድ ቤት/ቢሮ ዝርዝር መረጃ እና ስልክ ያስገቡ፦**", parse_mode="Markdown")
            return GENERIC_DESC

# --- BUYER CAR STEP BY STEP ---
async def buy_car_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    t_map = {"bcartype_personal": "የቤት መኪና", "bcartype_commercial": "የንግድ/ጭነት", "bcartype_heavy": "ከባድ ማሽን"}
    context.user_data['buy_car_type'] = t_map.get(query.data, "መኪና")
    
    await query.edit_message_text("🚘 **የሚፈልጉትን የመኪና ስም ወይም ሞዴል ያስገቡ፦**\n\n💡 *ምሳሌ፦* Toyota Vitz, Hyundai Tucson, Suzuki Desire...", parse_mode="Markdown")
    return BUY_CAR_MODEL

async def buy_car_model_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_car_model'] = update.message.text
    await update.message.reply_text("💰 **የተዘጋጀው ከፍተኛ ባጀት (በብር) ያስገቡ፦**\n\n💡 *ምሳሌ፦* እስከ 2.5 ሚሊዮን ብር", parse_mode="Markdown")
    return BUY_CAR_BUDGET

async def buy_car_budget_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_car_budget'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("💵 በካሽ (Cash)", callback_data="bpay_cash")],
        [InlineKeyboardButton("🏦 በባንክ ብድር / ሊዚንግ", callback_data="bpay_bank")],
        [InlineKeyboardButton("🔄 በሁለቱም ይቻላል", callback_data="bpay_any")]
    ]
    await update.message.reply_text("💳 **የመክፈያ መንገድ ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return BUY_CAR_PAY

async def buy_car_pay_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    p_map = {"bpay_cash": "ካሽ", "bpay_bank": "ባንክ ብድር", "bpay_any": "ማናቸውም"}
    context.user_data['buy_car_pay'] = p_map.get(query.data, "ካሽ")
    
    await query.edit_message_text("📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**", parse_mode="Markdown")
    return BUY_CAR_PHONE

async def buy_car_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_car_phone'] = update.message.text
    
    c_type = context.user_data.get('buy_car_type')
    c_model = context.user_data.get('buy_car_model')
    c_budget = context.user_data.get('buy_car_budget')
    c_pay = context.user_data.get('buy_car_pay')
    c_phone = context.user_data.get('buy_car_phone')

    formatted_desc = f"🚘 **አይነት:** {c_type}\n🏷️ **የሚፈለግ ሞዴል:** {c_model}\n💰 **ባጀት:** {c_budget}\n💳 **ክፍያ:** {c_pay}\n📞 **ስልክ:** {c_phone}"
    return await finalize_listing(update, context, "cat_car", formatted_desc)

# --- BUYER HOUSE STEP BY STEP ---
async def buy_house_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    h_map = {"bhtype_villa": "ቪላ", "bhtype_apt": "አፓርትመንት", "bhtype_condo": "ኮንዶሚኒየም", "bhtype_land": "ቦታ/መሬት"}
    context.user_data['buy_house_type'] = h_map.get(query.data, "ቤት")

    keyboard = [
        [InlineKeyboardButton("🛍️ ለመግዛት", callback_data="bhact_buy")],
        [InlineKeyboardButton("🔑 ለመከራየት", callback_data="bhact_rent")]
    ]
    await query.edit_message_text("❓ **መግዛት ነው ወይስ መከራየት የሚፈልጉት?**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return BUY_HOUSE_ACT

async def buy_house_act_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['buy_house_act'] = "ለመግዛት" if query.data == "bhact_buy" else "ለመከራየት"
    await query.edit_message_text("📍 **የሚፈልጉበትን አካባቢ/ቦታ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቦሌ አትላስ፣ ሲኤምሲ፣ ሳሪስ...", parse_mode="Markdown")
    return BUY_HOUSE_LOC

async def buy_house_loc_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_house_loc'] = update.message.text
    await update.message.reply_text("💰 **የተዘጋጀው ከፍተኛ ባጀት ያስገቡ፦**", parse_mode="Markdown")
    return BUY_HOUSE_BUDGET

async def buy_house_budget_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_house_budget'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("💵 በካሽ (Cash)", callback_data="bhpay_cash")],
        [InlineKeyboardButton("🏦 በባንክ ብድር", callback_data="bhpay_bank")],
        [InlineKeyboardButton("🔄 ማናቸውም", callback_data="bhpay_any")]
    ]
    await update.message.reply_text("💳 **የመክፈያ መንገድ ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return BUY_HOUSE_PAY

async def buy_house_pay_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    p_map = {"bhpay_cash": "ካሽ", "bhpay_bank": "ባንክ", "bhpay_any": "ማናቸውም"}
    context.user_data['buy_house_pay'] = p_map.get(query.data, "ካሽ")
    await query.edit_message_text("📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**", parse_mode="Markdown")
    return BUY_HOUSE_PHONE

async def buy_house_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_house_phone'] = update.message.text
    
    h_type = context.user_data.get('buy_house_type')
    h_act = context.user_data.get('buy_house_act')
    h_loc = context.user_data.get('buy_house_loc')
    h_budget = context.user_data.get('buy_house_budget')
    h_pay = context.user_data.get('buy_house_pay')
    h_phone = context.user_data.get('buy_house_phone')

    formatted_desc = f"🏠 **አይነት:** {h_type} ({h_act})\n📍 **አካባቢ:** {h_loc}\n💰 **ባጀት:** {h_budget}\n💳 **ክፍያ:** {h_pay}\n📞 **ስልክ:** {h_phone}"
    return await finalize_listing(update, context, "cat_house", formatted_desc)

# --- SELLER CAR FLOW ---
async def sell_car_make_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_make'] = update.message.text
    await update.message.reply_text("🚘 **የመኪናውን ሞዴል እና የሰራበት ዓ.ም (Model & Year) ያስገቡ፦**", parse_mode="Markdown")
    return SELL_CAR_MODEL

async def sell_car_model_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_model'] = update.message.text
    await update.message.reply_text("💰 **የመሸጫ/የመከራያ ዋጋ ያስገቡ፦**", parse_mode="Markdown")
    return SELL_CAR_PRICE

async def sell_car_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_price'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("💵 በካሽ (Cash)", callback_data="spay_cash")],
        [InlineKeyboardButton("🏦 በባንክ ብድር / ሊዚንግ", callback_data="spay_bank")],
        [InlineKeyboardButton("🔄 በሁለቱም ይቻላል", callback_data="spay_any")]
    ]
    await update.message.reply_text("💳 **የመክፈያ መንገድ ይምረጡ፦**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return SELL_CAR_PAY

async def sell_car_pay_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pay_map = {"spay_cash": "ካሽ", "spay_bank": "ባንክ ብድር", "spay_any": "ማናቸውም"}
    context.user_data['sell_payment'] = pay_map.get(query.data, "ካሽ")
    await query.edit_message_text("📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**", parse_mode="Markdown")
    return SELL_CAR_PHONE

async def sell_car_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['sell_phone'] = update.message.text
    await update.message.reply_text("📸 **በመጨረሻም የመኪናውን ፎቶ ያስገቡ፦**", parse_mode="Markdown")
    return SELL_CAR_PHOTO

async def sell_car_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    make = context.user_data.get('sell_make', 'N/A')
    model = context.user_data.get('sell_model', 'N/A')
    price = context.user_data.get('sell_price', 'N/A')
    payment = context.user_data.get('sell_payment', 'ካሽ')
    phone = context.user_data.get('sell_phone', 'N/A')

    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return SELL_CAR_PHOTO

    formatted_desc = f"🚘 **መኪና:** {make}\n🏷️ **ሞዴል:** {model}\n💰 **ዋጋ:** {price}\n💳 **ክፍያ:** {payment}\n📞 **ስልክ:** {phone}"
    return await finalize_listing(update, context, "cat_car", formatted_desc, photo_id=photo_id)

async def generic_desc_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text
    cat = context.user_data.get('category', 'cat_house')
    return await finalize_listing(update, context, cat, desc)

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
        
        # Category passes strictly to guarantee the right response form!
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
# 6. PROFESSIONAL RESPONSE FLOW (የምላሽ አሰጣጥ ደረጃዎች)
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
    await query.message.reply_text("📋 **የምላሽ ሰጭ ማንነት፦**\n\nእባክዎን ማንነትዎን ይምረጡ፦", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return RESP_ROLE

async def resp_role_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['resp_role'] = "👤 ባለቤት" if query.data == "resp_role_owner" else "👨‍💼 ደላላ"
    
    target_cat = context.user_data.get('target_cat', 'cat_car')

    if target_cat == "cat_car":
        await query.edit_message_text("🚘 **የመኪናውን ስም (Make/Brand) ያስገቡ፦**\n\n💡 *ምሳሌ፦* Toyota, Hyundai, Suzuki...", parse_mode="Markdown")
        return RESP_CAR_MAKE
    else:
        await query.edit_message_text("🏠 **የቤቱን/ቦታውን አድራሻ እና ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቦሌ አትላስ አካባቢ፣ ባለ 2 መኝታ አፓርትመንት...", parse_mode="Markdown")
        return RESP_HOUSE_DESC

# --- CAR RESPONSE STEPS ---
async def resp_car_make_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_make'] = update.message.text
    await update.message.reply_text("🚘 **የመኪናው ሞዴል እና የሰራበት ዓ.ም (Model & Year)፦**", parse_mode="Markdown")
    return RESP_CAR_MODEL

async def resp_car_model_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_model'] = update.message.text
    await update.message.reply_text("💰 **የመሸጫ/የመከራያ ዋጋ፦**", parse_mode="Markdown")
    return RESP_CAR_PRICE

async def resp_car_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_price'] = update.message.text
    await update.message.reply_text("📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**", parse_mode="Markdown")
    return RESP_CAR_PHONE

async def resp_car_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_phone'] = update.message.text
    await update.message.reply_text("📸 **በመጨረሻም የመኪናውን ፎቶ ያስገቡ፦**", parse_mode="Markdown")
    return RESP_CAR_PHOTO

async def resp_car_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        return RESP_CAR_PHOTO

    formatted_caption = (
        f"🎉 **አዲስ የቀረበ የመኪና አማራጭ!** (#REQ-{req_id})\n\n"
        f"🎭 **የላኪው ሚና:** {role}\n"
        f"🚘 **ስም (Brand):** {make}\n"
        f"🏷️ **ሞዴል & ዓ.ም:** {model}\n"
        f"💰 **ዋጋ:** {price}\n"
        f"📞 **ስልክ ቁጥር:** {phone}\n"
        f"👤 **ቴሌግራም:** @{responder.username if responder.username else responder.first_name}"
    )

    if target_user_id:
        try:
            await context.bot.send_photo(chat_id=target_user_id, photo=photo_id, caption=formatted_caption, parse_mode="Markdown")
            await update.message.reply_text("✅ **የቀረቡት የመኪና መረጃዎች እና ፎቶው ለጠያቂው በስኬት ተልከዋል!**", reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
        except Exception as e:
            logging.error(f"Error sending response: {e}")
            await update.message.reply_text("❌ መረጃውን መላክ አልተቻለም።")

    return ConversationHandler.END

# --- HOUSE RESPONSE STEPS ---
async def resp_house_desc_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_house_desc'] = update.message.text
    await update.message.reply_text("💰 **የቤቱ/የቦታው ዋጋ፦**", parse_mode="Markdown")
    return RESP_HOUSE_PRICE

async def resp_house_price_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_price'] = update.message.text
    await update.message.reply_text("📞 **እርስዎን የሚያገኙበት የስልክ ቁጥር ያስገቡ፦**", parse_mode="Markdown")
    return RESP_HOUSE_PHONE

async def resp_house_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_phone'] = update.message.text
    await update.message.reply_text("📸 **በመጨረሻም የቤቱን/ንብረቱን ፎቶ ያስገቡ፦**", parse_mode="Markdown")
    return RESP_HOUSE_PHOTO

async def resp_house_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    responder = update.effective_user
    target_user_id = context.user_data.get('target_user_id')
    req_id = context.user_data.get('target_req_id')
    role = context.user_data.get('resp_role', 'አቅራቢ')
    desc = context.user_data.get('resp_house_desc', 'N/A')
    price = context.user_data.get('resp_price', 'N/A')
    phone = context.user_data.get('resp_phone', 'N/A')
    
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    if not photo_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ይላኩ!")
        return RESP_HOUSE_PHOTO

    formatted_caption = (
        f"🎉 **አዲስ የቀረበ የቤት/ንብረት አማራጭ!** (#REQ-{req_id})\n\n"
        f"🎭 **የላኪው ሚና:** {role}\n"
        f"🏠 **የቤት/ቦታ መረጃ:** {desc}\n"
        f"💰 **ዋጋ:** {price}\n"
        f"📞 **ስልክ ቁጥር:** {phone}\n"
        f"👤 **ቴሌግራም:** @{responder.username if responder.username else responder.first_name}"
    )

    if target_user_id:
        try:
            await context.bot.send_photo(chat_id=target_user_id, photo=photo_id, caption=formatted_caption, parse_mode="Markdown")
            await update.message.reply_text("✅ **የቀረቡት የቤት መረጃዎች እና ፎቶው ለጠያቂው በስኬት ተልከዋል!**", reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True))
        except Exception as e:
            logging.error(f"Error sending response: {e}")
            await update.message.reply_text("❌ መረጃውን መላክ አልተቻለም።")

    return ConversationHandler.END

# ==============================================================================
# 7. MAIN FUNCTION
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))

    # Cancel Filter for Keyboard Buttons
    cancel_filter = MessageHandler(filters.Regex(".*(ዋና ገጽ|መግዛት|መሸጥ|መመዝገብ|መገለጫዬ|ድጋፍ).*"), cancel_flow)

    # Response Flow
    response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_item_response, pattern="^item_resp_")],
        states={
            RESP_ROLE: [CallbackQueryHandler(resp_role_chosen, pattern="^resp_role_")],
            
            # Car Response Steps
            RESP_CAR_MAKE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_make_received)],
            RESP_CAR_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_model_received)],
            RESP_CAR_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_price_received)],
            RESP_CAR_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_car_phone_received)],
            RESP_CAR_PHOTO: [MessageHandler(filters.PHOTO, resp_car_photo_received)],
            
            # House Response Steps
            RESP_HOUSE_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_house_desc_received)],
            RESP_HOUSE_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_house_price_received)],
            RESP_HOUSE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, resp_house_phone_received)],
            RESP_HOUSE_PHOTO: [MessageHandler(filters.PHOTO, resp_house_photo_received)],
        },
        fallbacks=[CommandHandler("start", start), cancel_filter],
    )

    # Market Buyer/Seller Flow
    market_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(".*መግዛት.*"), start_buy_flow),
            MessageHandler(filters.Regex(".*መሸጥ.*"), start_sell_flow)
        ],
        states={
            FLOW_ROLE: [CallbackQueryHandler(flow_role_chosen, pattern="^role_")],
            FLOW_CAT: [CallbackQueryHandler(flow_category_chosen, pattern="^cat_")],
            
            # Buyer Car Steps
            BUY_CAR_TYPE: [CallbackQueryHandler(buy_car_type_chosen, pattern="^bcartype_")],
            BUY_CAR_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_car_model_received)],
            BUY_CAR_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_car_budget_received)],
            BUY_CAR_PAY: [CallbackQueryHandler(buy_car_pay_chosen, pattern="^bpay_")],
            BUY_CAR_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_car_phone_received)],

            # Buyer House Steps
            BUY_HOUSE_TYPE: [CallbackQueryHandler(buy_house_type_chosen, pattern="^bhtype_")],
            BUY_HOUSE_ACT: [CallbackQueryHandler(buy_house_act_chosen, pattern="^bhact_")],
            BUY_HOUSE_LOC: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_house_loc_received)],
            BUY_HOUSE_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_house_budget_received)],
            BUY_HOUSE_PAY: [CallbackQueryHandler(buy_house_pay_chosen, pattern="^bhpay_")],
            BUY_HOUSE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_house_phone_received)],

            # Seller Car Steps
            SELL_CAR_MAKE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_make_received)],
            SELL_CAR_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_model_received)],
            SELL_CAR_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_price_received)],
            SELL_CAR_PAY: [CallbackQueryHandler(sell_car_pay_chosen, pattern="^spay_")],
            SELL_CAR_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, sell_car_phone_received)],
            SELL_CAR_PHOTO: [MessageHandler(filters.PHOTO, sell_car_photo_received)],

            GENERIC_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, generic_desc_received)],
        },
        fallbacks=[CommandHandler("start", start), cancel_filter],
    )

    app.add_handler(response_conv)
    app.add_handler(market_conv)

    print("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()
