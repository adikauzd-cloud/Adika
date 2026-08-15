# ==============================================================================
# models.py — Database connection, schema, CRUD
# ==============================================================================
import json
import random
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor, Json
import sqlite3

from config import DATABASE_URL, DB_FILE, logger, VIEW_BASELINE_MIN, VIEW_BASELINE_MAX

# ==============================================================================
# 1. DATABASE CONNECTION WITH CONTEXT MANAGER
# ==============================================================================

def get_db_connection():
    """Get a raw database connection."""
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

@contextmanager
def db_connection():
    """Context manager for database connections."""
    conn = None
    try:
        conn = get_db_connection()
        yield conn
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

def get_placeholder():
    """Get the appropriate placeholder for the database."""
    return "%s" if DATABASE_URL else "?"

# ==============================================================================
# 2. DATABASE INITIALIZATION
# ==============================================================================

def init_db():
    """Initialize database schema with indexes."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            
            if DATABASE_URL:
                # PostgreSQL schema
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(broker_chat_id, user_chat_id)
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
                
                # Add indexes for performance
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_req_type ON listings(req_type)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_category ON listings(main_category)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at DESC)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_brokers_status ON brokers(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_brokers_sub_city ON brokers(sub_city)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_brokers_chat_id ON brokers(chat_id)")
                
            else:
                # SQLite schema
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(broker_chat_id, user_chat_id)
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
                
                # SQLite indexes
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_req_type ON listings(req_type)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_category ON listings(main_category)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_brokers_status ON brokers(status)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_brokers_sub_city ON brokers(sub_city)")
                
                conn.commit()
            
            # Add missing columns (safe migrations)
            try:
                if DATABASE_URL:
                    cursor.execute("ALTER TABLE brokers ADD COLUMN IF NOT EXISTS username TEXT DEFAULT ''")
                    cursor.execute("ALTER TABLE brokers ADD COLUMN IF NOT EXISTS specialty TEXT DEFAULT ''")
                    cursor.execute("ALTER TABLE brokers ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE")
                    cursor.execute("ALTER TABLE brokers ADD COLUMN IF NOT EXISTS is_online BOOLEAN DEFAULT TRUE")
                    cursor.execute("ALTER TABLE brokers ADD COLUMN IF NOT EXISTS fayda_photo_id TEXT")
                else:
                    for stmt in [
                        "ALTER TABLE brokers ADD COLUMN username TEXT DEFAULT ''",
                        "ALTER TABLE brokers ADD COLUMN specialty TEXT DEFAULT ''",
                        "ALTER TABLE brokers ADD COLUMN is_verified INTEGER DEFAULT 0",
                        "ALTER TABLE brokers ADD COLUMN is_online INTEGER DEFAULT 1",
                        "ALTER TABLE brokers ADD COLUMN fayda_photo_id TEXT",
                    ]:
                        try:
                            cursor.execute(stmt)
                            conn.commit()
                        except Exception:
                            pass
            except Exception as e:
                logger.warning(f"Migration warning: {e}")
            
            logger.info("✅ Database initialized successfully")
            
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}", exc_info=True)
        raise

# ==============================================================================
# 3. LISTING OPERATIONS
# ==============================================================================

def add_listing(
    user_chat_id: int,
    user_name: str,
    req_type: str,
    main_category: str,
    sub_category: str,
    action_type: str,
    property_type: str,
    description: str,
    price: Optional[str] = None,
    phone: Optional[str] = None,
    photo_id: Optional[str] = None,
    extra_data: Optional[Dict[str, Any]] = None,
    photos: Optional[List[str]] = None
) -> Optional[int]:
    """Add a new listing to the database."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            
            if extra_data is None:
                extra_data = {}
            extra_json = json.dumps(extra_data, ensure_ascii=False) if not isinstance(extra_data, str) else extra_data
            
            # Sanitize inputs
            user_chat_id = int(user_chat_id) if user_chat_id else 0
            user_name = str(user_name or "User")[:100]
            req_type = str(req_type or "BUY").upper()
            main_category = str(main_category or "መኪና")[:50]
            sub_category = str(sub_category or "")[:50]
            action_type = str(action_type or "")[:50]
            property_type = str(property_type or "")[:50]
            description = str(description or "")[:2000]
            price = str(price or "")[:50]
            phone = str(phone or "")[:30]
            photo_id = str(photo_id) if photo_id else None
            
            baseline_views = random.randint(VIEW_BASELINE_MIN, VIEW_BASELINE_MAX)
            
            query = f"""
                INSERT INTO listings 
                (user_chat_id, user_name, req_type, main_category, sub_category, 
                 action_type, property_type, description, price, phone, photo_id, extra_data, status, view_count)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, 'pending', {p})
            """
            params = (user_chat_id, user_name, req_type, main_category, sub_category, 
                     action_type, property_type, description, price, phone, photo_id, extra_json, baseline_views)
            
            if DATABASE_URL:
                cursor.execute(query + " RETURNING id", params)
                row = cursor.fetchone()
                req_id = row["id"] if row else None
            else:
                cursor.execute(query, params)
                req_id = cursor.lastrowid
                conn.commit()
            
            # Save photos
            if photos and req_id:
                for photo in photos:
                    try:
                        cursor.execute(
                            f"INSERT INTO listing_photos (listing_id, photo_id) VALUES ({p}, {p})",
                            (req_id, str(photo))
                        )
                    except Exception as pe:
                        logger.error(f"Failed to save photo: {pe}")
                if not DATABASE_URL:
                    conn.commit()
            
            logger.info(f"✅ Listing added: #ADK-{req_id}")
            return req_id
            
    except Exception as e:
        logger.error(f"❌ Add listing error: {e}", exc_info=True)
        return None

def get_listing_by_id(listing_id: int) -> Optional[Dict[str, Any]]:
    """Get a listing by ID with its photos."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            
            cursor.execute(f"SELECT * FROM listings WHERE id = {p}", (listing_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            result = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
            
            # Parse extra_data
            if 'extra_data' in result and isinstance(result['extra_data'], str):
                try:
                    result['extra_data'] = json.loads(result['extra_data'])
                except:
                    result['extra_data'] = {}
            
            # Get photos
            try:
                cursor.execute(f"SELECT photo_id FROM listing_photos WHERE listing_id = {p}", (listing_id,))
                photo_rows = cursor.fetchall()
                result['photos'] = [dict(r)['photo_id'] if isinstance(r, dict) else r[0] for r in photo_rows]
            except Exception:
                result['photos'] = []
            
            return result
            
    except Exception as e:
        logger.error(f"Get listing error: {e}")
        return None

def get_listings_by_category_ordered(
    limit: int = 20, 
    offset: int = 0, 
    req_type: Optional[str] = None, 
    order: str = "DESC"
) -> List[Dict[str, Any]]:
    """Get listings with pagination and ordering."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            order_sql = "ASC" if str(order).upper() == "ASC" else "DESC"
            
            if req_type:
                query = f"""
                    SELECT * FROM listings 
                    WHERE status = 'pending' AND UPPER(req_type) = UPPER({p})
                    ORDER BY created_at {order_sql}
                    LIMIT {p} OFFSET {p}
                """
                cursor.execute(query, (req_type, limit, offset))
            else:
                query = f"""
                    SELECT * FROM listings 
                    WHERE status = 'pending' 
                    ORDER BY created_at {order_sql}
                    LIMIT {p} OFFSET {p}
                """
                cursor.execute(query, (limit, offset))
            
            rows = cursor.fetchall()
            results = []
            for row in rows:
                item = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
                if 'extra_data' in item and isinstance(item['extra_data'], str):
                    try:
                        item['extra_data'] = json.loads(item['extra_data'])
                    except:
                        item['extra_data'] = {}
                results.append(item)
            return results
            
    except Exception as e:
        logger.error(f"get_listings_by_category_ordered error: {e}")
        return []

def count_listings(req_type: Optional[str] = None) -> int:
    """Count listings with optional type filter."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            if req_type:
                p = get_placeholder()
                cursor.execute(
                    f"SELECT COUNT(*) as cnt FROM listings WHERE status = 'pending' AND UPPER(req_type) = UPPER({p})",
                    (req_type,)
                )
            else:
                cursor.execute("SELECT COUNT(*) as cnt FROM listings WHERE status = 'pending'")
            
            row = cursor.fetchone()
            if isinstance(row, dict):
                return row.get('cnt', 0)
            return row[0] if row else 0
            
    except Exception as e:
        logger.error(f"Count listings error: {e}")
        return 0

def update_listing_status(req_id: int, status: str) -> bool:
    """Update listing status."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            cursor.execute(f"UPDATE listings SET status = {p} WHERE id = {p}", (status, req_id))
            if not DATABASE_URL:
                conn.commit()
            logger.info(f"✅ Listing {req_id} status → {status}")
            return True
    except Exception as e:
        logger.error(f"Update listing error: {e}")
        return False

def increment_views_batch(item_ids: List[int], amount: int = 13) -> Dict[int, int]:
    """Increment view_count for multiple listings."""
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
        logger.error(f"increment_views_batch error: {e}")
    
    return results

def get_public_marketplace_items(limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
    """Get active marketplace listings."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            
            if DATABASE_URL:
                cursor.execute("""
                    SELECT * FROM listings 
                    WHERE UPPER(req_type) = 'SELL'
                      AND status != 'deleted'
                    ORDER BY created_at DESC NULLS LAST
                    LIMIT %s OFFSET %s
                """, (limit, offset))
                rows = cursor.fetchall()
                result = [dict(row) for row in rows]
            else:
                cursor.execute("""
                    SELECT * FROM listings 
                    WHERE UPPER(req_type) = 'SELL'
                      AND status != 'deleted'
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset))
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
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

def expire_old_listings(days: int = 30) -> int:
    """Mark old listings as expired."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            
            if DATABASE_URL:
                cursor.execute("""
                    UPDATE listings
                    SET status = 'expired'
                    WHERE status = 'pending'
                      AND created_at < (NOW() - INTERVAL '%s days')
                """ % int(days))
                count = cursor.rowcount
            else:
                cursor.execute("""
                    UPDATE listings
                    SET status = 'expired'
                    WHERE status = 'pending'
                      AND created_at < datetime('now', ?)
                """, (f'-{int(days)} days',))
                count = cursor.rowcount
                conn.commit()
            
            if count:
                logger.info(f"🧹 Auto-expiry: {count} listings expired")
            return count or 0
            
    except Exception as e:
        logger.error(f"expire_old_listings error: {e}", exc_info=True)
        return 0

# ==============================================================================
# 4. BROKER OPERATIONS
# ==============================================================================

def add_broker(
    chat_id: int,
    full_name: str,
    phone: str = "",
    role_type: str = "ደላላ",
    national_id_photo: Optional[str] = None,
    sub_city: str = "",
    specialty: str = "",
    username: str = "",
    fayda_photo_id: Optional[str] = None,
) -> Optional[int]:
    """Add or update a broker."""
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
        
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            
            # Check if exists
            cursor.execute(f"SELECT id FROM brokers WHERE chat_id = {p}", (chat_id,))
            existing = cursor.fetchone()
            existing_id = (existing["id"] if isinstance(existing, dict) else existing[0]) if existing else None
            
            if DATABASE_URL:
                from psycopg2.extras import Json
                prefs_val = Json(prefs)
                if existing_id:
                    cursor.execute(
                        f"""UPDATE brokers SET
                            full_name={p}, phone={p}, username={p}, role_type={p},
                            national_id_photo={p}, sub_city={p}, specialty={p},
                            status='pending'
                            WHERE chat_id={p} RETURNING id""",
                        (full_name, phone, username, role_type, photo, sub_city, specialty, chat_id),
                    )
                else:
                    cursor.execute(
                        f"""INSERT INTO brokers
                            (chat_id, full_name, phone, username, role_type, national_id_photo,
                             sub_city, specialty, notification_prefs, status, is_online)
                            VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},'pending', TRUE)
                            RETURNING id""",
                        (chat_id, full_name, phone, username, role_type, photo,
                         sub_city, specialty, prefs_val),
                    )
                row = cursor.fetchone()
                broker_id = (row["id"] if isinstance(row, dict) else row[0]) if row else existing_id
            else:
                prefs_json = json.dumps(prefs, ensure_ascii=False)
                if existing_id:
                    cursor.execute(
                        """UPDATE brokers SET full_name=?, phone=?, username=?, role_type=?,
                           national_id_photo=?, sub_city=?, specialty=?, status='pending'
                           WHERE chat_id=?""",
                        (full_name, phone, username, role_type, photo, sub_city, specialty, chat_id),
                    )
                    broker_id = existing_id
                else:
                    cursor.execute(
                        """INSERT INTO brokers
                           (chat_id, full_name, phone, username, role_type, national_id_photo,
                            sub_city, specialty, notification_prefs, status, is_online)
                           VALUES (?,?,?,?,?,?,?,?,?, 'pending', 1)""",
                        (chat_id, full_name, phone, username, role_type, photo,
                         sub_city, specialty, prefs_json),
                    )
                    broker_id = cursor.lastrowid
                conn.commit()
            
            logger.info(f"✅ Broker saved: id={broker_id}")
            return int(broker_id) if broker_id else None
            
    except Exception as e:
        logger.error(f"add_broker error: {e}", exc_info=True)
        return None

def get_broker(chat_id: int) -> Optional[Dict[str, Any]]:
    """Get broker by chat_id."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            cursor.execute(f"SELECT * FROM brokers WHERE chat_id = {p}", (chat_id,))
            row = cursor.fetchone()
            if row:
                result = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
                if 'notification_prefs' in result and isinstance(result['notification_prefs'], str):
                    try:
                        result['notification_prefs'] = json.loads(result['notification_prefs'])
                    except:
                        result['notification_prefs'] = {"car": True, "house": True, "enabled": True}
                return result
            return None
    except Exception as e:
        logger.error(f"get_broker error: {e}")
        return None

def update_broker_status(chat_id: int, status: str) -> bool:
    """Update broker status."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            cursor.execute(f"UPDATE brokers SET status = {p} WHERE chat_id = {p}", (status.lower(), chat_id))
            if not DATABASE_URL:
                conn.commit()
            return True
    except Exception as e:
        logger.error(f"Update broker status error: {e}")
        return False

def update_broker_notification_prefs(chat_id: int, prefs: Dict[str, Any]) -> bool:
    """Update broker notification preferences."""
    try:
        with db_connection() as conn:
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

def get_approved_brokers() -> List[Dict[str, Any]]:
    """Get all approved brokers."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM brokers WHERE status = 'approved'")
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
        logger.error(f"get_approved_brokers error: {e}")
        return []

def get_active_brokers(
    sub_city: Optional[str] = None, 
    status: str = "approved", 
    limit: int = 50, 
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Get active brokers with filters."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            
            where, params = [], []
            if status:
                where.append(f"status = {p}")
                params.append(status)
            if sub_city and sub_city not in ("ሁሉም", "አዲስ አበባ (ሙሉ)", "", None):
                where.append(f"sub_city = {p}")
                params.append(sub_city)
            
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""
            params += [int(limit), int(offset)]
            order = "ORDER BY created_at DESC NULLS LAST, id DESC" if DATABASE_URL else "ORDER BY id DESC"
            
            cursor.execute(
                f"SELECT * FROM brokers{where_sql} {order} LIMIT {p} OFFSET {p}",
                params,
            )
            
            rows = cursor.fetchall() or []
            cols = [col[0] for col in cursor.description] if cursor.description else []
            
            out = []
            for row in rows:
                try:
                    if isinstance(row, dict):
                        b = dict(row)
                    else:
                        b = dict(zip(cols, row))
                    
                    if b.get("chat_id") is None:
                        continue
                    
                    b["chat_id"] = int(b["chat_id"])
                    b["phone"] = b.get("phone") or ""
                    b["username"] = b.get("username") or ""
                    b["full_name"] = b.get("full_name") or "User"
                    b["sub_city"] = b.get("sub_city") or ""
                    b["specialty"] = b.get("specialty") or b.get("role_type") or ""
                    
                    if isinstance(b.get("notification_prefs"), str):
                        try:
                            b["notification_prefs"] = json.loads(b["notification_prefs"])
                        except:
                            b["notification_prefs"] = {}
                    
                    out.append(b)
                except Exception as row_err:
                    logger.warning(f"skip bad broker row: {row_err}")
                    continue
            
            return out
            
    except Exception as e:
        logger.error(f"get_active_brokers: {e}", exc_info=True)
        return []

def count_brokers(status: str = "approved") -> int:
    """Count brokers by status."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            if status:
                cursor.execute(f"SELECT COUNT(*) as cnt FROM brokers WHERE status = {p}", (status,))
            else:
                cursor.execute("SELECT COUNT(*) as cnt FROM brokers")
            row = cursor.fetchone()
            return int((row["cnt"] if isinstance(row, dict) else row[0]) or 0)
    except Exception as e:
        logger.error(f"count_brokers: {e}")
        return 0

def delete_broker(chat_id: int) -> bool:
    """Delete a broker."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            cursor.execute(f"DELETE FROM brokers WHERE chat_id = {p}", (int(chat_id),))
            if not DATABASE_URL:
                conn.commit()
            return True
    except Exception as e:
        logger.error(f"delete_broker: {e}")
        return False

# ==============================================================================
# 5. RATINGS OPERATIONS
# ==============================================================================

def add_broker_rating(broker_chat_id: int, user_chat_id: int, stars: int) -> bool:
    """Add or update a broker rating."""
    try:
        broker_chat_id = int(broker_chat_id)
        user_chat_id = int(user_chat_id)
        stars = int(stars)
        if stars < 1 or stars > 5:
            return False
        
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            
            # Upsert: delete old then insert
            cursor.execute(
                f"DELETE FROM ratings WHERE broker_chat_id = {p} AND user_chat_id = {p}",
                (broker_chat_id, user_chat_id),
            )
            cursor.execute(
                f"INSERT INTO ratings (broker_chat_id, user_chat_id, stars) VALUES ({p}, {p}, {p})",
                (broker_chat_id, user_chat_id, stars),
            )
            
            # Update average
            cursor.execute(
                f"SELECT AVG(stars) AS avg_stars, COUNT(*) AS total_count FROM ratings WHERE broker_chat_id = {p}",
                (broker_chat_id,),
            )
            result = cursor.fetchone()
            if isinstance(result, dict):
                avg_stars = float(result.get("avg_stars") or 5.0)
                total_count = int(result.get("total_count") or 0)
            else:
                avg_stars = float(result[0] or 5.0)
                total_count = int(result[1] or 0)
            
            cursor.execute(
                f"UPDATE brokers SET rating = {p}, total_ratings = {p} WHERE chat_id = {p}",
                (round(avg_stars, 1), total_count, broker_chat_id),
            )
            
            if not DATABASE_URL:
                conn.commit()
            
            logger.info(f"Rating: broker={broker_chat_id} stars={stars} avg={avg_stars}")
            return True
            
    except Exception as e:
        logger.error(f"add_broker_rating error: {e}", exc_info=True)
        return False

# ==============================================================================
# 6. OFFERS & ALERTS
# ==============================================================================

def save_broker_offer(request_id: int, broker_id: int, description: str, photo_id: Optional[str] = None) -> bool:
    """Save a broker's offer."""
    try:
        with db_connection() as conn:
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

def save_search_alert(user_chat_id: int, main_category: str, budget_min: str, budget_max: str) -> int:
    """Save a search alert."""
    try:
        with db_connection() as conn:
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

def get_matching_alerts(main_category: str, price: str) -> List[Dict[str, Any]]:
    """Get alerts matching a listing."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            p = get_placeholder()
            cursor.execute(f"""
                SELECT * FROM search_alerts 
                WHERE is_active = TRUE AND main_category = {p}
                ORDER BY created_at DESC
            """, (main_category,))
            rows = cursor.fetchall()
            
            try:
                price_num = float(price) if price else 0
            except (ValueError, TypeError):
                price_num = 0
            
            matching = []
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
        logger.error(f"get_matching_alerts error: {e}")
        return []

# ==============================================================================
# 7. STATS
# ==============================================================================

def get_platform_stats() -> Dict[str, int]:
    """Get platform statistics."""
    try:
        with db_connection() as conn:
            cursor = conn.cursor()
            stats = {}
            for key, sql in (
                ("active_listings", "SELECT COUNT(*) as cnt FROM listings WHERE status = 'pending'"),
                ("verified_brokers", "SELECT COUNT(*) as cnt FROM brokers WHERE status = 'approved'"),
                ("total_listings", "SELECT COUNT(*) as cnt FROM listings"),
                ("active_users", "SELECT COUNT(DISTINCT user_chat_id) as cnt FROM listings"),
            ):
                cursor.execute(sql)
                row = cursor.fetchone()
                stats[key] = int((row["cnt"] if isinstance(row, dict) else row[0]) or 0)
            return stats
    except Exception as e:
        logger.error(f"get_platform_stats: {e}")
        return {"active_listings": 0, "verified_brokers": 0, "total_listings": 0, "active_users": 0}
