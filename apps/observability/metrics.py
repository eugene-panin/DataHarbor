import logging

from apps.db.clickhouse_client import get_clickhouse_client, insert_batch
from apps.db.connection import get_db_cursor

logger = logging.getLogger(__name__)

def init_metrics_db():
    """Initializes scraper metrics and health tracking tables in PostgreSQL & ClickHouse."""
    try:
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scraper_execution_logs (
                    id SERIAL PRIMARY KEY,
                    bundle_name VARCHAR(100) NOT NULL,
                    status VARCHAR(50) NOT NULL,            -- SUCCESS, DEGRADED, FAILED, ZERO_ROWS
                    items_scraped INT DEFAULT 0,
                    duration_seconds NUMERIC(8, 2) DEFAULT 0.00,
                    http_200_count INT DEFAULT 0,
                    http_403_count INT DEFAULT 0,
                    http_429_count INT DEFAULT 0,
                    http_500_count INT DEFAULT 0,
                    error_message TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)

            cursor.execute("""
                CREATE OR REPLACE VIEW v_scraper_health_status AS
                SELECT 
                    bundle_name,
                    COUNT(*) AS total_runs_24h,
                    SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS success_runs_24h,
                    SUM(CASE WHEN status = 'ZERO_ROWS' OR status = 'DEGRADED' THEN 1 ELSE 0 END) AS anomaly_runs_24h,
                    SUM(items_scraped) AS total_items_scraped_24h,
                    MAX(created_at) AS last_run_timestamp,
                    MAX(CASE WHEN status = 'SUCCESS' THEN created_at ELSE NULL END) AS last_success_timestamp
                FROM scraper_execution_logs
                WHERE created_at >= NOW() - INTERVAL '24 HOURS'
                GROUP BY bundle_name;
            """)
        logger.info("Successfully initialized PostgreSQL scraper_execution_logs table via connection pool.")
    except Exception as e:
        logger.error(f"Error initializing PostgreSQL metrics DB: {e}")

    # Initialize ClickHouse OLAP metrics table
    try:
        ch_client = get_clickhouse_client()
        if ch_client:
            ch_client.command("""
                CREATE TABLE IF NOT EXISTS clickhouse_scraper_telemetry (
                    run_id UUID DEFAULT generateUUIDv4(),
                    bundle_name LowCardinality(String),
                    status LowCardinality(String),
                    items_scraped UInt32,
                    duration_seconds Float32,
                    http_403_count UInt32,
                    http_429_count UInt32,
                    created_at DateTime DEFAULT now()
                ) ENGINE = MergeTree()
                ORDER BY (bundle_name, status, created_at);
            """)
            logger.info("Successfully initialized ClickHouse scraper telemetry table.")
    except Exception as e:
        logger.error(f"Error initializing ClickHouse metrics DB: {e}")

def record_scraper_execution(
    bundle_name: str,
    status: str,
    items_scraped: int = 0,
    duration_seconds: float = 0.0,
    http_200_count: int = 0,
    http_403_count: int = 0,
    http_429_count: int = 0,
    http_500_count: int = 0,
    error_message: str | None = None
) -> int:
    """Records a scraper execution metric log into PostgreSQL connection pool & ClickHouse batch engine."""
    init_metrics_db()
    log_id = 0

    # 1. Save to PostgreSQL via Connection Pool
    try:
        with get_db_cursor(commit=True) as cursor:
            cursor.execute("""
                INSERT INTO scraper_execution_logs (
                    bundle_name, status, items_scraped, duration_seconds,
                    http_200_count, http_403_count, http_429_count, http_500_count, error_message
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                bundle_name, status, items_scraped, duration_seconds,
                http_200_count, http_403_count, http_429_count, http_500_count, error_message
            ))
            res = cursor.fetchone()
            log_id = res['id'] if isinstance(res, dict) else res[0]
    except Exception as e:
        logger.error(f"Failed to record scraper metric in PostgreSQL: {e}")

    # 2. Save to ClickHouse using Batch Insert Helper
    try:
        insert_batch(
            "clickhouse_scraper_telemetry",
            ["bundle_name", "status", "items_scraped", "duration_seconds", "http_403_count", "http_429_count"],
            [[bundle_name, status, items_scraped, duration_seconds, http_403_count, http_429_count]]
        )
    except Exception as e:
        logger.error(f"Failed to record scraper metric in ClickHouse: {e}")

    return log_id

if __name__ == "__main__":
    init_metrics_db()
