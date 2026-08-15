# models.py
"""
Adika Marketplace - Database Layer
PostgreSQL (preferred) + SQLite fallback.
Connection helpers + all CRUD operations.
"""

import json
import logging
import random
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor
import sqlite3

from config import DATABASE_URL, DB_FILE, ADMIN_CHAT_ID_INT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_db_connection():
    """Return a live connection (PostgreSQL or SQLite)."""
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        conn.autocommit = True
        return conn
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_placeholder() -> str:
    return "%s" if DATABASE_URL else "?"


def _row_to_dict(row, cursor=None) -> Dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if cursor and hasattr(cursor, "description"):
        return dict(zip([c[0] for c in cursor.description], row))
    return dict(row)


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_db() -> None:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        if DATABASE_URL:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id SERIAL PRIMARY KEY,
                    user_chat_id BIGINT NOT NULL,
                    user_name TEXT,
                    req_type TEXT NOT NULL,
                    main_category TEXT NOT NULL,
                    sub_category TEXT,
                    action_type TEXT,
                    property_type TEXT,
                    description TEXT NOT NULL,
                    price TEXT,
                    phone TEXT,
                    photo_id TEXT,
                    extra_data JSONB DEFAULT '{}',
                    status TEXT DEFAULT 'pending',
                    view_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS brokers (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    role_type TEXT NOT NULL,
                    national_id_photo TEXT,
                    sub_city TEXT NOT NULL,
                    rating REAL DEFAULT 5.0,
                    total_ratings INT DEFAULT 0,
                    completed_deals INT DEFAULT 0,
                    notification_prefs JSONB DEFAULT '{"car": true, "house": true, "price_min": 0, "price_max": 999999999, "enabled": true}',
                    status TEXT DEFAULT 'pending',
                    is_online BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS ratings (
                    id SERIAL PRIMARY KEY,
                    broker_chat_id BIGINT NOT NULL,
                    user_chat_id BIGINT NOT NULL,
                    stars INT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS broker_offers (
                    id SERIAL PRIMARY KEY,
                    request_id INTEGER NOT NULL,
                    broker_id BIGINT NOT NULL,
                    description TEXT,
                    photo_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS search_alerts (
                    id SERIAL PRIMARY KEY,
                    user_chat_id BIGINT NOT NULL,
                    main_category TEXT NOT NULL,
                    budget_min TEXT,
                    budget_max TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS listing_photos (
                    id SERIAL PRIMARY KEY,
                    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                    photo_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        else:
            # SQLite schema
            cur.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_chat_id INTEGER NOT NULL,
                    user_name TEXT,
                    req_type TEXT NOT NULL,
                    main_category TEXT NOT NULL,
                    sub_category TEXT,
                    action_type TEXT,
                    property_type TEXT,
                    description TEXT NOT NULL,
                    price TEXT,
                    phone TEXT,
                    photo_id TEXT,
                    extra_data TEXT DEFAULT '{}',
                    status TEXT DEFAULT 'pending',
                    view_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS brokers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    role_type TEXT NOT NULL,
                    national_id_photo TEXT,
                    sub_city TEXT NOT NULL,
                    rating REAL DEFAULT 5.0,
                    total_ratings INTEGER DEFAULT 0,
                    completed_deals INTEGER DEFAULT 0,
                    notification_prefs TEXT DEFAULT '{"car": true, "house": true, "price_min": 0, "price_max": 999999999, "enabled": true}',
                    status TEXT DEFAULT 'pending',
                    is_online INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker_chat_id INTEGER NOT NULL,
                    user_chat_id INTEGER NOT NULL,
                    stars INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS broker_offers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id INTEGER NOT NULL,
                    broker_id INTEGER NOT NULL,
                    description TEXT,
                    photo_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS search_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_chat_id INTEGER NOT NULL,
                    main_category TEXT NOT NULL,
                    budget_min TEXT,
                    budget_max TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS listing_photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER NOT NULL,
                    photo_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()

        # Safe ALTER for older DBs
        try:
            if DATABASE_URL:
                cur.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS extra_data JSONB DEFAULT '{}';")
                cur.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS view_count INTEGER DEFAULT 0;")
                cur.execute("ALTER TABLE brokers ADD COLUMN IF NOT EXISTS completed_deals INT DEFAULT 0;")
                cur.execute("ALTER TABLE brokers ADD COLUMN IF NOT EXISTS is_online BOOLEAN DEFAULT TRUE;")
            else:
                for col, typ in [
                    ("extra_data", "TEXT DEFAULT '{}'"),
                    ("view_count", "INTEGER DEFAULT 0"),
                ]:
                    try:
                        cur.execute(f"ALTER TABLE listings ADD COLUMN {col} {typ};")
                    except Exception:
                        pass
                for col, typ in [
                    ("completed_deals", "INTEGER DEFAULT 0"),
                    ("is_online", "INTEGER DEFAULT 1"),
                ]:
                    try:
                        cur.execute(f"ALTER TABLE brokers ADD COLUMN {col} {typ};")
                    except Exception:
                        pass
                conn.commit()
        except Exception as e:
            logger.warning(f"ALTER TABLE warning: {e}")

        logger.info("✅ Database initialised successfully")
    except Exception as e:
        logger.error(f"❌ Database init error: {e}", exc_info=True)
        if conn and not DATABASE_URL:
            conn.rollback()
    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------------------------
# Listings CRUD
# ---------------------------------------------------------------------------

def add_listing(
    user_chat_id: int,
    user_name: str,
    req_type: str,
    main_category: str,
    sub_category: str = "",
    action_type: str = "",
    property_type: str = "",
    description: str = "",
    price: Optional[str] = None,
    phone: Optional[str] = None,
    photo_id: Optional[str] = None,
    extra_data: Optional[Dict] = None,
    photos: Optional[List[str]] = None,
) -> Optional[int]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()

        extra_json = json.dumps(extra_data or {}, ensure_ascii=False)
        # Random baseline view count 35-90
        baseline_views = random.randint(35, 90)

        if DATABASE_URL:
            cur.execute(
                f"""
                INSERT INTO listings
                (user_chat_id, user_name, req_type, main_category, sub_category,
                 action_type, property_type, description, price, phone, photo_id,
                 extra_data, status, view_count)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p}::jsonb,'pending',{p})
                RETURNING id
                """,
                (
                    int(user_chat_id), str(user_name or "User"),
                    str(req_type).upper(), str(main_category),
                    str(sub_category or ""), str(action_type or ""),
                    str(property_type or ""), str(description),
                    str(price or ""), str(phone or ""),
                    photo_id, extra_json, baseline_views,
                ),
            )
            row = cur.fetchone()
            listing_id = row["id"] if isinstance(row, dict) else row[0]
        else:
            cur.execute(
                f"""
                INSERT INTO listings
                (user_chat_id, user_name, req_type, main_category, sub_category,
                 action_type, property_type, description, price, phone, photo_id,
                 extra_data, status, view_count)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},'pending',{p})
                """,
                (
                    int(user_chat_id), str(user_name or "User"),
                    str(req_type).upper(), str(main_category),
                    str(sub_category or ""), str(action_type or ""),
                    str(property_type or ""), str(description),
                    str(price or ""), str(phone or ""),
                    photo_id, extra_json, baseline_views,
                ),
            )
            listing_id = cur.lastrowid
            conn.commit()

        # Multi-photo support
        if photos and listing_id:
            for ph in photos[:5]:
                cur.execute(
                    f"INSERT INTO listing_photos (listing_id, photo_id) VALUES ({p},{p})",
                    (listing_id, ph),
                )
            if not DATABASE_URL:
                conn.commit()

        return listing_id
    except Exception as e:
        logger.error(f"add_listing error: {e}", exc_info=True)
        return None
    finally:
        if conn:
            conn.close()


def get_listing_by_id(listing_id: int) -> Optional[Dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(f"SELECT * FROM listings WHERE id = {p}", (listing_id,))
        row = cur.fetchone()
        if not row:
            return None
        item = _row_to_dict(row, cur)
        if isinstance(item.get("extra_data"), str):
            try:
                item["extra_data"] = json.loads(item["extra_data"])
            except Exception:
                item["extra_data"] = {}
        # photos
        cur.execute(f"SELECT photo_id FROM listing_photos WHERE listing_id = {p}", (listing_id,))
        photos = [r["photo_id"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
        if not photos and item.get("photo_id"):
            photos = [item["photo_id"]]
        item["photos"] = photos
        return item
    except Exception as e:
        logger.error(f"get_listing_by_id error: {e}")
        return None
    finally:
        if conn:
            conn.close()


def get_listings_by_category_ordered(
    limit: int = 12,
    offset: int = 0,
    req_type: Optional[str] = None,
    category: Optional[str] = None,
    order: str = "DESC",
    active_only: bool = True,
) -> List[Dict]:
    """Always ORDER BY created_at DESC (newest first)."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()

        where = ["status != 'deleted'"]
        params: List[Any] = []

        if active_only:
            where.append("status NOT IN ('sold','rented','expired')")
        if req_type:
            where.append(f"UPPER(req_type) = UPPER({p})")
            params.append(req_type)
        if category:
            where.append(f"main_category = {p}")
            params.append(category)

        where_sql = " AND ".join(where)
        order_sql = "DESC" if order.upper() != "ASC" else "ASC"

        cur.execute(
            f"""
            SELECT * FROM listings
            WHERE {where_sql}
            ORDER BY created_at {order_sql}
            LIMIT {p} OFFSET {p}
            """,
            params + [limit, offset],
        )
        rows = cur.fetchall()
        items = []
        for row in rows:
            item = _row_to_dict(row, cur)
            if isinstance(item.get("extra_data"), str):
                try:
                    item["extra_data"] = json.loads(item["extra_data"])
                except Exception:
                    item["extra_data"] = {}
            # photos
            cur.execute(
                f"SELECT photo_id FROM listing_photos WHERE listing_id = {p}",
                (item["id"],),
            )
            photos = [r["photo_id"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
            if not photos and item.get("photo_id"):
                photos = [item["photo_id"]]
            item["photos"] = photos
            if item.get("view_count") is None:
                item["view_count"] = 0
            items.append(item)
        return items
    except Exception as e:
        logger.error(f"get_listings_by_category_ordered error: {e}", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()


def count_listings(req_type: Optional[str] = None, active_only: bool = True) -> int:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        where = ["status != 'deleted'"]
        params = []
        if active_only:
            where.append("status NOT IN ('sold','rented','expired')")
        if req_type:
            where.append(f"UPPER(req_type) = UPPER({p})")
            params.append(req_type)
        cur.execute(f"SELECT COUNT(*) as cnt FROM listings WHERE {' AND '.join(where)}", params)
        row = cur.fetchone()
        return int(row["cnt"] if isinstance(row, dict) else row[0] or 0)
    except Exception as e:
        logger.error(f"count_listings error: {e}")
        return 0
    finally:
        if conn:
            conn.close()


def update_listing_status(listing_id: int, status: str) -> bool:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(f"UPDATE listings SET status = {p} WHERE id = {p}", (status, listing_id))
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"update_listing_status error: {e}")
        return False
    finally:
        if conn:
            conn.close()


def increment_view_count(listing_id: int, amount: int = 1) -> int:
    """Increment view_count. Returns new count."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(
            f"UPDATE listings SET view_count = COALESCE(view_count, 0) + {int(amount)} WHERE id = {p}",
            (listing_id,),
        )
        cur.execute(f"SELECT view_count FROM listings WHERE id = {p}", (listing_id,))
        row = cur.fetchone()
        if not DATABASE_URL:
            conn.commit()
        return int(row["view_count"] if isinstance(row, dict) else row[0] or 0)
    except Exception as e:
        logger.error(f"increment_view_count error: {e}")
        return 0
    finally:
        if conn:
            conn.close()


def expire_old_listings(days: int = 30) -> int:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if DATABASE_URL:
            cur.execute(
                """
                UPDATE listings SET status = 'expired'
                WHERE status = 'pending'
                  AND created_at < (NOW() - INTERVAL '%s days')
                """ % int(days)
            )
            count = cur.rowcount
        else:
            cur.execute(
                """
                UPDATE listings SET status = 'expired'
                WHERE status = 'pending'
                  AND created_at < datetime('now', ?)
                """,
                (f"-{int(days)} days",),
            )
            count = cur.rowcount
            conn.commit()
        logger.info(f"🧹 Auto-expiry: {count} listings marked expired")
        return count or 0
    except Exception as e:
        logger.error(f"expire_old_listings error: {e}")
        return 0
    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------------------------
# Brokers
# ---------------------------------------------------------------------------

def add_broker(
    chat_id: int,
    full_name: str,
    phone: str,
    role_type: str,
    national_id_photo: Optional[str],
    sub_city: str,
) -> Optional[int]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        if DATABASE_URL:
            cur.execute(
                f"""
                INSERT INTO brokers (chat_id, full_name, phone, role_type, national_id_photo, sub_city)
                VALUES ({p},{p},{p},{p},{p},{p})
                ON CONFLICT (chat_id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    phone = EXCLUDED.phone,
                    role_type = EXCLUDED.role_type,
                    national_id_photo = EXCLUDED.national_id_photo,
                    sub_city = EXCLUDED.sub_city,
                    status = 'pending'
                RETURNING id
                """,
                (chat_id, full_name, phone, role_type, national_id_photo, sub_city),
            )
            row = cur.fetchone()
            return row["id"] if isinstance(row, dict) else row[0]
        else:
            cur.execute(
                f"""
                INSERT OR REPLACE INTO brokers
                (chat_id, full_name, phone, role_type, national_id_photo, sub_city, status)
                VALUES ({p},{p},{p},{p},{p},{p},'pending')
                """,
                (chat_id, full_name, phone, role_type, national_id_photo, sub_city),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error(f"add_broker error: {e}")
        return None
    finally:
        if conn:
            conn.close()


def get_broker(chat_id: int) -> Optional[Dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(f"SELECT * FROM brokers WHERE chat_id = {p}", (chat_id,))
        row = cur.fetchone()
        if not row:
            return None
        b = _row_to_dict(row, cur)
        if isinstance(b.get("notification_prefs"), str):
            try:
                b["notification_prefs"] = json.loads(b["notification_prefs"])
            except Exception:
                b["notification_prefs"] = {}
        return b
    except Exception as e:
        logger.error(f"get_broker error: {e}")
        return None
    finally:
        if conn:
            conn.close()


def get_approved_brokers() -> List[Dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM brokers WHERE status = 'approved' ORDER BY created_at DESC")
        rows = cur.fetchall()
        result = []
        for row in rows:
            b = _row_to_dict(row, cur)
            if isinstance(b.get("notification_prefs"), str):
                try:
                    b["notification_prefs"] = json.loads(b["notification_prefs"])
                except Exception:
                    b["notification_prefs"] = {}
            result.append(b)
        return result
    except Exception as e:
        logger.error(f"get_approved_brokers error: {e}")
        return []
    finally:
        if conn:
            conn.close()


def get_approved_brokers_directory(sub_city: Optional[str] = None) -> List[Dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        if sub_city and sub_city != "ሁሉም":
            cur.execute(
                f"SELECT * FROM brokers WHERE status = 'approved' AND sub_city = {p} ORDER BY created_at DESC",
                (sub_city,),
            )
        else:
            cur.execute("SELECT * FROM brokers WHERE status = 'approved' ORDER BY created_at DESC")
        rows = cur.fetchall()
        result = []
        for row in rows:
            b = _row_to_dict(row, cur)
            if isinstance(b.get("notification_prefs"), str):
                try:
                    b["notification_prefs"] = json.loads(b["notification_prefs"])
                except Exception:
                    b["notification_prefs"] = {}
            result.append(b)
        return result
    except Exception as e:
        logger.error(f"get_approved_brokers_directory error: {e}")
        return []
    finally:
        if conn:
            conn.close()


def update_broker_status(chat_id: int, status: str) -> bool:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(f"UPDATE brokers SET status = {p} WHERE chat_id = {p}", (status, chat_id))
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"update_broker_status error: {e}")
        return False
    finally:
        if conn:
            conn.close()


def update_broker_notification_prefs(chat_id: int, prefs: Dict) -> bool:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        prefs_json = json.dumps(prefs)
        if DATABASE_URL:
            cur.execute(
                f"UPDATE brokers SET notification_prefs = {p}::jsonb WHERE chat_id = {p}",
                (prefs_json, chat_id),
            )
        else:
            cur.execute(
                f"UPDATE brokers SET notification_prefs = {p} WHERE chat_id = {p}",
                (prefs_json, chat_id),
            )
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"update_broker_notification_prefs error: {e}")
        return False
    finally:
        if conn:
            conn.close()


def save_broker_offer(request_id: int, broker_id: int, description: str, photo_id: Optional[str] = None) -> bool:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(
            f"INSERT INTO broker_offers (request_id, broker_id, description, photo_id) VALUES ({p},{p},{p},{p})",
            (request_id, broker_id, description, photo_id),
        )
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"save_broker_offer error: {e}")
        return False
    finally:
        if conn:
            conn.close()


def save_search_alert(user_chat_id: int, category: str, budget_min: str, budget_max: str) -> bool:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(
            f"""
            INSERT INTO search_alerts (user_chat_id, main_category, budget_min, budget_max)
            VALUES ({p},{p},{p},{p})
            """,
            (user_chat_id, category, budget_min, budget_max),
        )
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"save_search_alert error: {e}")
        return False
    finally:
        if conn:
            conn.close()


def rate_broker(broker_chat_id: int, user_chat_id: int, stars: int) -> bool:
    """Add a rating and recalculate average."""
    if not (1 <= stars <= 5):
        return False
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(
            f"INSERT INTO ratings (broker_chat_id, user_chat_id, stars) VALUES ({p},{p},{p})",
            (broker_chat_id, user_chat_id, stars),
        )
        cur.execute(
            f"SELECT AVG(stars), COUNT(*) FROM ratings WHERE broker_chat_id = {p}",
            (broker_chat_id,),
        )
        row = cur.fetchone()
        avg = float(row[0] if not isinstance(row, dict) else row["avg"] or 5.0)
        total = int(row[1] if not isinstance(row, dict) else row["count"] or 0)
        cur.execute(
            f"UPDATE brokers SET rating = {p}, total_ratings = {p} WHERE chat_id = {p}",
            (round(avg, 1), total, broker_chat_id),
        )
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"rate_broker error: {e}")
        return False
    finally:
        if conn:
            conn.close()
