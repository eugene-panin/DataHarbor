import logging
import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

_pool = None

def get_connection_params():
    """Resolves database connection parameters based on environment."""
    is_docker = os.path.exists("/.dockerenv")
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    if is_docker and ("localhost" in host or "127.0.0.1" in host):
        host = "postgres"

    port = int(os.getenv("POSTGRES_PORT", 5432))
    dbname = os.getenv("POSTGRES_DB", "postgres")
    user = os.getenv("POSTGRES_USER", "dataharbor")
    password = os.getenv("POSTGRES_PASSWORD", "")

    # Fallback container credentials when running inside Docker microservices
    if is_docker and not password:
        user = "dataharbor"
        password = "dataharbor"
        dbname = "dataharbor"

    return host, port, dbname, user, password

def init_connection_pool(minconn: int = 1, maxconn: int = 20):
    """Initializes global thread-safe PostgreSQL connection pool."""
    global _pool
    if _pool is None or _pool.closed:
        host, port, dbname, user, password = get_connection_params()
        try:
            _pool = ThreadedConnectionPool(
                minconn, maxconn,
                host=host, port=port, dbname=dbname, user=user, password=password,
                cursor_factory=RealDictCursor
            )
            logger.info(f"Initialized ThreadedConnectionPool ({minconn}-{maxconn}) for {user}@{host}:{port}/{dbname}")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL connection pool: {e}")
            raise e

def get_db_connection():
    """Gets a connection from the pool or creates a direct fallback connection."""
    global _pool
    if _pool is None or _pool.closed:
        init_connection_pool()
    try:
        return _pool.getconn()
    except Exception:
        host, port, dbname, user, password = get_connection_params()
        return psycopg2.connect(
            host=host, port=port, dbname=dbname, user=user, password=password,
            cursor_factory=RealDictCursor
        )

def release_db_connection(conn):
    """Releases a connection back to the thread pool."""
    global _pool
    if _pool and not _pool.closed and conn:
        try:
            _pool.putconn(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
    elif conn:
        try:
            conn.close()
        except Exception:
            pass

@contextmanager
def get_db_cursor(commit: bool = True):
    """Context manager for automatically checking out and returning DB connections."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        if commit:
            conn.commit()
        else:
            # A PostgreSQL SELECT still opens a transaction and can retain
            # relation locks. Connections are pooled, so release that
            # transaction before another asset reuses the connection for DDL.
            conn.rollback()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        release_db_connection(conn)
