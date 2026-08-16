# ==============================================================================
# models.py — Database connection, schema, CRUD
# ==============================================================================
import json
import random
from typing import Optional, List, Dict, Any

import psycopg2
from psycopg2.extras import RealDictCursor, Json
import sqlite3

from config import DATABASE_URL, DB_FILE, logger, VIEW_BASELINE_MIN, VIEW_BASELINE_MAX

def get_db_connection():
    if DATABASE_URL:
        cleaned_url = DATABASE_URL.strip().strip('"').strip("'")
        if cleaned_url.startswith("postgres://"):
            cleaned_url = cleaned_url.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(cleaned_url, cursor_factory=RealDictCursor)
        conn.autocommit = True
        return conn
    else:
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

def get_placeholder():
    return "%s" if DATABASE_URL else "?"

def init_db():
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("""
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
                    notification_prefs JSONB DEFAULT '{"car": true, "house": true, "price_min": 0, "price_max": 999999999, "enabled": true}',
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
        else:
            cursor.execute("""
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
            cursor.execute("""
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
                    notification_prefs TEXT DEFAULT '{"car": true, "house": true, "price_min": 0, "price_max": 999999999, "enabled": true}',
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker_chat_id INTEGER NOT NULL,
                    user_chat_id INTEGER NOT NULL,
                    stars INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broker_offers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id INTEGER NOT NULL,
                    broker_id INTEGER NOT NULL,
                    description TEXT,
                    photo_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_chat_id INTEGER NOT NULL,
                    main_category TEXT NOT NULL,
                    budget_min TEXT,
                    budget_max TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listing_photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER NOT NULL,
                    photo_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
        try:
            if DATABASE_URL:
                cursor.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS extra_data JSONB DEFAULT '{}';")
                cursor.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS view_count INTEGER DEFAULT 0;")
            else:
                try:
                    cursor.execute("ALTER TABLE listings ADD COLUMN extra_data TEXT DEFAULT '{}';")
                except:
                    pass
                try:
                    cursor.execute("ALTER TABLE listings ADD COLUMN view_count INTEGER DEFAULT 0;")
                except:
                    pass
            if not DATABASE_URL:
                conn.commit()
        except Exception as alter_err:
            logger.warning(f"ALTER TABLE warning: {alter_err}")
        logger.info("✅ Adika Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")
        if conn and not DATABASE_URL:
            conn.rollback()
    finally:
        if conn:
            conn.close()


# ==============================================================================
# 4. DATABASE OPERATIONS
# ==============================================================================

def add_listing(user_chat_id, user_name, req_type, main_category, sub_category,
                action_type, property_type, description, price=None, phone=None, 
                photo_id=None, extra_data=None, photos=None):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        if extra_data is None:
            extra_data = {}
        extra_json = json.dumps(extra_data, ensure_ascii=False) if not isinstance(extra_data, str) else extra_data
        user_chat_id = int(user_chat_id) if user_chat_id else 0
        user_name = str(user_name or "User")
        req_type = str(req_type or "BUY").upper()
        main_category = str(main_category or "መኪና")
        sub_category = str(sub_category or "")
        action_type = str(action_type or "")
        property_type = str(property_type or "")
        description = str(description or "")
        price = str(price or "")
        phone = str(phone or "")
        photo_id = str(photo_id) if photo_id else None
        import random as _rnd
        baseline_views = _rnd.randint(35, 90)  # social-proof baseline
        query = f"""
            INSERT INTO listings 
            (user_chat_id, user_name, req_type, main_category, sub_category, 
             action_type, property_type, description, price, phone, photo_id, extra_data, status, view_count)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, 'ONLINE', {p})
        """
        params = (
            user_chat_id, user_name, req_type, main_category, 
            sub_category, action_type, property_type, 
            description, price, phone, photo_id,
            extra_json, baseline_views
        )
        logger.info(f"📝 Inserting listing: user={user_chat_id}, type={req_type}, cat={main_category}")
        if DATABASE_URL:
            cursor.execute(query + " RETURNING id", params)
            row = cursor.fetchone()
            if row is None:
                logger.error("RETURNING id returned None")
                return None
            req_id = row["id"] if isinstance(row, dict) else row[0]
        else:
            cursor.execute(query, params)
            req_id = cursor.lastrowid
            conn.commit()
        logger.info(f"✅ Listing inserted with ID: {req_id}")
        if photos and req_id:
            logger.info(f"📸 Saving {len(photos)} photos for listing {req_id}")
            for photo in photos:
                try:
                    photo_str = str(photo)
                    cursor.execute(
                        f"INSERT INTO listing_photos (listing_id, photo_id) VALUES ({p}, {p})",
                        (req_id, photo_str)
                    )
                except Exception as pe:
                    logger.error(f"Failed to save photo for listing {req_id}: {pe}")
            if not DATABASE_URL:
                conn.commit()
        logger.info(f"✅ Listing added successfully → #ADK-{req_id}")
        return req_id
    except Exception as e:
        logger.error(f"❌ Add listing error: {e}", exc_info=True)
        if conn and not DATABASE_URL:
            try:
                conn.rollback()
            except:
                pass
        return None
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def get_listing_by_id(listing_id: int):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM listings WHERE id = {p}", (listing_id,))
        row = cursor.fetchone()
        if not row:
            return None
        result = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
        if 'extra_data' in result and isinstance(result['extra_data'], str):
            try:
                result['extra_data'] = json.loads(result['extra_data'])
            except:
                result['extra_data'] = {}
        try:
            cursor.execute(f"SELECT photo_id FROM listing_photos WHERE listing_id = {p}", (listing_id,))
            photo_rows = cursor.fetchall()
            result['photos'] = [dict(r)['photo_id'] if isinstance(r, dict) else r[0] for r in photo_rows]
        except Exception as e:
            logger.warning(f"Could not load photos for listing {listing_id}: {e}")
            result['photos'] = []
        return result
    except Exception as e:
        logger.error(f"Get listing by id error: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def get_listings_by_category(limit=10, offset=0, req_type=None):
    return get_listings_by_category_ordered(limit=limit, offset=offset, req_type=req_type, order="DESC")

def get_listings_by_category_ordered(limit=20, offset=0, req_type=None, order="DESC"):
    """Same filter as Mini App /api/explorer/listings: exclude deleted/sold/rented/expired."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        order_sql = "ASC" if str(order).upper() == "ASC" else "DESC"
        where = [
            "status IS NOT NULL",
            "status NOT IN ('deleted', 'sold', 'rented', 'expired')",
        ]
        params = []
        if req_type:
            where.append(f"UPPER(TRIM(req_type)) = UPPER(TRIM({p}))")
            params.append(str(req_type).strip())
        where_sql = " AND ".join(where)
        params.extend([int(limit), int(offset)])
        query = f"""
            SELECT * FROM listings
            WHERE {where_sql}
            ORDER BY COALESCE(created_at, CURRENT_TIMESTAMP) {order_sql}, id {order_sql}
            LIMIT {p} OFFSET {p}
        """
        if not DATABASE_URL:
            # SQLite: no CURRENT_TIMESTAMP in COALESCE the same way for missing
            query = f"""
                SELECT * FROM listings
                WHERE {where_sql}
                ORDER BY id {order_sql}
                LIMIT {p} OFFSET {p}
            """
        cursor.execute(query, params)
        rows = cursor.fetchall()
        results = []
        for row in rows:
            item = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
            if "extra_data" in item and isinstance(item["extra_data"], str):
                try:
                    item["extra_data"] = json.loads(item["extra_data"])
                except Exception:
                    item["extra_data"] = {}
            results.append(item)
        logger.info(f"get_listings_by_category_ordered type={req_type} → {len(results)} rows")
        return results
    except Exception as e:
        logger.error(f"get_listings_by_category_ordered error: {e}", exc_info=True)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def count_listings(req_type=None):
    """Count active listings — aligned with Mini App filters."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        where = [
            "status IS NOT NULL",
            "status NOT IN ('deleted', 'sold', 'rented', 'expired')",
        ]
        params = []
        if req_type:
            where.append(f"UPPER(TRIM(req_type)) = UPPER(TRIM({p}))")
            params.append(str(req_type).strip())
        where_sql = " AND ".join(where)
        cursor.execute(f"SELECT COUNT(*) as cnt FROM listings WHERE {where_sql}", params)
        row = cursor.fetchone()
        if isinstance(row, dict):
            return int(row.get("cnt") or 0)
        return int(row[0]) if row else 0
    except Exception as e:
        logger.error(f"Count listings error: {e}", exc_info=True)
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
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"UPDATE listings SET status = {p} WHERE id = {p}", (status, req_id))
        conn.commit()
        logger.info(f"✅ Listing {req_id} status updated to {status}")
        return True
    except Exception as e:
        logger.error(f"Update listing error: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def get_public_marketplace_items(limit: int = 20, offset: int = 0):
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return []
        cur = conn.cursor()
        p = get_placeholder()
        if DATABASE_URL:
            cur.execute("""
                SELECT * FROM listings 
                WHERE UPPER(req_type) = 'SELL'
                  AND status != 'deleted'
                ORDER BY created_at DESC NULLS LAST
                LIMIT %s OFFSET %s
            """, (limit, offset))
            rows = cur.fetchall()
            result = [dict(row) for row in rows]
        else:
            cur.execute("""
                SELECT * FROM listings 
                WHERE UPPER(req_type) = 'SELL'
                  AND status != 'deleted'
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
            result = [dict(zip(columns, row)) for row in rows]
        for item in result:
            if 'extra_data' in item and isinstance(item['extra_data'], str):
                try:
                    item['extra_data'] = json.loads(item['extra_data'])
                except:
                    item['extra_data'] = {}
        return result
    except Exception as e:
        logger.error(f"get_public_marketplace_items error: {e}", exc_info=True)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# ========== BROKER OPERATIONS ==========

def add_broker(
    chat_id,
    full_name,
    phone="",
    role_type="ደላላ",
    national_id_photo=None,
    sub_city="",
    specialty="",
    username="",
    fayda_photo_id=None,
) -> Optional[int]:
    """Insert or update broker. Returns broker id or None."""
    conn = None
    try:
        chat_id = int(chat_id)
        full_name = (str(full_name).strip() if full_name else "User")[:200]
        phone = (str(phone).strip() if phone else "")[:40]
        username = (str(username).strip() if username else "")[:120]
        role_type = (str(role_type).strip() if role_type else "ደላላ")[:80]
        sub_city = (str(sub_city).strip() if sub_city else "")[:80]
        specialty = (str(specialty).strip() if specialty else role_type)[:120]
        photo = str(national_id_photo) if national_id_photo else None
        fayda = str(fayda_photo_id) if fayda_photo_id else None
        prefs = {"car": True, "house": True, "enabled": True}

        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()

        # Safe column migrations
        try:
            if DATABASE_URL:
                for stmt in (
                    "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS username TEXT DEFAULT ''",
                    "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS specialty TEXT DEFAULT ''",
                    "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS is_online BOOLEAN DEFAULT TRUE",
                    "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS fayda_photo_id TEXT",
                ):
                    try:
                        cur.execute(stmt)
                    except Exception:
                        pass
            else:
                for stmt in (
                    "ALTER TABLE brokers ADD COLUMN username TEXT DEFAULT ''",
                    "ALTER TABLE brokers ADD COLUMN specialty TEXT DEFAULT ''",
                    "ALTER TABLE brokers ADD COLUMN is_verified INTEGER DEFAULT 0",
                    "ALTER TABLE brokers ADD COLUMN is_online INTEGER DEFAULT 1",
                    "ALTER TABLE brokers ADD COLUMN fayda_photo_id TEXT",
                ):
                    try:
                        cur.execute(stmt)
                        conn.commit()
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"broker col migrate: {e}")

        cur.execute(f"SELECT id FROM brokers WHERE chat_id = {p}", (chat_id,))
        existing = cur.fetchone()
        existing_id = (existing["id"] if isinstance(existing, dict) else existing[0]) if existing else None

        if DATABASE_URL:
            from psycopg2.extras import Json
            prefs_val = Json(prefs)
            if existing_id is not None:
                cur.execute(
                    f"""UPDATE brokers SET
                        full_name={p}, phone={p}, username={p}, role_type={p},
                        national_id_photo={p}, sub_city={p}, specialty={p},
                        status='ONLINE'
                        WHERE chat_id={p} RETURNING id""",
                    (full_name, phone, username, role_type, photo, sub_city, specialty, chat_id),
                )
            else:
                cur.execute(
                    f"""INSERT INTO brokers
                        (chat_id, full_name, phone, username, role_type, national_id_photo,
                         sub_city, specialty, notification_prefs, status, is_online)
                        VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},'ONLINE', TRUE)
                        RETURNING id""",
                    (chat_id, full_name, phone, username, role_type, photo,
                     sub_city, specialty, prefs_val),
                )
            row = cur.fetchone()
            broker_id = (row["id"] if isinstance(row, dict) else row[0]) if row else existing_id
        else:
            prefs_json = json.dumps(prefs, ensure_ascii=False)
            if existing_id is not None:
                cur.execute(
                    """UPDATE brokers SET full_name=?, phone=?, username=?, role_type=?,
                       national_id_photo=?, sub_city=?, specialty=?, status='ONLINE'
                       WHERE chat_id=?""",
                    (full_name, phone, username, role_type, photo, sub_city, specialty, chat_id),
                )
                broker_id = existing_id
            else:
                cur.execute(
                    """INSERT INTO brokers
                       (chat_id, full_name, phone, username, role_type, national_id_photo,
                        sub_city, specialty, notification_prefs, status, is_online)
                       VALUES (?,?,?,?,?,?,?,?,?, 'ONLINE', 1)""",
                    (chat_id, full_name, phone, username, role_type, photo,
                     sub_city, specialty, prefs_json),
                )
                broker_id = cur.lastrowid
            conn.commit()

        logger.info(f"✅ Broker saved id={broker_id} chat_id={chat_id} name={full_name!r}")
        return int(broker_id) if broker_id is not None else None
    except Exception as e:
        logger.error(f"add_broker FAILED: {e}", exc_info=True)
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



def get_broker(chat_id: int):
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"SELECT * FROM brokers WHERE chat_id = {p}", (chat_id,))
        row = cursor.fetchone()
        if row:
            return dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
        return None
    except Exception as e:
        logger.error(f"Get broker error: {e}")
        return None
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def update_broker_status(chat_id: int, status: str) -> bool:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"UPDATE brokers SET status = {p} WHERE chat_id = {p}", (status.lower(), chat_id))
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Update broker status error: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def update_broker_notification_prefs(chat_id: int, prefs: dict) -> bool:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        prefs_json = json.dumps(prefs, ensure_ascii=False)
        cursor.execute(f"UPDATE brokers SET notification_prefs = {p} WHERE chat_id = {p}", (prefs_json, chat_id))
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Update broker notification prefs error: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def get_approved_brokers():
    """Brokers eligible for notifications: ONLINE + approved (exclude rejected)."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM brokers
            WHERE status IS NULL
               OR LOWER(CAST(status AS TEXT)) IN ('approved', 'online', 'pending')
            """
        )
        rows = cursor.fetchall()
        results = []
        for row in rows:
            broker = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
            if 'notification_prefs' in broker and isinstance(broker['notification_prefs'], str):
                try:
                    broker['notification_prefs'] = json.loads(broker['notification_prefs'])
                except:
                    broker['notification_prefs'] = {"car": True, "house": True, "enabled": True}
            results.append(broker)
        return results
    except Exception as e:
        logger.error(f"Get approved brokers error: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def get_approved_brokers_directory(sub_city=None):
    return get_active_brokers(sub_city=sub_city, status="ONLINE")


def get_active_brokers(sub_city=None, status="ONLINE", limit=50, offset=0):
    """
    Fetch brokers for directory.
    Include every broker that is not rejected/deleted/banned.
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()

        # Simple inclusive filter — never hide pending/ONLINE/approved/NULL
        where = [
            "(status IS NULL OR LOWER(CAST(status AS TEXT)) NOT IN "
            "('rejected', 'deleted', 'banned', 'rejected'))"
        ]
        params = []

        if sub_city and str(sub_city).strip() not in ("ሁሉም", "አዲስ አበባ (ሙሉ)", "", "None"):
            where.append(f"sub_city = {p}")
            params.append(str(sub_city).strip())

        where_sql = " AND ".join(where)
        params += [int(limit), int(offset)]

        # Avoid NULLS LAST (breaks SQLite)
        sql = (
            f"SELECT * FROM brokers WHERE {where_sql} "
            f"ORDER BY id DESC LIMIT {p} OFFSET {p}"
        )
        logger.info(f"get_active_brokers SQL params={params} sub={sub_city!r}")
        cur.execute(sql, params)
        rows = cur.fetchall() or []
        cols = [col[0] for col in cur.description] if cur.description else []
        out = []
        for row in rows:
            try:
                b = dict(row) if isinstance(row, dict) else dict(zip(cols, row))
                if b.get("chat_id") is None:
                    continue
                b["chat_id"] = int(b["chat_id"])
                b["phone"] = b.get("phone") or ""
                b["username"] = b.get("username") or ""
                b["full_name"] = b.get("full_name") or "User"
                b["sub_city"] = b.get("sub_city") or ""
                b["specialty"] = b.get("specialty") or b.get("role_type") or ""
                b["status"] = b.get("status") or "ONLINE"
                if b.get("is_online") is None:
                    b["is_online"] = True
                if isinstance(b.get("notification_prefs"), str):
                    try:
                        b["notification_prefs"] = json.loads(b["notification_prefs"])
                    except Exception:
                        b["notification_prefs"] = {}
                out.append(b)
            except Exception as row_err:
                logger.warning(f"skip bad broker row: {row_err}")
                continue
        logger.info(f"get_active_brokers → {len(out)} brokers")
        return out
    except Exception as e:
        logger.error(f"get_active_brokers: {e}", exc_info=True)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass



def count_brokers(status="ONLINE") -> int:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if status in (None, "", "all"):
            cur.execute(
                "SELECT COUNT(*) as cnt FROM brokers WHERE status IS NULL OR status NOT IN ('rejected','deleted','banned')"
            )
        elif status in ("ONLINE", "online", "approved", "pending"):
            cur.execute(
                """SELECT COUNT(*) as cnt FROM brokers
                   WHERE status IS NULL
                      OR UPPER(COALESCE(status,'ONLINE')) IN ('ONLINE','APPROVED','PENDING')"""
            )
        else:
            p = get_placeholder()
            cur.execute(f"SELECT COUNT(*) as cnt FROM brokers WHERE status = {p}", (status,))
        row = cur.fetchone()
        return int((row["cnt"] if isinstance(row, dict) else row[0]) or 0)
    except Exception as e:
        logger.error(f"count_brokers: {e}")
        return 0
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
        cur.execute(f"DELETE FROM brokers WHERE chat_id = {p}", (int(chat_id),))
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


def get_platform_stats() -> dict:
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        stats = {}
        for key, sql in (
            ("active_listings", "SELECT COUNT(*) as cnt FROM listings WHERE status = 'ONLINE'"),
            ("verified_brokers", "SELECT COUNT(*) as cnt FROM brokers WHERE status = 'approved'"),
            ("total_listings", "SELECT COUNT(*) as cnt FROM listings"),
            ("active_users", "SELECT COUNT(DISTINCT user_chat_id) as cnt FROM listings"),
        ):
            cur.execute(sql)
            row = cur.fetchone()
            stats[key] = int((row["cnt"] if isinstance(row, dict) else row[0]) or 0)
        return stats
    except Exception as e:
        logger.error(f"get_platform_stats: {e}")
        return {"active_listings": 0, "verified_brokers": 0, "total_listings": 0, "active_users": 0}
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass



def save_broker_offer(request_id: int, broker_id: int, description: str, photo_id: str = None) -> bool:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"""
            INSERT INTO broker_offers (request_id, broker_id, description, photo_id)
            VALUES ({p}, {p}, {p}, {p})
        """, (request_id, broker_id, description, photo_id))
        if not DATABASE_URL:
            conn.commit()
        return True
    except Exception as e:
        logger.error(f"Save broker offer error: {e}")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# ========== RATINGS ==========

def add_broker_rating(broker_chat_id, user_chat_id, stars) -> bool:
    """
    2-step rating backend: save stars (1-5) and refresh average.
    Works on PostgreSQL and SQLite. Always commits.
    """
    conn = None
    try:
        broker_chat_id = int(broker_chat_id)
        user_chat_id = int(user_chat_id)
        stars = max(1, min(5, int(stars)))

        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()

        # --- Ensure schema ---
        if DATABASE_URL:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ratings (
                    id SERIAL PRIMARY KEY,
                    broker_chat_id BIGINT NOT NULL,
                    user_chat_id BIGINT NOT NULL,
                    stars INT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            try:
                cur.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ratings_broker_user_uidx "
                    "ON ratings (broker_chat_id, user_chat_id)"
                )
            except Exception as ix:
                logger.warning(f"ratings unique index: {ix}")
            for col_sql in (
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS rating REAL DEFAULT 5.0",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS total_ratings INT DEFAULT 0",
            ):
                try:
                    cur.execute(col_sql)
                except Exception:
                    pass
            # Upsert without relying solely on ON CONFLICT constraint name
            cur.execute(
                f"DELETE FROM ratings WHERE broker_chat_id = {p} AND user_chat_id = {p}",
                (broker_chat_id, user_chat_id),
            )
            cur.execute(
                f"INSERT INTO ratings (broker_chat_id, user_chat_id, stars) VALUES ({p}, {p}, {p})",
                (broker_chat_id, user_chat_id, stars),
            )
            cur.execute(
                f"SELECT COALESCE(AVG(stars), 5.0), COUNT(*) FROM ratings WHERE broker_chat_id = {p}",
                (broker_chat_id,),
            )
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    broker_chat_id INTEGER NOT NULL,
                    user_chat_id INTEGER NOT NULL,
                    stars INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (broker_chat_id, user_chat_id)
                )
            """)
            for col_sql in (
                "ALTER TABLE brokers ADD COLUMN rating REAL DEFAULT 5.0",
                "ALTER TABLE brokers ADD COLUMN total_ratings INTEGER DEFAULT 0",
            ):
                try:
                    cur.execute(col_sql)
                except Exception:
                    pass
            cur.execute(
                "DELETE FROM ratings WHERE broker_chat_id = ? AND user_chat_id = ?",
                (broker_chat_id, user_chat_id),
            )
            cur.execute(
                "INSERT INTO ratings (broker_chat_id, user_chat_id, stars) VALUES (?, ?, ?)",
                (broker_chat_id, user_chat_id, stars),
            )
            cur.execute(
                "SELECT COALESCE(AVG(stars), 5.0), COUNT(*) FROM ratings WHERE broker_chat_id = ?",
                (broker_chat_id,),
            )

        result = cur.fetchone()
        if isinstance(result, dict):
            vals = list(result.values())
            avg_stars = float(vals[0] or 5.0)
            total_count = int(vals[1] or 0)
        else:
            avg_stars = float(result[0] or 5.0)
            total_count = int(result[1] or 0)

        cur.execute(
            f"UPDATE brokers SET rating = {p}, total_ratings = {p} WHERE chat_id = {p}",
            (round(avg_stars, 1), total_count, broker_chat_id),
        )
        conn.commit()
        logger.info(
            f"✅ rating saved broker={broker_chat_id} user={user_chat_id} "
            f"stars={stars} avg={avg_stars:.1f} n={total_count}"
        )
        return True
    except Exception as e:
        logger.error(f"add_broker_rating error: {e}", exc_info=True)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass



def increment_listing_views(listing_id: int, amount: int = 1) -> int:
    """Increment view_count and return new value."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        listing_id = int(listing_id)
        amount = int(amount)
        if DATABASE_URL:
            cur.execute(
                f"UPDATE listings SET view_count = COALESCE(view_count, 0) + {p} WHERE id = {p} RETURNING view_count",
                (amount, listing_id),
            )
            row = cur.fetchone()
            conn.commit()
            if not row:
                return 0
            return int(row["view_count"] if isinstance(row, dict) else row[0])
        else:
            cur.execute(
                "UPDATE listings SET view_count = COALESCE(view_count, 0) + ? WHERE id = ?",
                (amount, listing_id),
            )
            conn.commit()
            cur.execute("SELECT view_count FROM listings WHERE id = ?", (listing_id,))
            row = cur.fetchone()
            if not row:
                return 0
            return int(row["view_count"] if isinstance(row, dict) else row[0])
    except Exception as e:
        logger.error(f"increment_listing_views: {e}")
        return 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass



def save_search_alert(user_chat_id: int, main_category: str, budget_min: str, budget_max: str) -> int:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"""
            INSERT INTO search_alerts (user_chat_id, main_category, budget_min, budget_max)
            VALUES ({p}, {p}, {p}, {p})
        """, (user_chat_id, main_category, budget_min or "", budget_max or ""))
        if DATABASE_URL:
            cursor.execute("SELECT lastval()")
            row = cursor.fetchone()
            alert_id = row[0] if not isinstance(row, dict) else list(row.values())[0]
        else:
            alert_id = cursor.lastrowid
            conn.commit()
        return alert_id or 0
    except Exception as e:
        logger.error(f"Save search alert error: {e}")
        return 0
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

def get_matching_alerts(main_category: str, price: str) -> list:
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        query = f"""
            SELECT * FROM search_alerts 
            WHERE is_active = TRUE AND main_category = {p}
            ORDER BY created_at DESC
        """
        cursor.execute(query, (main_category,))
        rows = cursor.fetchall()
        matching = []
        try:
            price_num = float(price) if price else 0
        except (ValueError, TypeError):
            price_num = 0
        for row in rows:
            alert = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
            try:
                alert_min = float(alert.get('budget_min', 0) or 0)
                alert_max = float(alert.get('budget_max', 999999999) or 999999999)
                if alert_min <= price_num <= alert_max:
                    matching.append(alert)
            except (ValueError, TypeError):
                matching.append(alert)
        return matching
    except Exception as e:
        logger.error(f"Get matching alerts error: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


# ==============================================================================
# 5. CONSTANTS & KEYBOARDS
# ==============================================================================


def expire_old_listings(days: int = 30) -> int:
    """
    Mark listings older than `days` as 'expired' if they are still active (pending).
    Safe: only touches status, never deletes rows.
    Returns number of rows updated.
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if DATABASE_URL:
            # PostgreSQL
            cur.execute("""
                UPDATE listings
                SET status = 'expired'
                WHERE status = 'ONLINE'
                  AND created_at < (NOW() - INTERVAL '%s days')
            """ % int(days))
            # rowcount available on cursor
            count = cur.rowcount
        else:
            # SQLite
            cur.execute("""
                UPDATE listings
                SET status = 'expired'
                WHERE status = 'ONLINE'
                  AND created_at < datetime('now', ?)
            """, (f'-{int(days)} days',))
            count = cur.rowcount
            conn.commit()
        logger.info(f"🧹 Auto-expiry: {count} listings marked expired (>{days} days)")
        return count or 0
    except Exception as e:
        logger.error(f"expire_old_listings error: {e}", exc_info=True)
        return 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass



