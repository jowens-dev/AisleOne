import sqlite3
import os

DB_PATH = os.environ.get(
    "AISLEONE_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "grocery.db")
)

# Wrapper classes for Turso / Libsql to provide sqlite3.Row-like behavior and DB-API compatibility
class LibsqlRow(dict):
    def __init__(self, mapping):
        super().__init__(mapping)
        self.__dict__.update(mapping)
        
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

class LibsqlCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor
        
    def execute(self, sql, params=()):
        self._cursor.execute(sql, params)
        return self
        
    def executemany(self, sql, params_seq):
        self._cursor.executemany(sql, params_seq)
        return self
        
    def executescript(self, script):
        self._cursor.executescript(script)
        return self
        
    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        fields = [col[0] for col in self._cursor.description]
        return LibsqlRow(zip(fields, row))
        
    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows:
            return []
        fields = [col[0] for col in self._cursor.description]
        return [LibsqlRow(zip(fields, r)) for r in rows]
        
    def __iter__(self):
        return iter(self.fetchall())
        
    def __getattr__(self, name):
        return getattr(self._cursor, name)

class LibsqlConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn
        
    def cursor(self):
        return LibsqlCursorWrapper(self._conn.cursor())
        
    def execute(self, sql, params=()):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur
        
    def commit(self):
        self._conn.commit()
        
    def rollback(self):
        self._conn.rollback()
        
    def close(self):
        self._conn.close()
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        
    def __getattr__(self, name):
        return getattr(self._conn, name)

def get_conn():
    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")
    
    if turso_url and turso_token:
        # Remote Turso Connection
        import libsql_experimental as libsql
        conn = libsql.connect(database=turso_url, auth_token=turso_token)
        conn = LibsqlConnectionWrapper(conn)
    else:
        # Local Fallback
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        
    cur = conn.cursor()
    
    # Self-healing migrations
    try:
        cur.execute("SELECT is_club FROM stores LIMIT 1")
    except Exception:
        try:
            cur.execute("ALTER TABLE stores ADD COLUMN is_club INTEGER DEFAULT 0")
            conn.commit()
        except Exception:
            pass
            
    try:
        cur.execute("SELECT id FROM users LIMIT 1")
    except Exception:
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    tier TEXT DEFAULT 'free',
                    club_memberships TEXT DEFAULT '[]',
                    zip_code TEXT DEFAULT '90210',
                    created_at TEXT DEFAULT NULL,
                    updated_at TEXT DEFAULT NULL
                )
            """)
            conn.commit()
        except Exception:
            pass
            
    try:
        cur.execute("SELECT zip_code FROM users LIMIT 1")
    except Exception:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN zip_code TEXT DEFAULT '90210'")
            conn.commit()
        except Exception:
            pass

    try:
        cur.execute("SELECT zip_code FROM prices LIMIT 1")
    except Exception:
        try:
            cur.execute("ALTER TABLE prices ADD COLUMN zip_code TEXT DEFAULT '90210'")
            cur.execute("DROP INDEX IF EXISTS idx_prices_unique")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_unique ON prices(store_id, product_variant_id, zip_code, date_collected)")
            conn.commit()
        except Exception:
            pass
            
    return conn

def init_db():
    with open(os.path.join(os.path.dirname(__file__), "../db/schema.sql")) as f:
        schema = f.read()
    conn = get_conn()
    conn.executescript(schema)
    conn.close()
