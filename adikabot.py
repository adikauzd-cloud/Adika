import os
import logging
from datetime import datetime
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

# ============================================================
# 1. CONFIGURATION
# ============================================================

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Enhanced logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation States
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

# ============================================================
# 2. START & MAIN MENU
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the bot"""
    try:
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
        
    except Exception as e:
        logger.error(f"Error in start: {e}", exc_info=True)
        await update.message.reply_text("❌ የሆነ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ።")
        return ConversationHandler.END

# ============================================================
# 3. BUYER FLOW
# ============================================================

async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle buyer role selection"""
    try:
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
        
    except Exception as e:
        logger.error(f"Error in buyer_start: {e}", exc_info=True)
        await update.callback_query.message.reply_text("❌ ስህተት ተከስቷል። እንደገና /start ይበሉ።")
        return ConversationHandler.END

async def category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle category selection"""
    try:
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
        
    except Exception as e:
        logger.error(f"Error in category_chosen: {e}", exc_info=True)
        await update.callback_query.message.reply_text("❌ ስህተት ተከስቷል። እንደገና ይሞክሩ።")
        return ConversationHandler.END

async def seller_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle seller type selection"""
    try:
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
        
    except Exception as e:
        logger.error(f"Error in seller_type_chosen: {e}", exc_info=True)
        await update.callback_query.message.reply_text("❌ ስህተት ተከስቷል። እንደገና ይሞክሩ።")
        return ConversationHandler.END

async def handle_inquiry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the user's inquiry"""
    try:
        user_text = update.message.text
        user = update.message.from_user
        
        category = context.user_data.get('category', 'አልተጠቀሰም').replace('cat_', '').capitalize()
        seller_type = context.user_data.get('seller_type', 'አልተጠቀሰም').replace('seller_', '').capitalize()
        
        # 1. Confirmation to buyer
        summary = (
            "✅ **ጥያቄዎ በ Adika Marketplace ተመዝግቧል!**\n\n"
            f"🔹 **ምድብ:** {category}\n"
            f"🔹 **የተመረጠ አቅራቢ:** {seller_type}\n"
            f"📝 **የእርስዎ ጥያቄ:** {user_text}\n\n"
            "🚀 ጥያቄዎ ለአቅራቢዎች ደርሷል። አማራጮች እንደደረሱን በቦቱ ይላኩልዎታል።"
        )
        await update.message.reply_text(summary, parse_mode="Markdown")
        
        # 2. Notify admin
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
                logger.info(f"✅ Admin notified about new inquiry from {user.id}")
            except Exception as e:
                logger.error(f"Failed to send to admin: {e}")
        
        # 3. Clear user data
        context.user_data.clear()
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in handle_inquiry: {e}", exc_info=True)
        await update.message.reply_text("❌ ስህተት ተከስቷል። እንደገና /start ይበሉ።")
        return ConversationHandler.END

# ============================================================
# 4. VENDOR REGISTRATION
# ============================================================

async def vendor_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start vendor registration"""
    try:
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
        
    except Exception as e:
        logger.error(f"Error in vendor_start: {e}", exc_info=True)
        await update.callback_query.message.reply_text("❌ ስህተት ተከስቷል። እንደገና /start ይበሉ።")
        return ConversationHandler.END

async def vendor_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle vendor type selection"""
    try:
        query = update.callback_query
        await query.answer()
        
        context.user_data['vendor_type'] = query.data
        
        await query.edit_message_text(
            "✍️ **እባክዎን የድርጅትዎን ወይም የእርስዎን ሙሉ ስም ያስገቡ፡**\n"
            "(ምሳሌ፡ *አቤል ካስቴል ሪል እስቴት* ወይም *ደላላ መሀመድ*)",
            parse_mode="Markdown"
        )
        return REG_NAME
        
    except Exception as e:
        logger.error(f"Error in vendor_type_chosen: {e}", exc_info=True)
        await update.callback_query.message.reply_text("❌ ስህተት ተከስቷል። እንደገና ይሞክሩ።")
        return ConversationHandler.END

async def vendor_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle vendor name input"""
    try:
        context.user_data['vendor_name'] = update.message.text
        
        await update.message.reply_text(
            "📞 **እባክዎን የስልክ ቁጥርዎን ያስገቡ፡**\n"
            "(ምሳሌ፡ *0911XXXXXX*)",
            parse_mode="Markdown"
        )
        return REG_PHONE
        
    except Exception as e:
        logger.error(f"Error in vendor_name_received: {e}", exc_info=True)
        await update.message.reply_text("❌ ስህተት ተከስቷል። እንደገና ይሞክሩ።")
        return ConversationHandler.END

async def vendor_phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle vendor phone input and complete registration"""
    try:
        context.user_data['vendor_phone'] = update.message.text
        user = update.message.from_user
        
        v_type = context.user_data.get('vendor_type', '').replace('vtype_', '').capitalize()
        v_name = context.user_data.get('vendor_name')
        v_phone = context.user_data.get('vendor_phone')
        
        # Confirmation to vendor
        conf_text = (
            "🎉 **ምዝገባዎ በስኬት ተጠናቋል!**\n\n"
            f"🏷️ **የአቅራቢ አይነት:** {v_type}\n"
            f"👤 **ስም:** {v_name}\n"
            f"📞 **ስልክ:** {v_phone}\n\n"
            "🔔 አካውንትዎ እንደተረጋገጠ (Verify) የገዢዎች ጥያቄ በቀጥታ በስልክዎ መድረስ ይጀምራል።\n\n"
            "📌 ለማረጋገጫ አስተዳዳሪውን ያግኙ።"
        )
        await update.message.reply_text(conf_text, parse_mode="Markdown")
        
        # Notify admin
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
                logger.info(f"✅ Admin notified about new vendor registration: {user.id}")
            except Exception as e:
                logger.error(f"Failed to send vendor reg to admin: {e}")
        
        # Clear user data
        context.user_data.clear()
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error in vendor_phone_received: {e}", exc_info=True)
        await update.message.reply_text("❌ ስህተት ተከስቷል። እንደገና /start ይበሉ።")
        return ConversationHandler.END

# ============================================================
# 5. CANCEL & ERROR HANDLERS
# ============================================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation"""
    try:
        await update.message.reply_text(
            "❌ ሂደቱ ተቋርጧል። እንደገና ለመጀመር /start ይበሉ።",
            parse_mode="Markdown"
        )
        context.user_data.clear()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in cancel: {e}")
        return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors"""
    logger.error(f"Exception occurred: {context.error}", exc_info=True)
    
    # Log the full error details
    error_type = type(context.error).__name__
    error_msg = str(context.error)
    logger.error(f"Error Type: {error_type}")
    logger.error(f"Error Message: {error_msg}")
    
    # Try to notify user
    try:
        if update and hasattr(update, 'effective_message'):
            await update.effective_message.reply_text(
                f"❌ **ስህተት ተከስቷል!**\n\n"
                f"🔴 {error_msg[:200]}\n\n"
                f"💡 እባክዎ እንደገና /start ይበሉ ወይም አስተዳዳሪውን ያግኙ።",
                parse_mode="Markdown"
            )
    except:
        pass

# ============================================================
# 6. MAIN FUNCTION
# ============================================================

def main():
    """Start the bot"""
    if not BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN በ .env ፋይል ውስጥ አልተገኘም!")
        print("💡 እባክዎ .env ፋይል ይፍጠሩ እና BOT_TOKEN ይጨምሩ።")
        return
    
    if not ADMIN_CHAT_ID:
        print("⚠️ WARNING: ADMIN_CHAT_ID አልተገኘም! አስተዳዳሪ ማሳወቂያዎች አይላኩም።")

    try:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        
        # Conversation Handler
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', start)],
            states={
                ROLE_SELECTION: [
                    CallbackQueryHandler(buyer_start, pattern='^role_buyer$'),
                    CallbackQueryHandler(vendor_start, pattern='^role_vendor$')
                ],
                CATEGORY: [
                    CallbackQueryHandler(category_chosen, pattern='^cat_')
                ],
                SELLER_TYPE: [
                    CallbackQueryHandler(seller_type_chosen, pattern='^seller_')
                ],
                INQUIRY_DETAILS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_inquiry)
                ],
                REG_TYPE: [
                    CallbackQueryHandler(vendor_type_chosen, pattern='^vtype_')
                ],
                REG_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, vendor_name_received)
                ],
                REG_PHONE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, vendor_phone_received)
                ],
            },
            fallbacks=[CommandHandler('cancel', cancel)],
        )
        
        app.add_handler(conv_handler)
        app.add_error_handler(error_handler)
        
        print("🚀 Adika Marketplace Bot is successfully running...")
        print(f"📌 Bot started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🤖 Bot Token: {BOT_TOKEN[:10]}...")
        print(f"👤 Admin ID: {ADMIN_CHAT_ID or 'Not set'}")
        
        app.run_polling()
        
    except Exception as e:
        logger.error(f"Failed to start bot: {e}", exc_info=True)
        print(f"❌ Failed to start bot: {e}")

if __name__ == '__main__':
    main()