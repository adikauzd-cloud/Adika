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
        
        # 1. Vendors Table
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

        # 2. Marketplace Listings Table
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

# ==============================================================================
# 3. DATABASE HELPER FUNCTIONS
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

def get_pending_vendors():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vendors WHERE is_verified = 0 AND is_active = 1 ORDER BY registered_at DESC")
        return cursor.fetchall()
    except Exception as e:
        logging.error(f"Get pending vendors error: {e}")
        return []
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
# 4. KEYBOARDS & CONSTANTS
# ==============================================================================
MAIN_KEYBOARD = [
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ መመዝገብ", "👤 መገለጫዬ"],
    ["📞 ድጋፍ", "🏠 ዋና ገጽ"]
]

FLOW_CAT, FLOW_DESC = range(2)
REG_V_TYPE, REG_V_NAME, REG_V_PHONE, REG_V_DOC = range(2, 6)
RESPONSE_DETAILS = 6

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

# ----- PROFILE & HELP -----
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    
    vendor = get_vendor_by_chat_id(user_id)
    if vendor:
        is_verified = vendor[6] if len(vendor) > 6 else 0
        status_text = "✅ የተረጋገጠ አቅራቢ" if is_verified else "⏳ ማረጋገጫ በመጠበቅ ላይ"
        text = (
            f"👤 **የአቅራቢ መገለጫ**\n\n"
            f"📛 **ስም/ድርጅት:** {vendor[2]}\n"
            f"📞 **ስልክ ቁጥር:** {vendor[3]}\n"
            f"🏷️ **የአቅራቢ አይነት:** {vendor[4]}\n"
            f"📊 **ሁኔታ:** {status_text}\n"
        )
    else:
        text = (
            f"👤 **የተጠቃሚ መገለጫ**\n\n"
            f"👋 **ስም:** {user_name}\n"
            f"🆔 **ID:** `{user_id}`\n\n"
            f"💡 እስካሁን እንደ አቅራቢ አልተመዘገቡም። ለመመዝገብ **«📝 እንደ አቅራቢ መመዝገብ»** የሚለውን ቁልፍ ይጫኑ።"
        )
    await update.message.reply_text(text, parse_mode="Markdown")
    return ConversationHandler.END

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📞 **Adika Marketplace የድጋፍ ማዕከል**\n\n"
        "ጥያቄ፣ አስተያየት ወይም እገዛ ከፈለጉ በቴሌግራም አድራሻችን ያግኙን፦\n"
        "💬 **አድሚን:** @AdikaSupport\n"
        "🌐 **ዌብሳይት:** AdikaCar.com"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")
    return ConversationHandler.END

# ----- BUY / SELL FLOW -----
async def start_buy_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['req_type'] = 'BUY'
    keyboard = [
        [InlineKeyboardButton("🚗 መኪና ፍለጋ (Auto)", callback_data="cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ ፍለጋ (Property)", callback_data="cat_house")],
        [InlineKeyboardButton("🏢 ንግድ ቤት / ቢሮ (Commercial)", callback_data="cat_commercial")],
    ]
    await update.message.reply_text(
        "🔍 **ለመግዛት/ለመከራየት የሚፈልጉትን ምድብ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return FLOW_CAT

async def start_sell_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['req_type'] = 'SELL'
    keyboard = [
        [InlineKeyboardButton("🚗 መኪና ለመሸጥ/ለማከራየት", callback_data="cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ ለመሸጥ/ለማከራየት", callback_data="cat_house")],
        [InlineKeyboardButton("🏢 ንግድ ቤት / ቢሮ", callback_data="cat_commercial")],
    ]
    await update.message.reply_text(
        "📢 **ለመሸጥ/ለማከራየት የሚፈልጉትን ምድብ ይምረጡ፦**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return FLOW_CAT

async def flow_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['category'] = query.data
    req_type = context.user_data.get('req_type', 'BUY')
    
    if req_type == 'BUY':
        msg = "✍️ **የሚፈልጉትን ዕቃ/ቤት/መኪና ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* «ቦሌ አካባቢ ባለ 2 መኝታ ቤት ኪራይ እስከ 40,000 ብር»"
    else:
        msg = "✍️ **የሚሸጡትን/የሚያከራዩትን ንብረት ዝርዝር መረጃ፣ ዋጋ እና ስልክ ቁጥር ያስገቡ፦**"
        
    await query.edit_message_text(msg, parse_mode="Markdown")
    return FLOW_DESC

async def save_listing_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    desc = update.message.text
    req_type = context.user_data.get('req_type', 'BUY')
    cat = context.user_data.get('category', 'General')

    req_id = add_listing(user.id, user.first_name, req_type, cat, desc)
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
            title = "📢 የሻጭ ማስታወቂያ"
            action_kbd = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ እፈልገዋለሁ (ደንበኛ አለኝ)", callback_data=f"item_want_{req_id}_{user.id}"),
                    InlineKeyboardButton("❌ አልፈልገውም", callback_data=f"item_nowant_{req_id}")
                ]
            ])

        await update.message.reply_text(
            f"✅ **{title}ዎ በስኬት ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"📝 **ዝርዝር:** {desc}\n\n"
            "🚀 ጥያቄዎ ለአቅራቢዎች ተልኳል፤ ምላሾች ሲኖሩ ይደርስዎታል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        if ADMIN_CHAT_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"🔔 **አዲስ {title}!** (#REQ-{req_id})\n\n👤 **ደብዳቤ ላኪ:** {user.first_name} (@{user.username})\n📝 **መረጃ:** {desc}",
                    reply_markup=action_kbd,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"Admin notify error: {e}")
    else:
        await update.message.reply_text("❌ ጥያቄውን ማስመዝገብ አልተቻለም።")
    return ConversationHandler.END

# ----- RESPONSE DETAILS HANDLING (WITH PHOTO & PHONE SUPPORT) -----
async def handle_response_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    responder = update.effective_user
    target_user_id = context.user_data.get('target_user_id')
    req_id = context.user_data.get('target_req_id')
    action_type = context.user_data.get('action_type', 'have')

    # ፎቶ ወይም ጽሁፍ መኖሩን ማረጋገጥ
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

            # ፎቶ ካለ ከነ ፎቶው፣ ከሌለ በጽሁፍ መላክ
            if photo_id:
                await context.bot.send_photo(chat_id=target_user_id, photo=photo_id, caption=full_msg, parse_mode="Markdown")
            else:
                await context.bot.send_message(chat_id=target_user_id, text=full_msg, parse_mode="Markdown")

            await update.message.reply_text("✅ መረጃዎ እና ፎቶው ለደንበኛው በስኬት ተልኳል! አመሰግናለሁ።")
        except Exception as e:
            logging.error(f"Error sending response details: {e}")
            await update.message.reply_text("❌ መረጃውን ለደንበኛው መላክ አልተቻለም።")
    else:
        await update.message.reply_text("❌ የደንበኛ መረጃ አልተገኘም።")

    return ConversationHandler.END

# ----- VENDOR REGISTRATION -----
async def start_vendor_reg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    existing = get_vendor_by_chat_id(user_id)
    if existing:
        is_verified = existing[6] if len(existing) > 6 else 0
        await update.message.reply_text(
            f"✅ አስቀድመው ተመዝግበዋል!\n\n👤 {existing[2]}\n📞 {existing[3]}\n🏢 {existing[4]}\n"
            f"📊 ሁኔታ: {'✅ የተረጋገጠ' if is_verified else '⏳ በመጠበቅ ላይ'}"
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
    await query.edit_message_text("✍️ **እባክዎን የድርጅትዎን ወይም የእርስዎን ሙሉ ስም ያስገቡ፦**")
    return REG_V_NAME

async def vendor_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['vendor_name'] = update.message.text
    await update.message.reply_text("📞 **እባክዎን የስልክ ቁጥርዎን ያስገቡ፦**")
    return REG_V_PHONE

async def vendor_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['vendor_phone'] = update.message.text
    await update.message.reply_text(
        "📄 **እባክዎን የመታወቂያ ወይም የንግድ ፈቃድ ፎቶ/ፋይል ይላኩ፦**",
        parse_mode="Markdown"
    )
    return REG_V_DOC

async def vendor_doc_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    doc_id = update.message.photo[-1].file_id if update.message.photo else (update.message.document.file_id if update.message.document else None)
    
    if not doc_id:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ፎቶ ወይም ፋይል ይላኩ!")
        return REG_V_DOC

    name = context.user_data.get('vendor_name')
    phone = context.user_data.get('vendor_phone')
    v_type = context.user_data.get('vendor_type')

    v_id = register_vendor_db(user.id, name, phone, v_type, doc_id)
    if v_id:
        await update.message.reply_text(
            "🎉 **ምዝገባዎ በስኬት ተጠናቋል!**\n\nአካውንትዎ በአድሚን ተመርምሮ እንደተረጋገጠ ማሳወቂያ ይደርስዎታል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        if ADMIN_CHAT_ID:
            try:
                admin_kbd = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ ፈቅድ (Approve)", callback_data=f"admin_approve_{v_id}"),
                        InlineKeyboardButton("❌ ውድቅ አድርግ", callback_data=f"admin_reject_{v_id}")
                    ]
                ])
                admin_text = f"🆕 **አዲስ የአቅራቢ ምዝገባ!** (#ID-{v_id})\n\n👤 **ስም:** {name}\n📞 **ስልክ:** {phone}\n🏷️ **ዘርፍ:** {v_type}"
                if update.message.photo:
                    await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=doc_id, caption=admin_text, reply_markup=admin_kbd, parse_mode="Markdown")
                else:
                    await context.bot.send_document(chat_id=ADMIN_CHAT_ID, document=doc_id, caption=admin_text, reply_markup=admin_kbd, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Admin notify error: {e}")
    else:
        await update.message.reply_text("❌ ምዝገባው አልተሳካም። እባክዎ እንደገና ይሞክሩ።")

    return ConversationHandler.END

# ==============================================================================
# 6. ADMIN COMMANDS & CALLBACKS
# ==============================================================================
async def admin_add_vendor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:
        return

    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("💡 **አጠቃቀም፦** `/add_vendor 0911XXXXXX የስም ዝርዝር`", parse_mode="Markdown")
            return
            
        phone = args[0]
        full_name = " ".join(args[1:])
        
        v_id = register_vendor_db(chat_id=None, full_name=full_name, phone=phone, vendor_type="Direct Broker", document_id="ADMIN_ADDED", is_verified=1)
        if v_id:
            await update.message.reply_text(f"✅ **ደላላ {full_name} ({phone}) በስኬት ተመዝግቧል!**", parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ ማስመዝገብ አልተቻለም (ምናልባት ስልኩ አስቀድሞ ተመዝግቧል)።")
    except Exception as e:
        await update.message.reply_text(f"❌ ስህተት፦ {e}")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ ይህ ትእዛዝ ለአድሚን ብቻ የተፈቀደ ነው!")
        return

    pending = get_pending_vendors()
    if not pending:
        await update.message.reply_text("✅ ምንም ያልተረጋገጠ አቅራቢ የለም።")
        return

    await update.message.reply_text(f"📋 **ያልተረጋገጡ አቅራቢዎች ብዛት:** {len(pending)}")
    for v in pending:
        v_id, chat_id, name, phone, v_type, doc_id, is_ver, is_act, reg_at = v
        admin_kbd = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ ፈቅድ", callback_data=f"admin_approve_{v_id}"),
                InlineKeyboardButton("❌ ውድቅ አድርግ", callback_data=f"admin_reject_{v_id}")
            ]
        ])
        caption = f"🆔 **ID:** {v_id}\n👤 **ስም:** {name}\n📞 **ስልክ:** {phone}\n🏷️ **ዘርፍ:** {v_type}"
        try:
            if doc_id and doc_id != "ADMIN_ADDED":
                await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=doc_id, caption=caption, reply_markup=admin_kbd, parse_mode="Markdown")
            else:
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=caption, reply_markup=admin_kbd, parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=caption, reply_markup=admin_kbd, parse_mode="Markdown")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # Admin approval callbacks
    if data.startswith("admin_approve_"):
        v_id = int(data.split("_")[2])
        if verify_vendor_db(v_id):
            await query.edit_message_caption(caption=f"✅ **አቅራቢው በስኬት ተረጋግጧል!**", parse_mode="Markdown")
    elif data.startswith("admin_reject_"):
        await query.edit_message_caption(caption=f"❌ **ምዝገባው ውድቅ ተደርጓል!**", parse_mode="Markdown")
        
    # Buyer Request Reactions (ለገዢ፡ አለኝ / የለኝም)
    elif data.startswith("item_have_"):
        parts = data.split("_")
        context.user_data['target_req_id'] = parts[2]
        context.user_data['target_user_id'] = int(parts[3])
        context.user_data['action_type'] = 'have'
        await query.message.reply_text(
            "✍️ **እባክዎን ያለዎትን ንብረት ዝርዝር መረጃ፣ ዋጋ፣ የእርስዎን የስልክ ቁጥር እና የንብረቱን ፎቶ አሁን ይላኩ፦**\n\n"
            "💡 *(ማስታወሻ፡ ፎቶ ካለዎት ከነጽሁፉ አብረው መላክ ይችላሉ)*",
            parse_mode="Markdown"
        )
        return RESPONSE_DETAILS

    elif data.startswith("item_nohave_"):
        await query.edit_message_text(text=f"{query.message.text}\n\n*(❌ የለኝም ብለው መልሰዋል)*")

    # Seller Request Reactions (ለሻጭ፡ እፈልገዋለሁ / አልፈልገውም)
    elif data.startswith("item_nowant_"):
        await query.edit_message_text(text=f"{query.message.text}\n\n*(❌ አልፈልገውም ብለው መልሰዋል)*")

    elif data.startswith("item_want_"):
        parts = data.split("_")
        context.user_data['target_req_id'] = parts[2]
        context.user_data['target_user_id'] = int(parts[3])
        context.user_data['action_type'] = 'want'
        await query.message.reply_text(
            "✍️ **እባክዎን ከዚህ ንብረት ጋር የሚጣጣም ያለዎትን የገዢ መረጃ፣ የእርስዎን የስልክ ቁጥር እና አስፈላጊ ፎቶ/ማብራሪያ አሁን ይላኩ፦**",
            parse_mode="Markdown"
        )
        return RESPONSE_DETAILS

# ==============================================================================
# 7. MAIN FUNCTION
# ==============================================================================
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    # Global Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("add_vendor", admin_add_vendor_cmd))
    
    app.add_handler(MessageHandler(filters.Regex("^(👤 መገለጫዬ|መገለጫዬ)$"), show_profile))
    app.add_handler(MessageHandler(filters.Regex("^(📞 ድጋፍ|ድጋፍ)$"), show_help))
    app.add_handler(MessageHandler(filters.Regex("^(🏠 ዋና ገጽ|ዋና ገጽ)$"), start))

    # Response Details Conversation (መረጃ እና ፎቶ ማስገቢያ)
    response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(callback_handler, pattern="^(item_have_|item_want_)")],
        states={
            RESPONSE_DETAILS: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handle_response_details)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    # Buyer / Seller Conversation
    market_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^(🔍 መግዛት / መከራየት|መግዛት / መከራየት)$"), start_buy_flow),
            MessageHandler(filters.Regex("^(📢 መሸጥ / ማከራየት|መሸጥ / ማከራየት)$"), start_sell_flow)
        ],
        states={
            FLOW_CAT: [CallbackQueryHandler(flow_category_chosen, pattern="^cat_")],
            FLOW_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_listing_request)],
        },
        fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^(🏠 ዋና ገጽ|ዋና ገጽ)$"), start)],
    )

    # Vendor Conversation
    vendor_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^(📝 እንደ አቅራቢ መመዝገብ|እንደ አቅራቢ መመዝገብ)$"), start_vendor_reg)],
        states={
            REG_V_TYPE: [CallbackQueryHandler(vendor_type_chosen, pattern="^vtype_")],
            REG_V_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, vendor_name_received)],
            REG_V_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, vendor_phone_received)],
            REG_V_DOC: [MessageHandler(filters.PHOTO | filters.Document.ALL, vendor_doc_received)],
        },
        fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^(🏠 ዋና ገጽ|ዋና ገጽ)$"), start)],
    )

    app.add_handler(response_conv)
    app.add_handler(market_conv)
    app.add_handler(vendor_conv)
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()
