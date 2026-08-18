# ==============================================================================
# models.py — Database connection, schema, CRUD
# ==============================================================================
import json
import random
from typing import Optional, List, Dict, Any

import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor, Json

from config import DATABASE_URL, DB_FILE, logger, VIEW_BASELINE_MIN, VIEW_BASELINE_MAX
import config as _app_config


_DB_BACKEND = "unknown"
LAST_DB_ERROR = ""


def _normalize_pg_url(url: str) -> str:
    """Normalize postgres URL and ensure SSL for Supabase / cloud hosts."""
    u = (url or "").strip().strip('"').strip("'")
    if u.startswith("postgres://"):
        u = u.replace("postgres://", "postgresql://", 1)
    # Supabase + Render: require SSL (IPv4 pooler still needs sslmode)
    if "sslmode=" not in u.lower():
        sep = "&" if "?" in u else "?"
        u = f"{u}{sep}sslmode=require"
    return u


def get_db_connection():
    """
    Hybrid connection:
      1) PostgreSQL via DATABASE_URL (Supabase pooler 6543 or direct 5432) + SSL
      2) Fallback SQLite if PG unavailable
    """
    global _DB_BACKEND
    if DATABASE_URL:
        try:
            cleaned = _normalize_pg_url(DATABASE_URL)
            # sslmode in URL is enough for psycopg2; also pass sslmode for safety
            conn = psycopg2.connect(
                cleaned,
                cursor_factory=RealDictCursor,
                connect_timeout=15,
            )
            conn.autocommit = True
            _DB_BACKEND = "postgres"
            try:
                _app_config.DB_BACKEND = "postgres"
            except Exception:
                pass
            return conn
        except Exception as e:
            logger.error(f"PostgreSQL connection failed ({e}); falling back to SQLite")
    # SQLite fallback
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except Exception:
        pass
    _DB_BACKEND = "sqlite"
    try:
        _app_config.DB_BACKEND = "sqlite"
    except Exception:
        pass
    return conn


def get_placeholder():
    if _DB_BACKEND == "postgres":
        return "%s"
    if _DB_BACKEND == "sqlite":
        return "?"
    return "%s" if DATABASE_URL else "?"


def is_postgres() -> bool:
    return _DB_BACKEND == "postgres"


def sql_like_op() -> str:
    return "ILIKE" if is_postgres() else "LIKE"






def init_db():
    conn = None
    try:
        conn = get_db_connection()
        if _DB_BACKEND == "postgres":
            logger.info("Successfully connected to Supabase PostgreSQL Pooler")
            logger.info("Connected to PostgreSQL Database")
        else:
            logger.warning("Using SQLite fallback (temporary — set DATABASE_URL to Supabase pooler port 6543)")
        cursor = conn.cursor()
        if _DB_BACKEND == "postgres":
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
            if is_postgres():
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
            if not is_postgres():
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


def ensure_core_tables():
    """Create minimal listings/brokers tables if missing (safe to call often)."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if is_postgres():
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
                    description TEXT NOT NULL DEFAULT '',
                    price TEXT,
                    phone TEXT,
                    photo_id TEXT,
                    extra_data JSONB DEFAULT '{}',
                    status TEXT DEFAULT 'ONLINE',
                    view_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS listing_photos (
                    id SERIAL PRIMARY KEY,
                    listing_id INTEGER NOT NULL,
                    photo_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS brokers (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT UNIQUE,
                    full_name TEXT,
                    phone TEXT,
                    username TEXT,
                    sub_city TEXT,
                    specialty TEXT,
                    status TEXT DEFAULT 'ONLINE',
                    notification_prefs JSONB DEFAULT '{"car":true,"house":true,"enabled":true}',
                    rating REAL DEFAULT 5.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
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
                    description TEXT NOT NULL DEFAULT '',
                    price TEXT,
                    phone TEXT,
                    photo_id TEXT,
                    extra_data TEXT DEFAULT '{}',
                    status TEXT DEFAULT 'ONLINE',
                    view_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS listing_photos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER NOT NULL,
                    photo_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS brokers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER UNIQUE,
                    full_name TEXT,
                    phone TEXT,
                    username TEXT,
                    sub_city TEXT,
                    specialty TEXT,
                    status TEXT DEFAULT 'ONLINE',
                    notification_prefs TEXT DEFAULT '{}',
                    rating REAL DEFAULT 5.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        logger.info("ensure_core_tables ok backend=%s", _DB_BACKEND)
    except Exception as e:
        logger.error("ensure_core_tables: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass



def ensure_listings_columns():
    """Add any missing columns the app expects (Supabase may have older schema)."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if is_postgres():
            alters = [
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS user_chat_id BIGINT",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS user_name TEXT",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS req_type TEXT",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS main_category TEXT",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS category TEXT",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS sub_category TEXT",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS action_type TEXT",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS property_type TEXT",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS description TEXT DEFAULT ''",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS price TEXT",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS phone TEXT",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS photo_id TEXT",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS extra_data JSONB DEFAULT '{}'::jsonb",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'ONLINE'",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS view_count INTEGER DEFAULT 0",
                "ALTER TABLE listings ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            ]
            for sql in alters:
                try:
                    cur.execute(sql)
                except Exception as e:
                    logger.debug("alter skip: %s (%s)", sql, e)
            # Backfill main_category from category if needed
            try:
                cur.execute("""
                    UPDATE listings
                    SET main_category = category
                    WHERE (main_category IS NULL OR main_category = '')
                      AND category IS NOT NULL AND category <> ''
                """)
            except Exception:
                pass
            try:
                cur.execute("""
                    UPDATE listings
                    SET category = main_category
                    WHERE (category IS NULL OR category = '')
                      AND main_category IS NOT NULL AND main_category <> ''
                """)
            except Exception:
                pass
        else:
            # SQLite: try add columns (ignore if exist)
            for col, typedef in [
                ("main_category", "TEXT"),
                ("category", "TEXT"),
                ("sub_category", "TEXT"),
                ("action_type", "TEXT"),
                ("property_type", "TEXT"),
                ("extra_data", "TEXT DEFAULT '{}'"),
                ("view_count", "INTEGER DEFAULT 0"),
                ("status", "TEXT DEFAULT 'ONLINE'"),
                ("user_chat_id", "INTEGER"),
                ("user_name", "TEXT"),
                ("req_type", "TEXT"),
                ("description", "TEXT"),
                ("price", "TEXT"),
                ("phone", "TEXT"),
                ("photo_id", "TEXT"),
            ]:
                try:
                    cur.execute(f"ALTER TABLE listings ADD COLUMN {col} {typedef}")
                except Exception:
                    pass
            conn.commit()
        logger.info("ensure_listings_columns done backend=%s", _DB_BACKEND)
    except Exception as e:
        logger.error("ensure_listings_columns: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_listings_column_set():
    """Return set of column names on listings table."""
    cols = set()
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if is_postgres():
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'listings'
            """)
            for row in cur.fetchall():
                name = row["column_name"] if isinstance(row, dict) else row[0]
                cols.add(str(name).lower())
        else:
            cur.execute("PRAGMA table_info(listings)")
            for row in cur.fetchall():
                # cid, name, type, ...
                if isinstance(row, dict):
                    cols.add(str(row.get("name", "")).lower())
                else:
                    cols.add(str(row[1]).lower())
    except Exception as e:
        logger.warning("get_listings_column_set: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
    return cols


def add_listing(user_chat_id, user_name, req_type, main_category, sub_category,
                action_type, property_type, description, price=None, phone=None, 
                photo_id=None, extra_data=None, photos=None):
    """Insert listing. Returns id or None. Sets LAST_DB_ERROR on failure."""
    global LAST_DB_ERROR
    LAST_DB_ERROR = ""
    conn = None
    try:
        try:
            ensure_core_tables()
            ensure_listings_columns()
        except Exception as _ee:
            logger.warning("ensure before insert: %s", _ee)
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        existing_cols = set()
        try:
            if is_postgres():
                cursor.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'listings'
                """)
                for row in cursor.fetchall():
                    name = row["column_name"] if isinstance(row, dict) else row[0]
                    existing_cols.add(str(name).lower())
            else:
                cursor.execute("PRAGMA table_info(listings)")
                for row in cursor.fetchall():
                    if isinstance(row, dict):
                        existing_cols.add(str(row.get("name", "")).lower())
                    else:
                        existing_cols.add(str(row[1]).lower())
        except Exception as ce:
            logger.warning("column introspect: %s", ce)

        if extra_data is None:
            extra_data = {}
        if isinstance(extra_data, str):
            try:
                extra_data = json.loads(extra_data)
            except Exception:
                extra_data = {"raw": extra_data}

        user_chat_id = int(user_chat_id) if user_chat_id else 0
        user_name = str(user_name or "User")[:200]
        req_type = str(req_type or "BUY").upper()
        main_category = str(main_category or (extra_data.get("category") if isinstance(extra_data, dict) else None) or (extra_data.get("car_type") if isinstance(extra_data, dict) else None) or "መኪና")[:100]
        if not main_category.strip():
            main_category = "መኪና"
        sub_category = str(sub_category or "")[:100]
        action_type = str(action_type or "")[:100]
        property_type = str(property_type or "")[:100]
        description = str(description or "")[:8000]
        price = str(price or "")[:100]
        phone = str(phone or "")[:50]
        photo_id = str(photo_id) if photo_id else None
        import random as _rnd
        baseline_views = int(_rnd.randint(35, 90))

        photo_list = []
        if photos:
            for ph in list(photos)[:3]:
                s = str(ph)
                if len(s) > 300000:
                    s = s[:300000]
                photo_list.append(s)

        # Build extra_data param safely
        extra_text = json.dumps(extra_data, ensure_ascii=False)
        if is_postgres():
            try:
                from psycopg2.extras import Json as PgJson
                extra_param = PgJson(extra_data)
            except Exception:
                extra_param = extra_text
        else:
            extra_param = extra_text

        logger.info(
            "📝 Insert listing user=%s type=%s cat=%s backend=%s photos=%s",
            user_chat_id, req_type, main_category, _DB_BACKEND, len(photo_list),
        )

        def _do_insert(with_extra=True, with_views=True):
            # Never allow NULL for NOT NULL columns on Supabase listings
            cat_val = (main_category or sub_category or "መኪና").strip() or "መኪና"
            req_val = (req_type or "SELL").strip().upper() or "SELL"
            desc_val = description if description is not None else ""
            if not str(desc_val).strip():
                desc_val = cat_val

            # Dual-map: Supabase may use category and/or main_category (both NOT NULL possible)
            candidates = [
                ("user_chat_id", user_chat_id),
                ("user_id", user_chat_id),  # alternate schema
                ("user_name", user_name or "User"),
                ("req_type", req_val),
                ("main_category", cat_val),
                ("category", cat_val),
                ("sub_category", sub_category or cat_val),
                ("action_type", action_type or ""),
                ("property_type", property_type or ""),
                ("description", desc_val),
                ("price", price or ""),
                ("phone", phone or ""),
                ("photo_id", photo_id),  # nullable OK
                ("status", "ONLINE"),
            ]
            if with_extra:
                candidates.append(("extra_data", extra_param))
            if with_views:
                candidates.append(("view_count", baseline_views))

            cols, vals = [], []
            for col, val in candidates:
                cl = col.lower()
                if existing_cols and cl not in existing_cols:
                    continue
                # Never bind Python None into NOT NULL text fields
                if val is None and cl in (
                    "category", "main_category", "req_type", "description",
                    "user_name", "status", "sub_category", "action_type",
                    "property_type", "price", "phone",
                ):
                    val = cat_val if cl in ("category", "main_category", "sub_category") else (
                        req_val if cl == "req_type" else (desc_val if cl == "description" else "")
                    )
                cols.append(col)
                vals.append(val)

            if not existing_cols:
                cols = [c for c, _ in candidates]
                vals = [v if v is not None else "" for _, v in candidates]

            # Force category / main_category if table has them but filter dropped them
            force_map = {
                "category": cat_val,
                "main_category": cat_val,
                "req_type": req_val,
                "description": desc_val,
            }
            for fcol, fval in force_map.items():
                if existing_cols and fcol not in existing_cols:
                    continue
                if fcol not in [c.lower() for c in cols]:
                    cols.append(fcol)
                    vals.append(fval)
                else:
                    # overwrite any accidental None
                    for i, c in enumerate(cols):
                        if c.lower() == fcol and (vals[i] is None or vals[i] == ""):
                            vals[i] = fval

            if not cols:
                raise RuntimeError("No matching columns on listings table")

            # Final safety: no None for category
            for i, c in enumerate(cols):
                if c.lower() in ("category", "main_category") and not vals[i]:
                    vals[i] = cat_val

            ph = ", ".join([p] * len(vals))
            colsql = ", ".join(cols)
            q = f"INSERT INTO listings ({colsql}) VALUES ({ph})"
            logger.info("INSERT cols=%s cat=%s", cols, cat_val)
            if is_postgres():
                cursor.execute(q + " RETURNING id", tuple(vals))
                row = cursor.fetchone()
                if not row:
                    return None
                return row["id"] if isinstance(row, dict) else row[0]
            cursor.execute(q, tuple(vals))
            return cursor.lastrowid

        req_id = None
        last_err = None
        for with_extra, with_views in ((True, True), (False, True), (False, False)):
            try:
                req_id = _do_insert(with_extra=with_extra, with_views=with_views)
                if req_id:
                    break
            except Exception as ie:
                last_err = ie
                logger.warning("insert attempt failed (extra=%s views=%s): %s", with_extra, with_views, ie)
                try:
                    if not is_postgres():
                        conn.rollback()
                except Exception:
                    pass

        if not req_id:
            LAST_DB_ERROR = str(last_err or "insert returned no id")
            logger.error("❌ Add listing failed: %s", LAST_DB_ERROR)
            return None

        if photo_list:
            for photo_str in photo_list:
                try:
                    cursor.execute(
                        f"INSERT INTO listing_photos (listing_id, photo_id) VALUES ({p}, {p})",
                        (req_id, photo_str),
                    )
                except Exception as pe:
                    logger.error("photo save failed: %s", pe)

        try:
            if not is_postgres():
                conn.commit()
            else:
                try:
                    conn.commit()
                except Exception:
                    pass
        except Exception as ce:
            logger.warning("commit: %s", ce)

        logger.info("✅ Listing added → #ADK-%s", req_id)
        return req_id
    except Exception as e:
        LAST_DB_ERROR = str(e)
        logger.error("❌ Add listing error: %s", e, exc_info=True)
        if conn:
            try:
                if not is_postgres():
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
        if not is_postgres():
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
        if is_postgres():
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
            if is_postgres():
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

        if is_postgres():
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


def delete_broker(chat_id: int) -> bool:
    """Delete a broker row by Telegram chat_id. Returns True on success."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        p = get_placeholder()
        chat_id = int(chat_id)
        cursor.execute(f"DELETE FROM brokers WHERE chat_id = {p}", (chat_id,))
        try:
            if not is_postgres():
                conn.commit()
            else:
                try:
                    conn.commit()
                except Exception:
                    pass
        except Exception:
            pass
        logger.info("Deleted broker chat_id=%s", chat_id)
        return True
    except Exception as e:
        logger.error(f"delete_broker error: {e}", exc_info=True)
        return False
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
        cursor = conn.cursor()
        p = get_placeholder()
        cursor.execute(f"UPDATE brokers SET status = {p} WHERE chat_id = {p}", (status.lower(), chat_id))
        if not is_postgres():
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
        if not is_postgres():
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


def ensure_brokers_columns():
    """Ensure brokers table has status / is_approved columns used by the app."""
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if is_postgres():
            for sql in [
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'ONLINE'",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS is_approved BOOLEAN DEFAULT TRUE",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS is_online BOOLEAN DEFAULT TRUE",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS chat_id BIGINT",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS full_name TEXT",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS phone TEXT",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS username TEXT",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS sub_city TEXT",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS specialty TEXT",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS notification_prefs JSONB DEFAULT '{}'::jsonb",
                "ALTER TABLE brokers ADD COLUMN IF NOT EXISTS rating REAL DEFAULT 5.0",
            ]:
                try:
                    cur.execute(sql)
                except Exception as e:
                    logger.debug("brokers alter skip: %s", e)
        else:
            for col, typedef in [
                ("status", "TEXT DEFAULT 'ONLINE'"),
                ("is_approved", "INTEGER DEFAULT 1"),
                ("is_online", "INTEGER DEFAULT 1"),
                ("chat_id", "INTEGER"),
                ("full_name", "TEXT"),
                ("phone", "TEXT"),
                ("username", "TEXT"),
                ("sub_city", "TEXT"),
                ("specialty", "TEXT"),
                ("notification_prefs", "TEXT DEFAULT '{}'"),
                ("rating", "REAL DEFAULT 5.0"),
            ]:
                try:
                    cur.execute(f"ALTER TABLE brokers ADD COLUMN {col} {typedef}")
                except Exception:
                    pass
            try:
                conn.commit()
            except Exception:
                pass
    except Exception as e:
        logger.warning("ensure_brokers_columns: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def _broker_table_columns(cur) -> set:
    cols = set()
    try:
        if is_postgres():
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'brokers'
            """)
            for row in cur.fetchall() or []:
                name = row["column_name"] if isinstance(row, dict) else row[0]
                cols.add(str(name).lower())
        else:
            cur.execute("PRAGMA table_info(brokers)")
            for row in cur.fetchall() or []:
                if isinstance(row, dict):
                    cols.add(str(row.get("name", "")).lower())
                else:
                    cols.add(str(row[1]).lower())
    except Exception as e:
        logger.warning("_broker_table_columns: %s", e)
    return cols


def _normalize_broker_row(broker: dict, cols_desc=None) -> dict:
    if not isinstance(broker, dict):
        broker = dict(zip([c[0] for c in (cols_desc or [])], broker)) if cols_desc else {}
    if isinstance(broker.get("notification_prefs"), str):
        try:
            broker["notification_prefs"] = json.loads(broker["notification_prefs"])
        except Exception:
            broker["notification_prefs"] = {"car": True, "house": True, "enabled": True}
    if not broker.get("notification_prefs"):
        broker["notification_prefs"] = {"car": True, "house": True, "enabled": True}
    # Status / approval fallbacks
    st = broker.get("status")
    if st is None or st == "":
        if broker.get("is_approved") in (True, 1, "1", "true", "TRUE"):
            st = "ONLINE"
        elif broker.get("is_approved") in (False, 0, "0", "false"):
            st = "rejected"
        else:
            st = "ONLINE"
    broker["status"] = st
    if broker.get("is_online") is None:
        broker["is_online"] = str(st).lower() not in ("rejected", "deleted", "banned", "offline")
    broker["phone"] = broker.get("phone") or ""
    broker["username"] = broker.get("username") or ""
    broker["full_name"] = broker.get("full_name") or broker.get("name") or "User"
    broker["sub_city"] = broker.get("sub_city") or ""
    broker["specialty"] = broker.get("specialty") or broker.get("role_type") or ""
    if broker.get("chat_id") is not None:
        try:
            broker["chat_id"] = int(broker["chat_id"])
        except Exception:
            pass
    return broker


def get_approved_brokers():
    """Brokers eligible for notifications. Safe if status column missing."""
    conn = None
    try:
        try:
            ensure_brokers_columns()
        except Exception:
            pass
        conn = get_db_connection()
        cursor = conn.cursor()
        cols = _broker_table_columns(cursor)
        p = get_placeholder()
        where_parts = []
        if "status" in cols:
            where_parts.append(
                "(status IS NULL OR LOWER(CAST(status AS TEXT)) IN "
                "('approved', 'online', 'pending', 'ONLINE', 'APPROVED', 'PENDING'))"
            )
        if "is_approved" in cols:
            where_parts.append("(is_approved IS NULL OR is_approved = TRUE OR is_approved = 1)")
        # If neither column exists, return all brokers
        if where_parts:
            # OR together: approved by status OR by flag; if only one exists use it
            if "status" in cols and "is_approved" in cols:
                sql = (
                    "SELECT * FROM brokers WHERE "
                    "(status IS NULL OR LOWER(CAST(status AS TEXT)) IN "
                    "('approved','online','pending')) "
                    "OR (is_approved IS NULL OR is_approved = TRUE OR is_approved = 1)"
                )
            else:
                sql = "SELECT * FROM brokers WHERE " + where_parts[0]
        else:
            sql = "SELECT * FROM brokers"
        try:
            cursor.execute(sql)
        except Exception as qe:
            logger.warning("get_approved_brokers filtered query failed (%s); selecting all", qe)
            cursor.execute("SELECT * FROM brokers")
        rows = cursor.fetchall() or []
        results = []
        for row in rows:
            broker = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cursor.description], row))
            broker = _normalize_broker_row(broker, cursor.description)
            # Skip clearly rejected
            st = str(broker.get("status") or "").lower()
            if st in ("rejected", "deleted", "banned"):
                continue
            results.append(broker)
        return results
    except Exception as e:
        logger.error(f"Get approved brokers error: {e}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass



def get_approved_brokers_directory(sub_city=None):
    return get_active_brokers(sub_city=sub_city, status="ONLINE")


def get_active_brokers(sub_city=None, status="ONLINE", limit=50, offset=0):
    """Directory list — works without status column."""
    conn = None
    try:
        try:
            ensure_brokers_columns()
        except Exception:
            pass
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        cols = _broker_table_columns(cur)

        where = []
        params = []
        if "status" in cols:
            where.append(
                "(status IS NULL OR LOWER(CAST(status AS TEXT)) NOT IN "
                "('rejected', 'deleted', 'banned'))"
            )
        elif "is_approved" in cols:
            where.append("(is_approved IS NULL OR is_approved = TRUE OR is_approved = 1)")

        if sub_city and str(sub_city).strip() not in ("ሁሉም", "አዲስ አበባ (ሙሉ)", "", "None"):
            if "sub_city" in cols or not cols:
                where.append(f"sub_city = {p}")
                params.append(str(sub_city).strip())

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        params += [int(limit), int(offset)]
        sql = f"SELECT * FROM brokers{where_sql} ORDER BY id DESC LIMIT {p} OFFSET {p}"
        try:
            cur.execute(sql, params)
        except Exception as qe:
            logger.warning("get_active_brokers query failed (%s); fallback all", qe)
            cur.execute(f"SELECT * FROM brokers ORDER BY id DESC LIMIT {p} OFFSET {p}", [int(limit), int(offset)])
        rows = cur.fetchall() or []
        out = []
        for row in rows:
            try:
                b = dict(row) if isinstance(row, dict) else dict(zip([c[0] for c in cur.description], row))
                b = _normalize_broker_row(b, cur.description)
                if b.get("chat_id") is None:
                    continue
                st = str(b.get("status") or "").lower()
                if st in ("rejected", "deleted", "banned"):
                    continue
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
    try:
        brokers = get_active_brokers(limit=500, offset=0)
        return len(brokers or [])
    except Exception as e:
        logger.error(f"count_brokers: {e}")
        return 0



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
        if not is_postgres():
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
        if is_postgres():
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
        if is_postgres():
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
        if is_postgres():
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
        if is_postgres():
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



