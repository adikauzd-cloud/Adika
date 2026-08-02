import logging
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

# Logging ማዘጋጀት
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# የConversation ደረጃዎች (States)
CATEGORY, SELLER_TYPE, INQUIRY_DETAILS = range(3)

# 1. Start Command - እንኳን ደህና መጡ
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("🚗 መኪና ፍለጋ (Auto)", callback_data="cat_car")],
        [InlineKeyboardButton("🏠 ቤት / ቦታ ፍለጋ (Property)", callback_data="cat_house")],
        [InlineKeyboardButton("🏢 ንግድ ቤት / ቢሮ (Commercial)", callback_data="cat_commercial")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = (
        "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
        "የሀገሪቱ ታላቁ የመኪና እና የንብረት ገበያ ማዕከል።\n"
        "እባክዎን የሚፈልጉትን አገልግሎት ምድብ ይምረጡ፡"
    )
    
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
        
    return CATEGORY

# 2. የአቅራቢ አይነት መምረጫ (Seller Type Selection)
async def category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    cat = query.data
    context.user_data['category'] = cat
    
    # በምድቡ መሠረት የአቅራቢ አማራጮችን ማዘጋጀት
    if cat == "cat_car":
        keyboard = [
            [InlineKeyboardButton("🏪 ከመኪና መሸጫ (Showroom)", callback_data="seller_showroom")],
            [InlineKeyboardButton("👤 ከባለቤቱ በቀጥታ (Direct Owner)", callback_data="seller_owner")],
            [InlineKeyboardButton("👨‍💼 ከተረጋገጡ ደላሎች (Verified Broker)", callback_data="seller_broker")],
            [InlineKeyboardButton("🌐 ከሁሉም አቅራቢዎች", callback_data="seller_all")]
        ]
    else:  # House or Commercial
        keyboard = [
            [InlineKeyboardButton("🏢 ከሪል እስቴት አልሚዎች (Developers)", callback_data="seller_realestate")],
            [InlineKeyboardButton("👤 ከባለቤቱ በቀጥታ (Direct Owner)", callback_data="seller_owner")],
            [InlineKeyboardButton("👨‍💼 ከተረጋገጡ ደላሎች (Verified Broker)", callback_data="seller_broker")],
            [InlineKeyboardButton("🌐 ከሁሉም አቅራቢዎች", callback_data="seller_all")]
        ]
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "📌 **ጥያቄዎ ለማን እንዲደርስ ይፈልጋሉ?**\n"
        "የሚፈልጉትን የአቅራቢ አይነት ይምረጡ፡",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return SELLER_TYPE

# 3. የፍላጎት መግለጫ (Inquiry Prompt)
async def seller_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    context.user_data['seller_type'] = query.data
    
    await query.edit_message_text(
        "✍️ **አሁን የሚፈልጉትን ዝርዝር ፍላጎት ይጻፉልን፡**\n\n"
        "💡 *ምሳሌ፡* «አዲስ አበባ ቦሌ አካባቢ ባለ 2 መኝታ ቤት ኪራይ እስከ 40,000 ብር»\n"
        "ወይም «2020 Model Vitz መኪና በ2 ሚሊዮን ብር ክልል»\n\n"
        "መልክትዎን ከታች ባለው የጽሑፍ ማዕቀፍ ያስገቡ፡",
        parse_mode="Markdown"
    )
    return INQUIRY_DETAILS

# 4. ጥያቄውን መቀበል እና ለአቅራቢዎች ማሰራጨት (Broadcast Process)
async def handle_inquiry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_text = update.message.text
    user = update.message.from_user
    
    category = context.user_data.get('category', 'አልተጠቀሰም')
    seller_type = context.user_data.get('seller_type', 'አልተጠቀሰም')
    
    # ለገዢው የማረጋገጫ መልእክት መላክ
    summary = (
        "✅ **ጥያቄዎ በ Adika Marketplace ተመዝግቧል!**\n\n"
        f"🔹 **ምድብ:** {category.replace('cat_', '').capitalize()}\n"
        f"🔹 **የተመረጠው አቅራቢ:** {seller_type.replace('seller_', '').capitalize()}\n"
        f"📝 **የእርስዎ ጥያቄ:** {user_text}\n\n"
        "🚀 ጥያቄዎ ወዲያውኑ ለተመዘገቡ አቅራቢዎች ደርሷል። አማራጮች እንደደረሱን እዚሁ በቦቱ ይላኩልዎታል።"
    )
    
    await update.message.reply_text(summary, parse_mode="Markdown")
    
    # ----------------------------------------------------
    # TODO: እዚህ ቦታ ላይ ጥያቄውን በዳታቤዝ (Database) መዝግቦ
    # ለተመዘገቡት አቅራቢዎች በቴሌግራም Notification የመላክ ስራ ይሰራል::
    # ----------------------------------------------------
    
    return ConversationHandler.END

# ረዳት፡ ስራውን ማቋረጫ (Cancel)
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("የነበረው ሂደት ተቋርጧል። እንደገና ለመጀመር /start ይበሉ።")
    return ConversationHandler.END

# MAIN FUNCTION
def main():
    # BOT TOKEN እዚህ ጋር ይተካ ወይም ከ .env ይነበብ
    BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CATEGORY: [CallbackQueryHandler(category_chosen, pattern='^cat_')],
            SELLER_TYPE: [CallbackQueryHandler(seller_type_chosen, pattern='^seller_')],
            INQUIRY_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_inquiry)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    
    app.add_handler(conv_handler)
    
    print("Adika Marketplace Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
