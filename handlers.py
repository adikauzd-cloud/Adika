# ==============================================================================
# handlers.py — Telegram bot handlers, keyboards, conversations
# ==============================================================================
import json
import os
import asyncio
import re
from datetime import datetime
from typing import Optional

from telegram import (
    Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup,
    WebAppInfo, KeyboardButton, ReplyKeyboardRemove,
)
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
)

from config import (
    logger, MAIN_KEYBOARD, ADMIN_CHAT_ID_INT, ADMIN_IDS,
    SUB_CITIES, TEXT_PAGE_SIZE, VIEW_INCREMENT, WEBAPP_URL, RENDER_EXTERNAL_HOSTNAME,
    SUPPORT_ADMIN_URL, SUPPORT_ADMIN_HANDLE,
    CAR_SUB_CATEGORIES, HOUSE_TYPES, PROPERTY_TYPES,
    FUEL_TYPES, TRANSMISSION_TYPES, CONDITIONS,
    BROKER_CATEGORIES, BROKER_REG_SUBCITIES,
)
from models import (
    add_listing, get_listing_by_id, get_listings_by_category_ordered,
    count_listings, update_listing_status, get_public_marketplace_items,
    add_broker, get_broker, update_broker_status, update_broker_notification_prefs,
    get_approved_brokers, get_approved_brokers_directory, get_active_brokers,
    add_broker_rating, save_broker_offer, save_search_alert, get_matching_alerts,
    increment_listing_views,
    delete_broker,
)

# Conversation states — match monolith
(
    BUYER_MAIN, BUYER_ACTION, BUYER_SUB, BUYER_PROPERTY, BUYER_HTYPE,
    BUYER_DETAILS, BUYER_PHONE, BUYER_BUDGET_RANGE, BUYER_ALERT,
    SELLER_MAIN, SELLER_ACTION, SELLER_SUB, SELLER_PROPERTY, SELLER_HTYPE,
    SELLER_DETAILS, SELLER_PRICE, SELLER_NEGOTIABLE, SELLER_URGENT,
    SELLER_CONDITION, SELLER_FUEL, SELLER_TRANSMISSION, SELLER_MILEAGE,
    SELLER_BEDROOMS, SELLER_PARKING, SELLER_PHONE, SELLER_PHOTO, SELLER_HOUSE_CONDITION,
    BROKER_NAME, BROKER_PHONE, BROKER_CATEGORY, BROKER_SUBCITY, BROKER_FAYDA,
    BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO,
) = range(34)

def validate_phone(phone: str) -> bool:
    if not phone:
        return False
    phone = phone.replace(' ', '').replace('-', '').replace('+', '')
    if re.match(r'^(09|07|01)\d{8}$', phone):
        return True
    if re.match(r'^(9|7)\d{8}$', phone):
        return True
    if re.match(r'^251(9|7)\d{8}$', phone):
        return True
    return False

def validate_contact(contact: str) -> bool:
    if not contact:
        return False
    contact = contact.strip()
    if contact.startswith('@'):
        username = contact[1:]
        if re.match(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$', username):
            return True
        return False
    return validate_phone(contact)

def validate_price(price: str) -> bool:
    price = price.replace(',', '').replace(' ', '')
    return price.isdigit()

def clean_description(desc: str, max_len: int = 60) -> str:
    if not desc:
        return ""
    junk = [
        'ዋጋ:', 'ስልክ:', 'አዲስ የሽያጭ', 'WebApp', 'አስቸኳይ ሽያጭ', 'መግለጫ:',
        '📝', '💰', '📞', '⚡', '📢', '🔄', '📦', 'NEW', 'እዱስ',
        '🔥 ለሽያጭ', '🔥 አሸጋጭ', 'የገበያ ቦታ', 'ለሽያጭ', 'ለኪራይ',
        'አይነት:', 'ምድብ:', 'ሁኔታ:', 'ነዳጅ:', 'ማርሽ:', 'ኪሎሜትር:',
        'መሸጥ', 'ማከራየት', 'መግዛት', 'መከራየት',
        '🚗', '🏠', '✨', '🔍', '🛏️', '🛁', '⛽', '⚙️', '🛣️', '📊',
        '🏡', '🏢', '🚚', '🚜', '✅', '❌', '⭐', '👤', '📍', '📛',
        '🎯', '🔔', '🛍️', '🔑', '📌', '💡', '🎉', '⏳', '⛔'
    ]
    clean = desc
    for j in junk:
        clean = clean.replace(j, '')
    clean = ' '.join(line.strip() for line in clean.splitlines() if line.strip())
    clean = ' '.join(clean.split())
    if len(clean) > max_len:
        clean = clean[:max_len] + "..."
    return clean.strip()

def relative_time_am(created_at) -> str:
    """Relative time in clean English (Just now, 5m ago, 2 hrs ago, Yesterday…)."""
    if not created_at:
        return ""
    try:
        if isinstance(created_at, str):
            ts = created_at.replace("Z", "+00:00")
            try:
                from datetime import datetime as _dt
                dt = _dt.fromisoformat(ts)
            except Exception:
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        dt = datetime.strptime(created_at[:26], fmt)
                        break
                    except Exception:
                        dt = None
                if dt is None:
                    return ""
        else:
            dt = created_at
        if getattr(dt, "tzinfo", None) is not None:
            dt = dt.replace(tzinfo=None)
        now = datetime.utcnow()
        secs = max(0, int((now - dt).total_seconds()))
        if secs < 60:
            return "Just now"
        if secs < 3600:
            m = secs // 60
            return f"{m}m ago"
        if secs < 86400:
            h = secs // 3600
            return f"{h} hr{'s' if h != 1 else ''} ago"
        if secs < 172800:
            return "Yesterday"
        days = secs // 86400
        if days < 30:
            return f"{days}d ago"
        months = days // 30
        if months < 12:
            return f"{months} mo ago"
        years = days // 365
        return f"{years}y ago"
    except Exception:
        return ""



def format_marketplace_card_professional(item: dict) -> str:
    """Text-mode card for Seller Listings and Buyer Requests."""
    item_id = item.get('id', 'N/A')
    main_cat = item.get('main_category', '')
    sub_cat = (item.get('sub_category') or '').strip()
    price = item.get('price', '-')
    phone = item.get('phone', '-')
    action = item.get('action_type', '')
    req_type = str(item.get('req_type', '')).upper()
    status = str(item.get('status', 'pending')).lower()
    views = item.get('view_count') or 0

    extra = item.get('extra_data', {})
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}

    # --- Header badge ---
    if req_type == "BUY":
        header = f"🎯  <code>#ADK-{item_id}</code>"
        price_label = "በጀት"
        price_display = f"💰 <b>{price_label}:</b> {extra.get('budget_range') or price or '—'} ብር"
    else:
        if status in ('sold', 'rented'):
            header = f"🔴 Sold Out  ·  <code>#ADK-{item_id}</code>"
        else:
            header = f"🟢  <code>#ADK-{item_id}</code>"
        negotiable = "የሚደራደር" if extra.get('negotiable', True) else "የማይደራደር"
        urgent = " ⚡ አስቸኳይ" if extra.get('urgent_sale') else ""
        price_display = f"💰 <b>ዋጋ:</b> {price} ብር <i>({negotiable})</i>{urgent}"

    title_display = main_cat or "ንብረት"
    if sub_cat:
        clean_sub = sub_cat.replace('🚗', '').replace('🚚', '').replace('🚜', '').strip()
        if clean_sub:
            title_display += f" ({clean_sub})"

    details = []
    if main_cat in ["መኪና", "car", "CAR"]:
        if extra.get('condition'): details.append(f"├ ሁኔታ: {extra['condition']}")
        if extra.get('fuel_type'): details.append(f"├ ነዳጅ: {extra['fuel_type']}")
        if extra.get('transmission'): details.append(f"├ ማርሽ: {extra['transmission']}")
        if extra.get('mileage'): details.append(f"├ ኪሎሜትር: {extra['mileage']} KM")
        if extra.get('car_type'):
            ct = str(extra['car_type']).replace('🚗', '').replace('🚚', '').replace('🚜', '').strip()
            if ct: details.append(f"├ አይነት: {ct}")
    else:
        if extra.get('condition'): details.append(f"├ ሁኔታ: {extra['condition']}")
        if extra.get('bedrooms'): details.append(f"├ መኝታ: {extra['bedrooms']}")
        if extra.get('bathrooms'): details.append(f"├ መታጠቢያ: {extra['bathrooms']}")
        if extra.get('parking'): details.append(f"├ ፓርኪንግ: {extra['parking']}")
        if extra.get('house_type'):
            ht = str(extra['house_type']).replace('🏠', '').replace('🏢', '').replace('🏡', '').strip()
            if ht: details.append(f"├ አይነት: {ht}")

    rel = relative_time_am(item.get('created_at'))
    lines = [
        header,
        "━━━━━━━━━━━━━━━━━━━━━",
        f"📌 <b>{title_display}</b>",
        price_display,
    ]
    if details:
        lines.append("")
        lines.append("⚙️ ዝርዝር")
        lines.extend(details)

    desc = clean_description(item.get('description', ''), 60)
    if desc:
        lines.append("")
        lines.append(f"📝 {desc}")

    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"👁️ {views} views" + (f"  ·  {rel}" if rel else ""))
    lines.append(f"📞 <code>{phone}</code>")
    return "\n".join(lines)


def format_seller_card(item: dict) -> str:
    return format_marketplace_card_professional(item)

def format_buyer_card(req: dict) -> str:
    return format_marketplace_card_professional(req)

def format_broker_profile_professional(b: dict) -> str:
    """Top badge row: green dot + online + Verified (not next to name)."""
    if not isinstance(b, dict):
        return "👤 —"
    try:
        rating = float(b.get("rating") or 5.0)
    except (TypeError, ValueError):
        rating = 5.0
    online = b.get("is_online", True)
    if online in (0, "0", False, "false", "False"):
        online = False
    if b.get("is_online") is None:
        online = True
    verified = str(b.get("status", "")).lower() in ("approved", "online") or bool(b.get("is_verified"))

    def _esc(v):
        s = str(v if v is not None else "—")
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    name = _esc(b.get("full_name") or "—")
    area = _esc(b.get("sub_city") or "—")
    role = _esc(b.get("specialty") or b.get("role_type") or "—")
    if online:
        status_line = "🟢 online"
    else:
        status_line = "⚪ offline"
    if verified:
        status_line += "  ·  🔵 Verified"
    return (
        f"{status_line}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 {name}\n"
        f"📍 {area}\n"
        f"💼 {role}\n"
        f"⭐ {rating:.1f} / 5.0"
    )



def get_nav_buttons(back_callback: str = None) -> list:
    buttons = []
    if back_callback:
        buttons.append(InlineKeyboardButton("⬅️ ተመለስ", callback_data=back_callback))
    buttons.append(InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home"))
    return buttons

def build_request_keyboard(req_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ አለኝ", callback_data=f"have_item_{req_id}_{user_id}"),
            InlineKeyboardButton("⏭️ ይለፈኝ", callback_data=f"nohave_item_{req_id}")
        ]
    ])

def build_seller_card_keyboard(item_id: int, owner_id: int, current_user_id: int, phone: str = "") -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🤝 ገዢ አለኝ", callback_data=f"have_buyer_{item_id}_{owner_id}"),
            InlineKeyboardButton("👤 ለራሴ ነው", callback_data=f"want_myself_{item_id}")
        ]
    ]
    if current_user_id == owner_id or current_user_id == ADMIN_CHAT_ID_INT:
        keyboard.append([
            InlineKeyboardButton("✅ Sold Out", callback_data=f"mark_sold_{item_id}")
        ])
    return InlineKeyboardMarkup(keyboard)

def build_marketplace_keyboard_clean(item_id: int, owner_id: int, current_user_id: int) -> InlineKeyboardMarkup:
    return build_seller_card_keyboard(item_id, owner_id, current_user_id)

def build_request_keyboard_clean(req_id: int, buyer_id: int) -> InlineKeyboardMarkup:
    return build_request_keyboard(req_id, buyer_id)

async def notify_brokers(bot, message_text: str, req_id: int, buyer_id: int, photos: list = None):
    try:
        approved_brokers = get_approved_brokers()
        if not approved_brokers:
            logger.warning("No approved brokers found")
            return
        
        listing = get_listing_by_id(req_id)
        if not listing:
            logger.error(f"Listing {req_id} not found")
            return
        
        main_category = listing.get('main_category', '')
        req_type = str(listing.get('req_type', 'BUY')).upper()
        owner_id = listing.get('user_chat_id')
        sent_count = 0
        
        for broker in approved_brokers:
            try:
                b_id = broker.get('chat_id')
                if not b_id:
                    continue
                
                prefs = broker.get('notification_prefs', {})
                if isinstance(prefs, str):
                    try: 
                        prefs = json.loads(prefs)
                    except: 
                        prefs = {}
                
                if not prefs.get('enabled', True):
                    continue
                if main_category in ['መኪና', 'car', 'CAR'] and not prefs.get('car', True):
                    continue
                if main_category in ['ቤት', 'house'] and not prefs.get('house', True):
                    continue
                
                if req_type == "SELL":
                    kbd = [[
                        InlineKeyboardButton("🤝 ገዢ አለኝ", callback_data=f"have_buyer_{req_id}_{owner_id}"),
                        InlineKeyboardButton("👤 ለራሴ", callback_data=f"want_myself_{req_id}")
                    ]]
                else:
                    kbd = [[
                        InlineKeyboardButton("✅ አለኝ", callback_data=f"have_item_{req_id}_{buyer_id}"),
                        InlineKeyboardButton("⏭️ ይለፈኝ", callback_data=f"nohave_item_{req_id}")
                    ]]
                
                if photos and len(photos) > 0:
                    try:
                        await bot.send_photo(
                            chat_id=b_id,
                            photo=photos[0],
                            caption=message_text,
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup(kbd)
                        )
                    except Exception as e:
                        logger.error(f"Failed to send photo to broker {b_id}: {e}")
                        await bot.send_message(
                            chat_id=b_id,
                            text=message_text,
                            parse_mode="HTML",
                            reply_markup=InlineKeyboardMarkup(kbd)
                        )
                else:
                    await bot.send_message(
                        chat_id=b_id,
                        text=message_text,
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(kbd)
                    )
                sent_count += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                logger.error(f"Notify broker error: {e}")
        
        logger.info(f"✅ Sent to {sent_count} brokers for #ADK-{req_id}")
    except Exception as e:
        logger.error(f"notify_brokers error: {e}", exc_info=True)

# ==============================================================================
# 8. START & HOME HANDLERS
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
   context.user_data.clear()
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

async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
   context.user_data.clear()
   welcome_text = "👋 **ወደ ዋና ገጽ ተመልሰዋል!**\n\nእባክዎን አማራጭ ይምረጡ፦"
   reply_markup = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
   if update.message:
       await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=reply_markup)
   elif update.callback_query:
       query = update.callback_query
       await query.answer()
       try:
           await query.delete_message()
       except Exception:
           pass
       await context.bot.send_message(
           chat_id=update.effective_user.id,
           text=welcome_text,
           parse_mode="Markdown",
           reply_markup=reply_markup
       )
   return ConversationHandler.END


# ==============================================================================
# 9. BUYER FLOW
# ==============================================================================

async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["req_type"] = "BUY"
    web_app_url = f"{WEBAPP_URL}/buyer-form"
    keyboard = [
        [InlineKeyboardButton("⚡ በቅጽ መሙያ (Mini App)", web_app=WebAppInfo(url=web_app_url))],
        [InlineKeyboardButton("🚗 መኪና", callback_data="flow_buy_cat_car")],
        [InlineKeyboardButton("🏠 ቤት እና ቦታ", callback_data="flow_buy_cat_house")],
        [InlineKeyboardButton("🏢 የንግድ ቦታ", callback_data="flow_buy_cat_commercial")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "🔍 <b>ምድብ ይምረጡ</b>\n\n"
        "💡 በአንድ ገጽ ላይ በቀላሉ ለመሙላት Mini App ይጠቀሙ።",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return BUYER_MAIN


async def buyer_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   cat = query.data.replace("flow_buy_cat_", "")
   context.user_data['main_category'] = cat
   if cat == "car":
       keyboard = [[InlineKeyboardButton(sub, callback_data=f"flow_buy_sub_{sub}")] for sub in CAR_SUB_CATEGORIES]
       keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
       await query.edit_message_text(
           "🚗 **የመኪና አይነት/ሞዴል ይምረጡ፦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return BUYER_SUB
   else:
       keyboard = [
           [InlineKeyboardButton("🛍️ መግዛት", callback_data="flow_buy_action_buy")],
           [InlineKeyboardButton("🔑 መከራየት", callback_data="flow_buy_action_rent")],
           [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
       ]
       await query.edit_message_text(
           "❓ **የሚፈልጉትን የድርጊት አይነት ይምረጡ፦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return BUYER_ACTION

async def buyer_sub_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   sub = query.data.replace("flow_buy_sub_", "")
   context.user_data['sub_category'] = sub
   keyboard = [
       [InlineKeyboardButton("🛍️ መግዛት", callback_data="flow_buy_action_buy")],
       [InlineKeyboardButton("🔑 መከራየት", callback_data="flow_buy_action_rent")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       f"✅ {sub}\n\n❓ **የሚፈልጉትን የድርጊት አይነት ይምረጡ፦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return BUYER_ACTION

async def buyer_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   action = query.data.replace("flow_buy_action_", "")
   context.user_data['action_type'] = "መግዛት" if action == "buy" else "መከራየት"
   await query.edit_message_text(
       "💰 **የበጀት ክልልዎን ያስገቡ፦**\n\n"
       "💡 *ምሳሌ፦* `500000-1000000` (ከ 500ሺህ እስከ 1 ሚሊዮን ብር)\n"
       "ወይም አንድ ቁጥር ብቻ ያስገቡ (ለምሳሌ 2000000)",
       parse_mode="Markdown"
   )
   return BUYER_BUDGET_RANGE

async def buyer_budget_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   context.user_data['budget_range'] = update.message.text.strip()
   keyboard = [
       [InlineKeyboardButton("✅ አዎ - ማሳወቂያ ይድረሰኝ", callback_data="alert_yes")],
       [InlineKeyboardButton("❌ አይ - አያስፈልገኝም", callback_data="alert_no")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await update.message.reply_text(
       "🔔 **ተመሳሳይ ንብረት ሲለቀቅ ማሳወቂያ እንዲደርስዎት ይፈልጋሉ?**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return BUYER_ALERT

async def buyer_alert_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   context.user_data['create_alert'] = (query.data == "alert_yes")
   if context.user_data.get('main_category') == "car":
       await query.edit_message_text(
           "✍️ **የሚፈልጉትን መኪና ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020፣ ነጭ ቀለም፣ ኦቶማቲክ",
           parse_mode="Markdown"
       )
       return BUYER_DETAILS
   else:
       keyboard = [[InlineKeyboardButton(ptype, callback_data=f"flow_buy_prop_{ptype}")] for ptype in PROPERTY_TYPES]
       keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
       await query.edit_message_text(
           "🏠 **የንብረት አይነት ይምረጡ፦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return BUYER_PROPERTY

async def buyer_property_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   prop = query.data.replace("flow_buy_prop_", "")
   context.user_data['property_type'] = prop
   keyboard = [[InlineKeyboardButton(htype, callback_data=f"flow_buy_htype_{htype}")] for htype in HOUSE_TYPES]
   keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
   await query.edit_message_text(
       "🏠 **የቤቱ አይነት ይምረጡ፦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return BUYER_HTYPE

async def buyer_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   htype = query.data.replace("flow_buy_htype_", "")
   context.user_data['property_subtype'] = htype
   await query.edit_message_text(
       f"🏠 **የቤቱ አይነት፦ {htype}**\n\n✍️ **የሚፈልጉትን ቤት/ቦታ ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቦሌ 2 መኝታ፣ ፓርኪንግ ያለው",
       parse_mode="Markdown"
   )
   return BUYER_DETAILS

async def buyer_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   context.user_data['description'] = update.message.text
   await update.message.reply_text(
       "📞 <b>ስልክ ቁጥር (አማራጭ)</b>\n\n"
       "🔒 ለግላዊነትዎ ስልክ <b>መስጠት አይገደዱም</b>።\n"
       "ደላሎች በ Telegram ብቻ ሊያገኙዎት ይችላሉ።\n\n"
       "💡 ስልክ ካለዎት ያስገቡ ወይም @username\n"
       "⏭️ ለመዝለል «አልፋለሁ» ይጫኑ።",
       parse_mode="HTML",
       reply_markup=ReplyKeyboardMarkup(
           [["⏭️ አልፋለሁ"], ["🏠 ዋና ገጽ"]],
           resize_keyboard=True,
       ),
   )
   return BUYER_PHONE

async def buyer_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phone OPTIONAL — privacy-first."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    text = (update.message.text or "").strip()
    user = update.effective_user
    telegram_user = ""
    phone = ""
    skip_tokens = {"⏭️ አልፋለሁ", "አልፋለሁ", "skip", "Skip", "SKIP", "-", "—", "."}

    if text not in skip_tokens:
        username_match = re.search(r"@\w+", text)
        if username_match:
            telegram_user = username_match.group()
            phone = text.replace(telegram_user, "").strip()
        else:
            phone = text
        digits = re.sub(r"\D", "", phone or "")
        if phone and digits and not validate_phone(phone):
            await update.message.reply_text(
                "❌ ትክክለኛ ስልክ (0911223344) ወይም «⏭️ አልፋለሁ» ይጫኑ።"
            )
            return BUYER_PHONE
        if phone and not digits:
            phone = ""

    if not telegram_user and user.username:
        telegram_user = f"@{user.username}"

    context.user_data["phone"] = phone
    context.user_data["telegram_user"] = telegram_user
    user_data = context.user_data
    desc = user_data.get("description", "")
    budget = user_data.get("budget_range", "")
    main_category = user_data.get("main_category", "")
    if user_data.get("property_subtype"):
        desc = f"🏠 {user_data.get('property_subtype')}\n{desc}"

    try:
        req_id = add_listing(
            user_chat_id=user.id,
            user_name=user.first_name or "User",
            req_type="BUY",
            main_category=main_category,
            sub_category=user_data.get("sub_category", ""),
            action_type=user_data.get("action_type", "መግዛት"),
            property_type=user_data.get("property_type", ""),
            description=desc,
            price=budget,
            phone=phone or "",
            extra_data={
                "create_alert": user_data.get("create_alert", False),
                "budget_range": budget,
                "telegram_user": telegram_user,
                "privacy_phone_skipped": not bool(phone),
            },
        )
        if req_id:
            phone_line = f"📞 ስልክ: {phone}\n" if phone else "🔒 ስልክ: የተደበቀ (Telegram ብቻ)\n"
            tg_line = f"📱 Telegram: {telegram_user}\n" if telegram_user else ""
            await update.message.reply_text(
                f"✅ <b>ማስታወቂያዎ በተሳካ ሁኔታ ተመዝግቧል! ለደላሎችም ተልኳል። ማስታወቂያዎን ማጥፋት ወይም ማስተካከል ሲፈልጉ በማንኛውም ጊዜ ወደ 'የገበያ ቦታ' በመሄድ ማስተካከል ይችላሉ።</b>\n\n"
                f"🆔 #ADK-{req_id}\n"
                f"📌 {main_category}\n"
                f"{phone_line}{tg_line}\n"
                "ደላሎች offer ይልኩልዎታል።",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
                parse_mode="HTML",
            )
            contact_display = phone or telegram_user or f"tg://user?id={user.id}"
            notification_text = format_marketplace_card_professional({
                "id": req_id,
                "main_category": main_category,
                "sub_category": user_data.get("sub_category", ""),
                "action_type": user_data.get("action_type", "መግዛት"),
                "req_type": "BUY",
                "description": desc,
                "price": budget,
                "phone": contact_display if phone else "Telegram only",
                "status": "pending",
                "view_count": 0,
                "extra_data": {"budget_range": budget, "telegram_user": telegram_user},
            })
            if not phone:
                notification_text = re.sub(
                    r"📞 <code>.*?</code>",
                    "🔒 <i>Contact via Telegram only</i>",
                    notification_text,
                )
            try:
                await notify_brokers(context.bot, notification_text, req_id, user.id, photos=None)
            except Exception as ne:
                logger.error(f"notify_brokers: {ne}", exc_info=True)
        else:
            await update.message.reply_text(
                "❌ ጥያቄ ማስቀመጥ አልተቻለም።",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            )
    except Exception as e:
        logger.error(f"buyer_phone save: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ ስህተት። እንደገና ይሞክሩ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
        )
    context.user_data.clear()
    return ConversationHandler.END


async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["req_type"] = "SELL"
    web_app_url = f"{WEBAPP_URL}/seller-form"
    keyboard = [
        [InlineKeyboardButton("⚡ በቅጽ መሙያ (Mini App)", web_app=WebAppInfo(url=web_app_url))],
        [InlineKeyboardButton("🚗 መኪና", callback_data="flow_sell_cat_car")],
        [InlineKeyboardButton("🏠 ቤት እና ቦታ", callback_data="flow_sell_cat_house")],
        [InlineKeyboardButton("🏢 የንግድ ቦታ", callback_data="flow_sell_cat_commercial")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "🔍 <b>ምድብ ይምረጡ</b>\n\n"
        "💡 በአንድ ገጽ ላይ በቀላሉ ለመሙላት Mini App ይጠቀሙ።",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return SELLER_MAIN


async def seller_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   cat = query.data.replace("flow_sell_cat_", "")
   context.user_data['main_category'] = cat
   if cat == "car":
       keyboard = [[InlineKeyboardButton(sub, callback_data=f"flow_sell_sub_{sub}")] for sub in CAR_SUB_CATEGORIES]
       keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
       await query.edit_message_text(
           "🚗 **የመኪና አይነት/ሞዴል ይምረጡ፦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return SELLER_SUB
   else:
       keyboard = [
           [InlineKeyboardButton("🛍️ መሸጥ", callback_data="flow_sell_action_sell")],
           [InlineKeyboardButton("🔑 ማከራየት", callback_data="flow_sell_action_rent")],
           [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
       ]
       await query.edit_message_text(
           "❓ **የድርጊት አይነት ይምረጡ፦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return SELLER_ACTION

async def seller_sub_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   sub = query.data.replace("flow_sell_sub_", "")
   context.user_data['sub_category'] = sub
   keyboard = [
       [InlineKeyboardButton("🛍️ መሸጥ", callback_data="flow_sell_action_sell")],
       [InlineKeyboardButton("🔑 ማከራየት", callback_data="flow_sell_action_rent")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       f"✅ {sub}\n\n❓ **የድርጊት አይነት ይምረጡ፦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_ACTION

async def seller_action_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   action = query.data.replace("flow_sell_action_", "")
   context.user_data['action_type'] = "መሸጥ" if action == "sell" else "ማከራየት"
   if context.user_data.get('main_category') == "car":
       keyboard = [[InlineKeyboardButton(cond, callback_data=f"flow_sell_cond_{cond}")] for cond in CONDITIONS]
       keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
       await query.edit_message_text(
           "📊 **የመኪናውን ሁኔታ ይምረጡ፦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return SELLER_CONDITION
   else:
       keyboard = [[InlineKeyboardButton(ptype, callback_data=f"flow_sell_prop_{ptype}")] for ptype in PROPERTY_TYPES]
       keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
       await query.edit_message_text(
           "🏠 **የንብረት አይነት ይምረጡ፦**",
           reply_markup=InlineKeyboardMarkup(keyboard),
           parse_mode="Markdown"
       )
       return SELLER_PROPERTY

async def seller_condition_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   cond = query.data.replace("flow_sell_cond_", "")
   context.user_data['condition'] = cond
   keyboard = [[InlineKeyboardButton(ftype, callback_data=f"flow_sell_fuel_{ftype}")] for ftype in FUEL_TYPES]
   keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
   await query.edit_message_text(
       f"✅ **ሁኔታ:** {cond}\n\n⛽ **የነዳጅ አይነት ይምረጡ፦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_FUEL

async def seller_fuel_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   fuel = query.data.replace("flow_sell_fuel_", "")
   context.user_data['fuel_type'] = fuel
   keyboard = [[InlineKeyboardButton(ttype, callback_data=f"flow_sell_trans_{ttype}")] for ttype in TRANSMISSION_TYPES]
   keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
   await query.edit_message_text(
       f"⛽ **ነዳጅ:** {fuel}\n\n⚙️ **የማርሽ አይነት ይምረጡ፦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_TRANSMISSION

async def seller_transmission_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   trans = query.data.replace("flow_sell_trans_", "")
   context.user_data['transmission'] = trans
   await query.edit_message_text(
       f"⚙️ **ማርሽ:** {trans}\n\n🛣️ **የኪሎሜትር መጠን ያስገቡ (KM)፦**\n\n💡 *ለምሳሌ፦* 50000",
       parse_mode="Markdown"
   )
   return SELLER_MILEAGE

async def seller_mileage(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   if not update.message.text.isdigit():
       await update.message.reply_text("❌ እባክዎ ቁጥር ብቻ ያስገቡ።")
       return SELLER_MILEAGE
   context.user_data['mileage'] = update.message.text
   await update.message.reply_text(
       "✍️ **የመኪናውን ዝርዝር መረጃ ያስገቡ፦**\n\n💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2020፣ ነጭ፣ አዲስ ጎማ፣ አክሲደንት ያልገጠመው",
       parse_mode="Markdown"
   )
   return SELLER_DETAILS

async def seller_property_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   prop = query.data.replace("flow_sell_prop_", "")
   context.user_data['property_type'] = prop
   keyboard = [[InlineKeyboardButton(htype, callback_data=f"flow_sell_htype_{htype}")] for htype in HOUSE_TYPES]
   keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
   await query.edit_message_text(
       "🏠 **የቤቱ አይነት ይምረጡ፦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_HTYPE

async def seller_htype_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   htype = query.data.replace("flow_sell_htype_", "")
   context.user_data['property_subtype'] = htype
   conditions = ["🆕 አዲስ", "✅ ጥሩ", "🔧 እድሳት የሚፈልግ"]
   keyboard = [[InlineKeyboardButton(cond, callback_data=f"flow_sell_hcond_{cond}")] for cond in conditions]
   keyboard.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
   await query.edit_message_text(
       f"🏠 **የቤቱ አይነት፦** {htype}\n\n📊 **የቤቱን ሁኔታ ይምረጡ፦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_HOUSE_CONDITION

async def seller_house_condition_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   cond = query.data.replace("flow_sell_hcond_", "")
   context.user_data['condition'] = cond
   keyboard = [
       [InlineKeyboardButton("1", callback_data="bed_1"), InlineKeyboardButton("2", callback_data="bed_2")],
       [InlineKeyboardButton("3", callback_data="bed_3"), InlineKeyboardButton("4", callback_data="bed_4")],
       [InlineKeyboardButton("5+", callback_data="bed_5+")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       f"📊 **ሁኔታ:** {cond}\n\n🛏️ **የመኝታ ክፍል ብዛት ይምረጡ፦**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_BEDROOMS

async def seller_bedrooms_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   beds = query.data.replace("bed_", "")
   context.user_data['bedrooms'] = beds
   keyboard = [
       [InlineKeyboardButton("🚗 አለ", callback_data="park_yes")],
       [InlineKeyboardButton("❌ የለም", callback_data="park_no")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       f"🛏️ **መኝታ:** {beds}\n\n🚗 **ፓርኪንግ አለው?**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_PARKING

async def seller_parking_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   parking = "አለ" if query.data == "park_yes" else "የለም"
   context.user_data['parking'] = parking
   await query.edit_message_text(
       f"🚗 **ፓርኪንግ:** {parking}\n\n✍️ **የቤቱን/ቦታውን ዝርዝር መረጃ ያስገቡ፦**\n💡 *ምሳሌ፦* ቦሌ አትላስ አካባቢ 3 መኝታ ቤት፣ ዘመናዊ ኩሽና",
       parse_mode="Markdown"
   )
   return SELLER_DETAILS

async def seller_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   context.user_data['description'] = update.message.text
   await update.message.reply_text(
       "💰 **የሚሸጡበትን/ሚያከራዩበትን ዋጋ ያስገቡ፦**",
       reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
       parse_mode="Markdown"
   )
   return SELLER_PRICE

async def seller_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   if not validate_price(update.message.text):
       await update.message.reply_text("❌ እባክዎ ቁጥር ብቻ ያስገቡ።")
       return SELLER_PRICE
   context.user_data['price'] = update.message.text
   keyboard = [
       [InlineKeyboardButton("✅ አዎ - የሚደራደር", callback_data="negotiable_yes")],
       [InlineKeyboardButton("❌ አይ - የማይደራደር", callback_data="negotiable_no")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await update.message.reply_text(
       "💰 **ዋጋው የሚደራደር ነው?**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_NEGOTIABLE

async def seller_negotiable_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   context.user_data['negotiable'] = (query.data == "negotiable_yes")
   keyboard = [
       [InlineKeyboardButton("⚡ አዎ - አስቸኳይ ነው", callback_data="urgent_yes")],
       [InlineKeyboardButton("❌ አይ - አስቸኳይ አይደለም", callback_data="urgent_no")],
       [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
   ]
   await query.edit_message_text(
       "⚡ **ይህ አስቸኳይ ሽያጭ ነው?**",
       reply_markup=InlineKeyboardMarkup(keyboard),
       parse_mode="Markdown"
   )
   return SELLER_URGENT

async def seller_urgent_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
   query = update.callback_query
   if query.data == "flow_home":
       return await go_home(update, context)
   await query.answer()
   context.user_data['urgent_sale'] = (query.data == "urgent_yes")
   await query.edit_message_text(
       "📞 **የስልክ ቁጥርዎን ያስገቡ፦**",
       parse_mode="Markdown"
   )
   return SELLER_PHONE

async def seller_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   text = update.message.text.strip()
   telegram_user = ""
   phone = text
   username_match = re.search(r'@\w+', text)
   if username_match:
       telegram_user = username_match.group()
       phone = text.replace(telegram_user, '').strip()
   if not validate_phone(phone):
       await update.message.reply_text("❌ ትክክለኛ የስልክ ቁጥር ያስገቡ። (ለምሳሌ፦ 0911223344 ወይም 0911223344 @Abebe)")
       return SELLER_PHONE
   context.user_data['phone'] = phone
   context.user_data['telegram_user'] = telegram_user
   await update.message.reply_text(
       "📸 **የንብረቱን ፎቶ ይላኩ (ወይም 'ዝለል' የሚለውን ይጻፉ)፦**\n\n"
       "💡 *እስከ 5 ፎቶዎች መላክ ይችላሉ። ሲጨርሱ 'ጨረስኩ' ብለው ይጻፉ።*",
       parse_mode="Markdown",
       reply_markup=ReplyKeyboardMarkup([["ዝለል"], ["ጨረስኩ"], ["🏠 ዋና ገጽ"]], resize_keyboard=True)
   )
   return SELLER_PHOTO

async def seller_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
   if update.message.text == "🏠 ዋና ገጽ":
       return await go_home(update, context)
   if update.message.text and update.message.text.lower() in ['ዝለል', 'ጨረስኩ', 'ቀጥል']:
       return await save_seller_listing(update, context)
   if update.message.photo:
       if 'photos' not in context.user_data:
           context.user_data['photos'] = []
       if len(context.user_data['photos']) < 5:
           context.user_data['photos'].append(update.message.photo[-1].file_id)
           count = len(context.user_data['photos'])
           await update.message.reply_text(
               f"📸 **ፎቶ {count}/5 ተቀብያለሁ!**\n\n"
               f"ተጨማሪ ፎቶ ይላኩ ወይም ለማቆም 'ጨረስኩ' ብለው ይጻፉ።",
               parse_mode="Markdown"
           )
       else:
           await update.message.reply_text(
               "⚠️ ከፍተኛው 5 ፎቶ ነው። 'ጨረስኩ' ብለው ይጻፉ።",
               parse_mode="Markdown"
           )
       return SELLER_PHOTO
   return SELLER_PHOTO

async def save_seller_listing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = context.user_data
    property_subtype = user_data.get('property_subtype', '')
    description = user_data.get('description', '')
    telegram_user = user_data.get('telegram_user', '')
    is_car = user_data.get('main_category') == "car"
    negotiable = user_data.get('negotiable', True)
    urgent_sale = user_data.get('urgent_sale', False)
    
    price = user_data.get('price', '')
    phone = user_data.get('phone', '')
    
    clean_description_text = clean_description(description, 100)
    
    extra_data = {
        'negotiable': negotiable,
        'urgent_sale': urgent_sale,
        'telegram_user': telegram_user,
        'req_type': 'SELL',
    }
    
    if is_car:
        extra_data.update({
            'condition': user_data.get('condition', ''),
            'fuel_type': user_data.get('fuel_type', ''),
            'transmission': user_data.get('transmission', ''),
            'mileage': user_data.get('mileage', ''),
            'car_type': user_data.get('sub_category', ''),
        })
    else:
        extra_data.update({
            'condition': user_data.get('condition', ''),
            'bedrooms': user_data.get('bedrooms', ''),
            'parking': user_data.get('parking', ''),
            'house_type': property_subtype,
        })
    
    photos = user_data.get('photos', [])
    photo_id = photos[0] if photos else None
    
    try:
        req_id = add_listing(
            user_chat_id=user.id,
            user_name=user.first_name or "User",
            req_type="SELL",
            main_category=user_data.get('main_category', ''),
            sub_category=user_data.get('sub_category', ''),
            action_type=user_data.get('action_type', 'መሸጥ'),
            property_type=user_data.get('property_type', ''),
            description=clean_description_text,
            price=price,
            phone=phone,
            photo_id=photo_id,
            extra_data=extra_data,
            photos=photos
        )
        
        if req_id:
            await update.message.reply_text(
                f"✅ <b>ማስታወቂያዎ በተሳካ ሁኔታ ተመዝግቧል! ለደላሎችም ተልኳል። ማስታወቂያዎን ማጥፋት ወይም ማስተካከል ሲፈልጉ በማንኛውም ጊዜ ወደ 'የገበያ ቦታ' በመሄድ ማስተካከል ይችላሉ።</b>\n\n"
                f"🆔 <b>የማስታወቂያ ቁጥር:</b> #ADK-{req_id}\n"
                f"📞 <b>ስልክ:</b> {phone}\n"
                + (f"📱 <b>Telegram:</b> {telegram_user}\n" if telegram_user else "") +
                f"\n📌 ማስታወቂያዎ ለደላሎች እና ለፈላጊዎች ተልኳል።",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
                parse_mode="HTML"
            )
            
            if photos:
                try:
                    await update.message.reply_photo(
                        photo=photos[0],
                        caption=f"📸 የማስታወቂያ #ADK-{req_id} ፎቶ",
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Failed to send photo: {e}")
            
            listing_data = {
                'id': req_id,
                'main_category': user_data.get('main_category', ''),
                'sub_category': user_data.get('sub_category', ''),
                'price': price,
                'phone': phone,
                'action_type': user_data.get('action_type', 'መሸጥ'),
                'req_type': 'SELL',
                'description': clean_description_text,
                'extra_data': extra_data
            }
            
            notification_text = format_marketplace_card_professional(listing_data)
            
            try:
                await notify_brokers(context.bot, notification_text, req_id, user.id, photos)
                logger.info(f"✅ Notification sent to brokers for #ADK-{req_id}")
            except Exception as e:
                logger.error(f"Failed to notify brokers: {e}")
        else:
            await update.message.reply_text(
                "❌ <b>ማስታወቂያውን መመዝገብ አልተቻለም።</b>",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"❌ Seller save error: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ <b>ስህተት ተከስቷል:</b> {str(e)[:100]}",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
    
    context.user_data.clear()
    return ConversationHandler.END


# ==============================================================================
# 11. BROKER REGISTRATION
# ==============================================================================

async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1: ask for Full / Business name (manual)."""
    context.user_data.clear()
    user = update.effective_user
    # Auto-capture Telegram identity (never asked)
    context.user_data["broker_chat_id"] = int(user.id)
    context.user_data["broker_username"] = (
        f"@{user.username}" if user.username else f"tg://user?id={user.id}"
    )
    await update.message.reply_text(
        "✍️ <b>የደላላ መመዝገቢያ</b>\n\n"
        "👤 <b>ሙሉ ስም / የንግድ ስም</b>ዎን ይጻፉ፦",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
    )
    return BROKER_NAME


async def broker_reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 2: store name → ask phone."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    name = (update.message.text or "").strip()
    if len(name) < 2:
        await update.message.reply_text("❌ እባክዎ ትክክለኛ ስም ያስገቡ።")
        return BROKER_NAME
    context.user_data["broker_name"] = name[:200]
    await update.message.reply_text(
        "📞 <b>የንግድ ስልክ ቁጥር</b>ዎን ይጻፉ፦\n"
        "ምሳሌ: <code>0911223344</code>",
        parse_mode="HTML",
    )
    return BROKER_PHONE


async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 3: store phone → Category chips."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    phone = (update.message.text or "").strip()
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("251") and len(digits) >= 12:
        phone = "0" + digits[3:12]
    elif len(digits) == 9 and digits[0] in ("9", "7"):
        phone = "0" + digits
    elif digits.startswith("0") and len(digits) == 10:
        phone = digits
    else:
        phone = digits or phone
    if not validate_phone(phone):
        await update.message.reply_text("❌ ትክክለኛ ስልክ ያስገቡ (0911223344)።")
        return BROKER_PHONE
    context.user_data["broker_phone"] = phone

    kb = [
        [InlineKeyboardButton(cat, callback_data=f"bcat_{i}")]
        for i, cat in enumerate(BROKER_CATEGORIES)
    ]
    kb.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await update.message.reply_text(
        "✅ ስልክ ተቀብሏል።\n\n💼 <b>የሙያ ዘርፍ ይምረጡ፦</b>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )
    await update.message.reply_text(
        "💼 ዘርፍ:",
        reply_markup=InlineKeyboardMarkup(kb),
    )
    return BROKER_CATEGORY


async def broker_reg_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 4: category → Sub-city chips."""
    q = update.callback_query
    await q.answer()
    if q.data == "flow_home":
        return await go_home(update, context)
    try:
        idx = int(q.data.replace("bcat_", ""))
        category = BROKER_CATEGORIES[idx]
    except (ValueError, IndexError):
        category = BROKER_CATEGORIES[-1]
    context.user_data["broker_category"] = category

    kb = [
        [InlineKeyboardButton(sc, callback_data=f"bsc_{i}")]
        for i, sc in enumerate(BROKER_REG_SUBCITIES)
    ]
    kb.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    try:
        await q.edit_message_text(
            f"✅ {category}\n\n📍 <b>ክፍለ ከተማ / አካባቢ ይምረጡ፦</b>",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="HTML",
        )
    except Exception:
        await context.bot.send_message(
            chat_id=q.from_user.id,
            text=f"✅ {category}\n\n📍 <b>ክፍለ ከተማ ይምረጡ፦</b>",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="HTML",
        )
    return BROKER_SUBCITY


async def broker_reg_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store sub-city → request Fayda Digital ID photo."""
    q = update.callback_query
    await q.answer()
    if q.data == "flow_home":
        return await go_home(update, context)
    try:
        idx = int(q.data.replace("bsc_", ""))
        sub_city = BROKER_REG_SUBCITIES[idx]
    except (ValueError, IndexError):
        sub_city = BROKER_REG_SUBCITIES[0]
    context.user_data["broker_subcity"] = sub_city
    try:
        await q.edit_message_text(
            f"✅ {sub_city}\n\n"
            "🪪 <b>እባክዎ የፋይዳ (Fayda Digital ID) ፎቶዎን ይላኩ።</b>",
            parse_mode="HTML",
        )
    except Exception:
        await context.bot.send_message(
            chat_id=q.from_user.id,
            text=(
                f"✅ {sub_city}\n\n"
                "🪪 እባክዎ የፋይዳ (Fayda Digital ID) ፎቶዎን ይላኩ።"
            ),
        )
    await context.bot.send_message(
        chat_id=q.from_user.id,
        text="📸 ፎቶውን አሁን ይላኩ።",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
    )
    return BROKER_FAYDA


async def broker_reg_fayda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive Fayda photo → SAVE broker to DB."""
    msg = update.message
    if msg and msg.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    if not msg or not msg.photo:
        await msg.reply_text("🪪 እባክዎ የፋይዳ ፎቶ ይላኩ (እንደ ምስል)።")
        return BROKER_FAYDA

    fayda_id = msg.photo[-1].file_id
    user = update.effective_user
    full_name = context.user_data.get("broker_name") or user.first_name or "User"
    phone = context.user_data.get("broker_phone") or ""
    category = context.user_data.get("broker_category") or "📦 አጠቃላይ ደላላ"
    sub_city = context.user_data.get("broker_subcity") or ""
    username = context.user_data.get("broker_username") or (
        f"@{user.username}" if user.username else f"tg://user?id={user.id}"
    )

    bid = add_broker(
        chat_id=int(user.id),
        full_name=full_name,
        phone=phone,
        role_type=category,
        national_id_photo=fayda_id,
        sub_city=sub_city,
        specialty=category,
        username=username,
        fayda_photo_id=fayda_id,
    )
    if bid:
        await msg.reply_text(
            "✅ <b>ምዝገባዎ ተጠናቋል!</b>\n"
            "⏳ አድሚን ካረጋገጠ በኋላ በመድረኩ ይታያሉ።",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
        )
        if ADMIN_CHAT_ID_INT:
            try:
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID_INT,
                    photo=fayda_id,
                    caption=(
                        f"🚨 አዲስ ደላላ + Fayda ID\n"
                        f"👤 {full_name}\n"
                        f"📞 {phone}\n"
                        f"🔗 {username}\n"
                        f"💼 {category} | 📍 {sub_city}\n"
                        f"ID: `{user.id}`"
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ አጽድቅ", callback_data=f"admin_appr_{user.id}"),
                        InlineKeyboardButton("❌ ሰርዝ", callback_data=f"admin_reje_{user.id}"),
                    ]]),
                )
            except Exception as e:
                logger.error(f"admin fayda notify: {e}")
    else:
        await msg.reply_text(
            "❌ ምዝገባ አልተሳካም። /start ይጫኑ።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
        )
    context.user_data.clear()
    return ConversationHandler.END


async def broker_have_item_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    broker = get_broker(user_id)
    if not broker:
        await query.message.reply_text("⛔ እባክዎ መጀመሪያ እንደ ደላላ ይመዝገቡ።")
        return ConversationHandler.END
    if str(broker.get("status") or "").lower() in ("rejected", "banned", "deleted"):
        await query.message.reply_text("⛔ መለያዎ አልተፈቀደም።")
        return ConversationHandler.END
    parts = query.data.split('_')
    if len(parts) < 3:
        await query.message.reply_text("❌ የተሳሳተ መረጃ ተላኳል።")
        return ConversationHandler.END
    req_id = parts[2]
    buyer_id = parts[3] if len(parts) >= 4 else None
    if not buyer_id:
        listing = get_listing_by_id(int(req_id)) if req_id.isdigit() else None
        if listing:
            buyer_id = listing.get('user_chat_id')
    if not buyer_id:
        await query.message.reply_text("❌ የፈላጊው መረጃ አልተገኘም።")
        return ConversationHandler.END
    context.user_data['target_req_id'] = req_id
    context.user_data['target_buyer_id'] = buyer_id
    await query.message.reply_text(
        f"✅ **ጥያቄ #ADK-{req_id}**\n\n"
        f"✍️ **ያለዎትን ንብረት ዝርዝር መረጃ እና ዋጋ ያስገቡ፦**\n\n"
        f"💡 *ምሳሌ፦* ቶዮታ ቪትዝ 2021፣ 30,000 KM፣ ዋጋ 2.4 ሚሊዮን",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
        parse_mode="Markdown"
    )
    return BROKER_OFFER_TEXT

async def broker_offer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data['offer_text'] = text
    await update.message.reply_text(
        "📸 **የንብረቱን ፎቶ ይላኩ፦**\n\n"
        "(ፎቶ ከሌልዎት `ፎቶ የለውም` ብለው ይጻፉ)",
        reply_markup=ReplyKeyboardMarkup([["ፎቶ የለውም"], ["🏠 ዋና ገጽ"]], resize_keyboard=True),
        parse_mode="Markdown"
    )
    return BROKER_OFFER_PHOTO

async def broker_offer_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    raw_buyer_id = context.user_data.get('target_buyer_id')
    req_id = context.user_data.get('target_req_id')
    offer_text = context.user_data.get('offer_text')
    
    if not raw_buyer_id or not req_id or not offer_text:
        await update.message.reply_text(
            "❌ <b>የሂደት ስህተት ተከሰቷል</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
        return ConversationHandler.END
    
    buyer_id = int(raw_buyer_id)
    broker_user = update.effective_user
    broker = get_broker(broker_user.id)
    broker_name = broker.get('full_name') if broker else (broker_user.first_name or "ደላላ")
    broker_phone = broker.get('phone', 'አልተጠቀሰም') if broker else 'አልተጠቀሰም'
    
    message_to_buyer = (
        f"🎉 <b>አዲስ አማራጭ ተገኝቷል!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>ጥያቄ፡</b> <code>#ADK-{req_id}</code>\n"
        f"👤 <b>አቅራቢ፡</b> {broker_name}\n"
        f"📞 <b>ስልክ፡</b> <code>{broker_phone}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>የንብረቱ ዝርዝር፡</b>\n{offer_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 ለበለጠ መረጃ ይደውሉ"
    )
    
    try:
        photo_id = None
        if update.message.photo:
            photo_id = update.message.photo[-1].file_id
        
        # Chat / Call actions for requester
        _uname = str((broker or {}).get("username") or "").lstrip("@")
        if _uname:
            _chat_url = f"https://t.me/{_uname}"
        elif broker_user.username:
            _chat_url = f"https://t.me/{broker_user.username}"
        else:
            _chat_url = f"tg://user?id={broker_user.id}"
        _rows = [[InlineKeyboardButton("💬 ቻት አድርግ", url=_chat_url)]]
        if broker_phone and str(broker_phone) not in ("አልተጠቀሰም", "N/A", "-", "", "None"):
            _rows.append([InlineKeyboardButton("📞 ደውል", callback_data=f"broker_call_{broker_user.id}")])
        offer_kb = InlineKeyboardMarkup(_rows)

        save_broker_offer(int(req_id), broker_user.id, offer_text, photo_id)
        
        if photo_id:
            await context.bot.send_photo(
                chat_id=buyer_id,
                photo=photo_id,
                caption=message_to_buyer,
                parse_mode="HTML",
                reply_markup=offer_kb,
            )
        else:
            await context.bot.send_message(
                chat_id=buyer_id,
                text=message_to_buyer,
                parse_mode="HTML",
                reply_markup=offer_kb,
            )
        
        await update.message.reply_text(
            "✅ <b>መረጃዎ ለፈላጊው ተልኳል!</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to send offer: {e}")
        await update.message.reply_text(
            "❌ <b>መረጃውን መላክ አልተቻለም</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
    
    context.user_data.clear()
    return ConversationHandler.END

async def have_buyer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    broker = get_broker(user_id)
    if not broker or broker.get('status') != 'approved':
        await query.answer("⛔ የተረጋገጡ ደላሎች ብቻ ነው!", show_alert=True)
        return
    await query.answer()
    parts = query.data.split('_')
    if len(parts) < 3:
        await query.answer("❌ የተሳሳተ መረጃ", show_alert=True)
        return
    item_id = parts[2]
    owner_id = parts[3] if len(parts) >= 4 else None
    listing = get_listing_by_id(int(item_id)) if str(item_id).isdigit() else None
    if not listing:
        await query.answer("❌ ማስታወቂያው አልተገኘም", show_alert=True)
        return
    phone = listing.get('phone', 'አልተገኘም')
    owner_name = listing.get('user_name', 'ባለቤት')
    text = (
        f"🤝 **ገዢ/ተከራይ አለዎት**\n\n"
        f"📦 ማስታወቂያ: `#ADK-{item_id}`\n"
        f"👤 ባለቤት: {owner_name}\n"
        f"📞 ስልክ: `{phone}`\n\n"
        f"💡 በቀጥታ ደውለው መገበያየት ይችላሉ።"
    )
    try:
        await query.edit_message_text(text=text, parse_mode="Markdown")
    except Exception:
        try:
            await query.edit_message_caption(caption=text, parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")

async def want_myself_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split('_')
    item_id = parts[2] if len(parts) >= 3 else "?"
    listing = get_listing_by_id(int(item_id)) if str(item_id).isdigit() else None
    phone = listing.get('phone', 'አልተገኘም') if listing else 'አልተገኘም'
    text = (
        f"👤 **ለራስዎ ይፈልጋሉ**\n\n"
        f"📦 ማስታወቂያ: `#ADK-{item_id}`\n"
        f"📞 የባለቤቱ ስልክ: `{phone}`\n\n"
        f"💡 በቀጥታ ደውለው መገበያየት ይችላሉ።"
    )
    try:
        await query.edit_message_text(text=text, parse_mode="Markdown")
    except Exception:
        try:
            await query.edit_message_caption(caption=text, parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=text,
                parse_mode="Markdown"
            )


# ==============================================================================
# 13. VIEW REQUESTS / MARKETPLACE / DIRECTORY
# ==============================================================================

# ---------- Hybrid choice: Web App vs Text Mode ----------

TEXT_PAGE_SIZE = 5  # items per text-mode page


async def marketplace_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    web_url = f"{WEBAPP_URL}/explorer"
    keyboard = [
        [InlineKeyboardButton("🌐 በ Mini App ክፈት", web_app=WebAppInfo(url=web_url))],
        [InlineKeyboardButton("⚡ በጽሁፍ ተመልከት", callback_data="view_text_marketplace_1")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "🛒 <b>የገበያ ቦታ</b>\n\n"
        "እባክዎ የመመልከቻ አማራጭ ይምረጡ፡\n\n"
        "🌐 <b>Mini App</b> — ሙሉ መረጃ እና ፎቶዎች\n"
        "⚡ <b>ቀላል ጽሁፍ</b> — ለዝቅተኛ ኔትወርክ",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def requests_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    web_url = f"{WEBAPP_URL}/explorer?tab=requests"
    keyboard = [
        [InlineKeyboardButton("🌐 በ Mini App ክፈት", web_app=WebAppInfo(url=web_url))],
        [InlineKeyboardButton("⚡ በጽሁፍ ተመልከት", callback_data="view_text_requests_1")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "📋 <b>የፈላጊዎች ዝርዝር</b>\n\n"
        "እባክዎ የመመልከቻ አማራጭ ይምረጡ፡\n\n"
        "🌐 <b>Mini App</b> — ሙሉ መረጃ እና ፎቶዎች\n"
        "⚡ <b>ቀላል ጽሁፍ</b> — ለዝቅተኛ ኔትወርክ",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )




def _format_tel_url(phone: str) -> Optional[str]:
    """Return tel:+251... URL or None if invalid."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", str(phone))
    if digits.startswith("0") and len(digits) == 10:
        return f"tel:+251{digits[1:]}"
    if digits.startswith("251") and len(digits) >= 12:
        return f"tel:+{digits}"
    if len(digits) >= 9:
        return f"tel:+{digits}"
    return None


def _build_single_card_keyboard(
    mode: str,
    item: dict,
    viewer_id: int = 0,
    page: int = 1,
    total_pages: int = 1,
    show_pagination: bool = False,
) -> InlineKeyboardMarkup:
    """
    Row1: Call (tel: URL when possible, else callback) | Sold Out (owner)
    Row2: pagination on last card
    Row3: Home
    """
    item_id = item.get("id")
    owner_id = int(item.get("user_chat_id") or 0)
    phone = (item.get("phone") or "").strip()
    status = str(item.get("status") or "").lower()
    rows = []

    row1 = []
    # Telegram rejects tel: URLs (BadRequest: wrong port number) — callback only
    if phone:
        row1.append(InlineKeyboardButton("📞 Call", callback_data=f"tm_call_{item_id}"))
    else:
        row1.append(InlineKeyboardButton("📞 N/A", callback_data=f"tm_call_{item_id}"))

    is_owner = viewer_id and owner_id and int(viewer_id) == owner_id
    is_admin = viewer_id in ADMIN_IDS if ADMIN_IDS else False
    if (is_owner or is_admin) and status not in ("sold", "rented", "deleted"):
        row1.append(InlineKeyboardButton("🏷️ Sold Out", callback_data=f"tm_sold_{item_id}"))
    rows.append(row1)

    if show_pagination and total_pages > 1:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("⬅️ ቀዳሚ", callback_data=f"view_text_{mode}_{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("ቀጣይ ➡️", callback_data=f"view_text_{mode}_{page + 1}"))
        rows.append(nav)

    rows.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    return InlineKeyboardMarkup(rows)


def _increment_views_batch(ids, amount=1):
    """Compat helper — returns {id: new_count}."""
    out = {}
    for lid in ids or []:
        try:
            out[int(lid)] = increment_listing_views(int(lid), amount=amount)
        except Exception:
            pass
    return out


async def text_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Text-mode Seller Listings & Buyer Requests.
    - ORDER BY created_at DESC → newest first on Page 1
    - One message per card, uniform Call / Sold Out keyboard
    """
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "noop":
        return

    user_id = query.from_user.id
    chat_id = query.message.chat_id if query.message else user_id

    # --- Mark Sold Out ---
    if data.startswith("tm_sold_"):
        try:
            listing_id = int(data.replace("tm_sold_", ""))
        except ValueError:
            return
        listing = get_listing_by_id(listing_id)
        if not listing:
            await query.answer("Not found", show_alert=True)
            return
        owner_id = listing.get('user_chat_id')
        is_admin = (user_id == ADMIN_CHAT_ID_INT and ADMIN_CHAT_ID_INT != 0)
        if int(owner_id or 0) != int(user_id) and not is_admin:
            await query.answer("⛔ Owner only!", show_alert=True)
            return
        if update_listing_status(listing_id, "sold"):
            await query.answer("✅ Marked as Sold Out!", show_alert=True)
            try:
                listing['status'] = 'sold'
                card = format_marketplace_card_professional(listing)
                mode = "marketplace" if str(listing.get('req_type', '')).upper() == 'SELL' else "requests"
                await query.edit_message_text(
                    text=card,
                    parse_mode="HTML",
                    reply_markup=_build_single_card_keyboard(
                        mode, listing, viewer_id=user_id, show_pagination=False
                    ),
                    disable_web_page_preview=True,
                )
            except Exception:
                pass
        else:
            await query.answer("Error", show_alert=True)
        return

    # --- Call: show phone ---
    if data.startswith("tm_call_"):
        try:
            listing_id = int(data.replace("tm_call_", ""))
        except ValueError:
            return
        listing = get_listing_by_id(listing_id) or {}
        phone = (listing.get("phone") or "").strip()
        if not phone:
            await query.answer("📞 ስልክ አልተመዘገበም", show_alert=True)
            return
        digits = re.sub(r"\D", "", phone)
        if digits.startswith("0") and len(digits) == 10:
            intl = "+251" + digits[1:]
        elif digits.startswith("251"):
            intl = "+" + digits
        else:
            intl = phone if phone.startswith("+") else phone
        await query.answer(f"📞 {intl}", show_alert=True)
        try:
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=f"📞 ለመደወል ቁጥሩን ይጫኑ (copy):\n\n<code>{intl}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    # Parse: view_text_{mode}_{page}  OR  text_mode_{mode}_{page}
    mode, page = None, 1
    if data.startswith("view_text_"):
        rest = data[len("view_text_"):]  # marketplace_1
        parts = rest.rsplit("_", 1)
        if len(parts) == 2:
            mode, page_s = parts[0], parts[1]
            try:
                page = max(1, int(page_s))
            except ValueError:
                page = 1
    elif data.startswith("text_mode_"):
        parts = data.split("_")
        # text_mode_marketplace_1
        if len(parts) >= 4:
            mode = parts[2]
            try:
                page = max(1, int(parts[3]))
            except ValueError:
                page = 1
    if mode not in ("marketplace", "requests"):
        logger.warning(f"text_mode unknown data={data!r}")
        return

    # Anyone can browse text marketplace/requests (no silent return)

    try:
        # NEWEST FIRST on Page 1
        if mode == "marketplace":
            total = count_listings(req_type="SELL")
            items = get_listings_by_category_ordered(
                limit=TEXT_PAGE_SIZE,
                offset=(page - 1) * TEXT_PAGE_SIZE,
                req_type="SELL",
                order="DESC",
            )
            title = "🛒 <b>የገበያ ቦታ</b> (ጽሁፍ)"
            empty_msg = "📭 ምንም የሚሸጡ ንብረቶች የሉም።"
        else:
            total = count_listings(req_type="BUY")
            items = get_listings_by_category_ordered(
                limit=TEXT_PAGE_SIZE,
                offset=(page - 1) * TEXT_PAGE_SIZE,
                req_type="BUY",
                order="DESC",
            )
            title = "📋 <b>የፈላጊዎች ጥያቄዎች</b> (ጽሁፍ)"
            empty_msg = "📭 ምንም ንቁ ጥያቄዎች የሉም።"

        if not items:
            await query.edit_message_text(
                empty_msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")
                ]]),
            )
            return

        for it in items:
            lid = it.get("id")
            if lid:
                try:
                    it["view_count"] = increment_listing_views(int(lid), amount=1)
                except Exception:
                    pass

        total_pages = max(1, (total + TEXT_PAGE_SIZE - 1) // TEXT_PAGE_SIZE)
        page = min(page, total_pages)

        try:
            await query.edit_message_text(
                f"{title}\n📄 ገጽ <b>{page}/{total_pages}</b>  •  ጠቅላላ <b>{total}</b>",
                parse_mode="HTML",
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{title}\n📄 ገጽ <b>{page}/{total_pages}</b>  •  ጠቅላላ <b>{total}</b>",
                parse_mode="HTML",
            )

        for idx, it in enumerate(items):
            is_last = (idx == len(items) - 1)
            card_text = format_marketplace_card_professional(it)
            kbd = _build_single_card_keyboard(
                mode=mode,
                item=it,
                viewer_id=user_id,
                page=page,
                total_pages=total_pages,
                show_pagination=is_last,
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=card_text,
                parse_mode="HTML",
                reply_markup=kbd,
                disable_web_page_preview=True,
            )

    except Exception as e:
        logger.error(f"text_mode_callback error: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="❌ መረጃ ማምጣት አልተቻለም። እባክዎ እንደገና ይሞክሩ።",
                parse_mode="HTML",
            )
        except Exception:
            pass


# Keep old full-photo chat view available if needed later
async def view_public_marketplace_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = get_public_marketplace_items(limit=15)
    user_id = update.effective_user.id
    if not items:
        await update.message.reply_text(
            "📭 ምንም ንብረቶች የሉም",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    await update.message.reply_text(
        f"🛍️ <b>{len(items)} ንብረቶች ተገኝተዋል</b>",
        parse_mode="HTML"
    )
    for item in items:
        photos = item.get('photos') or ([item['photo_id']] if item.get('photo_id') else [])
        card_text = format_marketplace_card_professional(item)
        reply_markup = build_marketplace_keyboard_clean(
            item_id=item.get('id'),
            owner_id=item.get('user_chat_id'),
            current_user_id=user_id
        )
        if photos:
            try:
                await update.message.reply_photo(
                    photo=photos[0], caption=card_text,
                    reply_markup=reply_markup, parse_mode="HTML"
                )
            except Exception:
                await update.message.reply_text(card_text, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await update.message.reply_text(card_text, reply_markup=reply_markup, parse_mode="HTML")


async def view_requests_clean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Legacy full list (kept for compatibility). Prefer hybrid via requests_choice."""
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID_INT)
    broker = get_broker(user_id)
    if not is_admin and not broker:
        await update.message.reply_text(
            "⛔ <b>ይህን ማየት የሚችሉት የተረጋገጡ ደላሎች ብቻ ናቸው!</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
        return
    if not is_admin and broker.get('status') != 'approved':
        await update.message.reply_text(
            "⏳ <b>ምዝገባዎ ገና አልጸደቀም</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
        return
    listings = get_listings_by_category_ordered(limit=20, offset=0, req_type="BUY", order="DESC")
    total = count_listings(req_type="BUY")
    if not listings:
        await update.message.reply_text(
            "📭 <b>ምንም ንቁ ጥያቄዎች የሉም</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML"
        )
        return
    broker_name = "👑 አድሚን" if is_admin else (broker.get('full_name') if broker else "ደላላ")
    await update.message.reply_text(
        f"📋 <b>የፈላጊዎች ዝርዝር</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>{broker_name}</b>\n🔔 <b>ጠቅላላ:</b> {total} ጥያቄዎች",
        parse_mode="HTML"
    )
    for listing in listings:
        card_text = format_marketplace_card_professional(listing)
        reply_markup = build_request_keyboard_clean(
            req_id=listing.get('id'),
            buyer_id=listing.get('user_chat_id')
        )
        try:
            await update.message.reply_text(card_text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send listing: {e}")


async def view_brokers_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show sub-city filter then list approved brokers."""
    kb = [[InlineKeyboardButton(sc, callback_data=f"dir_sc_{i}")]
          for i, sc in enumerate(BROKER_REG_SUBCITIES)]
    kb.append([InlineKeyboardButton("🌐 ሁሉም", callback_data="dir_sc_all")])
    kb.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await update.message.reply_text(
        "👥 <b>የደላሎች መድረክ</b>\n\n📍 አካባቢ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )


def _broker_chat_url(b: dict) -> str:
    """Always return a Telegram-valid URL (http/https/tg). Never empty."""
    chat_id = b.get("chat_id")
    try:
        chat_id = int(chat_id) if chat_id is not None else None
    except (TypeError, ValueError):
        chat_id = None

    uname = (b.get("username") or "").strip()
    # strip leading @ and reject placeholders
    if uname.startswith("@"):
        uname = uname[1:]
    if uname.startswith("tg://user?id="):
        return uname
    if uname.startswith("http://") or uname.startswith("https://"):
        return uname
    # valid telegram username: 5+ chars, alphanumeric + underscore
    if uname and re.match(r"^[A-Za-z0-9_]{5,}$", uname):
        return f"https://t.me/{uname}"
    if chat_id:
        return f"tg://user?id={chat_id}"
    # last resort — still valid URL so Telegram does not BadRequest
    return "https://t.me/AdikaSupport"


def _broker_card_keyboard(b: dict, viewer_id: int) -> InlineKeyboardMarkup:
    """Safe inline keyboard — never pass empty/invalid url= to Telegram."""
    chat_id_b = b.get("chat_id")
    try:
        chat_id_b = int(chat_id_b) if chat_id_b is not None else 0
    except (TypeError, ValueError):
        chat_id_b = 0

    phone = (b.get("phone") or "").strip()
    # keep digits only for display/callback
    phone_digits = re.sub(r"\D", "", phone)

    rows = []
    row1 = []
    # Callback only — Telegram rejects tel: inline URLs
    if phone_digits:
        row1.append(InlineKeyboardButton("📞 Call", callback_data=f"broker_call_{chat_id_b}"))
    else:
        row1.append(InlineKeyboardButton("📞 N/A", callback_data="broker_call_na"))
    row1.append(
        InlineKeyboardButton("💬 Message", url=_broker_chat_url(b))
    )
    rows.append(row1)
    rows.append([
        InlineKeyboardButton("⭐ ደረጃ ስጥ", callback_data=f"broker_rate_{chat_id_b}")
    ])
    try:
        viewer_id = int(viewer_id)
    except (TypeError, ValueError):
        viewer_id = 0
    if chat_id_b and (viewer_id == chat_id_b or viewer_id in ADMIN_IDS):
        rows.append([
            InlineKeyboardButton("🗑️ Delete Profile", callback_data=f"broker_del_{chat_id_b}")
        ])
    return InlineKeyboardMarkup(rows)


async def filter_brokers_by_subcity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "dir_sc_all":
        sub, label = None, "ሁሉም"
    else:
        try:
            idx = int(data.replace("dir_sc_", ""))
            sub = BROKER_REG_SUBCITIES[idx]
            label = sub
        except (ValueError, IndexError):
            sub, label = None, "ሁሉም"

    try:
        brokers = get_active_brokers(sub_city=sub, status="ONLINE", limit=30, offset=0)
    except Exception as e:
        logger.error(f"get_active_brokers failed: {e}", exc_info=True)
        await q.edit_message_text("❌ ደላሎችን ማምጣት አልተቻለም። ቆይተው ይሞክሩ።")
        return

    if not brokers and sub is not None:
        # Fallback: show all brokers if sub-city has none
        brokers = get_active_brokers(sub_city=None, status="ONLINE", limit=30, offset=0)
        label = f"{label} (ሁሉም — በዚህ አካባቢ አልተገኘም)"
    if not brokers:
        try:
            await q.edit_message_text(
                "📭 በአሁኑ ሰዓት የተመዘገቡ ደላሎች አልተገኙም።\n"
                "✍️ የደላላ መመዝገቢያ በመጠቀም ይመዝገቡ።",
                parse_mode="HTML",
            )
        except Exception:
            await context.bot.send_message(
                chat_id=q.from_user.id,
                text="📭 የተመዘገቡ ደላሎች አልተገኙም።",
            )
        return

    try:
        await q.edit_message_text(
            f"👥 <b>የተረጋገጡ ደላሎች</b> — {label}\nጠቅላላ: {len(brokers)}",
            parse_mode="HTML",
        )
    except Exception:
        await context.bot.send_message(
            chat_id=q.from_user.id,
            text=f"👥 የተረጋገጡ ደላሎች — {label} ({len(brokers)})",
        )

    viewer = q.from_user.id
    sent = 0
    for b in brokers:
        try:
            if not isinstance(b, dict):
                continue
            if not b.get("chat_id"):
                logger.warning(f"skip broker without chat_id: {b}")
                continue
            text = format_broker_profile_professional(b)
            kb = _broker_card_keyboard(b, viewer)
            await context.bot.send_message(
                chat_id=viewer,
                text=text,
                parse_mode="HTML",
                reply_markup=kb,
                disable_web_page_preview=True,
            )
            sent += 1
        except Exception as e:
            logger.error(
                f"broker card send failed id={b.get('id')} chat_id={b.get('chat_id')}: {e}",
                exc_info=True,
            )
            # try plain-text fallback without keyboard
            try:
                await context.bot.send_message(
                    chat_id=viewer,
                    text=(
                        f"👤 {b.get('full_name') or '—'}\n"
                        f"📍 {b.get('sub_city') or '—'}\n"
                        f"💼 {b.get('specialty') or b.get('role_type') or '—'}"
                    ),
                )
            except Exception as e2:
                logger.error(f"broker fallback also failed: {e2}")
                continue
    if sent == 0:
        await context.bot.send_message(
            chat_id=viewer,
            text="📭 ሊታዩ የሚችሉ ደላሎች አልተገኙም።",
        )


async def broker_call_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deliver click-to-copy phone number (avoids invalid tel: BadRequest)."""
    q = update.callback_query
    data = q.data or ""
    if data == "broker_call_na":
        await q.answer("📞 ስልክ አልተመዘገበም", show_alert=True)
        return
    try:
        cid = int(data.replace("broker_call_", ""))
    except ValueError:
        await q.answer("📞 ስልክ አልተገኘም", show_alert=True)
        return
    b = get_broker(cid) or {}
    phone = (b.get("phone") or "").strip()
    if not phone:
        await q.answer("📞 ስልክ አልተመዘገበም", show_alert=True)
        return
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("0") and len(digits) == 10:
        intl = "+251" + digits[1:]
    elif digits.startswith("251"):
        intl = "+" + digits
    else:
        intl = phone if phone.startswith("+") else phone
    await q.answer(f"📞 {intl}", show_alert=True)
    try:
        await context.bot.send_message(
            chat_id=q.from_user.id,
            text=f"📞 ለመደወል ቁጥሩን ይጫኑ (copy):\n\n<code>{intl}</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass


async def broker_rate_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1: show 1⭐–5⭐ inline buttons."""
    q = update.callback_query
    data = q.data or ""
    try:
        cid = int(data.replace("broker_rate_", ""))
    except ValueError:
        await q.answer("Invalid broker.", show_alert=True)
        return
    await q.answer()
    kb = [[
        InlineKeyboardButton(f"{n}⭐", callback_data=f"broker_star_{cid}_{n}")
        for n in range(1, 6)
    ]]
    await context.bot.send_message(
        chat_id=q.from_user.id,
        text="⭐ Rate this broker (1–5):",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def broker_star_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 2: persist score + success toast."""
    q = update.callback_query
    data = q.data or ""
    # broker_star_{cid}_{n}
    parts = data.split("_")
    try:
        cid = int(parts[2])
        stars = int(parts[3])
    except (IndexError, ValueError):
        await q.answer("Invalid rating.", show_alert=True)
        return
    try:
        ok = add_broker_rating(cid, q.from_user.id, stars)
    except Exception as e:
        logger.error(f"broker_star_cb: {e}", exc_info=True)
        ok = False
    if ok:
        await q.answer("✅ Rating saved successfully!", show_alert=True)
        try:
            await q.edit_message_text(
                f"✅ {stars}⭐ saved — thank you!"
            )
        except Exception:
            pass
    else:
        await q.answer("❌ Could not save rating. Try again.", show_alert=True)


async def broker_del_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        cid = int(q.data.replace("broker_del_", ""))
    except ValueError:
        return
    if q.from_user.id != cid and q.from_user.id not in ADMIN_IDS:
        await q.answer("⛔ Forbidden", show_alert=True)
        return
    if delete_broker(cid):
        await q.edit_message_text("🗑️ Profile deleted.")
    else:
        await q.answer("Error", show_alert=True)



async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    if update.effective_user.id != ADMIN_CHAT_ID_INT:
        await query.answer("⛔ ይህን ማድረግ የሚችሉት አድሚን ብቻ ናቸው!", show_alert=True)
        return
    if data.startswith("admin_appr_"):
        broker_telegram_id = int(data.replace("admin_appr_", ""))
        success = update_broker_status(broker_telegram_id, "approved")
        if success:
            try:
                await query.edit_message_caption(
                    caption=f"{query.message.caption}\n\n✅ **ሁኔታ፦ ተፀድቋል (Approved)**",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    chat_id=broker_telegram_id,
                    text=(
                        "🎉 **እንኳን ደስ አለዎት!**\n\n"
                        "የደላላ/አቅራቢ ምዝገባዎ በአድሚን ፀድቋል።\n"
                        "አሁን '📋 የፈላጊዎች ዝርዝር' በመጫን መስራት መጀመር ይችላሉ።"
                    ),
                    reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify approved broker: {e}")
        else:
            await query.message.reply_text("❌ የደላላውን ሁኔታ መቀየር አልተቻለም።")
    elif data.startswith("admin_reje_"):
        broker_telegram_id = int(data.replace("admin_reje_", ""))
        success = update_broker_status(broker_telegram_id, "rejected")
        if success:
            try:
                await query.edit_message_caption(
                    caption=f"{query.message.caption}\n\n❌ **ሁኔታ፦ ተሰርዟል (Rejected)**",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    chat_id=broker_telegram_id,
                    text="❌ **የምዝገባ ጥያቄዎ ውድቅ ተደርጓል!** እባክዎ እንደገና ይመዝገቡ።",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify rejected broker: {e}")

async def delete_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_CHAT_ID_INT)
    parts = query.data.split('_')
    if len(parts) < 3:
        await query.message.reply_text("❌ የተሳሳተ መረጃ ተላኳል።")
        return
    req_id = int(parts[-1])
    listing = get_listing_by_id(req_id)
    if not listing:
        await query.message.reply_text("❌ ጥያቄው አልተገኘም።")
        return
    if not is_admin and listing.get('user_chat_id') != user_id:
        await query.message.reply_text("⛔ ይህን ጥያቄ የማጥፋት ፈቃድ የለዎትም!")
        return
    success = update_listing_status(req_id, "deleted")
    if success:
        try:
            await query.edit_message_text(
                f"🗑️ **ጥያቄ #{req_id} በስኬት ተሰርዟል።**",
                parse_mode="Markdown"
            )
        except Exception:
            await query.message.reply_text(
                f"🗑️ **ጥያቄ #{req_id} በስኬት ተሰርዟል።**",
                parse_mode="Markdown"
            )
    else:
        await query.message.reply_text("❌ ጥያቄውን ማጥፋት አልተቻለም።")

async def nohave_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    broker = get_broker(user_id)
    if not broker or broker.get('status') != 'approved':
        await query.answer("⛔ ይህን ማድረግ የሚችሉት በአድሚን የተረጋገጡ ደላሎች ብቻ ናቸው!", show_alert=True)
        return
    parts = query.data.split('_')
    req_id = parts[-1] if parts else "?"
    await query.answer(f"ℹ️ ጥያቄ #{req_id} ተለፏል።", show_alert=False)
    try:
        await query.delete_message()
    except Exception:
        try:
            await query.edit_message_text(
                f"⏭️ **ጥያቄ #{req_id} ተለፏል።**",
                parse_mode="Markdown"
            )
        except Exception:
            pass

async def mark_sold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    listing_id = int(data.replace("mark_sold_", ""))
    listing = get_listing_by_id(listing_id)
    if not listing:
        await query.answer("❌ ማስታወቂያው አልተገኘም።", show_alert=True)
        return
    if listing.get('user_chat_id') != user_id and user_id != ADMIN_CHAT_ID_INT:
        await query.answer("⛔ ይህን ማድረግ የሚችሉት የማስታወቂያው ባለቤት ወይም አድሚን ብቻ ነው!", show_alert=True)
        return
    success = update_listing_status(listing_id, "sold")
    if success:
        try:
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\n✅ **ይህ ንብረት Sold Out/ተከራይቷል!**",
                parse_mode="Markdown"
            )
        except Exception:
            await query.edit_message_text(
                f"✅ **ማስታወቂያ #ADK-{listing_id} እንደተሸጠ/እንደተከራየ ምልክት ተደርጎበታል!**",
                parse_mode="Markdown"
            )
        await query.answer("✅ ማስታወቂያው እንደተሸጠ ምልክት ተደርጎበታል!", show_alert=True)
    else:
        await query.answer("❌ ስህተት ተከስቷል።", show_alert=True)


# ==============================================================================
# 15. SUPPORT HANDLER
# ==============================================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📞 <b>አዲካ ማርኬትፕሌስ — የደንበኞች ድጋፍ ማዕከል</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "❓ <b>እንዴት መጠቀም?</b>\n"
        "1️⃣ ለመግዛት / ለመከራየት — ፍላጎትዎን ይመዝግቡ\n"
        "2️⃣ ለመሸጥ / ለማከራየት — ንብረትዎን ያቅርቡ\n"
        "3️⃣ የገበያ ቦታ — የሚሸጡ ንብረቶችን ይመልከቱ\n"
        "4️⃣ የደላሎች መድረክ — የታመኑ ደላሎችን ያግኙ\n\n"
        f"📲 Admin: {SUPPORT_ADMIN_HANDLE}"
    )
    kb = [
        [InlineKeyboardButton("💬 ከአስተዳዳሪው ጋር ይወያዩ", url=SUPPORT_ADMIN_URL)],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML"
        )



async def notification_prefs_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    broker = get_broker(user_id)
    if not broker:
        await update.message.reply_text(
            "⛔ ይህን ማድረግ የሚችሉት የተመዘገቡ ደላሎች/አቅራቢዎች ብቻ ናቸው!",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
        )
        return
    prefs = broker.get('notification_prefs', {})
    if isinstance(prefs, str):
        try: prefs = json.loads(prefs)
        except: prefs = {"car": True, "house": True, "price_min": 0, "price_max": 999999999, "enabled": True}
    enabled_text = "✅ በርተዋል" if bool(prefs.get('enabled', True)) else "❌ ጠፍተዋል"
    car_text = "✅" if bool(prefs.get('car', True)) else "❌"
    house_text = "✅" if bool(prefs.get('house', True)) else "❌"
    keyboard = [
        [InlineKeyboardButton(f"🔔 ማሳወቂያዎች፦ {enabled_text}", callback_data="notif_pref_toggle")],
        [InlineKeyboardButton(f"🚗 መኪና፦ {car_text}", callback_data="notif_pref_car"),
         InlineKeyboardButton(f"🏠 ቤት፦ {house_text}", callback_data="notif_pref_house")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    await update.message.reply_text(
        f"⚙️ **የማሳወቂያ ምርጫዎች**\n\n"
        f"🔔 **ሁኔታ፦** {enabled_text}\n"
        f"🚗 **መኪና፦** {car_text}\n"
        f"🏠 **ቤት፦** {house_text}\n\n"
        f"ከታች ያሉትን ቁልፎች በመጠቀም ማስተካከል ይችላሉ።",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def notification_prefs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    broker = get_broker(user_id)
    if not broker:
        await query.answer("⛔ አልተፈቀደም!", show_alert=True)
        return
    prefs = broker.get('notification_prefs', {})
    if isinstance(prefs, str):
        try: prefs = json.loads(prefs)
        except: prefs = {"car": True, "house": True, "price_min": 0, "price_max": 999999999, "enabled": True}
    data = query.data
    if data == "notif_pref_toggle":
        prefs['enabled'] = not bool(prefs.get('enabled', True))
    elif data == "notif_pref_car":
        prefs['car'] = not bool(prefs.get('car', True))
    elif data == "notif_pref_house":
        prefs['house'] = not bool(prefs.get('house', True))
    update_broker_notification_prefs(user_id, prefs)
    enabled_text = "✅ በርተዋል" if bool(prefs.get('enabled', True)) else "❌ ጠፍተዋል"
    car_text = "✅" if bool(prefs.get('car', True)) else "❌"
    house_text = "✅" if bool(prefs.get('house', True)) else "❌"
    keyboard = [
        [InlineKeyboardButton(f"🔔 ማሳወቂያዎች፦ {enabled_text}", callback_data="notif_pref_toggle")],
        [InlineKeyboardButton(f"🚗 መኪና፦ {car_text}", callback_data="notif_pref_car"),
         InlineKeyboardButton(f"🏠 ቤት፦ {house_text}", callback_data="notif_pref_house")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]
    ]
    try:
        await query.edit_message_text(
            f"⚙️ **የማሳወቂያ ምርጫዎች**\n\n"
            f"🔔 **ሁኔታ፦** {enabled_text}\n"
            f"🚗 **መኪና፦** {car_text}\n"
            f"🏠 **ቤት፦** {house_text}\n\n"
            f"ከታች ያሉትን ቁልፎች በመጠቀም ማስተካከል ይችላሉ።",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception:
        pass


# ==============================================================================
# 17. MAIN ENGINE
# ==============================================================================




async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log full traceback and optionally notify the user."""
    import traceback
    err = context.error
    if err is not None:
        logger.error("Exception while handling an update: %s: %s", type(err).__name__, err)
        tb = "".join(traceback.format_exception(type(err), err, err.__traceback__))
        logger.error("Traceback:\n%s", tb)
    else:
        logger.error("Exception while handling an update: (no error object)")
    try:
        if update and isinstance(update, Update):
            logger.error(
                "Update context: user=%s chat=%s callback=%s text=%s",
                getattr(update.effective_user, "id", None),
                getattr(update.effective_chat, "id", None),
                getattr(update.callback_query, "data", None) if update.callback_query else None,
                (update.message.text[:80] if update.message and update.message.text else None),
            )
    except Exception:
        pass
    try:
        if update and isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ ይቅርታ፣ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ ወይም /start ይጫኑ።",
            )
    except Exception as e:
        logger.warning(f"error notify failed: {e}")
