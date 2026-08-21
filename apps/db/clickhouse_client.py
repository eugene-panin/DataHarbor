import os
import logging
from typing import Optional, List, Any
import clickhouse_connect

logger = logging.getLogger(__name__)

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "127.0.0.1")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "default")

def get_clickhouse_client():
    """Returns a ClickHouse connect client instance."""
    host = CLICKHOUSE_HOST
    if os.path.exists("/.dockerenv") and host in ["127.0.0.1", "localhost"]:
        host = "clickhouse"

    try:
        client = clickhouse_connect.get_client(
            host=host,
            port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            database=CLICKHOUSE_DB
        )
        return client
    except Exception as e:
        logger.error(f"Failed to connect to ClickHouse at {CLICKHOUSE_HOST}:{CLICKHOUSE_PORT}: {e}")
        return None

def insert_batch(table_name: str, column_names: List[str], data_matrix: List[List[Any]]) -> bool:
    """Inserts a batch of rows into ClickHouse for high-throughput OLAP performance."""
    if not data_matrix:
        return True

    client = get_clickhouse_client()
    if not client:
        logger.warning(f"ClickHouse client unavailable, skipping batch insert to '{table_name}'.")
        return False

    try:
        client.insert(table_name, data_matrix, column_names=column_names)
        logger.info(f"Successfully inserted batch of {len(data_matrix)} rows into ClickHouse table '{table_name}'.")
        return True
    except Exception as e:
        logger.error(f"Error during ClickHouse batch insert into '{table_name}': {e}")
        return False

def init_clickhouse_tables():
    """Initializes high-performance OLAP tables and vector search indices in ClickHouse."""
    client = get_clickhouse_client()
    if not client:
        return False

    try:
        # Generic scraper / pipeline telemetry (bundles may add their own tables)
        client.command("""
            CREATE TABLE IF NOT EXISTS clickhouse_scraper_telemetry (
                event_id UUID DEFAULT generateUUIDv4(),
                bundle_name LowCardinality(String),
                status LowCardinality(String),
                items_scraped UInt32 DEFAULT 0,
                duration_seconds Float32 DEFAULT 0,
                http_200_count UInt32 DEFAULT 0,
                http_403_count UInt32 DEFAULT 0,
                http_429_count UInt32 DEFAULT 0,
                error_message String DEFAULT '',
                created_at DateTime DEFAULT now()
            ) ENGINE = MergeTree()
            ORDER BY (bundle_name, created_at, event_id);
        """)

        logger.info("Successfully initialized ClickHouse OLAP tables and indices.")
        return True
    except Exception as e:
        logger.error(f"Error initializing ClickHouse tables: {e}")
        return False

if __name__ == "__main__":
    init_clickhouse_tables()
