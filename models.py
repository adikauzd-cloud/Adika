# ==============================================================================
# models.py — Database schema, connection, CRUD (Fixed)
# ==============================================================================
import json
import random
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from contextlib import contextmanager
import time
import logging

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
import sqlite3

from config import (
    DATABASE_URL, DB_FILE, logger,
    VIEW_BASELINE_MIN, VIEW_BASELINE_MAX,
    MAX_PHOTOS, PHONE_PATTERNS,
    ENVIRONMENT, CACHE_ENABLED
)

# ---------- Connection Pooling ----------
_pool = None
_pool_initialized = False

def get_db_connection():
    """Get a database connection with pooling for PostgreSQL."""
    global _pool, _pool_initialized
    
    if DATABASE_URL:
        if not _pool_initialized:
            try:
                _pool = SimpleConnectionPool(
                    minconn=1,
                    maxconn=10,
                    dsn=DATABASE_URL,
                    cursor_factory=RealDictCursor
                )
                _pool_initialized = True
                logger.info("✅ PostgreSQL connection pool initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize connection pool: {e}")
                raise
        
        try:
            return _pool.getconn()
        except Exception as e:
            logger.error(f"❌ Failed to get connection from pool: {e}")
            conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            conn.autocommit = True
            return conn
    
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def return_connection(conn):
    """Return connection to pool if using PostgreSQL."""
    global _pool
    if DATABASE_URL and _pool and _pool_initialized:
        try:
            _pool.putconn(conn)
        except Exception as e:
            logger.warning(f"Failed to return connection to pool: {e}")
            try:
                conn.close()
            except:
                pass

@contextmanager
def db_transaction():
    """Context manager for database transactions."""
    conn = None
    try:
        conn = get_db_connection()
        yield conn
        if not DATABASE_URL:
            conn.commit()
    except Exception as e:
        if conn and not DATABASE_URL:
            try:
                conn.rollback()
            except:
                pass
        raise
    finally:
        if conn:
            return_connection(conn)

def get_placeholder() -> str:
    return "%s" if DATABASE_URL else "?"

def _row_to_dict(row, cursor=None) -> Optional[dict]:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    if cursor is not None:
        try:
            columns = [c[0] for c in cursor.description]
            return dict(zip(columns, row))
        except:
            pass
    try:
        return dict(row)
    except:
        return None

def _parse_extra_data(item: dict) -> dict:
    """Parse extra_data field from JSON string to dict."""
    if not item:
        return {}
    if isinstance(item.get("extra_data"), str):
        try:
            item["extra_data"] = json.loads(item["extra_data"])
        except Exception:
            item["extra_data"] = {}
    return item

def _get_current_time():
    """Get current UTC time with timezone awareness."""
    return datetime.now(timezone.utc)

def init_db():
    """Initialize database with all tables and indexes."""
    try:
        with db_transaction() as conn:
            cur = conn.cursor()
            
            if DATABASE_URL:
                # PostgreSQL tables
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
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
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
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS ratings (
                        id SERIAL PRIMARY KEY,
                        broker_chat_id BIGINT NOT NULL,
                        user_chat_id BIGINT NOT NULL,
                        stars INT NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS broker_offers (
                        id SERIAL PRIMARY KEY,
                        request_id INTEGER NOT NULL,
                        broker_id BIGINT NOT NULL,
                        description TEXT,
                        photo_id TEXT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS search_alerts (
                        id SERIAL PRIMARY KEY,
                        user_chat_id BIGINT NOT NULL,
                        main_category TEXT NOT NULL,
                        budget_min TEXT,
                        budget_max TEXT,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS listing_photos (
                        id SERIAL PRIMARY KEY,
                        listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
                        photo_id TEXT NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                
                # Indexes
                for stmt in [
                    "CREATE INDEX IF NOT EXISTS idx_listings_status_type ON listings(status, req_type);",
                    "CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at DESC);",
                    "CREATE INDEX IF NOT EXISTS idx_listings_user ON listings(user_chat_id);",
                    "CREATE INDEX IF NOT EXISTS idx_listings_category ON listings(main_category);",
                    "CREATE INDEX IF NOT EXISTS idx_brokers_status ON brokers(status);",
                    "CREATE INDEX IF NOT EXISTS idx_brokers_sub_city ON brokers(sub_city);",
                    "CREATE INDEX IF NOT EXISTS idx_ratings_broker ON ratings(broker_chat_id);",
                ]:
                    try:
                        cur.execute(stmt)
                    except Exception as e:
                        logger.warning(f"Index creation warning: {e}")
            
            else:
                # SQLite tables
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
                
                for tbl in [
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(listing_id) REFERENCES listings(id) ON DELETE CASCADE
                    );""",
                ]:
                    cur.execute(tbl)
                
                # Add missing columns
                for col_sql in [
                    "ALTER TABLE listings ADD COLUMN view_count INTEGER DEFAULT 0;",
                    "ALTER TABLE brokers ADD COLUMN specialty TEXT DEFAULT '';",
                    "ALTER TABLE brokers ADD COLUMN completed_deals INTEGER DEFAULT 0;",
                    "ALTER TABLE brokers ADD COLUMN is_online INTEGER DEFAULT 1;",
                ]:
                    try:
                        cur.execute(col_sql)
                    except Exception:
                        pass
                
                # SQLite indexes
                for idx in [
                    "CREATE INDEX IF NOT EXISTS idx_listings_status_type ON listings(status, req_type);",
                    "CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at DESC);",
                    "CREATE INDEX IF NOT EXISTS idx_listings_user ON listings(user_chat_id);",
                    "CREATE INDEX IF NOT EXISTS idx_listings_category ON listings(main_category);",
                    "CREATE INDEX IF NOT EXISTS idx_brokers_status ON brokers(status);",
                    "CREATE INDEX IF NOT EXISTS idx_brokers_sub_city ON brokers(sub_city);",
                ]:
                    try:
                        cur.execute(idx)
                    except Exception:
                        pass
                
                if not DATABASE_URL:
                    conn.commit()
        
        logger.info("✅ Database initialized successfully")
    
    except Exception as e:
        logger.error(f"❌ init_db: {e}", exc_info=True)
        raise

# ---------- Retry Decorator ----------
def with_retry(retries=3, delay=1, backoff=2):
    """Decorator to retry database operations."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_error = None
            current_delay = delay
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < retries - 1:
                        logger.warning(f"Retry {attempt+1}/{retries} for {func.__name__}: {e}")
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        raise
            raise last_error
        return wrapper
    return decorator

# ---------- Listings ----------
@with_retry(retries=3)
def add_listing(
    user_chat_id, user_name, req_type, main_category, sub_category,
    action_type, property_type, description, price=None, phone=None,
    photo_id=None, extra_data=None, photos=None,
) -> Optional[int]:
    """Add a new listing with photo support."""
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
            str(description or "")[:2000],
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
        
        # Save photos
        if photos and req_id:
            for photo in photos[:MAX_PHOTOS]:
                try:
                    cur.execute(
                        f"INSERT INTO listing_photos (listing_id, photo_id) VALUES ({p},{p})",
                        (req_id, str(photo)),
                    )
                except Exception as pe:
                    logger.error(f"Photo save error: {pe}")
            if not DATABASE_URL:
                conn.commit()
        
        logger.info(f"✅ Listing #ADK-{req_id} added by user {user_chat_id}")
        return req_id
    
    except Exception as e:
        logger.error(f"add_listing: {e}", exc_info=True)
        return None
    finally:
        if conn:
            return_connection(conn)

def get_listing_by_id(listing_id: int) -> Optional[dict]:
    """Get a listing by ID with all photos."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        
        cur.execute(f"SELECT * FROM listings WHERE id = {p}", (listing_id,))
        row = cur.fetchone()
        if not row:
            return None
        
        result = _row_to_dict(row, cur)
        if result:
            result = _parse_extra_data(result)
        
        # Get photos
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
            return_connection(conn)

def get_listings_by_category_ordered(
    limit=20, offset=0, req_type=None, order="DESC"
) -> List[dict]:
    """Get listings with pagination and ordering."""
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
            if item:
                item = _parse_extra_data(item)
            results.append(item)
        
        return results
    
    except Exception as e:
        logger.error(f"get_listings_by_category_ordered: {e}")
        return []
    finally:
        if conn:
            return_connection(conn)

def count_listings(req_type=None) -> int:
    """Count total active listings."""
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
            return_connection(conn)

def update_listing_status(req_id: int, status: str) -> bool:
    """Update listing status."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        
        cur.execute(f"UPDATE listings SET status = {p} WHERE id = {p}", (status, req_id))
        if not DATABASE_URL:
            conn.commit()
        
        logger.info(f"✅ Listing #{req_id} status updated to {status}")
        return True
    
    except Exception as e:
        logger.error(f"update_listing_status: {e}")
        return False
    finally:
        if conn:
            return_connection(conn)

def increment_views(listing_ids: List[int], amount: int = 1) -> Dict[int, int]:
    """Increment view count for multiple listings."""
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
                logger.warning(f"View increment failed for {lid}: {e}")
        
        if not DATABASE_URL:
            conn.commit()
    
    except Exception as e:
        logger.error(f"increment_views: {e}")
    finally:
        if conn:
            return_connection(conn)
    
    return result

def get_public_marketplace_items(limit=20, offset=0) -> List[dict]:
    """Get public marketplace items."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        
        cur.execute(
            f"""SELECT * FROM listings
                WHERE UPPER(req_type)='SELL' AND status NOT IN ('deleted','expired')
                ORDER BY created_at DESC LIMIT {p} OFFSET {p}""",
            (limit, offset),
        )
        
        rows = cur.fetchall()
        out = []
        for row in rows:
            item = _row_to_dict(row, cur)
            if item:
                item = _parse_extra_data(item)
            out.append(item)
        return out
    
    except Exception as e:
        logger.error(f"get_public_marketplace_items: {e}")
        return []
    finally:
        if conn:
            return_connection(conn)

def expire_old_listings(days: int = 30) -> int:
    """Expire listings older than specified days."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        if DATABASE_URL:
            cur.execute(
                """UPDATE listings SET status='expired'
                   WHERE status='pending'
                     AND created_at < NOW() - INTERVAL '%s days'""",
                (days,),
            )
            count = cur.rowcount or 0
        else:
            cur.execute(
                """UPDATE listings SET status='expired'
                   WHERE status='pending'
                     AND created_at < datetime('now', ?)""",
                (f"-{days} days",),
            )
            count = cur.rowcount or 0
            conn.commit()
        
        logger.info(f"🧹 Expired {count} listings older than {days} days")
        return count
    
    except Exception as e:
        logger.error(f"expire_old_listings: {e}")
        return 0
    finally:
        if conn:
            return_connection(conn)

# ---------- Brokers ----------
@with_retry(retries=3)
def add_broker(chat_id, full_name, phone, role_type, national_id_photo, sub_city, specialty="") -> Optional[int]:
    """
    Add or update a broker.
    
    Args:
        chat_id: Telegram user ID
        full_name: Full name of the broker
        phone: Phone number
        role_type: Role type (e.g., "ደላላ")
        national_id_photo: Optional photo ID
        sub_city: Sub-city location
        specialty: Specialty area (e.g., "🚗 መኪና", "🏠 ቤት/ቦታ")
    
    Returns:
        broker_id if successful, None otherwise
    """
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        
        # Check if broker exists
        cur.execute(f"SELECT id FROM brokers WHERE chat_id = {p}", (chat_id,))
        existing = cur.fetchone()
        
        prefs = json.dumps({"car": True, "house": True, "enabled": True})
        
        if existing:
            # Update existing broker
            if DATABASE_URL:
                cur.execute(
                    f"""UPDATE brokers SET 
                        full_name = {p}, 
                        phone = {p}, 
                        role_type = {p},
                        national_id_photo = {p}, 
                        sub_city = {p}, 
                        specialty = {p}, 
                        status = 'pending'
                        WHERE chat_id = {p} 
                        RETURNING id""",
                    (full_name, phone, role_type, national_id_photo, sub_city, specialty, chat_id),
                )
                row = cur.fetchone()
                broker_id = row["id"] if isinstance(row, dict) else row[0]
            else:
                cur.execute(
                    """UPDATE brokers SET 
                        full_name = ?, 
                        phone = ?, 
                        role_type = ?,
                        national_id_photo = ?, 
                        sub_city = ?, 
                        specialty = ?, 
                        status = 'pending'
                        WHERE chat_id = ?""",
                    (full_name, phone, role_type, national_id_photo, sub_city, specialty, chat_id),
                )
                broker_id = existing["id"] if isinstance(existing, dict) else existing[0]
                conn.commit()
            
            logger.info(f"✅ Broker updated: {broker_id} for chat_id {chat_id}")
        else:
            # Insert new broker
            if DATABASE_URL:
                cur.execute(
                    f"""INSERT INTO brokers
                        (chat_id, full_name, phone, role_type, national_id_photo, sub_city,
                         specialty, notification_prefs, status)
                        VALUES ({p},{p},{p},{p},{p},{p},{p},{p},'pending') 
                        RETURNING id""",
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
            
            logger.info(f"✅ New broker added: {broker_id} for chat_id {chat_id}")
        
        return broker_id
    
    except psycopg2.IntegrityError as e:
        logger.error(f"❌ Database integrity error in add_broker: {e}")
        if conn and not DATABASE_URL:
            try:
                conn.rollback()
            except:
                pass
        return None
    except Exception as e:
        logger.error(f"❌ Error in add_broker: {e}", exc_info=True)
        if conn and not DATABASE_URL:
            try:
                conn.rollback()
            except:
                pass
        return None
    finally:
        if conn:
            return_connection(conn)

def get_broker(chat_id: int) -> Optional[dict]:
    """Get broker by chat ID."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        
        cur.execute(f"SELECT * FROM brokers WHERE chat_id = {p}", (chat_id,))
        row = cur.fetchone()
        if not row:
            return None
        
        result = _row_to_dict(row, cur)
        if result and isinstance(result.get("notification_prefs"), str):
            try:
                result["notification_prefs"] = json.loads(result["notification_prefs"])
            except Exception:
                result["notification_prefs"] = {"car": True, "house": True, "enabled": True}
        
        return result
    
    except Exception as e:
        logger.error(f"get_broker: {e}")
        return None
    finally:
        if conn:
            return_connection(conn)

def update_broker_status(chat_id: int, status: str) -> bool:
    """Update broker status."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        
        cur.execute(f"UPDATE brokers SET status = {p} WHERE chat_id = {p}", (status.lower(), chat_id))
        if not DATABASE_URL:
            conn.commit()
        
        logger.info(f"✅ Broker {chat_id} status updated to {status}")
        return True
    
    except Exception as e:
        logger.error(f"update_broker_status: {e}")
        return False
    finally:
        if conn:
            return_connection(conn)

def update_broker_notification_prefs(chat_id: int, prefs: dict) -> bool:
    """Update broker notification preferences."""
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
       
