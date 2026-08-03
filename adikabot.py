import logging
import sqlite3
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# Logging Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Database Setup
def init_db():
    conn = sqlite3.connect("broker_bot.db")
    cursor = conn.cursor()
    # Brokers Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS brokers (
                        user_id INTEGER PRIMARY KEY,
                        name TEXT,
                        phone TEXT,
                        location TEXT
                    )''')
    # Requests / Items Table
    cursor.execute('''CREATE TABLE IF NOT EXISTS active_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        type TEXT, -- 'BUY_CAR', 'BUY_HOUSE', 'SELL_CAR', 'SELL_HOUSE'
                        details TEXT,
                        status TEXT DEFAULT 'ACTIVE'
                    )''')
    conn.commit()
    conn.close()

init_db()

# States Definition
(
    # Broker Registration
    BROKER_NAME, BROKER_PHONE, BROKER_LOCATION,
    # Buyer Car
    BUY_CAR_MODEL, BUY_CAR_YEAR, BUY_CAR_BUDGET, BUY_CAR_PHONE,
    # Buyer House
    BUY_HOUSE_LOC, BUY_HOUSE_TYPE, BUY_HOUSE_BUDGET, BUY_HOUSE_PHONE,
    # Provider Has Item Response
    HAS_ITEM_DETAILS, HAS_ITEM_PHOTO,
    # Sell Car
    SELL_CAR_MODEL, SELL_CAR_YEAR, SELL_CAR_PRICE, SELL_CAR_NEG, SELL_CAR_PHONE, SELL_CAR_PHOTO,
    # Sell House
    SELL_HOUSE_LOC, SELL_HOUSE_TYPE, SELL_HOUSE_SQM, SELL_HOUSE_COND, SELL_HOUSE_PRICE, SELL_HOUSE_PHONE, SELL_HOUSE_PHOTO
) = range(23)

# Keyboards
MAIN_KEYBOARD = ReplyKeyboardMarkup([
    ["🔍 መግዛት / መከራየት", "📢 መሸጥ / ማከራየት"],
    ["📝 እንደ አቅራቢ መመዝገብ", "📋 የፈላጊዎች ዝርዝር"]
], resize_keyboard=True)

HOME_BTN = ["🏠 ዋና ገጽ"]
HOME_KEYBOARD = ReplyKeyboardMarkup([HOME_BTN], resize_keyboard=True)

# ----------------- Helper Functions -----------------
def is_broker(user_id):
    conn = sqlite3.connect("broker_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM brokers WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res is not None

# ----------------- Global Cancel / Home -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = "እንኳን ደህና መጡ! ወደ ደላላ እና አልሚዎች ማገናኛ ቦት በደህና መጡ። እባክዎን ከታች ካሉት አማራጮች ይመረጡ፦"
    if update.callback_query:
        await update.callback_query.message.reply_text(welcome_text, reply_markup=MAIN_KEYBOARD)
    else:
        await update.message.reply_text(welcome_text, reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END

# ----------------- 1. Broker Registration -----------------
async def start_broker_reg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 የደላላ/አቅራቢ ምዝገባ፦\nእባክዎን ሙሉ ስምዎን ያስገቡ፡", reply_markup=HOME_KEYBOARD)
    return BROKER_NAME

async def reg_broker_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['b_name'] = update.message.text
    await update.message.reply_text("እባክዎን ስልክ ቁጥርዎን ያስገቡ፡", reply_markup=HOME_KEYBOARD)
    return BROKER_PHONE

async def reg_broker_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['b_phone'] = update.message.text
    await update.message.reply_text("እርስዎ የሚሰሩበትን ዋና አካባቢ/ዞን ያስገቡ፡", reply_markup=HOME_KEYBOARD)
    return BROKER_LOCATION

async def reg_broker_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = context.user_data['b_name']
    phone = context.user_data['b_phone']
    loc = update.message.text

    conn = sqlite3.connect("broker_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO brokers VALUES (?, ?, ?, ?)", (user_id, name, phone, loc))
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ ምዝገባዎ በተሳካ ሁኔታ ተጠናቋል! አሁን '📋 የፈላጊዎች ዝርዝር' ገጽን ማየት ይችላሉ።", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END

# ----------------- 2. Buyer Flow (መግዛት / መከራየት) -----------------
async def buy_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = ReplyKeyboardMarkup([["🚗 መኪና መግዛት", "🏠 ቤት/ቦታ መግዛት"], HOME_BTN], resize_keyboard=True)
    await update.message.reply_text("ምን መግዛት/መከራየት ይፈልጋሉ?", reply_markup=keyboard)
    return BUY_CAR_MODEL

async def buy_choice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🚗 መኪና መግዛት":
        await update.message.reply_text("የሚፈልጉትን የመኪና ሞዴል/ብራንድ ያስገቡ (ምሳሌ፦ Toyota Vitz, Hyundai Tucson)፡", reply_markup=HOME_KEYBOARD)
        return BUY_CAR_MODEL
    elif text == "🏠 ቤት/ቦታ መግዛት":
        inline_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("ቦሌ", callback_data="loc_ቦሌ"), InlineKeyboardButton("ሲኤምሲ", callback_data="loc_ሲኤምሲ")],
            [InlineKeyboardButton("ሳሪስ", callback_data="loc_ሳሪስ"), InlineKeyboardButton("አያት", callback_data="loc_አያት")],
            [InlineKeyboardButton("ገርጂ", callback_data="loc_ገርጂ")]
        ])
        await update.message.reply_text("የሚፈልጉበትን አካባቢ ይምረጡ፡", reply_markup=inline_kb)
        return BUY_HOUSE_LOC

# --- Buy Car Flow ---
async def buy_car_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_car_model'] = update.message.text
    await update.message.reply_text("የምርት ዘመን Range ያስገቡ (ምሳሌ፦ 2015 - 2020)፡", reply_markup=HOME_KEYBOARD)
    return BUY_CAR_YEAR

async def buy_car_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_car_year'] = update.message.text
    await update.message.reply_text("ያዘጋጁት ባጀት Range ያስገቡ (ምሳሌ፦ 1.5 - 2.5 ሚሊዮን ብር)፡", reply_markup=HOME_KEYBOARD)
    return BUY_CAR_BUDGET

async def buy_car_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_car_budget'] = update.message.text
    await update.message.reply_text("እርስዎን ለማግኘት የሚያስችል ስልክ ቁጥር ያስገቡ፡", reply_markup=HOME_KEYBOARD)
    return BUY_CAR_PHONE

async def buy_car_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    details = f"🚗 **የመኪና ፍላጎት**\n• ሞዴል: {context.user_data['buy_car_model']}\n• የምርት ዘመን: {context.user_data['buy_car_year']}\n• ባጀት: {context.user_data['buy_car_budget']}\n• ስልክ: {phone}"
    
    conn = sqlite3.connect("broker_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO active_requests (user_id, type, details) VALUES (?, ?, ?)", 
                   (update.effective_user.id, 'BUY_CAR', details))
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ ጥያቄዎ በተሳካ ሁኔታ ተመዝግቧል! አቅራቢዎች/ደላሎች አይተው ያገኟዎታል።", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END

# --- Buy House Flow ---
async def buy_house_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['buy_house_loc'] = query.data.replace("loc_", "")
    
    inline_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("ቪላ", callback_data="ht_ቪላ"), InlineKeyboardButton("ሰርቪስ", callback_data="ht_ሰርቪስ")],
        [InlineKeyboardButton("አፓርታማ", callback_data="ht_አፓርታማ"), InlineKeyboardButton("መሬት/የጨረቃ", callback_data="ht_መሬት")],
        [InlineKeyboardButton("ሪል እስቴት", callback_data="ht_ሪል እስቴት")]
    ])
    await query.message.reply_text("የቤት/የቦታ ዓይነት ይምረጡ፡", reply_markup=inline_kb)
    return BUY_HOUSE_TYPE

async def buy_house_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['buy_house_type'] = query.data.replace("ht_", "")
    await query.message.reply_text("ያዘጋጁትን ባጀት Range ያስገቡ (ምሳሌ፦ 5 - 10 ሚሊዮን ብር)፡", reply_markup=HOME_KEYBOARD)
    return BUY_HOUSE_BUDGET

async def buy_house_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['buy_house_budget'] = update.message.text
    await update.message.reply_text("የሚያገኙበትን ስልክ ቁጥር ያስገቡ፡", reply_markup=HOME_KEYBOARD)
    return BUY_HOUSE_PHONE

async def buy_house_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text
    details = f"🏠 **የቤት/ቦታ ፍላጎት**\n• አካባቢ: {context.user_data['buy_house_loc']}\n• ዓይነት: {context.user_data['buy_house_type']}\n• ባጀት: {context.user_data['buy_house_budget']}\n• ስልክ: {phone}"
    
    conn = sqlite3.connect("broker_bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO active_requests (user_id, type, details) VALUES (?, ?, ?)", 
                   (update.effective_user.id, 'BUY_HOUSE', details))
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ ጥያቄዎ በተሳካ ሁኔታ ተመዝግቧል!", reply_markup=MAIN_KEYBOARD)
    return ConversationHandler.END

# ----------------- 3. Buyers List (ለደላሎች ብቻ) -----------------
async def list_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_broker(user_id):
        await update.message.reply_text("⚠️ እባክዎን መጀመሪያ '📝 እንደ አቅራቢ መመዝገብ' የሚለውን ተጭነው ይመዝገቡ።", reply_markup=MAIN_KEYBOARD)
        return

    conn = sqlite3.connect("broker_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, type, details FROM active_requests WHERE status = 'ACTIVE' ORDER BY id DESC LIMIT 10")
    requests = cursor.fetchall()
    conn.close()

    if not requests:
        await update.message.reply_text("አሁን ላይ ምንም ክፍት የፈላጊዎች ጥያቄ የለም።", reply_markup=MAIN_KEYBOARD)
        return

    for req_id, req_type, details in requests:
        btn = InlineKeyboardMarkup([[InlineKeyboardButton("✅ አለኝ", callback_data=f"has_{req_id}_{req_type}")]])
        await update.message.reply_text(f"{details}", reply_markup=btn, parse_mode="Markdown")

# ----------------- 4. Provider "✅ አለኝ" Response Flow -----------------
async def provider_has_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    req_id = data[1]
    req_type = "_".join(data[2:])

    context.user_data['responding_req_id'] = req_id
    context.user_data['responding_req_type'] = req_type

    await query.message.reply_text("💡 እባክዎን የእርስዎን ንብረት ሙሉ መረጃ (ሞዴል/አካባቢ፣ ዘመን/ስፋት፣ ዋጋ እና ስልክ ቁጥር) በአንድ ላይ ጽፈው ይላኩ፡", reply_markup=HOME_KEYBOARD)
    return HAS_ITEM_DETAILS

async def provider_has_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['resp_details'] = update.message.text
    await update.message.reply_text("እባክዎን የንብረቱን/የመኪናውን/የቤቱን ፎቶ ይላኩ፡", reply_markup=HOME_KEYBOARD)
    return HAS_ITEM_PHOTO

async def provider_has_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file_id = update.message.photo[-1].file_id
    req_id = context.user_data['responding_req_id']

    # Get buyer info
    conn = sqlite3.connect("broker_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM active_requests WHERE id = ?", (req_id,))
    res = cursor.fetchone()
    conn.close()

    if res:
        buyer_id = res[0]
        msg = f"🔔 **ከአቅራቢ/ደላላ የቀረበ መልስ!**\n\n{context.user_data['resp_details']}"
        try:
            await context.bot.send_photo(chat_id=buyer_id, photo=photo_file_id, caption=msg, parse_mode="Markdown")
            await update.message.reply_text("✅ መረጃው እና ፎቶው ለፈላጊው ወዲያውኑ ተልኳል!", reply_markup=MAIN_KEYBOARD)
        except Exception as e:
            await update.message.reply_text("❌ መረጃውን ለፈላጊው መላክ አልተቻለም (ተጠቃሚው ቦቱን ዘግቶት ሊሆን ይችላል)።", reply_markup=MAIN_KEYBOARD)
    
    return ConversationHandler.END

# ----------------- Main App Construction -----------------
def main():
    # Insert your Bot Token here
    app = Application.builder().token("YOUR_BOT_TOKEN_HERE").build()

    # Home button global handler
    home_handler = MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), start)

    # Broker Registration Conversation
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ መመዝገብ$"), start_broker_reg)],
        states={
            BROKER_NAME: [home_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, reg_broker_name)],
            BROKER_PHONE: [home_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, reg_broker_phone)],
            BROKER_LOCATION: [home_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, reg_broker_loc)],
        },
        fallbacks=[home_handler, CommandHandler("start", start)]
    )

    # Buyer Conversation
    buy_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buy_start)],
        states={
            BUY_CAR_MODEL: [home_handler, MessageHandler(filters.Regex("^(🚗 መኪና መግዛት|🏠 ቤት/ቦታ መግዛት)$"), buy_choice_handler), MessageHandler(filters.TEXT & ~filters.COMMAND, buy_car_model)],
            BUY_CAR_YEAR: [home_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, buy_car_year)],
            BUY_CAR_BUDGET: [home_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, buy_car_budget)],
            BUY_CAR_PHONE: [home_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, buy_car_phone)],
            
            BUY_HOUSE_LOC: [home_handler, CallbackQueryHandler(buy_house_loc, pattern="^loc_")],
            BUY_HOUSE_TYPE: [home_handler, CallbackQueryHandler(buy_house_type, pattern="^ht_")],
            BUY_HOUSE_BUDGET: [home_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, buy_house_budget)],
            BUY_HOUSE_PHONE: [home_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, buy_house_phone)],
        },
        fallbacks=[home_handler, CommandHandler("start", start)]
    )

    # Provider Has Response Conversation
    has_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(provider_has_click, pattern="^has_")],
        states={
            HAS_ITEM_DETAILS: [home_handler, MessageHandler(filters.TEXT & ~filters.COMMAND, provider_has_details)],
            HAS_ITEM_PHOTO: [home_handler, MessageHandler(filters.PHOTO, provider_has_photo)],
        },
        fallbacks=[home_handler, CommandHandler("start", start)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(broker_conv)
    app.add_handler(buy_conv)
    app.add_handler(has_conv)
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), list_requests))
    app.add_handler(home_handler)

    app.run_polling()

if __name__ == "__main__":
    main()
