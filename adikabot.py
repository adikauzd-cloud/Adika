import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# 1. Environment Variables ማንበብ
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Logging ማዘጋጀት
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Conversation ደረጃዎች (States)
(
    ROLE_SELECTION,
    CATEGORY,
    SELLER_TYPE,
    INQUIRY_DETAILS,
    REG_TYPE,
    REG_NAME,
    REG_PHONE,
    REG_CONFIRM
) = range(8)


# ------------------ START & MAIN MENU ------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("🔍 ዕቃ / ቤት / መኪና እፈልጋለሁ (ገዢ)", callback_data="role_buyer")],
        [InlineKeyboardButton("📝 እንደ አቅራቢ/ደላላ መመዝገብ እፈልጋለሁ", callback_data="role_vendor")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
        "የሀገሪቱ ታላቁ የመኪና፣ የቤት እና የንብረት ገበያ ማዕከል።\n\n"
        "እባክዎን ከታች ካሉት አማራጮች አንዱን ይምረጡ፡"
    )
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
        
    return ROLE_SELECTION


# ------------------ BUYER FLOW (የገዢዎች ክፍል) ------------------

async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🚗 መኪና ፍለጋ (Auto)", callback_data="cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ ፍለጋ (Property)", callback_data="cat_house")],
        [InlineKeyboardButton("🏢 ንግድ ቤት / ቢሮ (Commercial)", callback_data="cat_commercial")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🎯 **የሚፈልጉትን አገልግሎት ምድብ ይምረጡ፡**",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return CATEGORY


async def category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    cat = query.data
    context.user_data['category'] = cat
    
    if cat == "cat_car":
        keyboard = [
            [InlineKeyboardButton("🏪 ከመኪና መሸጫ (Showroom)", callback_data="seller_showroom")],
            [InlineKeyboardButton("👤 ከባለቤቱ በቀጥታ (Direct Owner)", callback_data="seller_owner")],
            [InlineKeyboardButton("👨‍💼 ከተረጋገጡ ደላሎች (Verified Broker)", callback_data="seller_broker")],
            [InlineKeyboardButton("🌐 ከሁሉም አቅራቢዎች", callback_data="seller_all")]
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("🏢 ከሪል እስቴት አልሚዎች (Developers)", callback_data="seller_realestate")],
            [InlineKeyboardButton("👤 ከባለቤቱ በቀጥታ (Direct Owner)", callback_data="seller_owner")],
            [InlineKeyboardButton("👨‍💼 ከተረጋገጡ ደላሎች (Verified Broker)", callback_data="seller_broker")],
            [InlineKeyboardButton("🌐 ከሁሉም አቅራቢዎች", callback_data="seller_all")]
        ]
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "📌 **ጥያቄዎ ለማን እንዲደርስ ይፈልጋሉ?**",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return SELLER_TYPE


async def seller_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    context.user_data['seller_type'] = query.data
    
    await query.edit_message_text(
        "✍️ **አሁን የሚፈልጉትን ዝርዝር ፍላጎት ይጻፉልን፡**\n\n"
        "💡 *ምሳሌ፡* «አዲስ አበባ ቦሌ አካባቢ ባለ 2 መኝታ ቤት ኪራይ እስከ 40,000 ብር»\n"
        "ወይም «2020 Model Vitz መኪና በ2 ሚሊዮን ብር ክልል»\n\n"
        "መልእክትዎን ከታች ባለው የጽሑፍ ማዕቀፍ ያስገቡ፡",
        parse_mode="Markdown"
    )
    return INQUIRY_DETAILS


async def handle_inquiry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_text = update.message.text
    user = update.message.from_user
    
    category = context.user_data.get('category', 'አልተጠቀሰም').replace('cat_', '').capitalize()
    seller_type = context.user_data.get('seller_type', 'አልተጠቀሰም').replace('seller_', '').capitalize()
    
    # 1. ለገዢው ማረጋገጫ መስጠት
    summary = (
        "✅ **ጥያቄዎ በ Adika Marketplace ተመዝግቧል!**\n\n"
        f"🔹 **ምድብ:** {category}\n"
        f"🔹 **የተመረጠ አቅራቢ:** {seller_type}\n"
        f"📝 **የእርስዎ ጥያቄ:** {user_text}\n\n"
        "🚀 ጥያቄዎ ለአቅራቢዎች ደርሷል። አማራጮች እንደደረሱን በቦቱ ይላኩልዎታል።"
    )
    await update.message.reply_text(summary, parse_mode="Markdown")
    
    # 2. ለአድሚን ጥያቄውን ማስተላለፍ (በ .env በተቀመጠው ADMIN_CHAT_ID)
    if ADMIN_CHAT_ID:
        admin_alert = (
            "🔔 **አዲስ የገዢ ጥያቄ ደርሷል!**\n\n"
            f"👤 **ገዢ:** @{user.username if user.username else 'የለውም'} (ID: {user.id})\n"
            f"🔹 **ምድብ:** {category}\n"
            f"🔹 **የተመረጠ አቅራቢ:** {seller_type}\n"
            f"📝 **ጥያቄ:** {user_text}"
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_alert, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Failed to send to admin: {e}")
            
    return ConversationHandler.END


# ------------------ VENDOR REGISTRATION FLOW (የአቅራቢዎች መመዝገቢያ) ------------------

async def vendor_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🏢 ሪል እስቴት አልሚ (Developer)", callback_data="vtype_realestate")],
        [InlineKeyboardButton("🏪 የመኪና መሸጫ (Showroom)", callback_data="vtype_showroom")],
        [InlineKeyboardButton("👨‍💼 የተመዘገበ ደላላ (Broker)", callback_data="vtype_broker")],
        [InlineKeyboardButton("👤 የግል ባለቤት (Direct Owner)", callback_data="vtype_owner")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📋 **የአቅራቢነት ምዝገባ**\n\n"
        "በAdika Marketplace ላይ በየትኛው ዘርፍ መመዝገብ ይፈልጋሉ?",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return REG_TYPE


async def vendor_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    context.user_data['vendor_type'] = query.data
    
    await query.edit_message_text(
        "✍️ **እባክዎን የድርጅትዎን ወይም የእርስዎን ሙሉ ስም ያስገቡ፡**\n"
        "(ምሳሌ፡ *አቤል ካስቴል ሪል እስቴት* ወይም *ደላላ መሀመድ*)"
    )
    return REG_NAME


async def vendor_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['vendor_name'] = update.message.text
    
    await update.message.reply_text(
        "📞 **እባክዎን የስልክ ቁጥርዎን ያስገቡ፡**\n"
        "(ምሳሌ፡ *0911XXXXXX*)"
    )
    return REG_PHONE


async def vendor_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['vendor_phone'] = update.message.text
    user = update.message.from_user
    
    v_type = context.user_data.get('vendor_type', '').replace('vtype_', '').capitalize()
    v_name = context.user_data.get('vendor_name')
    v_phone = context.user_data.get('vendor_phone')
    
    # ለተመዝጋቢው የሚላክ ማረጋገጫ
    conf_text = (
        "🎉 **ምዝገባዎ በስኬት ተጠናቋል!**\n\n"
        f"🏷️ **የአቅራቢ አይነት:** {v_type}\n"
        f"👤 **ስም:** {v_name}\n"
        f"📞 **ስልክ:** {v_phone}\n\n"
        "አካውንትዎ እንደተረጋገጠ (Verify እንደሆነ) የገዢዎች ጥያቄ በቀጥታ በስልክዎ መድረስ ይጀምራል።"
    )
    await update.message.reply_text(conf_text, parse_mode="Markdown")
    
    # ለአድሚን የመዝገብ መረጃ መላክ
    if ADMIN_CHAT_ID:
        admin_vendor_alert = (
            "🆕 **አዲስ አቅራቢ ተመዝግቧል!**\n\n"
            f"👤 **Telegram User:** @{user.username if user.username else 'የለውም'} (ID: {user.id})\n"
            f"🏷️ **አይነት:** {v_type}\n"
            f"📛 **ስም:** {v_name}\n"
            f"📞 **ስልክ:** {v_phone}"
        )
        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_vendor_alert, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Failed to send vendor reg to admin: {e}")
            
    return ConversationHandler.END


# ------------------ CANCEL & ERROR HANDLERS ------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("ሂደቱ ተቋርጧል። እንደገና ለመጀመር /start ይበሉ።")
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ኤረር ሲከሰት ሰርቨሩ እንዳይቋረጥ ማድረጊያ እና ኤረሩን መመዝገቢያ"""
    logging.error("Exception occurred while handling an update:", exc_info=context.error)


# ------------------ MAIN FUNCTION ------------------

def main():
    if not BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN በ .env ፋይል ውስጥ አልተገኘም!")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            ROLE_SELECTION: [
                CallbackQueryHandler(buyer_start, pattern='^role_buyer$'),
                CallbackQueryHandler(vendor_start, pattern='^role_vendor$')
            ],
            CATEGORY: [CallbackQueryHandler(category_chosen, pattern='^cat_')],
            SELLER_TYPE: [CallbackQueryHandler(seller_type_chosen, pattern='^seller_')],
            INQUIRY_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_inquiry)],
            REG_TYPE: [CallbackQueryHandler(vendor_type_chosen, pattern='^vtype_')],
            REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, vendor_name_received)],
            REG_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, vendor_phone_received)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    app.add_handler(conv_handler)
    
    # ኤረር ሀንድለሩን ማያያዝ
    app.add_error_handler(error_handler)
    
    print("🚀 Adika Marketplace Bot is successfully running...")
    app.run_polling()


if __name__ == '__main__':
    main()
