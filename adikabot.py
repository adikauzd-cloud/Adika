import logging
import os
import threading
import re
import asyncio  # ✅ ይህን ይጨምሩ
from typing import Optional, List, Dict, Any
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
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

# ... (የቀደመው ኮድ እንደበፊቱ ይቆያል)

# ==============================================================================
# 5. HELPER FUNCTIONS (የተስተካከለ - asyncio ተጨምሯል)
# ==============================================================================
async def notify_brokers(context: ContextTypes.DEFAULT_TYPE, message_text: str, req_id: int, buyer_id: int):
    """Notify all approved brokers about new listing or request"""
    approved_brokers = get_approved_brokers()
    if not approved_brokers:
        logger.info("No approved brokers found to notify")
        return
    
    logger.info(f"📢 Notifying {len(approved_brokers)} brokers about request #{req_id}")
    
    for b_id in approved_brokers:
        try:
            kbd = [[InlineKeyboardButton(f"👉 አለኝ - #{req_id}", callback_data=f"have_item_{req_id}_{buyer_id}")]]
            await context.bot.send_message(
                chat_id=b_id,
                text=message_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kbd)
            )
            await asyncio.sleep(0.05)  # ትንሽ መዘግየት ለመጨመር
        except Exception as e:
            logger.error(f"Failed to send notification to broker {b_id}: {e}")

# ==============================================================================
# 7. BUYER FLOW (የተስተካከለ - asyncio ተጨምሯል)
# ==============================================================================
async def buyer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    phone = update.message.text
    
    if phone == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if not validate_phone(phone):
        await update.message.reply_text("❌ ስልክ ቁጥሩ ትክክል አይደለም! እባክዎ እንደገና ያስገቡ።")
        return BUYER_PHONE
    
    main_cat = context.user_data.get('main_category', '')
    sub_cat = context.user_data.get('sub_category', '')
    action_type = context.user_data.get('action_type', '')
    prop_subtype = context.user_data.get('property_subtype', '')
    description = context.user_data.get('description', '')
    
    category_title = "🚗 አዲስ የመኪና ጥያቄ" if main_cat == "car" else "🏠 አዲስ የቤት/ቦታ ጥያቄ"
    
    full_desc = (
        f"📌 **{category_title}**\n"
        f"🔹 አይነት: {prop_subtype if prop_subtype else sub_cat}\n"
        f"🔄 ፍላጎት: {action_type}\n"
        f"📝 ዝርዝር: {description}\n"
        f"📞 ስልክ: {phone}"
    )
    
    req_id = add_listing(user.id, user.first_name, 'BUY', main_cat, sub_cat, action_type, prop_subtype, full_desc)
    
    if req_id:
        await update.message.reply_text(
            f"✅ **ጥያቄዎ በጥሩ ሁኔታ ተመዝግቧል!** (#REQ-{req_id})\n\n"
            f"📌 ጥያቄዎ ለተረጋገጡ ደላሎች የተላከ ሲሆን፣ ንብረቱ ያላቸው ደላሎች አማራጮችን ሲልኩልዎ እዚሁ ቴሌግራም ላይ ይደርስዎታል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        # ✅ ለደላሎች ማሳወቅ - asyncio ተጨምሯል
        notification_text = (
            f"🔔 **{category_title}! (#REQ-{req_id})**\n\n"
            f"{full_desc}\n\n"
            f"👉 ይህ ንብረት በእጅዎ ካለ ከታች **'አለኝ'** የሚለውን በመጫን ለፈላጊው መረጃ ይላኩ!"
        )
        await notify_brokers(context, notification_text, req_id, user.id)
    else:
        await update.message.reply_text("❌ ጥያቄውን መመዝገብ አልተቻለም። እባክዎ እንደገና ይሞክሩ።")

    return ConversationHandler.END

# ==============================================================================
# 8. SELLER FLOW (የተስተካከለ - asyncio ተጨምሯል)
# ==============================================================================
async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    
    if not photo_id:
        await update.message.reply_text("📸 **ፎቶ አልተላከም**\n\nያለ ፎቶ ማስታወቂያዎን ማስመዝገብ ይችላሉ።")
    
    property_subtype = context.user_data.get('property_subtype', '')
    description = context.user_data.get('description', '')
    if property_subtype:
        description = f"🏠 {property_subtype}\n{description}"
    
    desc = (
        f"📢 **አዲስ የሽያጭ/ኪራይ ማስታወቂያ!**\n"
        f"🔄 አይነት: {context.user_data.get('action_type')}\n"
        f"📝 ዝርዝር: {description}\n"
        f"💰 ዋጋ: {context.user_data.get('price')} ብር\n"
        f"📞 ስልክ: {context.user_data.get('phone')}"
    )
    
    req_id = add_listing(
        user.id, 
        user.first_name, 
        'SELL', 
        context.user_data.get('main_category'), 
        context.user_data.get('sub_category', ''), 
        context.user_data.get('action_type'), 
        context.user_data.get('property_type', ''), 
        desc
    )
    
    if req_id:
        await update.message.reply_text(
            "✅ **ማስታወቂያዎ በስኬት ተመዝግቧል!** 🎉\n\n"
            "📌 ማስታወቂያዎ ለደላሎች ተልኳል።\n"
            "📋 '📋 የፈላጊዎች ዝርዝር' ውስጥ ይታያል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        
        # ✅ ለደላሎች ማሳወቅ - asyncio ተጨምሯል
        notification_text = (
            f"📢 **አዲስ የሽያጭ/ኪራይ ማስታወቂያ!**\n\n"
            f"{desc}\n\n"
            f"👉 ይህን ማስታወቂያ ለፈላጊዎች ማሳወቅ ይችላሉ!"
        )
        await notify_brokers(context, notification_text, req_id, user.id)
    else:
        await update.message.reply_text(
            "❌ ማስታወቂያውን መመዝገብ አልተቻለም።\n\n"
            "💡 እባክዎ እንደገና ይሞክሩ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
    
    return ConversationHandler.END

# ==============================================================================
# 15. MAIN ENGINE (የተስተካከለ)
# ==============================================================================
def main():
    # ✅ asyncio ተጨምሯል
    import asyncio
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))

    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_message_handler = MessageHandler(cancel_filter, go_home)

    # Buyer conversation
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
        states={
            BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_message_handler],
            BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_"), cancel_message_handler],
            BUYER_SUB: [CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_"), CallbackQueryHandler(buyer_htype_chosen, pattern="^flow_buy_htype_"), cancel_message_handler],
            BUYER_PROPERTY: [CallbackQueryHandler(buyer_property_chosen, pattern="^flow_buy_prop_"), cancel_message_handler],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details), cancel_message_handler],
            BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # Seller conversation
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_"), cancel_message_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_message_handler],
            SELLER_SUB: [CallbackQueryHandler(seller_sub_chosen, pattern="^flow_sell_sub_"), CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_"), cancel_message_handler],
            SELLER_PROPERTY: [CallbackQueryHandler(seller_property_chosen, pattern="^flow_sell_prop_"), cancel_message_handler],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details), cancel_message_handler],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price), cancel_message_handler],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone), cancel_message_handler],
            SELLER_PHOTO: [MessageHandler(filters.PHOTO, seller_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # Broker registration conversation
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ/ደላላ መመዝገብ$"), broker_reg_start)],
        states={
            BROKER_ROLE: [CallbackQueryHandler(broker_role_chosen, pattern="^role_"), cancel_message_handler],
            BROKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name), cancel_message_handler],
            BROKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone), cancel_message_handler],
            BROKER_SUBCITY: [CallbackQueryHandler(broker_reg_subcity, pattern="^broker_sc_"), cancel_message_handler],
            BROKER_NID_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, broker_reg_nid_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # Broker response conversation
    broker_response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broker_have_item_click, pattern="^have_item_")],
        states={
            BROKER_OFFER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text), cancel_message_handler],
            BROKER_OFFER_PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, broker_offer_photo), cancel_message_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_message_handler],
        allow_reentry=True,
    )

    # ✅ ሁሉም handlers ተጨምረዋል
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(MessageHandler(cancel_filter, go_home))
    app.add_handler(CallbackQueryHandler(show_requests_page, pattern="^page_"))
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(admin_approval_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(admin_delete_listing, pattern="^admin_delete_"))
    app.add_handler(CallbackQueryHandler(filter_requests, pattern="^filter_"))
    app.add_handler(CallbackQueryHandler(search_requests, pattern="^search_requests$"))
    app.add_handler(CallbackQueryHandler(refresh_listings, pattern="^refresh_listings$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_input))

    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(broker_response_conv)

    logger.info("🚀 Adika Marketplace Bot ተጀምሯል...")
    app.run_polling()

if __name__ == "__main__":
    main()
