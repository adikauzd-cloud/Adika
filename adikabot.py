import os
import logging
import asyncio
from datetime import datetime
from flask import Flask, request, jsonify

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
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
# 1. CONFIGURATION & LOGGING
# ==============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "0")  # የደላላው/የAdmin Group ID
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==============================================================================
# 2. CONVERSATION STATES
# ==============================================================================
# Car Buyer States
CAR_BUY_MODEL, CAR_BUY_YEAR, CAR_BUY_BUDGET, CAR_BUY_CONTACT, CAR_BUY_PHONE, CAR_BUY_CONFIRM = range(6)

# Car Seller States
CAR_SELL_MODEL, CAR_SELL_YEAR, CAR_SELL_PRICE, CAR_SELL_NEGO, CAR_SELL_PHOTO, CAR_SELL_CONTACT, CAR_SELL_PHONE, CAR_SELL_CONFIRM = range(6, 14)

# Property States (House/Land)
PROP_TYPE, PROP_LOCATION, PROP_PRICE, PROP_NEGO, PROP_EXTRA, PROP_PHOTO, PROP_CONTACT, PROP_PHONE, PROP_CONFIRM = range(14, 23)

# Counter for Request IDs
request_counter = 1000

# ==============================================================================
# 3. KEYBOARDS & NAVIGATION
# ==============================================================================
def get_main_keyboard():
    """ዋናው Bottom Reply Keyboard"""
    keyboard = [
        ["🚗 መኪና (ለመግዛት / ለመሸጥ)", "🏠 ቤት/ቦታ (ለመግዛት / ለመሸጥ)"],
        ["📋 የእኔ ጥያቄዎች / ማስታወቂያዎች", "📞 እኛን ለማነጋገር"],
        ["🏠 ወደ ዋና ገጽ"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_cancel_inline():
    """በየደረጃው የሚታይ አቋርጥ/ወደ ዋና ገጽ መመለሻ"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="go_home")]])

def get_contact_choice_inline():
    """የመገናኛ መንገድ መረጣ Inline Keyboard"""
    keyboard = [
        [InlineKeyboardButton("📱 ስልክ ቁጥር ለማስገባት", callback_data="contact_phone")],
        [InlineKeyboardButton("✈️ በTelegram Username", callback_data="contact_username")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="go_home")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_nego_inline():
    """የድርድር ሁኔታ Inline Keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("🤝 ድርድር አለው", callback_data="nego_yes"),
            InlineKeyboardButton("🔒 ቋሚ ዋጋ (Fixed)", callback_data="nego_no")
        ],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="go_home")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_confirm_inline():
    """የማረጋገጫ (Confirmation) Inline Keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("✅ አረጋግጥ እና ላክ", callback_data="confirm_yes"),
            InlineKeyboardButton("✏️ አስተካክል / ሰርዝ", callback_data="confirm_no")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==============================================================================
# 4. GLOBAL START & HOME HANDLER
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ወደ ዋና ገጽ መመለሻ እና የWelcome Message ማሳያ"""
    context.user_data.clear()
    welcome_text = (
        "<b>እንኳን ወደ [የቦቱ ስም] በደህና መጡ! 👋</b>\n\n"
        "የሪል እስቴት እና የመኪና ደላላ አገልግሎታችንን በመጠቀም በፍጥነት ይግዙ፣ ይሽጡ ወይም ያከራዩ።\n\n"
        "<i>እባክዎን ከታች ካሉት አማራጮች የሚፈልጉትን ይምረጡ፦</i>"
    )
    
    if update.message:
        await update.message.reply_html(welcome_text, reply_markup=get_main_keyboard())
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_html(welcome_text, reply_markup=get_main_keyboard())
        
    return ConversationHandler.END

async def go_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Inline Button 'ወደ ዋና ገጽ' ሲነካ"""
    query = update.callback_query
    await query.answer()
    return await start(update, context)

# ==============================================================================
# 5. CAR BUYER FLOW (መኪና ለመግዛት)
# ==============================================================================
async def car_buy_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔹 <b>መኪና ለመግዛት - ደረጃ 1</b>\n\n"
        "እባክዎን የሚፈልጉትን የመኪና ዓይነት ወይም ሞዴል ያክሉ? (ምሳሌ፦ Toyota Vitz, Hyundai Tucson, Ford...)",
        parse_mode="HTML",
        reply_markup=get_cancel_inline()
    )
    return CAR_BUY_MODEL

async def car_buy_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['car_model'] = update.message.text
    await update.message.reply_text(
        "🔹 <b>ደረጃ 2 (የምርት ዘመን / Year Model)</b>\n\n"
        "የምርት ዘመን ይምረጡ ወይም ያስገቡ (ከስንት እስከ ስንት)? (ምሳሌ፦ 2015 - 2020)",
        parse_mode="HTML",
        reply_markup=get_cancel_inline()
    )
    return CAR_BUY_YEAR

async def car_buy_year(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['car_year'] = update.message.text
    await update.message.reply_text(
        "🔹 <b>ደረጃ 3 (የበጀት መጠን / Budget)</b>\n\n"
        "መመደብ የሚችሉት የበጀት መጠን ስንት ነው? (ምሳሌ፦ 2,000,000 - 3,000,000 ብር)",
        parse_mode="HTML",
        reply_markup=get_cancel_inline()
    )
    return CAR_BUY_BUDGET

async def car_buy_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['car_budget'] = update.message.text
    await update.message.reply_text(
        "🔹 <b>ደረጃ 4 (የመገናኛ መንገድ / Contact Method)</b>\n\n"
        "እርስዎን ለማነጋገር የትኛውን የመገናኛ መንገድ ይጠቀማሉ?",
        parse_mode="HTML",
        reply_markup=get_contact_choice_inline()
    )
    return CAR_BUY_CONTACT

async def car_buy_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "contact_phone":
        await query.message.reply_text("📱 እባክዎን ስልክ ቁጥርዎን ያስገቡ፦", reply_markup=get_cancel_inline())
        return CAR_BUY_PHONE
    else:
        username = query.from_user.username
        context.user_data['contact'] = f"@{username}" if username else "Username የለም (በTelegram ID)"
        return await show_car_buy_confirmation(query.message, context)

async def car_buy_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['contact'] = update.message.text
    return await show_car_buy_confirmation(update.message, context)

async def show_car_buy_confirmation(message_obj, context) -> int:
    data = context.user_data
    text = (
        "🔍 <b>የያስገቡት መረጃ ትክክለኛነት ያረጋግጡ፦</b>\n\n"
        f"🚘 <b>የመኪና ሞዴል፦</b> {data.get('car_model')}\n"
        f"📅 <b>የምርት ዘመን፦</b> {data.get('car_year')}\n"
        f"💰 <b>በጀት፦</b> {data.get('car_budget')}\n"
        f"📞 <b>መገናኛ፦</b> {data.get('contact')}\n\n"
        "ይህ መረጃ ይላክ?"
    )
    await message_obj.reply_html(text, reply_markup=get_confirm_inline())
    return CAR_BUY_CONFIRM

async def car_buy_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    global request_counter
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_yes":
        request_counter += 1
        req_id = f"#CAR-BUY-{request_counter}"
        
        await query.message.reply_html(
            f"✅ <b>ጥያቄዎ በተሳካ ሁኔታ ተመዝግቧል!</b>\n"
            f"🆔 የጥያቄ መለያ ቁጥር፦ <code>{req_id}</code>\n\n"
            "አስፈላጊው መኪና ሲገኝ ደላሎቻችን ያነጋግሩዎታል።",
            reply_markup=get_main_keyboard()
        )
        
        # Notify Admin
        if ADMIN_CHAT_ID != "0":
            data = context.user_data
            admin_msg = (
                f"🚨 <b>አዲስ የመኪና ግዢ ፍላጎት ({req_id})</b>\n\n"
                f"👤 ተጠቃሚ፦ {query.from_user.full_name}\n"
                f"🚘 ሞዴል፦ {data.get('car_model')}\n"
                f"📅 ዘመን፦ {data.get('car_year')}\n"
                f"💰 በጀት፦ {data.get('car_budget')}\n"
                f"📞 መገናኛ፦ {data.get('contact')}"
            )
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, parse_mode="HTML")
            
        context.user_data.clear()
        return ConversationHandler.END
    else:
        await query.message.reply_text("❌ ሂደቱ ተሰርዟል። እባክዎን እንደገና ይጀምሩ።", reply_markup=get_main_keyboard())
        context.user_data.clear()
        return ConversationHandler.END

# ==============================================================================
# 6. CAR SELLER FLOW (መኪና ለመሸጥ)
# ==============================================================================
async def car_sell_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔹 <b>መኪና ለመሸጥ - ደረጃ 1</b>\n\n"
        "የሚሸጡትን መኪና ሞዴል እና የሰሪው ስም ያስገቡ (ምሳሌ፦ Toyota Yaris Executive):",
        parse_mode="HTML",
        reply_markup=get_cancel_inline()
    )
    return CAR_SELL_MODEL

async def car_sell_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['sell_model'] = update.message.text
    await update.message.reply_text(
        "🔹 <b>ደረጃ 2 (የምርት ዘመን እና ሁኔታ)</b>\n\n"
        "የመኪናውን የምርት ዘመን (Year) እና ያገለገለበትን ሁኔታ ያስገቡ (ምሳሌ፦ 2018፣ በኢትዮጵያ ያልተነዳ / ያገለገለ):",
        parse_mode="HTML",
        reply_markup=get_cancel_inline()
    )
    return CAR_SELL_YEAR

async def car_sell_year(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['sell_year'] = update.message.text
    await update.message.reply_text(
        "🔹 <b>ደረጃ 3 (የመሸጫ ዋጋ)</b>\n\n"
        "የመኪናው መሸጫ ዋጋ ስንት ነው? (በብር)",
        parse_mode="HTML",
        reply_markup=get_cancel_inline()
    )
    return CAR_SELL_PRICE

async def car_sell_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['sell_price'] = update.message.text
    await update.message.reply_text(
        "እባክዎን የዋጋውን ሁኔታ ይምረጡ፦",
        reply_markup=get_nego_inline()
    )
    return CAR_SELL_NEGO

async def car_sell_nego(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['sell_nego'] = "ድርድር አለው" if query.data == "nego_yes" else "ቋሚ ዋጋ (Fixed)"
    
    await query.message.reply_text(
        "📸 <b>የመኪናው ፎቶዎች</b>\n\n"
        "እባክዎን የመኪናውን እስከ 5 ፎቶዎች ይላኩ (ሲጨርሱ '➡️ እለፍ/ቀጥል' የሚለውን ይጫኑ)፦",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➡️ እለፍ / ቀጥል", callback_data="skip_photo")],
            [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="go_home")]
        ])
    )
    return CAR_SELL_PHOTO

async def car_sell_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if 'photos' not in context.user_data:
        context.user_data['photos'] = []
    
    # Save photo file_id
    photo_file = update.message.photo[-1].file_id
    context.user_data['photos'].append(photo_file)
    
    await update.message.reply_text(
        f"✅ {len(context.user_data['photos'])} ፎቶ ተቀብለናል። ተጨማሪ መላክ ይችላሉ ወይም ቀጥል የሚለውን ይጫኑ።",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➡️ ቀጥል", callback_data="skip_photo")],
            [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="go_home")]
        ])
    )
    return CAR_SELL_PHOTO

async def car_sell_photo_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    await query.message.reply_text(
        "🔹 <b>ደረጃ 4 (የመገናኛ መንገድ)</b>\n\n"
        "የመገናኛ አማራጭዎን ይምረጡ፦",
        parse_mode="HTML",
        reply_markup=get_contact_choice_inline()
    )
    return CAR_SELL_CONTACT

async def car_sell_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "contact_phone":
        await query.message.reply_text("📱 እባክዎን ስልክ ቁጥርዎን ያስገቡ፦", reply_markup=get_cancel_inline())
        return CAR_SELL_PHONE
    else:
        username = query.from_user.username
        context.user_data['contact'] = f"@{username}" if username else "Username የለም"
        return await show_car_sell_confirmation(query.message, context)

async def car_sell_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['contact'] = update.message.text
    return await show_car_sell_confirmation(update.message, context)

async def show_car_sell_confirmation(message_obj, context) -> int:
    data = context.user_data
    photos_count = len(data.get('photos', []))
    text = (
        "📢 <b>የሽያጭ ማስታወቂያዎን ያረጋገጡ፦</b>\n\n"
        f"🚘 <b>ሞዴል፦</b> {data.get('sell_model')}\n"
        f"📅 <b>ዘመን/ሁኔታ፦</b> {data.get('sell_year')}\n"
        f"💰 <b>ዋጋ፦</b> {data.get('sell_price')} ({data.get('sell_nego')})\n"
        f"🖼 <b>የፎቶ ብዛት፦</b> {photos_count}\n"
        f"📞 <b>መገናኛ፦</b> {data.get('contact')}\n\n"
        "ይህ ማስታወቂያ ይፖስት?"
    )
    await message_obj.reply_html(text, reply_markup=get_confirm_inline())
    return CAR_SELL_CONFIRM

async def car_sell_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    global request_counter
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_yes":
        request_counter += 1
        req_id = f"#CAR-SELL-{request_counter}"
        
        await query.message.reply_html(
            f"✅ <b>የመኪና ሽያጭ ማስታወቂያዎ ተመዝግቧል!</b>\n"
            f"🆔 ማስታወቂያ መለያ ቁጥር፦ <code>{req_id}</code>",
            reply_markup=get_main_keyboard()
        )
        
        # Send to Admin
        if ADMIN_CHAT_ID != "0":
            data = context.user_data
            admin_msg = (
                f"📢 <b>አዲስ የመኪና ሽያጭ ({req_id})</b>\n\n"
                f"🚘 ሞዴል፦ {data.get('sell_model')}\n"
                f"📅 ዘመን፦ {data.get('sell_year')}\n"
                f"💰 ዋጋ፦ {data.get('sell_price')} ({data.get('sell_nego')})\n"
                f"📞 መገናኛ፦ {data.get('contact')}"
            )
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, parse_mode="HTML")
            
            # Send photos to Admin if any
            for photo in data.get('photos', []):
                await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=photo)

        context.user_data.clear()
        return ConversationHandler.END
    else:
        await query.message.reply_text("❌ ሂደቱ ተሰርዟል።", reply_markup=get_main_keyboard())
        context.user_data.clear()
        return ConversationHandler.END

# ==============================================================================
# 7. PROPERTY FLOW (ቤት እና ቦታ)
# ==============================================================================
async def prop_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("🏢 ኮንዶሚኒየም", callback_data="prop_condo"), InlineKeyboardButton("🏡 ቪላ / መኖሪያ ቤት", callback_data="prop_villa")],
        [InlineKeyboardButton("🏬 ንግድ ቤት/ፎቅ", callback_data="prop_shop"), InlineKeyboardButton("📐 ባዶ ቦታ/መሬት", callback_data="prop_land")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="go_home")]
    ]
    await update.message.reply_text(
        "🏠 <b>የቤት እና ቦታ ዝርዝር መረጃ ፍሰት</b>\n\n"
        "እባክዎን የቦታ/ንብረት አይነት ይምረጡ፦",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PROP_TYPE

async def prop_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    types = {
        "prop_condo": "ኮንዶሚኒየም",
        "prop_villa": "ቪላ / መኖሪያ ቤት",
        "prop_shop": "ንግድ ቤት/ፎቅ",
        "prop_land": "ባዶ ቦታ/መሬት"
    }
    context.user_data['prop_type'] = types.get(query.data, "ሌላ")
    
    await query.message.reply_text(
        "📍 <b>አድራሻ/ቦታ (Location)፦</b>\n\n"
        "ንብረቱ የሚገኝበትን ቦታ/አድራሻ ያስገቡ (ምሳሌ፦ አዲስ አበባ፣ ቦሌ ክፍለ ከተማ፣ አትላስ አካባቢ):",
        parse_mode="HTML",
        reply_markup=get_cancel_inline()
    )
    return PROP_LOCATION

async def prop_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['prop_loc'] = update.message.text
    await update.message.reply_text(
        "💰 <b>ዋጋ (Price)፦</b>\n\n"
        "የንብረቱ ጠቅላላ ዋጋ ስንት ነው? (በብር)",
        parse_mode="HTML",
        reply_markup=get_cancel_inline()
    )
    return PROP_PRICE

async def prop_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['prop_price'] = update.message.text
    await update.message.reply_text(
        "🤝 <b>የድርድር ሁኔታ፦</b>\n\n"
        "የዋጋው ሁኔታ እንዴት ነው?",
        parse_mode="HTML",
        reply_markup=get_nego_inline()
    )
    return PROP_NEGO

async def prop_nego(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['prop_nego'] = "ድርድር አለው" if query.data == "nego_yes" else "ቋሚ ዋጋ ነው"
    
    await query.message.reply_text(
        "➕ <b>ተጨማሪ ዝርዝር (Optional Step)፦</b>\n\n"
        "ተጨማሪ መረጃ (ምሳሌ፦ ስፋት በ ካሬ ሜትር፣ የካርታ ሁኔታ) ማከል ይፈልጋሉ?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ ጨምር", callback_data="extra_add"), InlineKeyboardButton("➡️ እለፍ/ቀጥል", callback_data="extra_skip")],
            [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="go_home")]
        ])
    )
    return PROP_EXTRA

async def prop_extra_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "extra_add":
        await query.message.reply_text("✍️ እባክዎን ተጨማሪ ዝርዝር መረጃውን ጽፈው ይላኩ፦", reply_markup=get_cancel_inline())
        return PROP_EXTRA
    else:
        context.user_data['prop_extra'] = "የለም"
        return await ask_prop_contact(query.message)

async def prop_extra_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['prop_extra'] = update.message.text
    return await ask_prop_contact(update.message)

async def ask_prop_contact(message_obj):
    await message_obj.reply_text(
        "📞 <b>የመገናኛ መንገድ ይምረጡ፦</b>",
        parse_mode="HTML",
        reply_markup=get_contact_choice_inline()
    )
    return PROP_CONTACT

async def prop_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "contact_phone":
        await query.message.reply_text("📱 እባክዎን ስልክ ቁጥርዎን ያስገቡ፦", reply_markup=get_cancel_inline())
        return PROP_PHONE
    else:
        username = query.from_user.username
        context.user_data['contact'] = f"@{username}" if username else "Username የለም"
        return await show_prop_confirmation(query.message, context)

async def prop_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['contact'] = update.message.text
    return await show_prop_confirmation(update.message, context)

async def show_prop_confirmation(message_obj, context) -> int:
    data = context.user_data
    text = (
        "🏠 <b>የቤት/ቦታ መረጃዎን ያረጋግጡ፦</b>\n\n"
        f"🏢 <b>አይነት፦</b> {data.get('prop_type')}\n"
        f"📍 <b>አድራሻ፦</b> {data.get('prop_loc')}\n"
        f"💰 <b>ዋጋ፦</b> {data.get('prop_price')} ({data.get('prop_nego')})\n"
        f"📝 <b>ተጨማሪ፦</b> {data.get('prop_extra')}\n"
        f"📞 <b>መገናኛ፦</b> {data.get('contact')}\n\n"
        "መረጃው ይመዝገብ?"
    )
    await message_obj.reply_html(text, reply_markup=get_confirm_inline())
    return PROP_CONFIRM

async def prop_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    global request_counter
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirm_yes":
        request_counter += 1
        req_id = f"#PROP-{request_counter}"
        
        await query.message.reply_html(
            f"✅ <b>የቤት/ቦታ መረጃዎ ተመዝግቧል!</b>\n"
            f"🆔 የመዝገብ ቁጥር፦ <code>{req_id}</code>",
            reply_markup=get_main_keyboard()
        )
        
        # Admin Alert
        if ADMIN_CHAT_ID != "0":
            data = context.user_data
            admin_msg = (
                f"🏠 <b>አዲስ የቤት/ቦታ መዝገብ ({req_id})</b>\n\n"
                f"🏢 አይነት፦ {data.get('prop_type')}\n"
                f"📍 አድራሻ፦ {data.get('prop_loc')}\n"
                f"💰 ዋጋ፦ {data.get('prop_price')} ({data.get('prop_nego')})\n"
                f"📝 ተጨማሪ፦ {data.get('prop_extra')}\n"
                f"📞 መገናኛ፦ {data.get('contact')}"
            )
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, parse_mode="HTML")

        context.user_data.clear()
        return ConversationHandler.END
    else:
        await query.message.reply_text("❌ ሂደቱ ተሰርዟል።", reply_markup=get_main_keyboard())
        context.user_data.clear()
        return ConversationHandler.END

# ==============================================================================
# 8. GENERAL BUTTON HANDLERS
# ==============================================================================
async def car_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'🚗 መኪና (ለመግዛት / ለመሸጥ)' ሲነካ የሚመጣ መረጣ"""
    keyboard = [
        [InlineKeyboardButton("🔍 መኪና ለመግዛት", callback_data="start_car_buy")],
        [InlineKeyboardButton("📢 መኪና ለመሸጥ", callback_data="start_car_sell")],
        [InlineKeyboardButton("🏠 ወደ ዋና ገጽ", callback_data="go_home")]
    ]
    await update.message.reply_text(
        "🚗 <b>የመኪና አገልግሎት</b>\n\nምን ማድረግ ይፈልጋሉ?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 እስካሁን ያስገቧቸው ጥያቄዎች እና ማስታወቂያዎች የሉም።")

async def contact_us(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📞 <b>እኛን ለማነጋገር፦</b>\n\n📱 ስልክ፦ +251 900 000 000\n✈️ Telegram: @AdikaSupportBot", parse_mode="HTML")

# ==============================================================================
# 9. FLASK SERVER & MAIN FUNCTION
# ==============================================================================
web_app = Flask(__name__)
bot_app = None

@web_app.route('/')
def index():
    return f"🚀 Adika Marketplace Bot Running! Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

@web_app.route('/webhook', methods=['POST'])
def webhook():
    global bot_app
    if not bot_app:
        return "Bot Not Ready", 500
    try:
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, bot_app.bot)
        loop = asyncio.get_event_loop()
        loop.create_task(bot_app.process_update(update))
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return f"Error: {e}", 500

def main():
    global bot_app
    app = Application.builder().token(BOT_TOKEN).build()
    bot_app = app
    
    # Home Filter
    home_filter = filters.Regex("^🏠 ወደ ዋና ገጽ$")

    # 1. Car Buyer Conversation
    car_buy_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(car_buy_start, pattern="^start_car_buy$"),
            MessageHandler(filters.Regex("^🚗 መኪና ለመግዛት$"), car_buy_start)
        ],
        states={
            CAR_BUY_MODEL: [MessageHandler(filters.TEXT & ~home_filter, car_buy_model)],
            CAR_BUY_YEAR: [MessageHandler(filters.TEXT & ~home_filter, car_buy_year)],
            CAR_BUY_BUDGET: [MessageHandler(filters.TEXT & ~home_filter, car_buy_budget)],
            CAR_BUY_CONTACT: [CallbackQueryHandler(car_buy_contact, pattern="^contact_")],
            CAR_BUY_PHONE: [MessageHandler(filters.TEXT & ~home_filter, car_buy_phone)],
            CAR_BUY_CONFIRM: [CallbackQueryHandler(car_buy_confirm_handler, pattern="^confirm_")],
        },
        fallbacks=[MessageHandler(home_filter, start), CommandHandler("start", start), CallbackQueryHandler(go_home_callback, pattern="^go_home$")],
        allow_reentry=True
    )

    # 2. Car Seller Conversation
    car_sell_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(car_sell_start, pattern="^start_car_sell$"),
            MessageHandler(filters.Regex("^🚘 መኪና ለመሸጥ$"), car_sell_start)
        ],
        states={
            CAR_SELL_MODEL: [MessageHandler(filters.TEXT & ~home_filter, car_sell_model)],
            CAR_SELL_YEAR: [MessageHandler(filters.TEXT & ~home_filter, car_sell_year)],
            CAR_SELL_PRICE: [MessageHandler(filters.TEXT & ~home_filter, car_sell_price)],
            CAR_SELL_NEGO: [CallbackQueryHandler(car_sell_nego, pattern="^nego_")],
            CAR_SELL_PHOTO: [
                MessageHandler(filters.PHOTO, car_sell_photo),
                CallbackQueryHandler(car_sell_photo_skip, pattern="^skip_photo$")
            ],
            CAR_SELL_CONTACT: [CallbackQueryHandler(car_sell_contact, pattern="^contact_")],
            CAR_SELL_PHONE: [MessageHandler(filters.TEXT & ~home_filter, car_sell_phone)],
            CAR_SELL_CONFIRM: [CallbackQueryHandler(car_sell_confirm_handler, pattern="^confirm_")],
        },
        fallbacks=[MessageHandler(home_filter, start), CommandHandler("start", start), CallbackQueryHandler(go_home_callback, pattern="^go_home$")],
        allow_reentry=True
    )

    # 3. Property Conversation
    prop_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🏠 ቤት/ቦታ \(ለመግዛት / ለመሸጥ\)$"), prop_start)],
        states={
            PROP_TYPE: [CallbackQueryHandler(prop_type_chosen, pattern="^prop_")],
            PROP_LOCATION: [MessageHandler(filters.TEXT & ~home_filter, prop_location)],
            PROP_PRICE: [MessageHandler(filters.TEXT & ~home_filter, prop_price)],
            PROP_NEGO: [CallbackQueryHandler(prop_nego, pattern="^nego_")],
            PROP_EXTRA: [
                CallbackQueryHandler(prop_extra_choice, pattern="^extra_"),
                MessageHandler(filters.TEXT & ~home_filter, prop_extra_text)
            ],
            PROP_CONTACT: [CallbackQueryHandler(prop_contact, pattern="^contact_")],
            PROP_PHONE: [MessageHandler(filters.TEXT & ~home_filter, prop_phone)],
            PROP_CONFIRM: [CallbackQueryHandler(prop_confirm_handler, pattern="^confirm_")],
        },
        fallbacks=[MessageHandler(home_filter, start), CommandHandler("start", start), CallbackQueryHandler(go_home_callback, pattern="^go_home$")],
        allow_reentry=True
    )

    # General Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(home_filter, start))
    app.add_handler(CallbackQueryHandler(go_home_callback, pattern="^go_home$"))
    
    app.add_handler(MessageHandler(filters.Regex("^🚗 መኪና \(ለመግዛት / ለመሸጥ\)$"), car_main_menu))
    app.add_handler(MessageHandler(filters.Regex("^📋 የእኔ ጥያቄዎች / ማስታወቂያዎች$"), my_requests))
    app.add_handler(MessageHandler(filters.Regex("^📞 እኛን ለማነጋገር$"), contact_us))

    # Add Conversations
    app.add_handler(car_buy_conv)
    app.add_handler(car_sell_conv)
    app.add_handler(prop_conv)

    if WEBHOOK_URL:
        logger.info(f"🔗 Setting Webhook to: {WEBHOOK_URL}/webhook")
        app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        web_app.run(host="0.0.0.0", port=PORT, debug=False)
    else:
        logger.info("🚀 Starting Bot in Polling Mode...")
        app.run_polling()

if __name__ == "__main__":
    main()
