# ==============================================================================
# handlers.py — Telegram bot handlers, keyboards, conversations
# ==============================================================================
import json
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
    logger, MAIN_KEYBOARD, ADMIN_CHAT_ID_INT, ADMIN_IDS, SUB_CITIES, SPECIALTIES,
    TEXT_PAGE_SIZE, VIEW_INCREMENT, RENDER_EXTERNAL_HOSTNAME, WEBAPP_URL,
    SUPPORT_ADMIN_URL, SUPPORT_ADMIN_HANDLE,
    CAR_SUB_CATEGORIES, HOUSE_TYPES, PROPERTY_TYPES,
    FUEL_TYPES, TRANSMISSION_TYPES, CONDITIONS,
)
from models import (
    add_listing, get_listing_by_id, get_listings_by_category_ordered,
    count_listings, update_listing_status, increment_views,
    add_broker, get_broker, update_broker_status, update_broker_notification_prefs,
    get_approved_brokers, get_approved_brokers_directory, delete_broker,
    add_broker_rating, save_broker_offer, save_search_alert,
)

# Conversation states
(
    BUYER_MAIN, BUYER_ACTION, BUYER_SUB, BUYER_PROPERTY, BUYER_HTYPE,
    BUYER_DETAILS, BUYER_PHONE, BUYER_BUDGET_RANGE, BUYER_ALERT,
    SELLER_MAIN, SELLER_ACTION, SELLER_SUB, SELLER_PROPERTY, SELLER_HTYPE,
    SELLER_DETAILS, SELLER_PRICE, SELLER_NEGOTIABLE, SELLER_URGENT,
    SELLER_CONDITION, SELLER_FUEL, SELLER_TRANSMISSION, SELLER_MILEAGE,
    SELLER_BEDROOMS, SELLER_PARKING, SELLER_PHONE, SELLER_PHOTO, SELLER_HOUSE_CONDITION,
    BROKER_PHONE, BROKER_SUBCITY, BROKER_SPECIALTY,
    BROKER_OFFER_TEXT, BROKER_OFFER_PHOTO,
) = range(32)


# ---------- Helpers ----------

def validate_phone(phone: str) -> bool:
    if not phone:
        return False
    phone = phone.replace(" ", "").replace("-", "").replace("+", "")
    return bool(
        re.match(r"^(09|07|01)\d{8}$", phone)
        or re.match(r"^(9|7)\d{8}$", phone)
        or re.match(r"^251(9|7)\d{8}$", phone)
    )


def relative_time_am(created_at) -> str:
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
        now = datetime.utcnow()
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
    except Exception:
        return ""


def clean_description(desc: str, max_len: int = 60) -> str:
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


def format_card(item: dict) -> str:
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
        price_display = f"💰 <b>በጀት:</b> {extra.get('budget_range') or price or '—'} ብር"
    else:
        header = f"[🔴 Sold]  <code>#ADK-{item_id}</code>" if status in ("sold", "rented") else f"[🟢 Available]  <code>#ADK-{item_id}</code>"
        neg = "የሚደራደር" if extra.get("negotiable", True) else "የማይደራደር"
        urgent = " ⚡ አስቸኳይ" if extra.get("urgent_sale") else ""
        price_display = f"💰 <b>ዋጋ:</b> {price} ብር <i>({neg})</i>{urgent}"

    title = main_cat or "ንብረት"
    if sub_cat:
        title += f" ({sub_cat})"

    rel = relative_time_am(item.get("created_at"))
    lines = [header, "━━━━━━━━━━━━━━━━━━━━━", f"📌 <b>{title}</b>", price_display]
    desc = clean_description(item.get("description", ""), 60)
    if desc:
        lines += ["", f"📝 {desc}"]
    lines += [
        "━━━━━━━━━━━━━━━━━━━━━",
        f"👁️ <b>{views}</b> እይታዎች" + (f"  •  🕐 {rel}" if rel else ""),
        f"📞 <code>{phone}</code>",
    ]
    return "\n".join(lines)


def format_broker_card(b: dict) -> str:
    rating = float(b.get("rating") or 5)
    stars = "⭐" * min(5, int(rating))
    online = b.get("is_online", True)
    status = "🟢 ONLINE" if online else "⚪ OFFLINE"
    return (
        f"👤 <b>{b.get('full_name', '—')}</b>  {status}\n"
        f"✅ የታመነ ደላላ\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 ክፍለ ከተማ: {b.get('sub_city', '—')}\n"
        f"🎯 ሙያ: {b.get('specialty') or b.get('role_type', '—')}\n"
        f"⭐ {rating}/5.0 {stars}  ({b.get('total_ratings') or 0})\n"
        f"🤝 Completed: {b.get('completed_deals') or 0}\n"
        f"📞 <code>{b.get('phone', '—')}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )


def build_card_keyboard(mode: str, item: dict, viewer_id: int = 0,
                        page: int = 1, total_pages: int = 1,
                        show_pagination: bool = False) -> InlineKeyboardMarkup:
    """Uniform: Call | Sold Out → pagination → home."""
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


# ---------- Core handlers ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "👋 **እንኳን ወደ Adika Marketplace በደህና መጡ!**\n\n"
        "የመኪና፣ የቤት እና የንብረት ገበያ ማዕከል።\n"
        "እባክዎን አማራጭ ይምረጡ፦",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
    )
    return ConversationHandler.END


async def go_home(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    text = "👋 **ወደ ዋና ገጽ ተመልሰዋል!**\n\nእባክዎን አማራጭ ይምረጡ፦"
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
    logger.error("Exception while handling update:", exc_info=context.error)
    try:
        if update and isinstance(update, Update) and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ ይቅርታ፣ ስህተት ተከስቷል። እባክዎ እንደገና ይሞክሩ ወይም /start ይጫኑ።",
            )
    except Exception as e:
        logger.warning(f"error notify failed: {e}")


# ---------- Hybrid marketplace / requests ----------

async def marketplace_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = f"{WEBAPP_URL}/explorer"
    kb = [
        [InlineKeyboardButton("🌐 በዌብ አፕ ክፈት (ሙሉ ፎቶዎች)", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton("⚡ በጽሁፍ እይ (ለዝቅተኛ ኔትወርክ)", callback_data="text_mode_marketplace_1")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "🛒 <b>የገበያ ቦታ</b>\n\nእባክዎን የማሳያ መንገድ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )


async def requests_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS
    broker = get_broker(user_id)
    if not is_admin and (not broker or broker.get("status") != "approved"):
        await update.message.reply_text(
            "⛔ <b>ይህን ማየት የሚችሉት የተረጋገጡ ደላሎች ብቻ ናቸው!</b>",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            parse_mode="HTML",
        )
        return
    url = f"{WEBAPP_URL}/explorer?tab=requests"
    kb = [
        [InlineKeyboardButton("🌐 በዌብ አፕ ክፈት (ሙሉ ፎቶዎች)", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton("⚡ በጽሁፍ እይ (ለዝቅተኛ ኔትወርክ)", callback_data="text_mode_requests_1")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "📋 <b>የፈላጊዎች ጥያቄዎች</b>\n\nእባክዎን የማሳያ መንገድ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )


async def text_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            await query.edit_message_text("⛔ የተረጋገጡ ደላሎች ብቻ!", parse_mode="HTML")
            return

    try:
        req_type = "SELL" if mode == "marketplace" else "BUY"
        total = count_listings(req_type=req_type)
        items = get_listings_by_category_ordered(
            limit=TEXT_PAGE_SIZE, offset=(page - 1) * TEXT_PAGE_SIZE,
            req_type=req_type, order="DESC",
        )
        title = "🛒 <b>የገበያ ቦታ</b>" if mode == "marketplace" else "📋 <b>የፈላጊዎች ጥያቄዎች</b>"
        if not items:
            await query.edit_message_text(
                "📭 ምንም አልተገኘም።",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")]]),
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
            await context.bot.send_message(chat_id=chat_id, text="❌ መረጃ ማምጣት አልተቻለም።")
        except Exception:
            pass


# ---------- Brokers directory ----------

async def view_brokers_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(sc, callback_data=f"dir_sc_{sc}")] for sc in SUB_CITIES[:8]]
    kb.append([InlineKeyboardButton("🌐 ሁሉም", callback_data="dir_sc_ሁሉም")])
    kb.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await update.message.reply_text(
        "📍 <b>የደላሎች መድረክ</b>\n\nክፍለ ከተማ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )


async def filter_brokers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    sub = query.data.replace("dir_sc_", "")
    brokers = get_approved_brokers_directory(sub_city=sub)
    if not brokers:
        await query.edit_message_text(f"📭 በ{sub} ደላሎች አልተገኙም።", parse_mode="HTML")
        return

    await query.edit_message_text(
        f"📋 <b>የተረጋገጡ ደላሎች</b> — {sub}\nጠቅላላ: {len(brokers)}",
        parse_mode="HTML",
    )
    viewer = query.from_user.id
    for b in brokers[:15]:
        chat_id_b = b.get("chat_id")
        rows = [[
            InlineKeyboardButton("📞 Call", callback_data=f"broker_call_{chat_id_b}"),
            InlineKeyboardButton("💬 Direct Chat", url=f"tg://user?id={chat_id_b}"),
        ], [
            InlineKeyboardButton("⭐ ደረጃ ስጥ", callback_data=f"broker_rate_{chat_id_b}"),
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
    q = update.callback_query
    await q.answer()
    try:
        cid = int(q.data.replace("broker_call_", ""))
    except ValueError:
        return
    b = get_broker(cid)
    await q.answer(f"📞 {(b or {}).get('phone') or 'N/A'}", show_alert=True)


async def broker_rate_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await q.message.reply_text("⭐ ደረጃ ይምረጡ (1–5):", reply_markup=InlineKeyboardMarkup(kb))


async def broker_star_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split("_")
    try:
        cid, stars = int(parts[2]), int(parts[3])
    except (IndexError, ValueError):
        return
    if add_broker_rating(cid, q.from_user.id, stars):
        await q.edit_message_text(f"✅ {stars}⭐ ተመዝግቧል። እናመሰግናለን!")
    else:
        await q.edit_message_text("❌ ስህተት ተከስቷል።")


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


# ---------- Zero-friction broker registration ----------

async def broker_reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data.clear()
    context.user_data["broker_name"] = user.first_name or user.full_name or "User"
    context.user_data["broker_username"] = f"@{user.username}" if user.username else f"tg://user?id={user.id}"
    context.user_data["broker_role"] = "ደላላ"
    kb = [[KeyboardButton("📱 ስልክ ቁጥሬን አጋራ", request_contact=True)], ["🏠 ዋና ገጽ"]]
    await update.message.reply_text(
        f"✍️ <b>የደላላ መመዝገቢያ</b>\n\n"
        f"👤 ስም: <b>{context.user_data['broker_name']}</b> (ከTelegram)\n"
        f"📱 {context.user_data['broker_username']}\n\n"
        f"እባክዎ ስልክ ቁጥርዎን ያጋሩ፦",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True),
        parse_mode="HTML",
    )
    return BROKER_PHONE


async def broker_reg_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Accept contact share OR typed phone, then move to sub-city chips."""
    msg = update.message
    if msg and msg.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)

    phone = None
    if msg and msg.contact and msg.contact.phone_number:
        phone = msg.contact.phone_number
    elif msg and msg.text:
        phone = msg.text.strip()

    if not phone:
        await msg.reply_text(
            "❌ ስልክ አልተገኘም። ቁልፉን ይጫኑ ወይም ቁጥር ይጻፉ።",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📱 ስልክ ቁጥሬን አጋራ", request_contact=True)], ["🏠 ዋና ገጽ"]],
                resize_keyboard=True,
            ),
        )
        return BROKER_PHONE

    # Normalize: keep digits only for storage validation
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("251") and len(digits) >= 12:
        phone_norm = "0" + digits[3:12]
    elif len(digits) == 9 and digits[0] in ("9", "7"):
        phone_norm = "0" + digits
    else:
        phone_norm = digits if digits.startswith("0") else phone

    if not validate_phone(phone_norm) and not validate_phone(phone):
        await msg.reply_text(
            "❌ ትክክለኛ የኢትዮጵያ ስልክ ያስገቡ (ምሳሌ 0911223344)።",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📱 ስልክ ቁጥሬን አጋራ", request_contact=True)], ["🏠 ዋና ገጽ"]],
                resize_keyboard=True,
            ),
        )
        return BROKER_PHONE

    context.user_data["broker_phone"] = phone_norm if validate_phone(phone_norm) else phone

    # Index-based callback_data (avoids emoji/slash issues in Telegram)
    kb = []
    row = []
    for i, sc in enumerate(SUB_CITIES):
        row.append(InlineKeyboardButton(sc, callback_data=f"bsc_{i}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    await msg.reply_text(
        "✅ ስልክ ተቀብሏል።\n\n📍 <b>ክፍለ ከተማ ይምረጡ፦</b>",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )
    await msg.reply_text(
        "📍 ክፍለ ከተማ:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )
    return BROKER_SUBCITY


async def broker_reg_subcity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "flow_home":
        return await go_home(update, context)
    try:
        idx = int(q.data.replace("bsc_", ""))
        context.user_data["broker_subcity"] = SUB_CITIES[idx]
    except (ValueError, IndexError):
        context.user_data["broker_subcity"] = q.data.replace("bsc_", "")
    kb = [
        [InlineKeyboardButton(s, callback_data=f"bsp_{i}")]
        for i, s in enumerate(SPECIALTIES)
    ]
    kb.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    sub = context.user_data.get("broker_subcity", "")
    text = f"✅ {sub}\n\n🎯 <b>የሙያ ዘርፍ ይምረጡ፦</b>"
    try:
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    except Exception:
        await context.bot.send_message(
            chat_id=q.from_user.id,
            text=text,
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="HTML",
        )
    return BROKER_SPECIALTY


async def broker_reg_specialty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Final step: resolve specialty index and INSERT into brokers."""
    q = update.callback_query
    await q.answer()
    if q.data == "flow_home":
        return await go_home(update, context)

    try:
        idx = int(q.data.replace("bsp_", ""))
        specialty = SPECIALTIES[idx]
    except (ValueError, IndexError):
        specialty = q.data.replace("bsp_", "") or "🔄 ሁለቱም"

    user = update.effective_user
    full_name = context.user_data.get("broker_name") or user.first_name or "User"
    phone = context.user_data.get("broker_phone") or ""
    sub_city = context.user_data.get("broker_subcity") or ""

    try:
        bid = add_broker(
            chat_id=user.id,
            full_name=full_name,
            phone=phone,
            role_type="ደላላ",
            national_id_photo=None,
            sub_city=sub_city,
            specialty=specialty,
        )
    except Exception as e:
        logger.error(f"broker_reg_specialty add_broker: {e}", exc_info=True)
        bid = None

    if bid:
        ok_msg = "✅ <b>ምዝገባዎ ተጠናቋል!</b>\n⏳ አድሚን ካረጋገጠ በኋላ ማሳወቂያ ይደርስዎታል።"
        try:
            await q.edit_message_text(ok_msg, parse_mode="HTML")
        except Exception:
            await context.bot.send_message(chat_id=user.id, text=ok_msg, parse_mode="HTML")
        if ADMIN_CHAT_ID_INT:
            try:
                admin_text = (
                    f"🚨 አዲስ ደላላ\n"
                    f"👤 {full_name}\n"
                    f"📞 {phone}\n"
                    f"📍 {sub_city} | {specialty}\n"
                    f"ID: `{user.id}`"
                )
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID_INT,
                    text=admin_text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ አጽድቅ", callback_data=f"admin_appr_{user.id}"),
                        InlineKeyboardButton("❌ ሰርዝ", callback_data=f"admin_reje_{user.id}"),
                    ]]),
                )
            except Exception as e:
                logger.error(f"admin notify: {e}")
        await context.bot.send_message(
            chat_id=user.id,
            text="ወደ ዋና ገጽ ተመልሰዋል።",
            reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
        )
    else:
        fail_msg = "❌ ምዝገባ አልተሳካም። እባክዎ እንደገና ይሞክሩ ወይም /start ይጫኑ።"
        try:
            await q.edit_message_text(fail_msg, parse_mode="HTML")
        except Exception:
            await context.bot.send_message(
                chat_id=user.id,
                text=fail_msg,
                reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
            )
    context.user_data.clear()
    return ConversationHandler.END


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
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


# ---------- Notification prefs ----------

async def notification_prefs_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    broker = get_broker(update.effective_user.id)
    if not broker:
        await update.message.reply_text(
            "⛔ የተመዘገቡ ደላሎች ብቻ!",
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
        [InlineKeyboardButton(f"🔔 ማሳወቂያ: {en}", callback_data="notif_pref_toggle")],
        [
            InlineKeyboardButton(f"🚗 መኪና: {car}", callback_data="notif_pref_car"),
            InlineKeyboardButton(f"🏠 ቤት: {house}", callback_data="notif_pref_house"),
        ],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        f"⚙️ <b>የማሳወቂያ ማስተካከያ</b>\n\n🔔 {en}  🚗 {car}  🏠 {house}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )


async def notification_prefs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        [InlineKeyboardButton(f"🔔 ማሳወቂያ: {en}", callback_data="notif_pref_toggle")],
        [
            InlineKeyboardButton(f"🚗 መኪና: {car}", callback_data="notif_pref_car"),
            InlineKeyboardButton(f"🏠 ቤት: {house}", callback_data="notif_pref_house"),
        ],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    try:
        await q.edit_message_text(
            f"⚙️ <b>የማሳወቂያ ማስተካከያ</b>\n\n🔔 {en}  🚗 {car}  🏠 {house}",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="HTML",
        )
    except Exception:
        pass


# ---------- Admin approval ----------

async def admin_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                    text="🎉 ምዝገባዎ ፀድቋል! አሁን የፈላጊዎች ጥያቄዎችን ማየት ይችላሉ።",
                    reply_markup=ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True),
                )
            except Exception:
                pass
            await q.edit_message_text((q.message.text or "") + "\n\n✅ Approved")
    elif data.startswith("admin_reje_"):
        tid = int(data.replace("admin_reje_", ""))
        update_broker_status(tid, "rejected")
        try:
            await context.bot.send_message(chat_id=tid, text="❌ ምዝገባዎ ውድቅ ሆኗል።")
        except Exception:
            pass
        await q.edit_message_text((q.message.text or "") + "\n\n❌ Rejected")


# ---------- Simplified buyer/seller entry (WebApp primary) ----------

async def buyer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dual choice: Web App form OR step-by-step bot chat form."""
    url = f"{WEBAPP_URL}/buyer-form"
    kb = [
        [InlineKeyboardButton("🌐 በ Web App ይሙሉ", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton("💬 በ ቦት ፎርም ይሙሉ", callback_data="botform_buy_start")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "🔍 <b>ለመግዛት / ለመከራየት</b>\n\nእባክዎ የመሙያ መንገድ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )


async def seller_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dual choice: Web App form OR step-by-step bot chat form."""
    url = f"{WEBAPP_URL}/seller-form"
    kb = [
        [InlineKeyboardButton("🌐 በ Web App ይሙሉ", web_app=WebAppInfo(url=url))],
        [InlineKeyboardButton("💬 በ ቦት ፎርም ይሙሉ", callback_data="botform_sell_start")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await update.message.reply_text(
        "📢 <b>ለመሸጥ / ለማከራየት</b>\n\nእባክዎ የመሙያ መንገድ ይምረጡ፦",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="HTML",
    )


async def botform_buy_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    context.user_data["req_type"] = "BUY"
    kb = [
        [InlineKeyboardButton("🚗 መኪና", callback_data="bf_buy_cat_car")],
        [InlineKeyboardButton("🏠 ቤት", callback_data="bf_buy_cat_house")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await q.edit_message_text("📦 <b>ምድብ ይምረጡ፦</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return BUYER_MAIN


async def botform_sell_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    context.user_data.clear()
    context.user_data["req_type"] = "SELL"
    kb = [
        [InlineKeyboardButton("🚗 መኪና", callback_data="bf_sell_cat_car")],
        [InlineKeyboardButton("🏠 ቤት", callback_data="bf_sell_cat_house")],
        [InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")],
    ]
    await q.edit_message_text("📦 <b>ምድብ ይምረጡ፦</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return SELLER_MAIN


async def bf_buy_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data == "flow_home":
        return await go_home(update, context)
    await q.answer()
    context.user_data["main_category"] = "መኪና" if "car" in q.data else "ቤት"
    await q.edit_message_text(
        f"✅ {context.user_data['main_category']}\n\n💰 <b>የበጀት ክልል ያስገቡ</b>\nምሳሌ: <code>500000-1500000</code>",
        parse_mode="HTML",
    )
    return BUYER_BUDGET_RANGE


async def bf_buy_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data["budget_range"] = update.message.text.strip()
    await update.message.reply_text(
        "✍️ <b>ዝርዝር ፍላጎትዎን ይጻፉ፦</b>",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
    )
    return BUYER_DETAILS


async def bf_buy_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data["description"] = update.message.text
    await update.message.reply_text("📞 <b>ስልክ ቁጥርዎን ያስገቡ፦</b>", parse_mode="HTML")
    return BUYER_PHONE


async def bf_buy_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    phone = update.message.text.strip()
    if not validate_phone(phone):
        await update.message.reply_text("❌ ትክክለኛ ስልክ ያስገቡ።")
        return BUYER_PHONE
    user = update.effective_user
    ud = context.user_data
    req_id = add_listing(
        user_chat_id=user.id, user_name=user.first_name or "User", req_type="BUY",
        main_category=ud.get("main_category", "መኪና"), sub_category="", action_type="መግዛት",
        property_type="", description=ud.get("description", ""), price=ud.get("budget_range", ""),
        phone=phone,
        extra_data={"budget_range": ud.get("budget_range", ""), "telegram_user": f"@{user.username}" if user.username else ""},
    )
    kb = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    if req_id:
        await update.message.reply_text(f"✅ ጥያቄዎ ተመዝግቧል! 🆔 #ADK-{req_id}", reply_markup=kb)
    else:
        await update.message.reply_text("❌ ማስቀመጥ አልተቻለም።", reply_markup=kb)
    context.user_data.clear()
    return ConversationHandler.END


async def bf_sell_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data == "flow_home":
        return await go_home(update, context)
    await q.answer()
    context.user_data["main_category"] = "መኪና" if "car" in q.data else "ቤት"
    await q.edit_message_text(
        f"✅ {context.user_data['main_category']}\n\n✍️ <b>መግለጫ ይጻፉ፦</b>",
        parse_mode="HTML",
    )
    return SELLER_DETAILS


async def bf_sell_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    context.user_data["description"] = update.message.text
    await update.message.reply_text(
        "💰 <b>ዋጋ ያስገቡ (ብር)፦</b>",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([["🏠 ዋና ገጽ"]], resize_keyboard=True),
    )
    return SELLER_PRICE


async def bf_sell_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    price = update.message.text.replace(",", "").replace(" ", "")
    if not price.isdigit():
        await update.message.reply_text("❌ ቁጥር ብቻ ያስገቡ።")
        return SELLER_PRICE
    context.user_data["price"] = price
    await update.message.reply_text("📞 <b>ስልክ ቁጥርዎን ያስገቡ፦</b>", parse_mode="HTML")
    return SELLER_PHONE


async def bf_sell_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🏠 ዋና ገጽ":
        return await go_home(update, context)
    phone = update.message.text.strip()
    if not validate_phone(phone):
        await update.message.reply_text("❌ ትክክለኛ ስልክ ያስገቡ።")
        return SELLER_PHONE
    user = update.effective_user
    ud = context.user_data
    req_id = add_listing(
        user_chat_id=user.id, user_name=user.first_name or "User", req_type="SELL",
        main_category=ud.get("main_category", "መኪና"), sub_category="", action_type="መሸጥ",
        property_type="", description=ud.get("description", ""), price=ud.get("price", ""),
        phone=phone,
        extra_data={"negotiable": True, "telegram_user": f"@{user.username}" if user.username else ""},
    )
    kb = ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True)
    if req_id:
        await update.message.reply_text(f"✅ ማስታወቂያዎ ተመዝግቧል! 🆔 #ADK-{req_id}", reply_markup=kb)
    else:
        await update.message.reply_text("❌ ማስቀመጥ አልተቻለም።", reply_markup=kb)
    context.user_data.clear()
    return ConversationHandler.END


# ---------- Register all handlers ----------

def register_handlers(app):
    cancel = MessageHandler(filters.Regex("^🏠 ዋና ገጽ$"), go_home)

    broker_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✍️ የደላላ/አቅራቢ መመዝገቢያ$"), broker_reg_start)],
        states={
            BROKER_PHONE: [
                MessageHandler(filters.CONTACT, broker_reg_phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, broker_reg_phone),
                cancel,
            ],
            BROKER_SUBCITY: [
                CallbackQueryHandler(broker_reg_subcity, pattern=r"^(bsc_|flow_home)"),
            ],
            BROKER_SPECIALTY: [
                CallbackQueryHandler(broker_reg_specialty, pattern=r"^(bsp_|flow_home)"),
            ],
        },
        fallbacks=[CommandHandler("start", start), cancel],
        allow_reentry=True,
        per_message=False,
    )

    buy_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(botform_buy_start, pattern="^botform_buy_start$")],
        states={
            BUYER_MAIN: [CallbackQueryHandler(bf_buy_category, pattern=r"^(bf_buy_cat_|flow_home)")],
            BUYER_BUDGET_RANGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bf_buy_budget), cancel],
            BUYER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, bf_buy_details), cancel],
            BUYER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bf_buy_phone), cancel],
        },
        fallbacks=[CommandHandler("start", start), cancel],
        allow_reentry=True,
    )

    sell_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(botform_sell_start, pattern="^botform_sell_start$")],
        states={
            SELLER_MAIN: [CallbackQueryHandler(bf_sell_category, pattern=r"^(bf_sell_cat_|flow_home)")],
            SELLER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, bf_sell_details), cancel],
            SELLER_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bf_sell_price), cancel],
            SELLER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bf_sell_phone), cancel],
        },
        fallbacks=[CommandHandler("start", start), cancel],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(broker_conv)
    app.add_handler(buy_conv)
    app.add_handler(sell_conv)

    app.add_handler(MessageHandler(filters.Regex("^🔍 ለመግዛት / ለመከራየት$"), buyer_start))
    app.add_handler(MessageHandler(filters.Regex("^📢 ለመሸጥ / ለማከራየት$"), seller_start))
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
    logger.info("✅ Handlers registered")
