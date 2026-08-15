# ==============================================================================
# እነዚህን ተግባራት ወደ handlers.py ያክሉ (ከሌሎቹ አጠገብ)
# ==============================================================================

def _increment_views_batch(item_ids: List[int], amount: int = 13) -> Dict[int, int]:
    """Increment view_count for multiple listings by a random amount."""
    if not item_ids:
        return {}
    
    results = {}
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            
            for item_id in item_ids:
                boost = random.randint(3, 7)
                cursor.execute(f"SELECT view_count FROM listings WHERE id = {p}", (item_id,))
                row = cursor.fetchone()
                if row:
                    current = row[0] if not isinstance(row, dict) else row.get('view_count', 0)
                    new_count = (current or 0) + boost + amount
                    cursor.execute(f"UPDATE listings SET view_count = {p} WHERE id = {p}", (new_count, item_id))
                    results[item_id] = new_count
            
            if not DATABASE_URL:
                conn.commit()
            
    except Exception as e:
        logger.error(f"_increment_views_batch error: {e}")
    
    return results


def _build_single_card_keyboard(
    mode: str, 
    item: Dict[str, Any], 
    viewer_id: int, 
    page: int = 1, 
    total_pages: int = 1, 
    show_pagination: bool = True
) -> InlineKeyboardMarkup:
    """Build keyboard for a single card in text-mode view."""
    item_id = item.get('id')
    status = str(item.get('status', 'pending')).lower()
    is_sold = status in ('sold', 'rented', 'expired')
    owner_id = item.get('user_chat_id')
    is_admin = (viewer_id == ADMIN_CHAT_ID_INT and ADMIN_CHAT_ID_INT != 0)
    
    buttons = []
    
    # Main action buttons
    if mode == "marketplace":
        if not is_sold:
            buttons.append([
                InlineKeyboardButton("📞 Call", callback_data=f"tm_call_{item_id}"),
                InlineKeyboardButton("🤝 Contact", callback_data=f"have_buyer_{item_id}_{owner_id}")
            ])
        else:
            buttons.append([
                InlineKeyboardButton("📞 Call", callback_data=f"tm_call_{item_id}"),
                InlineKeyboardButton("🔴 Sold", callback_data="noop")
            ])
    else:  # requests mode
        buttons.append([
            InlineKeyboardButton("📞 Call", callback_data=f"tm_call_{item_id}"),
            InlineKeyboardButton("✅ Have it", callback_data=f"have_item_{item_id}_{item.get('user_chat_id')}")
        ])
    
    # Owner/Admin controls
    if not is_sold and (int(owner_id or 0) == int(viewer_id) or is_admin):
        buttons.append([
            InlineKeyboardButton("✅ Mark Sold", callback_data=f"tm_sold_{item_id}")
        ])
    
    # Pagination
    if show_pagination and total_pages > 1:
        nav_buttons = []
        if page > 1:
            nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"text_mode_{mode}_{page-1}"))
        nav_buttons.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"text_mode_{mode}_{page+1}"))
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("🏠 ዋና ገጽ", callback_data="flow_home")])
    return InlineKeyboardMarkup(buttons)
