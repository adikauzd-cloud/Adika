import logging
import os
import threading
import psycopg2
import requests
import json
import base64
import math
from datetime import datetime, timedelta
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
    return "✅ Broker Connect Bot በስኬት እየሰራ ይገኛል!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# ==============================================================================
# 1. CONFIGURATION & DATABASE
# ==============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN environment variable ውስጥ አልተገኘም።")

LOGO_FILE_ID = "AgACAgQAAxkBAAEszTBqZGhpfKNE12Y948HvU4JhQHfZrQAC0g1rG4xKIFPy4FmrrNxjRAEAAwIAA3gAAz0E"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# ==============================================================================
# 2. DATABASE CONNECTION & INITIALIZATION
# ==============================================================================

def get_db_connection():
    if DATABASE_URL:
        db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        return conn
    else:
        import sqlite3
        return sqlite3.connect("broker_bot.db")

def get_placeholder():
    return "%s" if DATABASE_URL else "?"

def init_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Brokers table
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS brokers (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    email TEXT,
                    broker_type TEXT NOT NULL,
                    experience_years INTEGER DEFAULT 0,
                    location TEXT NOT NULL,
                    is_verified INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS brokers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    email TEXT,
                    broker_type TEXT NOT NULL,
                    experience_years INTEGER DEFAULT 0,
                    location TEXT NOT NULL,
                    is_verified INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        # Client requests table
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS client_requests (
                    id SERIAL PRIMARY KEY,
                    client_chat_id BIGINT NOT NULL,
                    client_name TEXT,
                    request_type TEXT NOT NULL,
                    description TEXT,
                    budget TEXT,
                    location TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS client_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_chat_id INTEGER NOT NULL,
                    client_name TEXT,
                    request_type TEXT NOT NULL,
                    description TEXT,
                    budget TEXT,
                    location TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        # Broker connections table
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broker_connections (
                    id SERIAL PRIMARY KEY,
                    request_id INTEGER NOT NULL,
                    broker_id INTEGER NOT NULL,
                    client_chat_id BIGINT NOT NULL,
                    broker_chat_id BIGINT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (request_id) REFERENCES client_requests (id),
                    FOREIGN KEY (broker_id) REFERENCES brokers (id)
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broker_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id INTEGER NOT NULL,
                    broker_id INTEGER NOT NULL,
                    client_chat_id INTEGER NOT NULL,
                    broker_chat_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'pending',
                    connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (request_id) REFERENCES client_requests (id),
                    FOREIGN KEY (broker_id) REFERENCES brokers (id)
                )
            """)
        
        # Search history table
        if DATABASE_URL:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_history (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    search_term TEXT NOT NULL,
                    search_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    search_term TEXT NOT NULL,
                    search_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        if DATABASE_URL:
            conn.commit()
        logging.info("✅ Database initialized successfully")
        
    except Exception as e:
        logging.error(f"Database initialization error: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 3. DATABASE HELPER FUNCTIONS
# ==============================================================================

# ========== BROKER FUNCTIONS ==========
def register_broker_db(chat_id, full_name, phone, email, broker_type, experience_years, location):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        if DATABASE_URL:
            cursor.execute(f"""
                INSERT INTO brokers (chat_id, full_name, phone, email, broker_type, experience_years, location, is_verified)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, 0)
                RETURNING id
            """, (chat_id, full_name, phone, email, broker_type, experience_years, location))
            broker_id = cursor.fetchone()[0]
            conn.commit()
        else:
            cursor.execute(f"""
                INSERT INTO brokers (chat_id, full_name, phone, email, broker_type, experience_years, location, is_verified)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """, (chat_id, full_name, phone, email, broker_type, experience_years, location))
            broker_id = cursor.lastrowid
        
        logging.info(f"✅ Broker registered: {full_name} (ID: {broker_id})")
        return broker_id
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Register broker error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_broker_by_chat_id(chat_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM brokers WHERE chat_id = {p} AND is_active = 1", (chat_id,))
        row = cursor.fetchone()
        return row
    except Exception as e:
        logging.error(f"Get broker error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_broker_by_id(broker_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM brokers WHERE id = {p} AND is_active = 1", (broker_id,))
        row = cursor.fetchone()
        return row
    except Exception as e:
        logging.error(f"Get broker by ID error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_all_brokers():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM brokers WHERE is_active = 1 AND is_verified = 1 ORDER BY registered_at DESC")
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logging.error(f"Get all brokers error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_brokers_by_type(broker_type):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM brokers WHERE broker_type = {p} AND is_active = 1 AND is_verified = 1", (broker_type,))
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logging.error(f"Get brokers by type error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_pending_brokers():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM brokers WHERE is_verified = 0 AND is_active = 1 ORDER BY registered_at DESC")
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logging.error(f"Get pending brokers error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def verify_broker_db(broker_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"UPDATE brokers SET is_verified = 1 WHERE id = {p}", (broker_id,))
        if DATABASE_URL:
            conn.commit()
        logging.info(f"✅ Broker {broker_id} verified")
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Verify broker error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def delete_broker_db(broker_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"UPDATE brokers SET is_active = 0 WHERE id = {p}", (broker_id,))
        if DATABASE_URL:
            conn.commit()
        logging.info(f"✅ Broker {broker_id} deleted")
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Delete broker error: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ========== REQUEST FUNCTIONS ==========
def add_client_request(client_chat_id, client_name, request_type, description, budget, location):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        if DATABASE_URL:
            cursor.execute(f"""
                INSERT INTO client_requests (client_chat_id, client_name, request_type, description, budget, location)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p})
                RETURNING id
            """, (client_chat_id, client_name, request_type, description, budget, location))
            request_id = cursor.fetchone()[0]
            conn.commit()
        else:
            cursor.execute(f"""
                INSERT INTO client_requests (client_chat_id, client_name, request_type, description, budget, location)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (client_chat_id, client_name, request_type, description, budget, location))
            request_id = cursor.lastrowid
        
        logging.info(f"✅ Request added: {request_type} (ID: {request_id})")
        return request_id
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Add request error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_request_by_id(request_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM client_requests WHERE id = {p}", (request_id,))
        row = cursor.fetchone()
        return row
    except Exception as e:
        logging.error(f"Get request error: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_pending_requests():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM client_requests WHERE status = 'pending' ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logging.error(f"Get pending requests error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def update_request_status(request_id, status):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"UPDATE client_requests SET status = {p} WHERE id = {p}", (status, request_id))
        if DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Update request status error: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ========== CONNECTION FUNCTIONS ==========
def add_connection(request_id, broker_id, client_chat_id, broker_chat_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        
        cursor.execute(f"""
            INSERT INTO broker_connections (request_id, broker_id, client_chat_id, broker_chat_id)
            VALUES ({p}, {p}, {p}, {p})
        """, (request_id, broker_id, client_chat_id, broker_chat_id))
        
        cursor.execute(f"UPDATE client_requests SET status = 'connected' WHERE id = {p}", (request_id,))
        
        if DATABASE_URL:
            conn.commit()
        logging.info(f"✅ Connection added: Request {request_id} -> Broker {broker_id}")
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Add connection error: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_connections_by_broker(broker_chat_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"""
            SELECT bc.*, cr.request_type, cr.description, cr.location
            FROM broker_connections bc
            JOIN client_requests cr ON bc.request_id = cr.id
            WHERE bc.broker_chat_id = {p}
            ORDER BY bc.connected_at DESC
        """, (broker_chat_id,))
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logging.error(f"Get connections error: {e}")
        return []
    finally:
        if conn:
            conn.close()

def get_connections_by_client(client_chat_id):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"""
            SELECT bc.*, b.full_name, b.phone, b.broker_type, b.location
            FROM broker_connections bc
            JOIN brokers b ON bc.broker_id = b.id
            WHERE bc.client_chat_id = {p}
            ORDER BY bc.connected_at DESC
        """, (client_chat_id,))
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logging.error(f"Get connections error: {e}")
        return []
    finally:
        if conn:
            conn.close()

# ========== SEARCH HISTORY ==========
def save_search_history(user_id, search_term):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"""
            INSERT INTO search_history (user_id, search_term)
            VALUES ({p}, {p})
        """, (user_id, search_term))
        if DATABASE_URL:
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Save search history error: {e}")
    finally:
        if conn:
            conn.close()

def get_user_search_history(user_id, limit=10):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"""
            SELECT search_term, search_date FROM search_history 
            WHERE user_id = {p} ORDER BY search_date DESC LIMIT {p}
        """, (user_id, limit))
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logging.error(f"Get search history error: {e}")
        return []
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 4. STATISTICS FUNCTIONS
# ==============================================================================

def get_bot_statistics():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM brokers")
        total_brokers = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM brokers WHERE is_verified = 1")
        verified_brokers = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM brokers WHERE is_verified = 0")
        pending_brokers = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM client_requests")
        total_requests = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM client_requests WHERE status = 'pending'")
        pending_requests = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM broker_connections")
        total_connections = cursor.fetchone()[0]
        return {
            'total_brokers': total_brokers,
            'verified_brokers': verified_brokers,
            'pending_brokers': pending_brokers,
            'total_requests': total_requests,
            'pending_requests': pending_requests,
            'total_connections': total_connections
        }
    except Exception as e:
        logging.error(f"Get statistics error: {e}")
        return {}
    finally:
        if conn:
            conn.close()

def get_top_brokers(limit=5):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT b.id, b.full_name, b.broker_type, COUNT(bc.id) as connection_count
            FROM brokers b
            LEFT JOIN broker_connections bc ON b.id = bc.broker_id
            WHERE b.is_verified = 1 AND b.is_active = 1
            GROUP BY b.id, b.full_name, b.broker_type
            ORDER BY connection_count DESC
            LIMIT {limit}
        """ if DATABASE_URL else f"""
            SELECT b.id, b.full_name, b.broker_type, COUNT(bc.id) as connection_count
            FROM brokers b
            LEFT JOIN broker_connections bc ON b.id = bc.broker_id
            WHERE b.is_verified = 1 AND b.is_active = 1
            GROUP BY b.id, b.full_name, b.broker_type
            ORDER BY connection_count DESC
            LIMIT {limit}
        """)
        rows = cursor.fetchall()
        return rows
    except Exception as e:
        logging.error(f"Get top brokers error: {e}")
        return []
    finally:
        if conn:
            conn.close()

# ==============================================================================
# 5. KEYBOARDS
# ==============================================================================

MAIN_KEYBOARD = [
    ["🔍 ደላላ ፈልግ", "📋 ደላላ መዝግብ"],
    ["📝 አዲስ ጥያቄ", "👤 መገለጫዬ"],
    ["📊 የተመዘገቡ ደላሎች", "📋 ግንኙነቶች"],
    ["📞 ድጋፍ", "📊 ስታቲስቲክስ"],
    ["🏠 ዋና ገጽ"]
]

BROKER_TYPES = [
    "🚗 የመኪና ደላላ",
    "🏠 የቤት ደላላ",
    "🏢 የንብረት ደላላ",
    "📦 የሸቀጥ ደላላ",
    "🔧 የአገልግሎት ደላላ",
    "🏦 የፋይናንስ ደላላ",
    "⚖️ የህግ ደላላ"
]

REQUEST_TYPES = [
    "🏠 ቤት ለሽያጭ",
    "🏠 ቤት ለኪራይ",
    "🚗 መኪና ለሽያጭ",
    "🚗 መኪና ለኪራይ",
    "🏢 ንብረት ለሽያጭ",
    "📦 ሸቀጥ ለሽያጭ",
    "🔧 አገልግሎት"
]

LOCATION_KEYBOARD = [
    ["ቦሌ", "አራዳ", "አዲስ ከተማ"],
    ["የካ", "ቂርቆስ", "ልደታ"],
    ["ኮልፌ ቀራኒዮ", "ንፋስ ስልክ", "አቃቂ ቃሊቲ"],
    ["ባህር ዳር", "ጎንደር", "ደሴ"],
    ["ሐረር", "ጅማ", "አርባ ምንጭ"],
    ["🏠 ዋና ገጽ"]
]

# ==============================================================================
# 6. STATES
# ==============================================================================

# Broker Registration States
REG_NAME = 10
REG_PHONE = 11
REG_EMAIL = 12
REG_TYPE = 13
REG_EXPERIENCE = 14
REG_LOCATION = 15

# Client Request States
REQ_TYPE = 20
REQ_DESCRIPTION = 21
REQ_BUDGET = 22
REQ_LOCATION = 23

# General States
WAITING_FOR_SEARCH = 30
WAITING_FOR_CONNECTION = 40
WAITING_FOR_PRICE = 50

# ==============================================================================
# 7. HANDLERS - START
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name if update.effective_user else "ወዳጄ"
    user_id = update.effective_user.id
    
    welcome_text = (
        f"👋 ሰላም {user_name}! ወደ **Broker Connect** በደህና መጡ።\n\n"
        f"━━━ 🤝 ስለ ቦቱ ━━━\n"
        f"• 🏢 ደላሎችን እና ደንበኞችን ያገናኛል\n"
        f"• 🔍 ደላላ መፈለግ ወይም መመዝገብ ይችላሉ\n"
        f"• 📝 አዲስ ጥያቄ ማስገባት ይችላሉ\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 የሚፈልጉትን አገልግሎት ከታች ይምረጡ፦"
    )
    
    if update.message:
        try:
            await update.message.reply_photo(
                photo=LOGO_FILE_ID,
                caption=welcome_text,
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            )
        except Exception as e:
            logging.error(f"Photo error: {e}")
            await update.message.reply_text(
                welcome_text,
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            )
    return ConversationHandler.END

# ==============================================================================
# 8. HANDLERS - BROKER REGISTRATION
# ==============================================================================

async def start_broker_reg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check if already registered
    existing = get_broker_by_chat_id(user_id)
    if existing:
        await update.message.reply_text(
            "✅ አስቀድመው እንደ ደላላ ተመዝግበዋል!\n\n"
            f"👤 {existing[2]}\n"
            f"🏢 {existing[5]}\n"
            f"⭐ {existing[6]} አመታት\n"
            f"📍 {existing[7]}\n\n"
            f"📊 ሁኔታ: {'✅ የተረጋገጠ' if existing[8] else '⏳ በመጠበቅ ላይ'}",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return ConversationHandler.END
    
    await update.message.reply_text(
        "📋 **ደላላ ምዝገባ**\n\n"
        "1️⃣ ሙሉ ስምዎን ይላኩ:",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True)
    )
    return REG_NAME

async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await start(update, context)
    
    context.user_data["broker_name"] = update.message.text
    await update.message.reply_text("📞 2️⃣ ስልክ ቁጥርዎን ይላኩ:")
    return REG_PHONE

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await start(update, context)
    
    context.user_data["broker_phone"] = update.message.text
    await update.message.reply_text("✉️ 3️⃣ ኢሜል አድራሻዎን ይላኩ (ካለ፣ ካልሆነ 'የለም' ይላኩ):")
    return REG_EMAIL

async def broker_reg_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await start(update, context)
    
    email = update.message.text
    context.user_data["broker_email"] = "" if email.lower() == "የለም" else email
    
    keyboard = []
    for i, b_type in enumerate(BROKER_TYPES):
        keyboard.append([InlineKeyboardButton(b_type, callback_data=f"broker_type_{i}")])
    
    await update.message.reply_text(
        "4️⃣ የደላላ አይነትዎን ይምረጡ:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REG_TYPE

async def broker_reg_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    index = int(query.data.split("_")[2])
    context.user_data["broker_type"] = BROKER_TYPES[index]
    
    await query.edit_message_text(
        f"✅ ዘርፍ: {BROKER_TYPES[index]}\n\n"
        f"5️⃣ የልምድ አመታትዎን ይላኩ (ቁጥር ብቻ):"
    )
    return REG_EXPERIENCE

async def broker_reg_experience(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await start(update, context)
    
    try:
        context.user_data["broker_experience"] = int(update.message.text)
        await update.message.reply_text(
            "📍 6️⃣ የሚሰሩበትን አካባቢ ይምረጡ ወይም ይላኩ:",
            reply_markup=ReplyKeyboardMarkup(LOCATION_KEYBOARD, resize_keyboard=True)
        )
        return REG_LOCATION
    except ValueError:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ቁጥር ይላኩ (ለምሳሌ፦ 5):")
        return REG_EXPERIENCE

async def broker_reg_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await start(update, context)
    
    context.user_data["broker_location"] = update.message.text
    chat_id = update.effective_user.id
    
    broker_id = register_broker_db(
        chat_id,
        context.user_data["broker_name"],
        context.user_data["broker_phone"],
        context.user_data["broker_email"],
        context.user_data["broker_type"],
        context.user_data["broker_experience"],
        context.user_data["broker_location"]
    )
    
    if broker_id:
        await update.message.reply_text(
            f"✅ **በስኬት ተመዝግበዋል!**\n\n"
            f"👤 {context.user_data['broker_name']}\n"
            f"🏢 {context.user_data['broker_type']}\n"
            f"⭐ {context.user_data['broker_experience']} አመታት\n"
            f"📍 {context.user_data['broker_location']}\n\n"
            f"⏳ እየተረጋገጠ ነው... ማሳወቂያ ይጠብቁ!",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        # Notify admin
        admin_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ ፈቅድ", callback_data=f"verify_broker_{broker_id}")],
            [InlineKeyboardButton("❌ ውድቅ አድርግ", callback_data=f"reject_broker_{broker_id}")]
        ])
        
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🔔 **አዲስ ደላላ ምዝገባ!**\n\n"
                 f"👤 {context.user_data['broker_name']}\n"
                 f"📞 {context.user_data['broker_phone']}\n"
                 f"✉️ {context.user_data['broker_email'] or 'የለም'}\n"
                 f"🏢 {context.user_data['broker_type']}\n"
                 f"⭐ {context.user_data['broker_experience']} አመታት\n"
                 f"📍 {context.user_data['broker_location']}\n"
                 f"🆔 {broker_id}",
            reply_markup=admin_keyboard
        )
    else:
        await update.message.reply_text(
            "❌ ምዝገባ አልተሳካም። እባክዎ እንደገና ይሞክሩ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 9. HANDLERS - FIND BROKERS
# ==============================================================================

async def find_brokers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for i, b_type in enumerate(BROKER_TYPES):
        keyboard.append([InlineKeyboardButton(b_type, callback_data=f"find_type_{i}")])
    keyboard.append([InlineKeyboardButton("🔙 ወደ መጀመሪያ", callback_data="go_home")])
    
    await update.message.reply_text(
        "🔍 **ደላላ ፈልግ**\n\n"
        "የሚፈልጉትን የደላላ አይነት ይምረጡ:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def find_brokers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("find_type_"):
        index = int(data.split("_")[2])
        broker_type = BROKER_TYPES[index]
        
        brokers = get_brokers_by_type(broker_type)
        
        if brokers:
            text = f"📋 **{broker_type} ደላሎች**\n\n"
            for broker in brokers:
                text += f"👤 {broker[2]}\n"
                text += f"📞 {broker[3]}\n"
                text += f"⭐ {broker[6]} አመታት\n"
                text += f"📍 {broker[7]}\n"
                text += f"🆔 {broker[0]}\n"
                text += "────────────────────\n"
            
            keyboard = [[InlineKeyboardButton("🔙 ተመለስ", callback_data="find_back")]]
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text(
                f"😅 በ{broker_type} ምንም የተመዘገበ ደላላ የለም።\n\n"
                f"💡 እንደ ደላላ ለመመዝገብ '📋 ደላላ መዝግብ' ይጫኑ።",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 ተመለስ", callback_data="find_back")
                ]])
            )
    
    elif data == "find_back":
        await query.edit_message_text(
            "🔍 ወደ ደላላ ፍለጋ ተመለስክ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )

# ==============================================================================
# 10. HANDLERS - NEW REQUEST
# ==============================================================================

async def new_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for i, r_type in enumerate(REQUEST_TYPES):
        keyboard.append([InlineKeyboardButton(r_type, callback_data=f"req_type_{i}")])
    keyboard.append([InlineKeyboardButton("🔙 ሰረዝ", callback_data="go_home")])
    
    await update.message.reply_text(
        "📝 **አዲስ ጥያቄ**\n\n"
        "የጥያቄ አይነት ይምረጡ:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REQ_TYPE

async def new_request_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    index = int(query.data.split("_")[2])
    context.user_data["request_type"] = REQUEST_TYPES[index]
    
    await query.edit_message_text(
        f"✅ የጥያቄ አይነት: {REQUEST_TYPES[index]}\n\n"
        f"📝 ዝርዝር መረጃ ይላኩ (ለምሳሌ፦ '3 መኝታ ቤት፣ 2 መታጠቢያ'):"
    )
    return REQ_DESCRIPTION

async def new_request_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await start(update, context)
    
    context.user_data["request_description"] = update.message.text
    await update.message.reply_text("💰 የበጀት መጠን ይላኩ (ለምሳሌ፦ '5,000,000 ብር'):")
    return REQ_BUDGET

async def new_request_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await start(update, context)
    
    context.user_data["request_budget"] = update.message.text
    await update.message.reply_text(
        "📍 አካባቢ ይምረጡ ወይም ይላኩ:",
        reply_markup=ReplyKeyboardMarkup(LOCATION_KEYBOARD, resize_keyboard=True)
    )
    return REQ_LOCATION

async def new_request_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await start(update, context)
    
    context.user_data["request_location"] = update.message.text
    user = update.effective_user
    
    request_id = add_client_request(
        user.id,
        user.first_name or "",
        context.user_data["request_type"],
        context.user_data["request_description"],
        context.user_data["request_budget"],
        context.user_data["request_location"]
    )
    
    if request_id:
        await update.message.reply_text(
            f"✅ **ጥያቄዎ ተመዝግቧል!** (ID: #{request_id})\n\n"
            f"📋 {context.user_data['request_type']}\n"
            f"📝 {context.user_data['request_description']}\n"
            f"💰 {context.user_data['request_budget']}\n"
            f"📍 {context.user_data['request_location']}\n\n"
            f"🔔 ለተመዘገቡ ደላሎች ተልኳል። መልስ ይጠብቁ...",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        # Notify all verified brokers
        brokers = get_all_brokers()
        for broker in brokers:
            try:
                keyboard = [[InlineKeyboardButton("✅ አለኝ", callback_data=f"broker_have_{request_id}_{user.id}_{broker[0]}")]]
                await context.bot.send_message(
                    chat_id=broker[1],
                    text=f"🔔 **አዲስ ጥያቄ!**\n\n"
                         f"📋 {context.user_data['request_type']}\n"
                         f"📝 {context.user_data['request_description']}\n"
                         f"💰 {context.user_data['request_budget']}\n"
                         f"📍 {context.user_data['request_location']}\n\n"
                         f"❓ አለህ?",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logging.error(f"Error notifying broker {broker[1]}: {e}")
        
        # Save search history
        save_search_history(user.id, context.user_data["request_type"])
        
    else:
        await update.message.reply_text("❌ ጥያቄውን ማስመዝገብ አልተቻለም።")
    
    return ConversationHandler.END

# ==============================================================================
# 11. HANDLERS - BROKER RESPONSE (HAVE)
# ==============================================================================

async def broker_have_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data.split("_")
    request_id = int(data[2])
    client_chat_id = data[3]
    broker_id = int(data[4])
    broker_chat_id = update.effective_user.id
    
    # Get broker info
    broker = get_broker_by_id(broker_id)
    if not broker:
        await query.edit_message_text("❌ የደላላ መረጃ አልተገኘም።")
        return
    
    # Check if already connected
    if add_connection(request_id, broker_id, client_chat_id, broker_chat_id):
        # Send broker info to client
        await context.bot.send_message(
            chat_id=client_chat_id,
            text=f"✅ **ደላላ ተገኝቷል!**\n\n"
                 f"👤 **{broker[2]}**\n"
                 f"📞 {broker[3]}\n"
                 f"🏢 {broker[5]}\n"
                 f"⭐ {broker[6]} አመታት ልምድ\n"
                 f"📍 {broker[7]}\n\n"
                 f"📞 በመደወል ይነጋገሩት!",
            parse_mode="Markdown"
        )
        
        await query.edit_message_text(
            f"✅ ምላሽህ ተልኳል!\n\n"
            f"👤 {broker[2]}\n"
            f"📞 {broker[3]}\n\n"
            f"📌 ደንበኛው በቅርቡ ያነጋግርሃል።",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 ዋና ሜኑ", callback_data="go_home")
            ]])
        )
    else:
        await query.edit_message_text(
            "❌ ግንኙነቱን መመዝገብ አልተቻለም። ምናልባት አስቀድሞ መልስ ሰጥተህ ይሆናል።"
        )

# ==============================================================================
# 12. HANDLERS - PROFILE
# ==============================================================================

async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check if broker
    broker = get_broker_by_chat_id(user_id)
    if broker:
        text = (
            f"👤 **መገለጫህ**\n\n"
            f"📛 {broker[2]}\n"
            f"📞 {broker[3]}\n"
            f"✉️ {broker[4] or 'የለም'}\n"
            f"🏢 {broker[5]}\n"
            f"⭐ {broker[6]} አመታት\n"
            f"📍 {broker[7]}\n"
            f"📊 {'✅ የተረጋገጠ' if broker[8] else '⏳ በመጠበቅ ላይ'}\n"
            f"📅 {broker[9]}\n"
        )
        await update.message.reply_text(text, parse_mode="Markdown")
        return
    
    # Check if client has requests
    connections = get_connections_by_client(user_id)
    if connections:
        text = "📋 **የእርስዎ ግንኙነቶች**\n\n"
        for conn in connections:
            text += f"👤 {conn[7]}\n"
            text += f"📞 {conn[8]}\n"
            text += f"🏢 {conn[9]}\n"
            text += f"📍 {conn[10]}\n"
            text += "────────────────────\n"
        await update.message.reply_text(text, parse_mode="Markdown")
        return
    
    await update.message.reply_text(
        "👤 ምንም መረጃ አልተገኘም።\n\n"
        "💡 እንደ ደላላ ለመመዝገብ '📋 ደላላ መዝግብ' ይጫኑ።",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    )

# ==============================================================================
# 13. HANDLERS - LIST BROKERS
# ==============================================================================

async def list_all_brokers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brokers = get_all_brokers()
    
    if not brokers:
        await update.message.reply_text(
            "📭 ምንም የተመዘገበ ደላላ የለም።\n\n"
            "💡 የመጀመሪያ ደላላ ለመሆን '📋 ደላላ መዝግብ' ይጫኑ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    text = "📊 **የተመዘገቡ ደላሎች**\n\n"
    for broker in brokers[:15]:
        text += f"👤 {broker[2]}\n"
        text += f"🏢 {broker[5]}\n"
        text += f"⭐ {broker[6]} አመታት\n"
        text += f"📍 {broker[7]}\n"
        text += "────────────────────\n"
    
    if len(brokers) > 15:
        text += f"\n... እና {len(brokers)-15} ሌሎች ደላሎች"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ==============================================================================
# 14. HANDLERS - CONNECTIONS
# ==============================================================================

async def my_connections(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check if broker
    broker = get_broker_by_chat_id(user_id)
    if broker:
        connections = get_connections_by_broker(user_id)
        if connections:
            text = "📋 **የእርስዎ ግንኙነቶች**\n\n"
            for conn in connections:
                text += f"📝 {conn[5]}\n"
                text += f"📋 {conn[6]}\n"
                text += f"📍 {conn[7]}\n"
                text += f"🕐 {conn[9]}\n"
                text += "────────────────────\n"
            await update.message.reply_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text(
                "📋 ምንም ግንኙነቶች የሉም።\n\n"
                "💡 አዲስ ጥያቄ ሲመጣ 'አለኝ' ብለህ መልስ ስጥ!",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
            )
        return
    
    # Check if client
    connections = get_connections_by_client(user_id)
    if connections:
        text = "📋 **የእርስዎ ግንኙነቶች**\n\n"
        for conn in connections:
            text += f"👤 {conn[7]}\n"
            text += f"📞 {conn[8]}\n"
            text += f"🏢 {conn[9]}\n"
            text += f"📍 {conn[10]}\n"
            text += "────────────────────\n"
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "📋 ምንም ግንኙነቶች የሉም።\n\n"
            "💡 አዲስ ጥያቄ ለማስገባት '📝 አዲስ ጥያቄ' ይጫኑ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )

# ==============================================================================
# 15. HANDLERS - ADMIN
# ==============================================================================

async def admin_manage_brokers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ ይህ ለአድሚን ብቻ ነው።")
        return
    
    pending = get_pending_brokers()
    
    if not pending:
        await update.message.reply_text(
            "✅ ምንም ያልተረጋገጠ ደላላ የለም።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    
    text = "📋 **ያልተረጋገጡ ደላሎች**\n\n"
    for broker in pending:
        text += f"🆔 {broker[0]}\n"
        text += f"👤 {broker[2]}\n"
        text += f"📞 {broker[3]}\n"
        text += f"🏢 {broker[5]}\n"
        text += f"📍 {broker[7]}\n"
        text += f"📅 {broker[9]}\n"
        text += "────────────────────\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id != ADMIN_CHAT_ID:
        await query.edit_message_text("⛔ ለአድሚን ብቻ")
        return
    
    data = query.data
    if data.startswith("verify_broker_"):
        broker_id = int(data.split("_")[2])
        if verify_broker_db(broker_id):
            broker = get_broker_by_id(broker_id)
            if broker:
                await query.edit_message_text(f"✅ ደላላ {broker[2]} ተረጋግጧል!")
                # Notify broker
                try:
                    await context.bot.send_message(
                        chat_id=broker[1],
                        text=f"🎉 **በስኬት ተረጋገጡ!**\n\n"
                             f"👤 {broker[2]}\n"
                             f"🏢 {broker[5]}\n\n"
                             f"📌 አሁን አዳዲስ ጥያቄዎች ይደርስዎታል!"
                    )
                except:
                    pass
        else:
            await query.edit_message_text("❌ ማረጋገጥ አልተቻለም።")
    
    elif data.startswith("reject_broker_"):
        broker_id = int(data.split("_")[2])
        broker = get_broker_by_id(broker_id)
        if broker:
            delete_broker_db(broker_id)
            await query.edit_message_text(f"❌ ደላላ {broker[2]} ውድቅ ተደርጓል!")
            try:
                await context.bot.send_message(
                    chat_id=broker[1],
                    text="❌ የደላላ ምዝገባዎ ውድቅ ተደርጓል። ለበለጠ መረጃ አስተዳዳሪውን ያግኙ።"
                )
            except:
                pass

# ==============================================================================
# 16. HANDLERS - STATISTICS
# ==============================================================================

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID)
    
    stats = get_bot_statistics()
    top_brokers = get_top_brokers()
    search_history = get_user_search_history(user_id, 5)
    
    text = "📊 **ስታቲስቲክስ**\n\n"
    text += f"👤 **ደላሎች**\n"
    text += f"• ጠቅላላ: {stats.get('total_brokers', 0)}\n"
    text += f"• የተረጋገጡ: {stats.get('verified_brokers', 0)}\n"
    if is_admin:
        text += f"• ያልተረጋገጡ: {stats.get('pending_brokers', 0)}\n"
    text += "\n"
    
    text += f"📝 **ጥያቄዎች**\n"
    text += f"• ጠቅላላ: {stats.get('total_requests', 0)}\n"
    text += f"• በመጠበቅ ላይ: {stats.get('pending_requests', 0)}\n"
    text += "\n"
    
    text += f"🤝 **ግንኙነቶች**\n"
    text += f"• ጠቅላላ: {stats.get('total_connections', 0)}\n"
    text += "\n"
    
    if top_brokers:
        text += "🏆 **ከፍተኛ ደላሎች**\n"
        for idx, (bid, name, btype, count) in enumerate(top_brokers, 1):
            text += f"• {idx}. {name} ({count} ግንኙነቶች)\n"
        text += "\n"
    
    if search_history:
        text += "📝 **የቅርብ ጊዜ ፍለጋዎች**\n"
        for term, date in search_history:
            text += f"• {term}\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ==============================================================================
# 17. HANDLERS - HELP
# ==============================================================================

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
❓ **እንዴት እንደሚሰራ**

🤝 **ደላላ ከሆንክ:**
• '📋 ደላላ መዝግብ' ተጫን
• መረጃህን ሙሉ ለሙሉ አስገባ
• አስተዳዳሪ ካረጋገጠ በኋላ አዲስ ጥያቄ ሲመጣ ማሳወቂያ ታገኛለህ
• 'አለኝ' ብለህ መልስ ስጥ ደንበኛው መረጃህን ያገኛል

🔍 **ደንበኛ ከሆንክ:**
• '🔍 ደላላ ፈልግ' ተጫን
• የምትፈልገውን የደላላ አይነት ምረጥ
• የደላሎች ዝርዝር ታያለህ
• '📝 አዲስ ጥያቄ' ተጫን ለደላላ ለመላክ

📞 **ግንኙነት:**
• ደላላ ሲያገኝ 'አለኝ' ይላል
• የደላላውን ስልክ ቁጥር ታገኛለህ
• በቀጥታ ተደውለህ ተነጋገር

📌 **ሌሎች አማራጮች:**
• '👤 መገለጫዬ' - መረጃህን ተመልከት
• '📋 ግንኙነቶች' - ያስተናገድካቸውን ግንኙነቶች ተመልከት
• '📊 ስታቲስቲክስ' - የቦቱ አጠቃቀም መረጃ
• '📞 ድጋፍ' - ለእርዳታ ያግኙን
"""
    await update.message.reply_text(help_text, parse_mode="Markdown")

# ==============================================================================
# 18. MAIN FUNCTION
# ==============================================================================

def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    # ========== BROKER REGISTRATION CONVERSATION ==========
    broker_reg_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📋 ደላላ መዝግብ$"), start_broker_reg)],
        states={
            REG_NAME: [MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start), MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name)],
            REG_PHONE: [MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start), MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone)],
            REG_EMAIL: [MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start), MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_email)],
            REG_TYPE: [CallbackQueryHandler(broker_reg_type_callback, pattern="^broker_type_")],
            REG_EXPERIENCE: [MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start), MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_experience)],
            REG_LOCATION: [MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start), MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_location)],
        },
        fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start)],
    )

    # ========== NEW REQUEST CONVERSATION ==========
    request_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 አዲስ ጥያቄ$"), new_request)],
        states={
            REQ_TYPE: [CallbackQueryHandler(new_request_type_callback, pattern="^req_type_")],
            REQ_DESCRIPTION: [MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start), MessageHandler(filters.TEXT & ~filters.COMMAND, new_request_description)],
            REQ_BUDGET: [MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start), MessageHandler(filters.TEXT & ~filters.COMMAND, new_request_budget)],
            REQ_LOCATION: [MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start), MessageHandler(filters.TEXT & ~filters.COMMAND, new_request_location)],
        },
        fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start)],
    )

    # ========== COMMAND HANDLERS ==========
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("manage", admin_manage_brokers))

    # ========== MESSAGE HANDLERS ==========
    app.add_handler(MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start))
    app.add_handler(MessageHandler(filters.Regex("^🔍 ደላላ ፈልግ$"), find_brokers))
    app.add_handler(MessageHandler(filters.Regex("^👤 መገለጫዬ$"), my_profile))
    app.add_handler(MessageHandler(filters.Regex("^📊 የተመዘገቡ ደላሎች$"), list_all_brokers))
    app.add_handler(MessageHandler(filters.Regex("^📋 ግንኙነቶች$"), my_connections))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), show_help))
    app.add_handler(MessageHandler(filters.Regex("^📊 ስታቲስቲክስ$"), show_stats))

    # ========== CALLBACK QUERY HANDLERS ==========
    app.add_handler(CallbackQueryHandler(find_brokers_callback, pattern="^find_"))
    app.add_handler(CallbackQueryHandler(broker_have_callback, pattern="^broker_have_"))
    app.add_handler(CallbackQueryHandler(admin_verify_callback, pattern="^(verify_broker_|reject_broker_)"))
    app.add_handler(CallbackQueryHandler(lambda u, c: start(u, c), pattern="^go_home$"))

    # ========== CONVERSATION HANDLERS ==========
    app.add_handler(broker_reg_conv)
    app.add_handler(request_conv)

    # ========== ERROR HANDLER ==========
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        logging.error(f"Update {update} caused error {context.error}")
    
    app.add_error_handler(error_handler)

    print("🤖 Broker Connect Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()