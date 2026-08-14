# ==============================================================================
# 17. MAIN ENGINE - FIXED VERSION
# ==============================================================================

def main():
    global bot_app

    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    bot_app = app

    cancel_filter = filters.Regex("^🏠 ዋና ገጽ$")
    cancel_handler = MessageHandler(cancel_filter, go_home)

    # Buyer Conversation
    buyer_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 መግዛት / መከራየት$"), buyer_start)],
        states={
            BUYER_MAIN: [CallbackQueryHandler(buyer_category_chosen, pattern="^flow_buy_cat_"), cancel_handler],
            BUYER_ACTION: [CallbackQueryHandler(buyer_action_chosen, pattern="^flow_buy_action_"), cancel_handler],
            BUYER_SUB: [CallbackQueryHandler(buyer_sub_chosen, pattern="^flow_buy_sub_"), cancel_handler],
            BUYER_PROPERTY: [CallbackQueryHandler(buyer_property_chosen, pattern="^flow_buy_prop_"), cancel_handler],
            BUYER_HTYPE: [CallbackQueryHandler(buyer_htype_chosen, pattern="^flow_buy_htype_"), cancel_handler],
            BUYER_BUDGET_RANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_budget_range), cancel_handler],
            BUYER_ALERT: [CallbackQueryHandler(buyer_alert_choice, pattern="^alert_"), cancel_handler],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_details), cancel_handler],
            BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone), cancel_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    # Seller Conversation
    seller_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📢 መሸጥ / ማከራየት$"), seller_start)],
        states={
            SELLER_MAIN: [CallbackQueryHandler(seller_category_chosen, pattern="^flow_sell_cat_"), cancel_handler],
            SELLER_ACTION: [CallbackQueryHandler(seller_action_chosen, pattern="^flow_sell_action_"), cancel_handler],
            SELLER_SUB: [CallbackQueryHandler(seller_sub_chosen, pattern="^flow_sell_sub_"), cancel_handler],
            SELLER_PROPERTY: [CallbackQueryHandler(seller_property_chosen, pattern="^flow_sell_prop_"), cancel_handler],
            SELLER_HTYPE: [CallbackQueryHandler(seller_htype_chosen, pattern="^flow_sell_htype_"), cancel_handler],
            SELLER_CONDITION: [
                CallbackQueryHandler(seller_condition_chosen, pattern="^flow_sell_cond_"),
                cancel_handler
            ],
            SELLER_HOUSE_CONDITION: [
                CallbackQueryHandler(seller_house_condition_chosen, pattern="^flow_sell_hcond_"),
                cancel_handler
            ],
            SELLER_FUEL: [CallbackQueryHandler(seller_fuel_chosen, pattern="^flow_sell_fuel_"), cancel_handler],
            SELLER_TRANSMISSION: [CallbackQueryHandler(seller_transmission_chosen, pattern="^flow_sell_trans_"), cancel_handler],
            SELLER_MILEAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_mileage), cancel_handler],
            SELLER_BEDROOMS: [CallbackQueryHandler(seller_bedrooms_chosen, pattern="^bed_"), cancel_handler],
            SELLER_PARKING: [CallbackQueryHandler(seller_parking_chosen, pattern="^park_"), cancel_handler],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details), cancel_handler],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price), cancel_handler],
            SELLER_NEGOTIABLE: [CallbackQueryHandler(seller_negotiable_chosen, pattern="^negotiable_"), cancel_handler],
            SELLER_URGENT: [CallbackQueryHandler(seller_urgent_chosen, pattern="^urgent_"), cancel_handler],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone), cancel_handler],
            SELLER_PHOTO: [
                MessageHandler(filters.PHOTO, seller_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_photo),
                cancel_handler
            ],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    # Broker Registration
    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 እንደ አቅራቢ/ደላላ መመዝገብ$"), broker_reg_start)],
        states={
            BROKER_ROLE: [CallbackQueryHandler(broker_role_chosen, pattern="^role_"), cancel_handler],
            BROKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_name), cancel_handler],
            BROKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone), cancel_handler],
            BROKER_SUBCITY: [CallbackQueryHandler(broker_reg_subcity, pattern="^broker_sc_"), cancel_handler],
            BROKER_NID_PHOTO: [MessageHandler(filters.PHOTO, broker_reg_nid_photo), cancel_handler],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    # Broker Offer Response
    broker_response_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(broker_have_item_click, pattern="^have_item_")],
        states={
            BROKER_OFFER_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_text), cancel_handler],
            BROKER_OFFER_PHOTO: [
                MessageHandler(filters.PHOTO, broker_offer_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, broker_offer_photo),
                cancel_handler
            ],
        },
        fallbacks=[CommandHandler("start", start), cancel_handler],
        allow_reentry=True,
    )

    # Register Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)
    app.add_handler(broker_conv)
    app.add_handler(broker_response_conv)

    # ============================================================
    # REGULAR MESSAGE HANDLERS - FIXED VERSION
    # ============================================================
    
    # አዲሱን MarkdownV2 እትም ይጠቀሙ
    app.add_handler(MessageHandler(filters.Regex("^🛍️ የገበያ ቦታ (የሚሸጡ)$"), view_public_marketplace_md))
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ዝርዝር$"), view_requests_md))
    
    # የደላሎች ማውጫ
    app.add_handler(MessageHandler(filters.Regex("^👥 የደላሎች/አቅራቢዎች ማውጫ$"), view_brokers_directory))
    app.add_handler(MessageHandler(filters.Regex("^📞 ድጋፍ$"), help_command))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ የማሳወቂያ ምርጫ$"), notification_prefs_start))
    app.add_handler(cancel_handler)

    # Callback query handlers
    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(admin_approval_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(delete_request_callback, pattern=r"^delete_req_"))
    app.add_handler(CallbackQueryHandler(nohave_item_callback, pattern="^nohave_item_"))
    app.add_handler(CallbackQueryHandler(filter_brokers_by_subcity_callback, pattern="^dir_sc_"))
    app.add_handler(CallbackQueryHandler(mark_sold_callback, pattern="^mark_sold_"))
    app.add_handler(CallbackQueryHandler(have_buyer_callback, pattern="^have_buyer_"))
    app.add_handler(CallbackQueryHandler(want_myself_callback, pattern="^want_myself_"))
    app.add_handler(CallbackQueryHandler(notification_prefs_callback, pattern="^notif_pref_"))
    
    # የገጽ አሰሳ ምላሽ
    app.add_handler(CallbackQueryHandler(marketplace_page_callback, pattern="^mpage_"))
    app.add_handler(CallbackQueryHandler(requests_page_callback, pattern="^rpage_"))

    logger.info("🚀 Adika Marketplace Bot በስኬት ተጀምሯል...")
    app.run_polling()


if __name__ == "__main__":
    main()
