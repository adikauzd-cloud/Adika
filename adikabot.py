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
        
        # Vendors Table
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

# ==============================================================================
# 3. DB HELPERS
# ==============================================================================
def register_vendor_db(chat_id, full_name, phone, vendor_type, document_id, is_verified=0):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        if DATABASE_URL:
            cursor.execute(f"""
                INSERT INTO vendors (chat_id, full_name, phone, vendor_type, document_id, is_verified)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}) RETURNING id
            """, (chat_id, full_name, phone, vendor_type, document_id, is_verified))
            v_id = cursor.fetchone()[0]
        else:
            cursor.execute(f"""
                INSERT INTO vendors (chat_id, full_name, phone, vendor_type, document_id, is_verified)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p})
            """, (chat_id, full_name, phone, vendor_type, document_id, is_verified))
            v_id = cursor.lastrowid
        return v_id
    except Exception as e:
        logging.error(f"Register vendor error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_vendor_by_chat_id(chat_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM vendors WHERE chat_id = {p}", (chat_id,))
        return cursor.fetchone()
    except Exception as e:
        logging.error(f"Get vendor error: {e}")
        return None
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
# 4. KEYBOARDS & STATES
# ==============================================================================
MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ መመዝገብ", "👤 መገለጫዬ"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]

# Flow States
FLOW_ROLE, FLOW_CAT, FLOW_CAR_TYPE, FLOW_CAR_PAYMENT, FLOW_DESC = range(5)
REG_V_TYPE, REG_V_NAME, REG_V_PHONE, REG_V_DOC = range(5, 9)
RESPONSE_DETAILS = 9

# ==============================================================================
# 5. HANDLERS
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

# ----- BUY / SELL FLOW WITH INLINE KEYBOARDS -----
async def start_buy_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    role_text = "👤 ባለቤት/ለራሱ" if query.data == "role_self" else "👨‍💼 ደላላ"
    context.user_data['user_role'] = role_text

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

    # መኪና ገዢ ከሆነ ፕሮፌሽናል Inline Form እናሳየዋለን
    if cat == "cat_car" and req_type == 'BUY':
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

    # ለሌሎች ወይም ለሻጭ
    if req_type == 'BUY':
        msg = "✍️ **የሚፈልጉትን ዕቃ/ቤት ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* «ቦሌ አካባቢ ባለ 2 መኝታ ቤት ኪራይ እስከ 40,000 ብር»"
    else:
        msg = (
            "📸✍️ **የሚሸጡትን/የሚያከራዩትን ንብረት ፎቶ እና ዝርዝር መረጃ አብረው ይላኩ፦**\n\n"
            "💡 *ማስታወሻ፦* ፎቶውን በሚልኩበት ጊዜ በሥሩ (Caption) ላይ የንብረቱን ዝርዝር መረጃ፣ ዋጋ እና የስልክ ቁጥርዎን ጽፈው ይላኩ።"
        )
    await query.edit_message_text(msg, parse_mode="Markdown")
    return FLOW_DESC

# --- CAR SPECIFIC INLINE STEPS ---
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

    pay_map = {
        "pay_cash": "ካሽ",
        "pay_bank": "ባንክ ብድር",
        "pay_any": "ማናቸውም"
    }
    context.user_data['car_payment'] = pay_map.get(query.data, "ካሽ")

    await query.edit_message_text(
        "✍️ **አሁን የመኪናውን ሞዴል፣ የባጀት መጠን እና የስልክ ቁጥርዎን ጽፈው ይላኩ፦**\n\n"
        "💡 *ምሳሌ፦* «ሱዙኪ ዲዛየር 2022 ወይም ቪትዝ፣ ባጀት እስከ 2.5 ሚሊዮን ብር፣ ስልክ፡ 0911XXXXXX»",
        parse_mode="Markdown"
    )
    return FLOW_DESC

async def save_listing_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    req_type = context.user_data.get('req_type', 'BUY')
    cat = context.user_data.get('category', 'General')
    role = context.user_data.get('user_role', 'ባለቤት')

    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    desc = update.message.caption if photo_id else update.message.text

    if not desc:
        await update.message.reply_text("❌ እባክዎ አስፈላጊውን መረጃ በጽሁፍ ያስገቡ!")
        return FLOW_DESC

    # በመኪና መስመር ከመጣ የተመረጡትን Inline አማራጮች ያቀናጃል
    car_info = ""
    if cat == "cat_car" and req_type == 'BUY':
        c_type = context.user_data.get('car_type', 'መኪና')
        c_pay = context.user_data.get('car_payment', 'ካሽ')
        car_info = f"🚘 **አይነት:** {c_type}\n💳 **ክፍያ:** {c_pay}\n"

    full_desc = f"[{role}]\n{car_info}{desc}"
    req_id = add_listing(user.id, user.first_name, req_type, cat, full_desc)

    if req_id:
        if req_type == 'BUY':
            title = "🔍 የገዢ ጥያቄ"
            action_kbd = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ አለኝ (ንብረቱ አለኝ)", callback_data=f"item_have_{req_id}_{user.id}"),
                    InlineKeyboardButton("❌ የለኝም", callback_data=f"item_nohave_{req_id}")
                ]
            ])
        else:
            title = "📢 የሻጭ/አካራይ ማስታወቂያ"
            action_kbd = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ እፈልገዋለሁ (ደንበኛ አለኝ)", callback_data=f"item_want_{req_id}_{user.id}"),
                    InlineKeyboardButton("❌ አልፈልገውም", callback_data=f"item_nowant_{req_id}")
                ]
            ])

        await update.message.reply_text(
            f"✅ **{title}ዎ በስኬት ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"👤 **ማንነት:** {role}\n"
            f"{car_info}"
            f"📝 **ዝርዝር:** {desc}\n\n"
            "🚀 ጥያቄዎ ለአቅራቢዎች ተልኳል፤ ምላሾች ሲኖሩ ይደርስዎታል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID:
            try:
                admin_msg = f"🔔 **አዲስ {title}!** (#REQ-{req_id})\n\n👤 **ላኪ:** {user.first_name} (@{user.username})\n🎭 **ማንነት:** {role}\n{car_info}📝 **መረጃ:**\n{desc}"
                if photo_id:
                    await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=photo_id, caption=admin_msg, reply_markup=action_kbd, parse_mode="Markdown")
                else:
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, reply_markup=action_kbd, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Admin notify error: {e}")
    else:
        await update.message.reply_text("❌ ጥያቄውን ማስመዝገብ አልተቻለም።")
    return ConversationHandler.END

# ----- OTHER HANDLERS (RESPONSE DETAILS & VENDOR) -----
async def handle_response_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    responder = update.effective_user
    target_user_id = context.user_data.get('target_user_id')
    req_id = context.user_data.get('target_req_id')
    action_type = context.user_data.get('action_type', 'have')

    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    text_content = update.message.caption if photo_id else update.message.text

    if not text_content and not photo_id:
        await update.message.reply_text("❌ እባክዎ መረጃውን በጽሁፍ ወይም ከፎቶ ጋር አብረው ይላኩ።")
        return RESPONSE_DETAILS

    if target_user_id:
        try:
            if action_type == 'have':
                header = f"🎉 **ከአቅራቢ/ደላላ የቀረበ ንብረት አማራጭ!** (#REQ-{req_id})\n\n👤 **አቅራቢ:** {responder.first_name} (@{responder.username})\n"
            else:
                header = f"🎉 **የሚሸጡትን ንብረት የሚፈልግ ደላላ/ገዢ ተገኝቷል!** (#REQ-{req_id})\n\n👤 **ደላላ/አቅራቢ:** {responder.first_name} (@{responder.username})\n"

            full_msg = f"{header}\n📝 **የቀረበ መረጃ እና የስልክ ቁጥር፦**\n{text_content}"

            if photo_id:
                await context.bot.send_photo(chat_id=target_user_id, photo=photo_id, caption=full_msg, parse_mode="Markdown")
            else:
                await context.bot.send_message(chat_id=target_user_id, text=full_msg, parse_mode="Markdown")

            await update.message.reply_text("✅ መረጃዎ እና ፎቶው ለደንበኛው በስኬት ተልኳል! አመሰግናለሁ።")
        except Exception as e:
            logging.error(f"Error sending response details: {e}")
            await update.message.reply_text("❌ መረጃውን ለደንበኛው መላክ አልተቻለም።")
    return ConversationHandler.END

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("item_have_"):
        parts = data.split("_")
        context.user_data['target_req_id'] = parts[2]
        context.user_data['target_user_id'] = int(parts[3])
        context.user_data['action_type'] = 'have'
        await query.message.reply_text(
            "✍️ **እባክዎን ያለዎትን ንብረት ዝርዝር መረጃ፣ ዋጋ፣ የእርስዎን የስልክ ቁጥር እና የንብረቱን ፎቶ አሁን ይላኩ፦**",
            parse_mode="Markdown"
        )
        return RESPONSE_DETAILS

    elif data.startswith("item_want_"):
        parts = data.split("_")
        context.user_data['target_req_id'] = parts[2]
        context.user_data['target_user_id'] = int(parts[3])
        context.user_data['action_type'] = 'want'
        await query.message.reply_text(
            "✍️ **እባክዎን ከዚህ ንብረት ጋር የሚጣጣም ያለዎትን የገዢ መረጃ፣ የእርስዎን የስልክ ቁጥር እና አስፈላጊ ፎቶ አሁን ይላኩ፦**",
            parse_mode="Markdown"
        )
        return RESPONSE_DETAILS

# ==============================================================================
# 6. MAIN FUNCTION
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    
    # Response details conversation
    response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^(item_have_|item_want_)")],
        states={
            RESPONSE_DETAILS: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_response_details)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    # Market Buyer/Seller Conversation
    market_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^(🔍 መግዛት / መከራየት|መግዛት / መከራየት)$"), start_buy_flow),
            MessageHandler(filters.Regex("^(📢 መሸጥ / ማከራየት|መሸጥ / ማከራየት)$"), start_sell_flow)
        ],
        states={
            FLOW_ROLE: [CallbackQueryHandler(flow_role_chosen, pattern="^role_")],
            FLOW_CAT: [CallbackQueryHandler(flow_category_chosen, pattern="^cat_")],
            FLOW_CAR_TYPE: [CallbackQueryHandler(flow_car_type_chosen, pattern="^cartype_")],
            FLOW_CAR_PAYMENT: [CallbackQueryHandler(flow_car_payment_chosen, pattern="^pay_")],
            FLOW_DESC: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, save_listing_request)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(response_conv)
    app.add_handler(market_conv)
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()
