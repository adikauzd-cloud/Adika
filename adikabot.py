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
# 0. FLASK WEB SERVER (ለ Render Web Service የሚያስፈልግ)
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
# 2. DATABASE INITIALIZATION (PostgreSQL / SQLite)
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
        
        # 1. የአቅራቢዎች / ደላሎች ሰንጠረዥ (Vendors Table)
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vendors (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    vendor_type TEXT NOT NULL,
                    is_verified INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vendors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    vendor_type TEXT NOT NULL,
                    is_verified INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

        # 2. የገዢዎች ጥያቄ ሰንጠረዥ (Requests Table)
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS buyer_requests (
                    id SERIAL PRIMARY KEY,
                    buyer_chat_id BIGINT NOT NULL,
                    buyer_name TEXT,
                    category TEXT NOT NULL,
                    seller_preference TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS buyer_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    buyer_chat_id INTEGER NOT NULL,
                    buyer_name TEXT,
                    category TEXT NOT NULL,
                    seller_preference TEXT NOT NULL,
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
# 3. DATABASE HELPER FUNCTIONS
# ==============================================================================
def register_vendor_db(chat_id, full_name, phone, vendor_type):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"""
            INSERT INTO vendors (chat_id, full_name, phone, vendor_type)
            VALUES ({p}, {p}, {p}, {p})
        """, (chat_id, full_name, phone, vendor_type))
        return True
    except Exception as e:
        logging.error(f"Register vendor error: {e}")
        return False
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

def add_buyer_request(buyer_chat_id, buyer_name, category, seller_preference, description):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        if DATABASE_URL:
            cursor.execute(f"""
                INSERT INTO buyer_requests (buyer_chat_id, buyer_name, category, seller_preference, description)
                VALUES ({p}, {p}, {p}, {p}, {p}) RETURNING id
            """, (buyer_chat_id, buyer_name, category, seller_preference, description))
            req_id = cursor.fetchone()[0]
        else:
            cursor.execute(f"""
                INSERT INTO buyer_requests (buyer_chat_id, buyer_name, category, seller_preference, description)
                VALUES ({p}, {p}, {p}, {p}, {p})
            """, (buyer_chat_id, buyer_name, category, seller_preference, description))
            req_id = cursor.lastrowid
        return req_id
    except Exception as e:
        logging.error(f"Add buyer request error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def verify_vendor_db(vendor_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"UPDATE vendors SET is_verified = 1 WHERE id = {p}", (vendor_id,))
        return True
    except Exception as e:
        logging.error(f"Verify vendor error: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 4. KEYBOARDS & CONSTANTS
# ==============================================================================
MAIN_KEYBOARD = [
    ["🔍 ዕቃ/ቤት/መኪና እፈልጋለሁ", "📝 እንደ አቅራቢ መመዝገብ"],
    ["👤 መገለጫዬ", "📞 ድጋፍ"],
    ["🏠 ዋና ገጽ"]
]

# States
REQ_CATEGORY, REQ_SELLER_PREF, REQ_DETAILS = range(3)
REG_V_TYPE, REG_V_NAME, REG_V_PHONE = range(3, 6)

# ==============================================================================
# 5. HANDLERS
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
        "የሀገሪቱ ታላቁ የመኪና፣ የቤት እና የንብረት ገበያ ማዕከል።\n\n"
        "እባክዎን ከታች ካሉት አማራጮች አንዱን ይምረጡ፡"
    )
    await update.message.reply_text(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )
    return ConversationHandler.END

# ----- የገዢ ጥያቄ ሂደት (Buyer Flow) -----
async def start_buyer_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🚗 መኪና ፍለጋ (Auto)", callback_data="cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ ፍለጋ (Property)", callback_data="cat_house")],
        [InlineKeyboardButton("🏢 ንግድ ቤት / ቢሮ (Commercial)", callback_data="cat_commercial")],
    ]
    await update.message.reply_text(
        "🎯 **የሚፈልጉትን አገልግሎት ምድብ ይምረጡ፡**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return REQ_CATEGORY

async def category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['category'] = query.data
    keyboard = [
        [InlineKeyboardButton("🏢 ከሪል እስቴት/ሾውሩም", callback_data="pref_company")],
        [InlineKeyboardButton("👤 ከባለቤቱ በቀጥታ", callback_data="pref_owner")],
        [InlineKeyboardButton("👨‍💼 ከተረጋገጡ ደላሎች", callback_data="pref_broker")],
        [InlineKeyboardButton("🌐 ከሁሉም አቅራቢዎች", callback_data="pref_all")]
    ]
    await query.edit_message_text(
        "📌 **ጥያቄዎ ለማን እንዲደርስ ይፈልጋሉ?**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return REQ_SELLER_PREF

async def seller_pref_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['seller_pref'] = query.data
    await query.edit_message_text(
        "✍️ **አሁን የሚፈልጉትን ዝርዝር ፍላጎት ይጻፉልን፡**\n\n"
        "💡 *ምሳሌ፡* «አዲስ አበባ ቦሌ አካባቢ ባለ 2 መኝታ ቤት ኪራይ እስከ 40,000 ብር»\n"
        "ወይም «2020 Model Vitz መኪና በ2 ሚሊዮን ብር ክልል»",
        parse_mode="Markdown"
    )
    return REQ_DETAILS

async def save_buyer_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    desc = update.message.text
    cat = context.user_data.get('category', 'General')
    pref = context.user_data.get('seller_pref', 'All')

    req_id = add_buyer_request(user.id, user.first_name, cat, pref, desc)
    
    if req_id:
        await update.message.reply_text(
            f"✅ **ጥያቄዎ በ Adika Marketplace ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"📝 **ጥያቄዎ:** {desc}\n\n"
            "🚀 ለአቅራቢዎች ተልኳል፤ አማራጮች ሲኖሩ ይደርስዎታል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        # ለአድሚን ማሳወቅ
        if ADMIN_CHAT_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"🔔 **አዲስ የገዢ ጥያቄ!** (#REQ-{req_id})\n\n👤 {user.first_name} (@{user.username})\n📝 {desc}"
                )
            except Exception as e:
                logging.error(f"Admin notify error: {e}")
    else:
        await update.message.reply_text("❌ ጥያቄውን ማስመዝገብ አልተቻለም።")
        
    return ConversationHandler.END

# ----- የአቅራቢ ምዝገባ ሂደት (Vendor Registration) -----
async def start_vendor_reg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    existing = get_vendor_by_chat_id(user_id)
    if existing:
        await update.message.reply_text(
            f"✅ አስቀድመው ተመዝግበዋል!\n\n👤 {existing[2]}\n📞 {existing[3]}\n🏢 {existing[4]}\n"
            f"📊 ሁኔታ: {'✅ የተረጋገጠ' if existing[5] else '⏳ በመጠበቅ ላይ'}"
        )
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("🏢 ሪል እስቴት አልሚ", callback_data="vtype_realestate")],
        [InlineKeyboardButton("🏪 የመኪና መሸጫ (Showroom)", callback_data="vtype_showroom")],
        [InlineKeyboardButton("👨‍💼 የተመዘገበ ደላላ", callback_data="vtype_broker")],
        [InlineKeyboardButton("👤 የግል ባለቤት", callback_data="vtype_owner")]
    ]
    await update.message.reply_text(
        "📋 **የአቅራቢነት ምዝገባ**\n\nበየትኛው ዘርፍ መመዝገብ ይፈልጋሉ?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return REG_V_TYPE

async def vendor_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data['vendor_type'] = query.data
    await query.edit_message_text("✍️ **እባክዎን የድርጅትዎን ወይም የእርስዎን ሙሉ ስም ያስገቡ፡**")
    return REG_V_NAME

async def vendor_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['vendor_name'] = update.message.text
    await update.message.reply_text("📞 **እባክዎን የስልክ ቁጥርዎን ያስገቡ፡**")
    return REG_V_PHONE

async def vendor_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    phone = update.message.text
    name = context.user_data.get('vendor_name')
    v_type = context.user_data.get('vendor_type')

    if register_vendor_db(user.id, name, phone, v_type):
        await update.message.reply_text(
            "🎉 **ምዝገባዎ በስኬት ተጠናቋል!**\n\nአካውንትዎ እንደተረጋገጠ ማሳወቂያ ይደርስዎታል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        if ADMIN_CHAT_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"🆕 **አዲስ አቅራቢ ተመዝግቧል!**\n\n👤 {name}\n📞 {phone}\n🏷️ {v_type}"
                )
            except Exception as e:
                logging.error(f"Admin notify error: {e}")
    else:
        await update.message.reply_text("❌ ምዝገባው አልተሳካም። እባክዎ እንደገና ይሞክሩ።")

    return ConversationHandler.END

# ==============================================================================
# 6. MAIN FUNCTION
# ==============================================================================
def main():
    init_db()
    
    # Render Port Binding እንዲሰራ Flask በ Background ማስነሳት
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    # ገዢዎች ጥያቄ ማቅረቢያ Conversational Handler
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 ዕቃ/ቤት/መኪና እፈልጋለሁ$"), start_buyer_request)],
        states={
            REQ_CATEGORY: [CallbackQueryHandler(category_chosen, pattern="^cat_")],
            REQ_SELLER_PREF: [CallbackQueryHandler(seller_pref_chosen, pattern="^pref_")],
            REQ_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_buyer_request)],
        },
        fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start)],
    )

    # አቅራቢዎች መመዝገቢያ Conversational Handler
    vendor_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ መመዝገብ$"), start_vendor_reg)],
        states={
            REG_V_TYPE: [CallbackQueryHandler(vendor_type_chosen, pattern="^vtype_")],
            REG_V_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, vendor_name_received)],
            REG_V_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, vendor_phone_received)],
        },
        fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start)],
    )

    # Handlers ማያያዝ
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start))
    app.add_handler(buyer_conv)
    app.add_handler(vendor_conv)

    # Error Handler
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logging.error(f"Update {update} caused error {context.error}")

    app.add_error_handler(error_handler)

    print("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()
