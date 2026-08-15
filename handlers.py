# ==============================================================================
# handlers.py — Telegram bot handlers, keyboards, conversations (COMPLETE)
# ==============================================================================
import json
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from telegram import (
    Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup,
    WebAppInfo, KeyboardButton, ReplyKeyboardRemove,
)
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
)

from config import (
    logger, MAIN_KEYBOARD, ADMIN_CHAT_ID_INT, ADMIN_IDS, SUB_CITIES, SPECIALTIES,
    TEXT_PAGE_SIZE, VIEW_INCREMENT, BASE_URL,
    SUPPORT_ADMIN_URL, SUPPORT_ADMIN_HANDLE,
    CAR_SUB_CATEGORIES, HOUSE_TYPES, PROPERTY_TYPES,
    FUEL_TYPES, TRANSMISSION_TYPES, CONDITIONS,
    PHONE_PATTERNS, MAX_DESCRIPTION_LENGTH, AUTO_EXPIRE_DAYS,
)
from models import (
    add_listing, get_listing_by_id, get_listings_by_category_ordered,
    count_listings, update_listing_status, increment_views,
    add_broker, get_broker, update_broker_status, update_broker_notification_prefs,
    get_approved_brokers, get_approved_brokers_directory, delete_broker,
    add_broker_rating, save_broker_offer, save_search_alert,
)

# ---------- Conversation States ----------
# Broker Registration States
PHONE_NUMBER, SUB_CITY, SPECIALTY, SAVE_BROKER = range(4)

# Buyer Conversation States
(
    BUYER_MAIN,
    BUYER_CATEGORY,
    BUYER_SUB_CATEGORY,
    BUYER_PROPERTY_TYPE,
    BUYER_BUDGET,
    BUYER_DESCRIPTION,
    BUYER_PHONE,
    BUYER_ALERT,
    BUYER_CONFIRM,
) = range(9)

# Seller Conversation States
(
    SELLER_MAIN,
    SELLER_CATEGORY,
    SELLER_SUB_CATEGORY,
    SELLER_PROPERTY_TYPE,
    SELLER_DETAILS,
    SELLER_PRICE,
    SELLER_NEGOTIABLE,
    SELLER_URGENT,
    SELLER_CONDITION,
    SELLER_FUEL,
    SELLER_TRANSMISSION,
    SELLER_MILEAGE,
    SELLER_BEDROOMS,
    SELLER_PARKING,
    SELLER_PHONE,
    SELLER_PHOTOS,
    SELLER_CONFIRM,
) = range(17)

# ---------- Validation Helpers ----------
def validate_phone(phone: str) -> bool:
    """Validate Ethiopian phone number."""
    if not phone:
        return False
    phone = phone.replace(" ", "").replace("-", "").replace("+", "")
    return any(re.match(pattern, phone) for pattern in PHONE_PATTERNS)

def validate_price(price: str) -> bool:
    """Validate price format."""
    if not price:
        return False
    cleaned = re.sub(r'[^\d]', '', price)
    return bool(cleaned) and len(cleaned) <= 15

def sanitize_input(text: str) -> str:
    """Sanitize user input to prevent injection."""
    if not text:
        return ""
    return re.sub(r'[<>]', '', text)[:MAX_DESCRIPTION_LENGTH]

# ---------- Time Helpers ----------
def relative_time_am(created_at) -> str:
    """Format time in Amharic style."""
    if not created_at:
        return ""
    try:
        if isinstance(created_at, str):
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
                try:
                    created_at = datetime.strptime(created_at[:26].replace("T", " "), fmt if "T" not in str(created_at) else fmt)
                    break
                except ValueError:
                    continue
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(str(created_at).replace("Z", ""))
                except Exception:
                    return str(created_at)[:16]
        
        now = datetime.now(timezone.utc)
        if hasattr(created_at, "tzinfo") and created_at.tzinfo:
            created_at = created_at.replace(tzinfo=None)
        
        secs = max(0, int((now - created_at).total_seconds()))
        if secs < 60:
            return "አሁን"
        if secs < 3600:
            return f"ከ {secs // 60} ደቂቃ በፊት"
        if secs < 86400:
            return f"ከ {secs // 3600} ሰዓት በፊት"
        if secs < 172800:
            return f"ትላንት {created_at.strftime('%H:%M')}"
        if secs < 604800:
            return f"ከ {secs // 86400} ቀን በፊት"
        return created_at.strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        logger.warning(f"Time formatting error: {e}")
        return ""

def clean_description(desc: str, max_len: int = 60) -> str:
    """Clean and truncate description."""
    if not desc:
        return ""
    junk = [
        "ዋጋ:", "ስልክ:", "መግለጫ:", "📝", "💰", "📞", "⚡", "📢", "📦",
        "አይነት:", "ሁኔታ:", "ነዳጅ:", "ማርሽ:", "ኪሎሜትር:",
    ]
    clean = desc
    for j in junk:
        clean = clean.replace(j, "")
    clean = " ".join(clean.split())
    return (clean[:max_len] + "...") if len(clean) > max_len else clean

# ---------- Formatting Helpers ----------
def format_card(item: dict) -> str:
    """Format a listing card with English status badges."""
    item_id = item.get("id", "N/A")
    main_cat = item.get("main_category", "")
    sub_cat = (item.get("sub_category") or "").strip()
    price = item.get("price", "-")
    phone = item.get("phone", "-")
    req_type = str(item.get("req_type", "")).upper()
    status = str(item.get("status", "pending")).lower()
    views = item.get("view_count") or 0
    extra = item.get("extra_data") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}

    if req_type == "BUY":
        header = f"[🎯 Buyer Request]  <code>#ADK-{item_id}</code>"
        price_display = f"💰 <b>Budget:</b> {extra.get('budget_range') or price or '—'} ETB"
    else:
        if status in ("sold", "rented"):
            header = f"[🔴 Sold]  <code>#ADK-{item_id}</code>"
        else:
            header = f"[🟢 Available]  <code>#ADK-{item_id}</code>"
        neg = "Negotiable" if extra.get("negotiable", True) else "Fixed"
        urgent = " ⚡ Urgent" if extra.get("urgent_sale") else ""
        price_display = f"💰 <b>Price:</b> {price} ETB <i>({neg})</i>{urgent}"

    title = main_cat or "Property"
    if sub_cat:
        title += f" ({sub_cat})"

    rel = relative_time_am(item.get("created_at"))
    lines = [header, "━━━━━━━━━━━━━━━━━━━━━", f"📌 <b>{title}</b>", price_display]
    desc = clean_description(item.get("description", ""), 60)
    if desc:
        lines += ["", f"📝 {desc}"]
    lines += [
        "━━━━━━━━━━━━━━━━━━━━━",
        f"👁️ <b>{views}</b> views" + (f"  •  🕐 {rel}" if rel else ""),
        f"📞 <code>{phone}</code>",
    ]
    return "\n".join(lines)

def format_broker_card(b: dict) -> str:
    """Format a broker card."""
    rating = float(b.get("rating") or 5)
    stars = "⭐" * min(5, int(rating))
    online = b.get("is_online", True)
    status = "🟢 ONLINE" if online else "⚪ OFFLINE"
    return (
        f"👤 <b>{b.get('full_name', '—')}</b>  {status}\n"
        f"✅ Trusted Broker\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 Sub-City: {b.get('sub_city', '—')}\n"
        f"🎯 Specialty: {b.get('specialty') or b.get('role_type', '—')}\n"
        f"⭐ {rating}/5.0 {stars}  ({b.get('total_ratings') or 0})\n"
        f"🤝 Completed: {b.get('completed_deals') or 0}\n"
        f"📞 <code>{b.get('phone', '—')}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

def build_card_keyboard(mode: str, item: dict, viewer_id: int = 0,
                        page: int = 1, total_pages: int = 1,
                        show_pagination: bool = False) -> InlineKeyboardMarkup:
    """Build card keyboard with actions."""
    rows = []
    item_id = item.get("id")
    owner_id = item.get("user_chat_id")
    phone = (item.get("phone") or "").strip()
    status = str(item.get("status", "")).lower()
    inactive = status in ("sold", "rented", "deleted", "expired")
    is_owner = bool(viewer_id and owner_id and int(viewer_id) == int(owner_id))
    is_admin = viewer_id in ADMIN_IDS

    row1 = []
    if phone and not inactive:
        row1.append(InlineKeyboardButton("📞 Call", callback_data=f"tm_call_{item_id}"))
    if (is_owner or is_admin) and not inactive:
        row1.append(InlineKeyboardButton("🏷️ Sold Out", callback_data=f"tm_sold_{item_id}"))
    if row1:
        rows.append(row1)

    if show_pagination:
        nav = []
        if page > 1:
            nav.append(InlineKeyboardButton("◀️ ቀዳሚ", callback_data=f"text_mode_{mode}_{page - 1}"))
        nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav.append(InlineKeyboardButton("ቀጣይ ▶️", callback_data=f"text_mode_{mode}_{page + 1}"))
        if nav:
            rows.append(nav)
        rows.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    return InlineKeyboardMarkup(rows)

# ---------- Core Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler."""
    context.user_data.clear()
    await update.message.reply_text(
        "👋 **Welcome to Adika Marketplace!**\n\n"
        "የመኪና፣ የቤት እና የንብረት ገበያ ማዕከል።\n"
        "እባክዎን አማራጭ ይምረጡ፦",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
    )
    return ConversationHandler.END

async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to home menu."""
    context.user_data.clear()
    text = "👋 **Returned to home!**\n\nእባክዎን አማራጭ ይምረጡ፦"
    kb = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    elif update.callback_query:
        q = update.callback_query
        await q.answer()
        try:
            await q.delete_message()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=update.effective_user.id, text=text, parse_mode="Markdown", reply_markup=kb
        )
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler."""
    logger.error("Exception while handling update:", exc_info=context.error)
    try:
        if update and isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ Sorry, an error occurred. Please try again or use /start.",
            )
    except Exception as e:
        logger.warning(f"Error notification failed: {e}")

# ---------- Hybrid Marketplace / Requests ----------
async def marketplace_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Marketplace entry point."""
    url = f"{BASE_URL}/explorer"
    kb = [
        [InlineKeyboardButton("🌐 Open in Web App (Full Photos)", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton("⚡ Text Mode (Low Network)", callback_data="text_mode_marketplace_1")],
        [InlineKeyboardButton("🏠 Home", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "🛒 <b>Marketplace</b>\n\nChoose your viewing mode:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )

async def requests_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Requests entry point (brokers only)."""
    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS
    broker = get_broker(user_id)
    
    if not is_admin and (not broker or broker.get("status") != "approved"):
        await update.message.reply_text(
            "⛔ <b>Only approved brokers can view this!</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML",
        )
        return
    
    url = f"{BASE_URL}/explorer?tab=requests"
    kb = [
        [InlineKeyboardButton("🌐 Open in Web App (Full Photos)", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton("⚡ Text Mode (Low Network)", callback_data="text_mode_requests_1")],
        [InlineKeyboardButton("🏠 Home", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "📋 <b>Buyer Requests</b>\n\nChoose your viewing mode:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )

async def text_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text mode browsing."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "noop":
        return

    user_id = query.from_user.id
    chat_id = query.message.chat_id if query.message else user_id

    if data.startswith("tm_sold_"):
        try:
            lid = int(data.replace("tm_sold_", ""))
        except ValueError:
            return
        
        listing = get_listing_by_id(lid)
        if not listing:
            await query.answer("Not found", show_alert=True)
            return
        
        owner = listing.get("user_chat_id")
        if int(owner or 0) != int(user_id) and user_id not in ADMIN_IDS:
            await query.answer("⛔ Owner only!", show_alert=True)
            return
        
        if update_listing_status(lid, "sold"):
            await query.answer("✅ Marked as Sold Out!", show_alert=True)
            listing["status"] = "sold"
            try:
                mode = "marketplace" if str(listing.get("req_type", "")).upper() == "SELL" else "requests"
                await query.edit_message_text(
                    format_card(listing), parse_mode="HTML",
                    reply_markup=build_card_keyboard(mode, listing, viewer_id=user_id),
                    disable_web_page_preview=True,
                )
            except Exception:
                pass
        return

    if data.startswith("tm_call_"):
        try:
            lid = int(data.replace("tm_call_", ""))
        except ValueError:
            return
        listing = get_listing_by_id(lid)
        await query.answer(f"📞 {(listing or {}).get('phone') or 'N/A'}", show_alert=True)
        return

    parts = data.split("_")
    if len(parts) < 4 or parts[0] != "text":
        return
    
    mode = parts[2]
    try:
        page = max(1, int(parts[3]))
    except (ValueError, IndexError):
        page = 1

    if mode == "requests":
        broker = get_broker(user_id)
        if user_id not in ADMIN_IDS and (not broker or broker.get("status") != "approved"):
            await query.edit_message_text("⛔ Only approved brokers!", parse_mode="HTML")
            return

    try:
        req_type = "SELL" if mode == "marketplace" else "BUY"
        total = count_listings(req_type=req_type)
        items = get_listings_by_category_ordered(
            limit=TEXT_PAGE_SIZE, offset=(page - 1) * TEXT_PAGE_SIZE,
            req_type=req_type, order="DESC",
        )
        
        title = "🛒 <b>Marketplace</b>" if mode == "marketplace" else "📋 <b>Buyer Requests</b>"
        
        if not items:
            await query.edit_message_text(
                "📭 Nothing found.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="flow_home")]]),
            )
            return

        counts = increment_views([i["id"] for i in items if i.get("id")], VIEW_INCREMENT)
        for it in items:
            if it.get("id") in counts:
                it["view_count"] = counts[it["id"]]

        total_pages = max(1, (total + TEXT_PAGE_SIZE - 1) // TEXT_PAGE_SIZE)
        page = min(page, total_pages)

        try:
            await query.edit_message_text(
                f"{title}\n📄 Page <b>{page}/{total_pages}</b>  •  Total <b>{total}</b>",
                parse_mode="HTML",
            )
        except Exception:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{title}\n📄 Page <b>{page}/{total_pages}</b>  •  Total <b>{total}</b>",
                parse_mode="HTML",
            )

        for idx, it in enumerate(items):
            await context.bot.send_message(
                chat_id=chat_id,
                text=format_card(it),
                parse_mode="HTML",
                reply_markup=build_card_keyboard(
                    mode, it, viewer_id=user_id, page=page,
                    total_pages=total_pages, show_pagination=(idx == len(items) - 1),
                ),
                disable_web_page_preview=True,
            )
    
    except Exception as e:
        logger.error(f"text_mode_callback: {e}", exc_info=True)
        try:
            await context.bot.send_message(chat_id=chat_id, text="❌ Failed to load data.")
        except Exception:
            pass

# ---------- Brokers Directory ----------
async def view_brokers_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show brokers directory."""
    kb = [[InlineKeyboardButton(sc, callback_data=f"dir_sc_{sc}")] for sc in SUB_CITIES[:8]]
    kb.append([InlineKeyboardButton("🌐 All", callback_data="dir_sc_ሁሉም")])
    kb.append([InlineKeyboardButton("🏠 Home", callback_data="flow_home")])
    
    await update.message.reply_text(
        "📍 <b>Brokers Directory</b>\n\nSelect sub-city:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )

async def filter_brokers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Filter brokers by sub-city."""
    query = update.callback_query
    await query.answer()
    sub = query.data.replace("dir_sc_", "")
    brokers = get_approved_brokers_directory(sub_city=sub)
    
    if not brokers:
        await query.edit_message_text(f"📭 No brokers found in {sub}.", parse_mode="HTML")
        return

    await query.edit_message_text(
        f"📋 <b>Approved Brokers</b> — {sub}\nTotal: {len(brokers)}",
        parse_mode="HTML",
    )
    
    viewer = query.from_user.id
    for b in brokers[:15]:
        chat_id_b = b.get("chat_id")
        rows = [[
            InlineKeyboardButton("📞 Call", callback_data=f"broker_call_{chat_id_b}"),
            InlineKeyboardButton("💬 Direct Chat", url=f"tg://user?id={chat_id_b}"),
        ], [
            InlineKeyboardButton("⭐ Rate", callback_data=f"broker_rate_{chat_id_b}"),
        ]]
        if viewer == chat_id_b or viewer in ADMIN_IDS:
            rows.append([InlineKeyboardButton("🗑️ Delete Profile", callback_data=f"broker_del_{chat_id_b}")])
        
        await context.bot.send_message(
            chat_id=viewer,
            text=format_broker_card(b),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(rows),
        )

async def broker_call_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broker call."""
    q = update.callback_query
    await q.answer()
    try:
        cid = int(q.data.replace("broker_call_", ""))
    except ValueError:
        return
    b = get_broker(cid)
    await q.answer(f"📞 {(b or {}).get('phone') or 'N/A'}", show_alert=True)

async def broker_rate_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start broker rating."""
    q = update.callback_query
    await q.answer()
    try:
        cid = int(q.data.replace("broker_rate_", ""))
    except ValueError:
        return
    kb = [[
        InlineKeyboardButton(f"{n}⭐", callback_data=f"broker_star_{cid}_{n}")
        for n in range(1, 6)
    ]]
    await q.message.reply_text("⭐ Select rating (1–5):", reply_markup=InlineKeyboardMarkup(kb))

async def broker_star_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broker rating submission."""
    q = update.callback_query
    await q.answer()
    parts = q.data.split("_")
    try:
        cid, stars = int(parts[2]), int(parts[3])
    except (IndexError, ValueError):
        return
    
    if add_broker_rating(cid, q.from_user.id, stars):
        await q.edit_message_text(f"✅ {stars}⭐ rating submitted. Thank you!")
    else:
        await q.edit_message_text("❌ Error submitting rating.")

async def broker_del_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broker deletion."""
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

# ---------- Broker Registration ----------
async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start broker registration."""
    user = update.effective_user
    context.user_data.clear()
    context.user_data["broker_name"] = user.first_name or user.full_name or "User"
    context.user_data["broker_username"] = f"@{user.username}" if user.username else f"tg://user?id={user.id}"
    context.user_data["broker_role"] = "ደላላ"
    
    kb = [[KeyboardButton("📱 Share my phone number", request_contact=True)], ["🏠 ዋና ገጽ"]]
    await update.message.reply_text(
        f"✍️ <b>Broker Registration</b>\n\n"
        f"👤 Name: <b>{context.user_data['broker_name']}</b> (from Telegram)\n"
        f"📱 {context.user_data['broker_username']}\n\n"
        f"Please share your phone number:",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True),
        parse_mode="HTML",
    )
    return PHONE_NUMBER

async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle phone number input."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = (update.message.text or "").strip()
        if not validate_phone(phone):
            await update.message.reply_text("❌ Please enter a valid Ethiopian phone number.")
            return PHONE_NUMBER
    
    context.user_data["broker_phone"] = phone
    
    kb = [[InlineKeyboardButton(sc, callback_data=f"bsc_{sc}")] for sc in SUB_CITIES[:10]]
    kb.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await update.message.reply_text(
        "📍 <b>Select your sub-city:</b>",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )
    return SUB_CITY

async def broker_reg_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sub-city selection."""
    q = update.callback_query
    if q.data == "flow_home":
        return await go_home(update, context)
    
    await q.answer()
    context.user_data["broker_subcity"] = q.data.replace("bsc_", "")
    
    kb = [[InlineKeyboardButton(s, callback_data=f"bsp_{s}")] for s in SPECIALTIES]
    kb.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    
    await q.edit_message_text(
        "🎯 <b>Select your specialty:</b>",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )
    return SPECIALTY

async def broker_reg_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle specialty selection and save broker."""
    q = update.callback_query
    if q.data == "flow_home":
        return await go_home(update, context)
    
    await q.answer()
    specialty = q.data.replace("bsp_", "")
    user = update.effective_user
    
    try:
        broker_id = add_broker(
            chat_id=user.id,
            full_name=context.user_data.get("broker_name", user.first_name),
            phone=context.user_data.get("broker_phone", ""),
            role_type="ደላላ",
            national_id_photo=None,
            sub_city=context.user_data.get("broker_subcity", ""),
            specialty=specialty,
        )
        
        if broker_id:
            await q.edit_message_text(
                "✅ <b>Registration complete!</b>\n⏳ You will be notified when an admin approves your registration.",
                parse_mode="HTML",
            )
            
            if ADMIN_CHAT_ID_INT:
                try:
                    await context.bot.send_message(
                        chat_id=ADMIN_CHAT_ID_INT,
                        text=(
                            f"🚨 New broker registration\n"
                            f"👤 {context.user_data.get('broker_name')}\n"
                            f"📞 {context.user_data.get('broker_phone')}\n"
                            f"📍 {context.user_data.get('broker_subcity')} | {specialty}\n"
                            f"ID: `{user.id}`"
                        ),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("✅ Approve", callback_data=f"admin_appr_{user.id}"),
                            InlineKeyboardButton("❌ Reject", callback_data=f"admin_reje_{user.id}"),
                        ]]),
                    )
                except Exception as e:
                    logger.error(f"Admin notification failed: {e}")
            
            await context.bot.send_message(
                chat_id=user.id,
                text="🏠 Return to main menu",
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            )
        else:
            await q.edit_message_text(
                "❌ Registration failed. Please try again later.",
                parse_mode="HTML",
            )
            logger.error(f"Broker registration failed for user {user.id}")
    
    except Exception as e:
        logger.error(f"Broker registration error: {e}", exc_info=True)
        await q.edit_message_text(
            "❌ An error occurred during registration. Please try again later.",
            parse_mode="HTML",
        )
    
    context.user_data.clear()
    return ConversationHandler.END

# ---------- Support ----------
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help and support command."""
    text = (
        "📞 <b>Adika Marketplace — Support Center</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "❓ <b>How to use:</b>\n"
        "1️⃣ Buy/Rent — Register your request\n"
        "2️⃣ Sell/Rent out — List your property\n"
        "3️⃣ Marketplace — View available properties\n"
        "4️⃣ Brokers Directory — Find trusted brokers\n\n"
        f"📲 Admin: {SUPPORT_ADMIN_HANDLE}"
    )
    kb = [
        [InlineKeyboardButton("💬 Contact Admin", url=SUPPORT_ADMIN_URL)],
        [InlineKeyboardButton("🏠 Home", callback_data="flow_home")],
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

# ---------- Notification Prefs ----------
async def notification_prefs_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start notification preferences."""
    broker = get_broker(update.effective_user.id)
    if not broker:
        await update.message.reply_text(
            "⛔ Only registered brokers!",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
        )
        return
    
    prefs = broker.get("notification_prefs") or {}
    if isinstance(prefs, str):
        try:
            prefs = json.loads(prefs)
        except Exception:
            prefs = {}
    
    en = "✅" if prefs.get("enabled", True) else "❌"
    car = "✅" if prefs.get("car", True) else "❌"
    house = "✅" if prefs.get("house", True) else "❌"
    
    kb = [
        [InlineKeyboardButton(f"🔔 Notifications: {en}", callback_data="notif_pref_toggle")],
        [
            InlineKeyboardButton(f"🚗 Cars: {car}", callback_data="notif_pref_car"),
            InlineKeyboardButton(f"🏠 Houses: {house}", callback_data="notif_pref_house"),
        ],
        [InlineKeyboardButton("🏠 Home", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        f"⚙️ <b>Notification Preferences</b>\n\n🔔 {en}  🚗 {car}  🏠 {house}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )

async def notification_prefs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle notification preference toggles."""
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    broker = get_broker(uid)
    if not broker:
        return
    
    prefs = broker.get("notification_prefs") or {}
    if isinstance(prefs, str):
        try:
            prefs = json.loads(prefs)
        except Exception:
            prefs = {"car": True, "house": True, "enabled": True}
    
    d = q.data
    if d == "notif_pref_toggle":
        prefs["enabled"] = not prefs.get("enabled", True)
    elif d == "notif_pref_car":
        prefs["car"] = not prefs.get("car", True)
    elif d == "notif_pref_house":
        prefs["house"] = not prefs.get("house", True)
    
    update_broker_notification_prefs(uid, prefs)
    
    en = "✅" if prefs.get("enabled", True) else "❌"
    car = "✅" if prefs.get("car", True) else "❌"
    house = "✅" if prefs.get("house", True) else "❌"
    
    kb = [
        [InlineKeyboardButton(f"🔔 Notifications: {en}", callback_data="notif_pref_toggle")],
        [
            InlineKeyboardButton(f"🚗 Cars: {car}", callback_data="notif_pref_car"),
            InlineKeyboardButton(f"🏠 Houses: {house}", callback_data="notif_pref_house"),
        ],
        [InlineKeyboardButton("🏠 Home", callback_data="flow_home")],
    ]
    
    try:
        await q.edit_message_text(
            f"⚙️ <b>Notification Preferences</b>\n\n🔔 {en}  🚗 {car}  🏠 {house}",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="HTML",
        )
    except Exception:
        pass

# ---------- Admin Approval ----------
async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin broker approval/rejection."""
    q = update.callback_query
    await q.answer()
    
    if update.effective_user.id not in ADMIN_IDS:
        await q.answer("⛔ Admin only", show_alert=True)
        return
    
    data = q.data
    if data.startswith("admin_appr_"):
        tid = int(data.replace("admin_appr_", ""))
        if update_broker_status(tid, "approved"):
            try:
                await context.bot.send_message(
                    chat_id=tid,
                    text="🎉 Your registration has been approved! You can now view buyer requests.",
                    reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
                )
            except Exception:
                pass
            await q.edit_message_text((q.message.text or "") + "\n\n✅ Approved")
    
    elif data.startswith("admin_reje_"):
        tid = int(data.replace("admin_reje_", ""))
        update_broker_status(tid, "rejected")
        try:
            await context.bot.send_message(chat_id=tid, text="❌ Your registration has been rejected.")
        except Exception:
            pass
        await q.edit_message_text((q.message.text or "") + "\n\n❌ Rejected")

# ---------- BUYER CONVERSATION ----------
async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start buyer flow with dual form selection."""
    url = f"{BASE_URL}/buyer-form"
    kb = [
        [InlineKeyboardButton("🌐 Fill via Web App", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton("💬 Fill via Bot Form", callback_data="buyer_bot_form")],
        [InlineKeyboardButton("🏠 Home", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "🔍 <b>Buy / Rent</b>\n\nChoose how you want to submit your request:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )
    return BUYER_MAIN

async def buyer_bot_form_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start buyer bot conversation form."""
    query = update.callback_query if update.callback_query else None
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message
    
    await message.reply_text(
        "📝 <b>Buyer Request Form</b>\n\n"
        "Let's collect your request details step by step.\n"
        "What type of property are you looking for?",
        reply_markup=ReplyKeyboardMarkup([
            ["🚗 መኪና", "🏠 ቤት/ቦታ"],
            ["🏠 ዋና ገጽ"]
        ], resize_keyboard=True),
        parse_mode="HTML",
    )
    return BUYER_CATEGORY

async def buyer_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buyer category selection."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    category = update.message.text
    context.user_data["buyer_category"] = category
    
    await update.message.reply_text(
        f"✅ Selected: {category}\n\n"
        f"Please enter your budget range (e.g., 500,000 - 2,000,000 ETB):",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
    )
    return BUYER_BUDGET

async def buyer_budget_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buyer budget input."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    budget = update.message.text
    context.user_data["buyer_budget"] = budget
    
    await update.message.reply_text(
        "📝 Please describe what you're looking for in detail:\n"
        "(e.g., Toyota Vitz 2020, white, automatic, etc.)",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
    )
    return BUYER_DESCRIPTION

async def buyer_description_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buyer description input."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    description = sanitize_input(update.message.text)
    context.user_data["buyer_description"] = description
    
    await update.message.reply_text(
        "📞 Please enter your phone number (e.g., 0911223344):",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
    )
    return BUYER_PHONE

async def buyer_phone_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buyer phone input."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    phone = update.message.text.strip()
    if not validate_phone(phone):
        await update.message.reply_text(
            "❌ Please enter a valid Ethiopian phone number (e.g., 0911223344):",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
        )
        return BUYER_PHONE
    
    context.user_data["buyer_phone"] = phone
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, notify me", callback_data="buyer_alert_yes")],
        [InlineKeyboardButton("❌ No, thanks", callback_data="buyer_alert_no")],
    ])
    await update.message.reply_text(
        "🔔 Would you like to receive notifications when similar properties are listed?",
        reply_markup=kb,
        parse_mode="HTML",
    )
    return BUYER_ALERT

async def buyer_alert_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle buyer alert preference."""
    query = update.callback_query
    await query.answer()
    
    context.user_data["buyer_alert"] = query.data == "buyer_alert_yes"
    
    await query.edit_message_text(
        "📋 <b>Please confirm your request:</b>\n\n"
        f"📦 Category: {context.user_data.get('buyer_category', '—')}\n"
        f"💰 Budget: {context.user_data.get('buyer_budget', '—')}\n"
        f"📝 Description: {context.user_data.get('buyer_description', '—')}\n"
        f"📞 Phone: {context.user_data.get('buyer_phone', '—')}\n"
        f"🔔 Alerts: {'✅ Yes' if context.user_data.get('buyer_alert') else '❌ No'}\n\n"
        "✅ Submit request?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Submit", callback_data="buyer_submit")],
            [InlineKeyboardButton("❌ Cancel", callback_data="flow_home")],
        ]),
    )
    return BUYER_CONFIRM

async def buyer_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Submit buyer request."""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    
    try:
        budget = context.user_data.get("buyer_budget", "—")
        description = context.user_data.get("buyer_description", "")
        phone = context.user_data.get("buyer_phone", "")
        category = context.user_data.get("buyer_category", "መኪና")
        create_alert = context.user_data.get("buyer_alert", False)
        
        full_desc = f"💰 Budget: {budget}\n📝 {description}\n📞 {phone}\n"
        
        req_id = add_listing(
            user_chat_id=user.id,
            user_name=user.first_name or "User",
            req_type="BUY",
            main_category=category,
            sub_category="",
            action_type="መግዛት",
            property_type="",
            description=full_desc,
            price=budget,
            phone=phone,
            extra_data={
                "budget_range": budget,
                "create_alert": create_alert,
                "telegram_user": f"@{user.username}" if user.username else "",
            },
        )
        
        if req_id:
            if create_alert:
                save_search_alert(user.id, category, "", "")
            
            await query.edit_message_text(
                "✅ <b>Your request has been submitted successfully!</b>\n\n"
                f"📋 Request ID: #ADK-{req_id}\n"
                "📢 Brokers will contact you soon.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="flow_home")]]),
            )
            logger.info(f"✅ Buyer request #{req_id} submitted by user {user.id}")
        else:
            await query.edit_message_text(
                "❌ Failed to submit request. Please try again later.",
                parse_mode="HTML",
            )
    
    except Exception as e:
        logger.error(f"Buyer submit error: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ An error occurred. Please try again later.",
            parse_mode="HTML",
        )
    
    context.user_data.clear()
    return ConversationHandler.END

# ---------- SELLER CONVERSATION ----------
async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start seller flow with dual form selection."""
    url = f"{BASE_URL}/seller-form"
    kb = [
        [InlineKeyboardButton("🌐 Fill via Web App", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton("💬 Fill via Bot Form", callback_data="seller_bot_form")],
        [InlineKeyboardButton("🏠 Home", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "📢 <b>Sell / Rent Out</b>\n\nChoose how you want to submit your listing:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )
    return SELLER_MAIN

async def seller_bot_form_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start seller bot conversation form."""
    query = update.callback_query if update.callback_query else None
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message
    
    await message.reply_text(
        "📝 <b>Seller Listing Form</b>\n\n"
        "Let's collect your listing details step by step.\n"
        "What type of property are you selling?",
        reply_markup=ReplyKeyboardMarkup([
            ["🚗 መኪና", "🏠 ቤት/ቦታ"],
            ["🏠 ዋና ገጽ"]
        ], resize_keyboard=True),
        parse_mode="HTML",
    )
    return SELLER_CATEGORY

async def seller_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller category selection."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    category = update.message.text
    context.user_data["seller_category"] = category
    
    if category == "🚗 መኪና":
        await update.message.reply_text(
            "🚗 Select car type:",
            reply_markup=ReplyKeyboardMarkup([
                ["የቤት መኪና", "የሥራ መኪና"],
                ["ከባድ ተሽከርካሪ", "🏠 ዋና ገጽ"]
            ], resize_keyboard=True),
            parse_mode="HTML",
        )
        return SELLER_SUB_CATEGORY
    else:
        await update.message.reply_text(
            "🏠 Select house/property type:",
            reply_markup=ReplyKeyboardMarkup([
                ["ቪላ", "አፓርታማ", "ኮንዶሚኒየም"],
                ["ሪል እስቴት", "መሬት", "🏠 ዋና ገጽ"]
            ], resize_keyboard=True),
            parse_mode="HTML",
        )
        return SELLER_PROPERTY_TYPE

async def seller_sub_category_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller car sub-category selection."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data["seller_sub_category"] = update.message.text
    
    await update.message.reply_text(
        "⛽ Select fuel type:",
        reply_markup=ReplyKeyboardMarkup([
            ["ቤንዚን", "ናፍጣ"],
            ["ኤሌክትሪክ", "ሀይብሪድ"],
            ["🏠 ዋና ገጽ"]
        ], resize_keyboard=True),
        parse_mode="HTML",
    )
    return SELLER_FUEL

async def seller_fuel_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller fuel type selection."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data["seller_fuel"] = update.message.text
    
    await update.message.reply_text(
        "⚙️ Select transmission type:",
        reply_markup=ReplyKeyboardMarkup([
            ["ማንዋል", "ኦቶማቲክ"],
            ["🏠 ዋና ገጽ"]
        ], resize_keyboard=True),
        parse_mode="HTML",
    )
    return SELLER_TRANSMISSION

async def seller_transmission_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller transmission selection."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data["seller_transmission"] = update.message.text
    
    await update.message.reply_text(
        "📊 Select condition:",
        reply_markup=ReplyKeyboardMarkup([
            ["አዲስ", "ያገለገለ"],
            ["ጥገና የሚፍልግ", "🏠 ዋና ገጽ"]
        ], resize_keyboard=True),
        parse_mode="HTML",
    )
    return SELLER_CONDITION

async def seller_condition_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller condition selection."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data["seller_condition"] = update.message.text
    
    await update.message.reply_text(
        "🛣️ Enter mileage (KM):",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
        parse_mode="HTML",
    )
    return SELLER_MILEAGE

async def seller_mileage_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller mileage input."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data["seller_mileage"] = sanitize_input(update.message.text)
    
    await update.message.reply_text(
        "💰 Enter your price (ETB):",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
        parse_mode="HTML",
    )
    return SELLER_PRICE

async def seller_property_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller property type selection."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data["seller_property_type"] = update.message.text
    
    await update.message.reply_text(
        "🛏️ Number of bedrooms:",
        reply_markup=ReplyKeyboardMarkup([
            ["1", "2", "3"],
            ["4", "5+", "🏠 ዋና ገጽ"]
        ], resize_keyboard=True),
        parse_mode="HTML",
    )
    return SELLER_BEDROOMS

async def seller_bedrooms_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller bedrooms selection."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data["seller_bedrooms"] = update.message.text
    
    await update.message.reply_text(
        "🚗 Does it have parking?",
        reply_markup=ReplyKeyboardMarkup([
            ["አለ", "የለም"],
            ["🏠 ዋና ገጽ"]
        ], resize_keyboard=True),
        parse_mode="HTML",
    )
    return SELLER_PARKING

async def seller_parking_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller parking selection."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data["seller_parking"] = update.message.text
    
    await update.message.reply_text(
        "📊 Select condition:",
        reply_markup=ReplyKeyboardMarkup([
            ["አዲስ", "ጥሩ"],
            ["እድሳት የሚፍልግ", "🏠 ዋና ገጽ"]
        ], resize_keyboard=True),
        parse_mode="HTML",
    )
    return SELLER_HOUSE_CONDITION

async def seller_house_condition_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller house condition selection."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    context.user_data["seller_house_condition"] = update.message.text
    
    await update.message.reply_text(
        "💰 Enter your price (ETB):",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
        parse_mode="HTML",
    )
    return SELLER_PRICE

async def seller_price_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller price input."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    price = update.message.text.replace(',', '').replace(' ', '')
    if not price.isdigit():
        await update.message.reply_text(
            "❌ Please enter a valid number:",
            reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
            parse_mode="HTML",
        )
        return SELLER_PRICE
    
    context.user_data["seller_price"] = price
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="seller_neg_yes")],
        [InlineKeyboardButton("❌ No", callback_data="seller_neg_no")],
    ])
    await update.message.reply_text(
        "💰 Is the price negotiable?",
        reply_markup=kb,
        parse_mode="HTML",
    )
    return SELLER_NEGOTIABLE

async def seller_negotiable_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller negotiable preference."""
    query = update.callback_query
    await query.answer()
    
    context.user_data["seller_negotiable"] = query.data == "seller_neg_yes"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Yes, it's urgent", callback_data="seller_urgent_yes")],
        [InlineKeyboardButton("⏳ No, regular", callback_data="seller_urgent_no")],
    ])
    await query.edit_message_text(
        "⚡ Is this an urgent sale?",
        reply_markup=kb,
        parse_mode="HTML",
    )
    return SELLER_URGENT

async def seller_urgent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller urgent preference."""
    query = update.callback_query
    await query.answer()
    
    context.user_data["seller_urgent"] = query.data == "seller_urgent_yes"
    
    await query.edit_message_text(
        "📝 Enter a detailed description of your property:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
    )
    return SELLER_DETAILS

async def seller_details_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller description input."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    description = sanitize_input(update.message.text)
    context.user_data["seller_description"] = description
    
    await update.message.reply_text(
        "📞 Enter your phone number (e.g., 0911223344):",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
        parse_mode="HTML",
    )
    return SELLER_PHONE

async def seller_phone_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle seller phone input."""
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    
    phone = update.message.text.strip()
    if not validate_phone(phone):
        await update.message.reply_text(
            "❌ Please enter a valid Ethiopian phone number (e.g., 0911223344):",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
        )
        return SELLER_PHONE
    
    context.user_data["seller_phone"] = phone
    
    category = context.user_data.get("seller_category", "—")
    price = context.user_data.get("seller_price", "—")
    negotiable = "✅ Yes" if context.user_data.get("seller_negotiable") else "❌ No"
    urgent = "⚡ Yes" if context.user_data.get("seller_urgent") else "⏳ No"
    
    if category == "🚗 መኪና":
        details = (
            f"🚗 Car: {context.user_data.get('seller_sub_category', '—')}\n"
            f"⛽ Fuel: {context.user_data.get('seller_fuel', '—')}\n"
            f"⚙️ Transmission: {context.user_data.get('seller_transmission', '—')}\n"
            f"📊 Condition: {context.user_data.get('seller_condition', '—')}\n"
            f"🛣️ Mileage: {context.user_data.get('seller_mileage', '—')} KM\n"
        )
    else:
        details = (
            f"🏠 Type: {context.user_data.get('seller_property_type', '—')}\n"
            f"🛏️ Bedrooms: {context.user_data.get('seller_bedrooms', '—')}\n"
            f"🚗 Parking: {context.user_data.get('seller_parking', '—')}\n"
            f"📊 Condition: {context.user_data.get('seller_house_condition', '—')}\n"
        )
    
    await update.message.reply_text(
        "📋 <b>Please confirm your listing:</b>\n\n"
        f"📦 Category: {category}\n"
        f"{details}"
        f"💰 Price: {price} ETB\n"
        f"🤝 Negotiable: {negotiable}\n"
        f"⚡ Urgent: {urgent}\n"
        f"📝 Description: {context.user_data.get('seller_description', '—')[:100]}...\n"
        f"📞 Phone: {context.user_data.get('seller_phone', '—')}\n\n"
        "✅ Submit listing?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Submit", callback_data="seller_submit")],
            [InlineKeyboardButton("❌ Cancel", callback_data="flow_home")],
        ]),
    )
    return SELLER_CONFIRM

async def seller_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Submit seller listing."""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    
    try:
        category = context.user_data.get("seller_category", "መኪና")
        price = context.user_data.get("seller_price", "")
        description = context.user_data.get("seller_description", "")
        phone = context.user_data.get("seller_phone", "")
        
        is_car = category == "🚗 መኪና"
        
        if is_car:
            sub_category = context.user_data.get("seller_sub_category", "")
            extra = {
                "fuel_type": context.user_data.get("seller_fuel", ""),
                "transmission": context.user_data.get("seller_transmission", ""),
                "mileage": context.user_data.get("seller_mileage", ""),
                "condition": context.user_data.get("seller_condition", ""),
                "negotiable": context.user_data.get("seller_negotiable", True),
                "urgent_sale": context.user_data.get("seller_urgent", False),
            }
        else:
            sub_category = context.user_data.get("seller_property_type", "")
            extra = {
                "bedrooms": context.user_data.get("seller_bedrooms", ""),
                "parking": context.user_data.get("seller_parking", ""),
                "condition": context.user_data.get("seller_house_condition", ""),
                "negotiable": context.user_data.get("seller_negotiable", True),
                "urgent_sale": context.user_data.get("seller_urgent", False),
            }
        
        full_desc = f"💰 Price: {price} ETB\n📝 {description}\n📞 {phone}\n"
        
        req_id = add_listing(
            user_chat_id=user.id,
            user_name=user.first_name or "User",
            req_type="SELL",
            main_category=category,
            sub_category=sub_category,
            action_type="መሸጥ",
            property_type="",
            description=full_desc,
            price=price,
            phone=phone,
            extra_data=extra,
        )
        
        if req_id:
            await query.edit_message_text(
                "✅ <b>Your listing has been submitted successfully!</b>\n\n"
                f"📋 Listing ID: #ADK-{req_id}\n"
                "📢 Your listing will be visible in the marketplace soon.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="flow_home")]]),
            )
            logger.info(f"✅ Seller listing #{req_id} submitted by user {user.id}")
        else:
            await query.edit_message_text(
                "❌ Failed to submit listing. Please try again later.",
                parse_mode="HTML",
            )
    
    except Exception as e:
        logger.error(f"Seller submit error: {e}", exc_info=True)
        await query.edit_message_text(
            "❌ An error occurred. Please try again later.",
            parse_mode="HTML",
        )
    
    context.user_data.clear()
    return ConversationHandler.END

# ---------- Register Handlers ----------
def register_handlers(app):
    """Register all handlers with the application."""
    cancel = MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), go_home)

    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✍️ የደላላ/አቅራቢ መመዝገቢያ$"), broker_reg_start)],
        states={
            PHONE_NUMBER: [
                MessageHandler(filters.CONTACT, broker_reg_phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone),
                cancel,
            ],
            SUB_CITY: [
                CallbackQueryHandler(broker_reg_subcity, pattern="^bsc_"),
                CallbackQueryHandler(go_home, pattern="^flow_home$"),
            ],
            SPECIALTY: [
                CallbackQueryHandler(broker_reg_specialty, pattern="^bsp_"),
                CallbackQueryHandler(go_home, pattern="^flow_home$"),
            ],
        },
        fallbacks=[CommandHandler("start", start), cancel],
        allow_reentry=True,
        name="broker_registration",
        persistent=False,
    )

    buyer_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(buyer_bot_form_start, pattern="^buyer_bot_form$"),
            MessageHandler(filters.Regex("^🔍 ለመግዛት / ለመከራየት$"), buyer_start),
        ],
        states={
            BUYER_MAIN: [
                MessageHandler(filters.Regex("^(🚗 መኪና|🏠 ቤት/ቦታ)$"), buyer_category_chosen),
                cancel,
            ],
            BUYER_CATEGORY: [
                MessageHandler(filters.Regex("^(🚗 መኪና|🏠 ቤት/ቦታ)$"), buyer_category_chosen),
                cancel,
            ],
            BUYER_BUDGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_budget_entered),
                cancel,
            ],
            BUYER_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_description_entered),
                cancel,
            ],
            BUYER_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, buyer_phone_entered),
                cancel,
            ],
            BUYER_ALERT: [
                CallbackQueryHandler(buyer_alert_callback, pattern="^buyer_alert_"),
                CallbackQueryHandler(go_home, pattern="^flow_home$"),
            ],
            BUYER_CONFIRM: [
                CallbackQueryHandler(buyer_submit, pattern="^buyer_submit$"),
                CallbackQueryHandler(go_home, pattern="^flow_home$"),
            ],
        },
        fallbacks=[CommandHandler("start", start), cancel],
        allow_reentry=True,
        name="buyer_form",
        persistent=False,
    )

    seller_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(seller_bot_form_start, pattern="^seller_bot_form$"),
            MessageHandler(filters.Regex("^📢 ለመሸጥ / ለማከራየት$"), seller_start),
        ],
        states={
            SELLER_MAIN: [
                MessageHandler(filters.Regex("^(🚗 መኪና|🏠 ቤት/ቦታ)$"), seller_category_chosen),
                cancel,
            ],
            SELLER_CATEGORY: [
                MessageHandler(filters.Regex("^(🚗 መኪና|🏠 ቤት/ቦታ)$"), seller_category_chosen),
                cancel,
            ],
            SELLER_SUB_CATEGORY: [
                MessageHandler(filters.Regex("^(የቤት መኪና|የሥራ መኪና|ከባድ ተሽከርካሪ)$"), seller_sub_category_chosen),
                cancel,
            ],
            SELLER_FUEL: [
                MessageHandler(filters.Regex("^(ቤንዚን|ናፍጣ|ኤሌክትሪክ|ሀይብሪድ)$"), seller_fuel_chosen),
                cancel,
            ],
            SELLER_TRANSMISSION: [
                MessageHandler(filters.Regex("^(ማንዋል|ኦቶማቲክ)$"), seller_transmission_chosen),
                cancel,
            ],
            SELLER_CONDITION: [
                MessageHandler(filters.Regex("^(አዲስ|ያገለገለ|ጥገና የሚፍልግ)$"), seller_condition_chosen),
                cancel,
            ],
            SELLER_MILEAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_mileage_entered),
                cancel,
            ],
            SELLER_PROPERTY_TYPE: [
                MessageHandler(filters.Regex("^(ቪላ|አፓርታማ|ኮንዶሚኒየም|ሪል እስቴት|መሬት)$"), seller_property_type_chosen),
                cancel,
            ],
            SELLER_BEDROOMS: [
                MessageHandler(filters.Regex("^(1|2|3|4|5\\+)$"), seller_bedrooms_chosen),
                cancel,
            ],
            SELLER_PARKING: [
                MessageHandler(filters.Regex("^(አለ|የለም)$"), seller_parking_chosen),
                cancel,
            ],
            SELLER_HOUSE_CONDITION: [
                MessageHandler(filters.Regex("^(አዲስ|ጥሩ|እድሳት የሚፍልግ)$"), seller_house_condition_chosen),
                cancel,
            ],
            SELLER_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_price_entered),
                cancel,
            ],
            SELLER_NEGOTIABLE: [
                CallbackQueryHandler(seller_negotiable_callback, pattern="^seller_neg_"),
                CallbackQueryHandler(go_home, pattern="^flow_home$"),
            ],
            SELLER_URGENT: [
                CallbackQueryHandler(seller_urgent_callback, pattern="^seller_urgent_"),
                CallbackQueryHandler(go_home, pattern="^flow_home$"),
            ],
            SELLER_DETAILS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_details_entered),
                cancel,
            ],
            SELLER_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, seller_phone_entered),
                cancel,
            ],
            SELLER_CONFIRM: [
                CallbackQueryHandler(seller_submit, pattern="^seller_submit$"),
                CallbackQueryHandler(go_home, pattern="^flow_home$"),
            ],
        },
        fallbacks=[CommandHandler("start", start), cancel],
        allow_reentry=True,
        name="seller_form",
        persistent=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(broker_conv)
    app.add_handler(buyer_conv)
    app.add_handler(seller_conv)

    app.add_handler(MessageHandler(filters.Regex("^🛒 የገበያ ቦታ$"), marketplace_choice))
    app.add_handler(MessageHandler(filters.Regex("^📋 የፈላጊዎች ጥያቄዎች$"), requests_choice))
    app.add_handler(MessageHandler(filters.Regex("^👥 የደላሎች መድረክ$"), view_brokers_directory))
    app.add_handler(MessageHandler(filters.Regex("^📞 እገዛ / Support$"), help_command))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ የማሳወቂያ ማስተካከያ$"), notification_prefs_start))
    app.add_handler(cancel)

    app.add_handler(CallbackQueryHandler(go_home, pattern="^flow_home$"))
    app.add_handler(CallbackQueryHandler(text_mode_callback, pattern=r"^(text_mode_|tm_sold_|tm_call_)"))
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(filter_brokers_callback, pattern="^dir_sc_"))
    app.add_handler(CallbackQueryHandler(broker_call_cb, pattern="^broker_call_"))
    app.add_handler(CallbackQueryHandler(broker_rate_cb, pattern="^broker_rate_"))
    app.add_handler(CallbackQueryHandler(broker_star_cb, pattern="^broker_star_"))
    app.add_handler(CallbackQueryHandler(broker_del_cb, pattern="^broker_del_"))
    app.add_handler(CallbackQueryHandler(admin_approval_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(notification_prefs_callback, pattern="^notif_pref_"))

    app.add_error_handler(error_handler)
    logger.info("✅ All handlers registered")
