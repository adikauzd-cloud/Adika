# ==============================================================================
# models.py — Database schema, connection, CRUD
# ==============================================================================
import json
import random
from typing import Optional, List, Dict, Any

import psycopg2
from psycopg2.extras import RealDictCursor
import sqlite3

from config import (
    DATABASE_URL, DB_FILE, logger,
    VIEW_BASELINE_MIN, VIEW_BASELINE_MAX,
)


def get_db_connection():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        conn.autocommit = True
        return conn
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_placeholder() -> str:
    return "%s" if DATABASE_URL else "?"


def _row_to_dict(row, cursor=None) -> Optional[dict]:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    if cursor is not None:
        return dict(zip([c[0] for c in cursor.description], row))
    try:
        return dict(row)
    except Exception:
        return None


def init_db():
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
                    specialty TEXT DEFAULT '',
                    rating REAL DEFAULT 5.0,
                    total_ratings INT DEFAULT 0,
                    completed_deals INT DEFAULT 0,
                    is_online BOOLEAN DEFAULT TRUE,
                    notification_prefs JSONB DEFAULT '{"car": true, "house": true, "enabled": true}',
                    status TEXT DEFAULT 'pending',
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
            for stmt in (
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS view_count INTEGER DEFAULT 0;",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS specialty TEXT DEFAULT '';",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS completed_deals INT DEFAULT 0;",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS is_online BOOLEAN DEFAULT TRUE;",
                "CREATE INDEX IF NOT EXISTS idx_listings_status_type ON listings(status, req_type);",
                "CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at DESC);",
                "CREATE INDEX IF NOT EXISTS idx_brokers_status ON brokers(status);",
            ):
                try:
                    cur.execute(stmt)
                except Exception as e:
                    logger.warning(f"migration: {e}")
        else:
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
                    specialty TEXT DEFAULT '',
                    rating REAL DEFAULT 5.0,
                    total_ratings INTEGER DEFAULT 0,
                    completed_deals INTEGER DEFAULT 0,
                    is_online INTEGER DEFAULT 1,
                    notification_prefs TEXT DEFAULT '{"car": true, "house": true, "enabled": true}',
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            for tbl in (
                """CREATE TABLE IF NOT EXISTS ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker_chat_id INTEGER NOT NULL,
                    user_chat_id INTEGER NOT NULL,
                    stars INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );""",
                """CREATE TABLE IF NOT EXISTS broker_offers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id INTEGER NOT NULL,
                    broker_id INTEGER NOT NULL,
                    description TEXT,
                    photo_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );""",
                """CREATE TABLE IF NOT EXISTS search_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_chat_id INTEGER NOT NULL,
                    main_category TEXT NOT NULL,
                    budget_min TEXT,
                    budget_max TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );""",
                """CREATE TABLE IF NOT EXISTS listing_photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER NOT NULL,
                    photo_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );""",
            ):
                cur.execute(tbl)
            for col_sql in (
                "ALTER TABLE listings ADD COLUMN view_count INTEGER DEFAULT 0;",
                "ALTER TABLE brokers ADD COLUMN specialty TEXT DEFAULT '';",
                "ALTER TABLE brokers ADD COLUMN completed_deals INTEGER DEFAULT 0;",
                "ALTER TABLE brokers ADD COLUMN is_online INTEGER DEFAULT 1;",
            ):
                try:
                    cur.execute(col_sql)
                except Exception:
                    pass
            conn.commit()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ init_db: {e}", exc_info=True)
        if conn and not DATABASE_URL:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ---------- Listings ----------

def add_listing(
    user_chat_id, user_name, req_type, main_category, sub_category,
    action_type, property_type, description, price=None, phone=None,
    photo_id=None, extra_data=None, photos=None,
) -> Optional[int]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        extra_json = json.dumps(extra_data or {}, ensure_ascii=False)
        baseline = random.randint(VIEW_BASELINE_MIN, VIEW_BASELINE_MAX)
        params = (
            int(user_chat_id or 0),
            str(user_name or "User"),
            str(req_type or "BUY").upper(),
            str(main_category or "መኪና"),
            str(sub_category or ""),
            str(action_type or ""),
            str(property_type or ""),
            str(description or ""),
            str(price or ""),
            str(phone or ""),
            str(photo_id) if photo_id else None,
            extra_json,
            baseline,
        )
        q = f"""
            INSERT INTO listings
            (user_chat_id, user_name, req_type, main_category, sub_category,
             action_type, property_type, description, price, phone, photo_id,
             extra_data, status, view_count)
            VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},'pending',{p})
        """
        if DATABASE_URL:
            cur.execute(q + " RETURNING id", params)
            row = cur.fetchone()
            req_id = row["id"] if isinstance(row, dict) else row[0]
        else:
            cur.execute(q, params)
            req_id = cur.lastrowid
            conn.commit()

        if photos and req_id:
            for photo in photos:
                try:
                    cur.execute(
                        f"INSERT INTO listing_photos (listing_id, photo_id) VALUES ({p},{p})",
                        (req_id, str(photo)),
                    )
                except Exception as pe:
                    logger.error(f"photo save: {pe}")
            if not DATABASE_URL:
                conn.commit()
        logger.info(f"✅ Listing #ADK-{req_id}")
        return req_id
    except Exception as e:
        logger.error(f"add_listing: {e}", exc_info=True)
        if conn and not DATABASE_URL:
            try:
                conn.rollback()
            except Exception:
                pass
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_listing_by_id(listing_id: int) -> Optional[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(f"SELECT * FROM listings WHERE id = {p}", (listing_id,))
        row = cur.fetchone()
        result = _row_to_dict(row, cur)
        if not result:
            return None
        if isinstance(result.get("extra_data"), str):
            try:
                result["extra_data"] = json.loads(result["extra_data"])
            except Exception:
                result["extra_data"] = {}
        cur.execute(f"SELECT photo_id FROM listing_photos WHERE listing_id = {p}", (listing_id,))
        photos = cur.fetchall()
        result["photos"] = [
            (r["photo_id"] if isinstance(r, dict) else r[0]) for r in photos
        ]
        if not result["photos"] and result.get("photo_id"):
            result["photos"] = [result["photo_id"]]
        return result
    except Exception as e:
        logger.error(f"get_listing_by_id: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_listings_by_category_ordered(
    limit=20, offset=0, req_type=None, order="DESC"
) -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        order_sql = "ASC" if str(order).upper() == "ASC" else "DESC"
        if req_type:
            cur.execute(
                f"""SELECT * FROM listings
                    WHERE status = 'pending' AND UPPER(req_type) = UPPER({p})
                    ORDER BY created_at {order_sql}
                    LIMIT {p} OFFSET {p}""",
                (req_type, limit, offset),
            )
        else:
            cur.execute(
                f"""SELECT * FROM listings WHERE status = 'pending'
                    ORDER BY created_at {order_sql} LIMIT {p} OFFSET {p}""",
                (limit, offset),
            )
        rows = cur.fetchall()
        results = []
        for row in rows:
            item = _row_to_dict(row, cur)
            if item and isinstance(item.get("extra_data"), str):
                try:
                    item["extra_data"] = json.loads(item["extra_data"])
                except Exception:
                    item["extra_data"] = {}
            results.append(item)
        return results
    except Exception as e:
        logger.error(f"get_listings_by_category_ordered: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def count_listings(req_type=None) -> int:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if req_type:
            p = get_placeholder()
            cur.execute(
                f"SELECT COUNT(*) as cnt FROM listings WHERE status='pending' AND UPPER(req_type)=UPPER({p})",
                (req_type,),
            )
        else:
            cur.execute("SELECT COUNT(*) as cnt FROM listings WHERE status='pending'")
        row = cur.fetchone()
        if isinstance(row, dict):
            return int(row.get("cnt") or 0)
        return int(row[0]) if row else 0
    except Exception as e:
        logger.error(f"count_listings: {e}")
        return 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def update_listing_status(req_id: int, status: str) -> bool:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(f"UPDATE listings SET status = {p} WHERE id = {p}", (status, req_id))
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"update_listing_status: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def increment_views(listing_ids: List[int], amount: int = 1) -> Dict[int, int]:
    result = {}
    if not listing_ids:
        return result
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        for lid in listing_ids:
            try:
                cur.execute(
                    f"UPDATE listings SET view_count = COALESCE(view_count,0) + {int(amount)} WHERE id = {p}",
                    (lid,),
                )
                cur.execute(f"SELECT view_count FROM listings WHERE id = {p}", (lid,))
                row = cur.fetchone()
                if row is not None:
                    result[lid] = row["view_count"] if isinstance(row, dict) else row[0]
            except Exception as e:
                logger.warning(f"view +{amount} failed {lid}: {e}")
        if not DATABASE_URL:
            conn.commit()
    except Exception as e:
        logger.error(f"increment_views: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return result


def get_public_marketplace_items(limit=20, offset=0) -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(
            f"""SELECT * FROM listings
                WHERE UPPER(req_type)='SELL' AND status != 'deleted'
                ORDER BY created_at DESC LIMIT {p} OFFSET {p}""",
            (limit, offset),
        )
        rows = cur.fetchall()
        out = []
        for row in rows:
            item = _row_to_dict(row, cur)
            if item and isinstance(item.get("extra_data"), str):
                try:
                    item["extra_data"] = json.loads(item["extra_data"])
                except Exception:
                    item["extra_data"] = {}
            out.append(item)
        return out
    except Exception as e:
        logger.error(f"get_public_marketplace_items: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def expire_old_listings(days: int = 30) -> int:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if DATABASE_URL:
            cur.execute(
                """UPDATE listings SET status='expired'
                   WHERE status='pending'
                     AND created_at < NOW() - make_interval(days => %s)""",
                (int(days),),
            )
            count = cur.rowcount or 0
        else:
            cur.execute(
                """UPDATE listings SET status='expired'
                   WHERE status='pending'
                     AND created_at < datetime('now', ?)""",
                (f"-{int(days)} days",),
            )
            count = cur.rowcount or 0
            conn.commit()
        logger.info(f"🧹 expired {count} listings")
        return count
    except Exception as e:
        logger.error(f"expire_old_listings: {e}")
        return 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# ---------- Brokers ----------

def add_broker(chat_id, full_name, phone, role_type, national_id_photo, sub_city, specialty="") -> Optional[int]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(f"SELECT id FROM brokers WHERE chat_id = {p}", (chat_id,))
        existing = cur.fetchone()
        prefs = json.dumps({"car": True, "house": True, "enabled": True})
        if existing:
            if DATABASE_URL:
                cur.execute(
                    f"""UPDATE brokers SET full_name={p}, phone={p}, role_type={p},
                        national_id_photo={p}, sub_city={p}, specialty={p}, status='pending'
                        WHERE chat_id={p} RETURNING id""",
                    (full_name, phone, role_type, national_id_photo, sub_city, specialty, chat_id),
                )
                row = cur.fetchone()
                broker_id = row["id"] if isinstance(row, dict) else row[0]
            else:
                cur.execute(
                    """UPDATE brokers SET full_name=?, phone=?, role_type=?,
                       national_id_photo=?, sub_city=?, specialty=?, status='pending'
                       WHERE chat_id=?""",
                    (full_name, phone, role_type, national_id_photo, sub_city, specialty, chat_id),
                )
                broker_id = existing["id"] if isinstance(existing, dict) else existing[0]
                conn.commit()
        else:
            if DATABASE_URL:
                cur.execute(
                    f"""INSERT INTO brokers
                        (chat_id, full_name, phone, role_type, national_id_photo, sub_city,
                         specialty, notification_prefs, status)
                        VALUES ({p},{p},{p},{p},{p},{p},{p},{p},'pending') RETURNING id""",
                    (chat_id, full_name, phone, role_type, national_id_photo, sub_city, specialty, prefs),
                )
                row = cur.fetchone()
                broker_id = row["id"] if isinstance(row, dict) else row[0]
            else:
                cur.execute(
                    """INSERT INTO brokers
                       (chat_id, full_name, phone, role_type, national_id_photo, sub_city,
                        specialty, notification_prefs, status)
                       VALUES (?,?,?,?,?,?,?,?, 'pending')""",
                    (chat_id, full_name, phone, role_type, national_id_photo, sub_city, specialty, prefs),
                )
                broker_id = cur.lastrowid
                conn.commit()
        logger.info(f"✅ Broker {broker_id}")
        return broker_id
    except Exception as e:
        logger.error(f"add_broker: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_broker(chat_id: int) -> Optional[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(f"SELECT * FROM brokers WHERE chat_id = {p}", (chat_id,))
        return _row_to_dict(cur.fetchone(), cur)
    except Exception as e:
        logger.error(f"get_broker: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def update_broker_status(chat_id: int, status: str) -> bool:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(f"UPDATE brokers SET status = {p} WHERE chat_id = {p}", (status.lower(), chat_id))
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"update_broker_status: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def update_broker_notification_prefs(chat_id: int, prefs: dict) -> bool:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(
            f"UPDATE brokers SET notification_prefs = {p} WHERE chat_id = {p}",
            (json.dumps(prefs, ensure_ascii=False), chat_id),
        )
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"update_broker_notification_prefs: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_approved_brokers() -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM brokers WHERE status = 'approved' ORDER BY created_at DESC")
        rows = cur.fetchall()
        results = []
        for row in rows:
            b = _row_to_dict(row, cur)
            if b and isinstance(b.get("notification_prefs"), str):
                try:
                    b["notification_prefs"] = json.loads(b["notification_prefs"])
                except Exception:
                    b["notification_prefs"] = {"car": True, "house": True, "enabled": True}
            results.append(b)
        return results
    except Exception as e:
        logger.error(f"get_approved_brokers: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_approved_brokers_directory(sub_city=None) -> List[dict]:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        if sub_city and sub_city != "ሁሉም":
            cur.execute(
                f"""SELECT * FROM brokers WHERE status='approved' AND sub_city={p}
                    ORDER BY created_at DESC""",
                (sub_city,),
            )
        else:
            cur.execute(
                "SELECT * FROM brokers WHERE status='approved' ORDER BY created_at DESC"
            )
        rows = cur.fetchall()
        return [_row_to_dict(r, cur) for r in rows]
    except Exception as e:
        logger.error(f"get_approved_brokers_directory: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def delete_broker(chat_id: int) -> bool:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(f"DELETE FROM brokers WHERE chat_id = {p}", (chat_id,))
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"delete_broker: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def add_broker_rating(broker_chat_id, user_chat_id, stars) -> bool:
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
            f"SELECT AVG(stars) as avg_stars, COUNT(*) as total_count FROM ratings WHERE broker_chat_id={p}",
            (broker_chat_id,),
        )
        result = cur.fetchone()
        if isinstance(result, dict):
            avg_stars = result.get("avg_stars") or 5.0
            total_count = result.get("total_count") or 0
        else:
            avg_stars = result[0] if result and result[0] else 5.0
            total_count = result[1] if result and result[1] else 0
        cur.execute(
            f"UPDATE brokers SET rating={p}, total_ratings={p} WHERE chat_id={p}",
            (round(float(avg_stars), 1), total_count, broker_chat_id),
        )
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"add_broker_rating: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def save_broker_offer(request_id, broker_id, description, photo_id=None) -> bool:
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
        logger.error(f"save_broker_offer: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def save_search_alert(user_chat_id, main_category, budget_min, budget_max) -> int:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cur.execute(
            f"""INSERT INTO search_alerts (user_chat_id, main_category, budget_min, budget_max)
                VALUES ({p},{p},{p},{p})""",
            (user_chat_id, main_category, budget_min or "", budget_max or ""),
        )
        if DATABASE_URL:
            cur.execute("SELECT lastval()")
            row = cur.fetchone()
            return (list(row.values())[0] if isinstance(row, dict) else row[0]) or 0
        alert_id = cur.lastrowid
        conn.commit()
        return alert_id or 0
    except Exception as e:
        logger.error(f"save_search_alert: {e}")
        return 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
