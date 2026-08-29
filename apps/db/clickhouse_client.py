import logging
import os
from typing import Any

import clickhouse_connect

logger = logging.getLogger(__name__)

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "127.0.0.1")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "default")

# Soft-disable without connection attempts (e.g. local CLI without CH stack).
_CLICKHOUSE_ENABLED = os.getenv("CLICKHOUSE_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

_client = None
_unavailable = False
_unavailable_logged = False


def _mark_unavailable(reason: str) -> None:
    """Remember CH is down for this process; log once at warning."""
    global _unavailable, _unavailable_logged, _client
    _unavailable = True
    _client = None
    if not _unavailable_logged:
        _unavailable_logged = True
        logger.warning("ClickHouse unavailable — OLAP writes disabled (%s)", reason)


def reset_clickhouse_client_cache() -> None:
    """Clear cached client / unavailable flag (tests)."""
    global _client, _unavailable, _unavailable_logged
    _client = None
    _unavailable = False
    _unavailable_logged = False


def get_clickhouse_client():
    """Return a ClickHouse client, or None when disabled / unreachable.

    Failed auth or connection is cached so scrapers do not spam ERROR logs
    on every ``record_scraper_execution`` call.
    """
    global _client

    if not _CLICKHOUSE_ENABLED:
        _mark_unavailable("CLICKHOUSE_ENABLED=0")
        return None
    if _unavailable:
        return None
    if _client is not None:
        return _client

    host = CLICKHOUSE_HOST
    if os.path.exists("/.dockerenv") and host in ["127.0.0.1", "localhost"]:
        host = "clickhouse"

    try:
        client = clickhouse_connect.get_client(
            host=host,
            port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            database=CLICKHOUSE_DB,
        )
        # Cheap ping so bad passwords fail here once, not on every insert.
        client.query("SELECT 1")
        _client = client
        return _client
    except Exception as e:
        _mark_unavailable(f"{host}:{CLICKHOUSE_PORT}: {e}")
        return None


def insert_batch(table_name: str, column_names: list[str], data_matrix: list[list[Any]]) -> bool:
    """Inserts a batch of rows into ClickHouse for high-throughput OLAP performance."""
    if not data_matrix:
        return True

    client = get_clickhouse_client()
    if not client:
        return False

    try:
        client.insert(table_name, data_matrix, column_names=column_names)
        logger.info(
            "Successfully inserted batch of %s rows into ClickHouse table '%s'.",
            len(data_matrix),
            table_name,
        )
        return True
    except Exception as e:
        logger.error("Error during ClickHouse batch insert into '%s': %s", table_name, e)
        _mark_unavailable(f"insert into {table_name}: {e}")
        return False


def init_clickhouse_tables():
    """Initializes high-performance OLAP tables and vector search indices in ClickHouse."""
    client = get_clickhouse_client()
    if not client:
        return False

    try:
        client.command(
            """
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
            """
        )
        logger.info("Successfully initialized ClickHouse OLAP tables and indices.")
        return True
    except Exception as e:
        logger.error("Error initializing ClickHouse tables: %s", e)
        _mark_unavailable(f"init tables: {e}")
        return False


if __name__ == "__main__":
    init_clickhouse_tables()
