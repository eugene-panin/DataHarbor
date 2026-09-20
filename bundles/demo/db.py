"""Schema + upsert for bundle `demo`."""
from __future__ import annotations

import logging
from typing import Any

from apps.db.connection import get_db_cursor

logger = logging.getLogger(__name__)


def init_bundle_tables() -> None:
    """Create the PostgreSQL table for scraped demo items."""
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS demo_items (
                id SERIAL PRIMARY KEY,
                company_name TEXT NOT NULL,
                summary TEXT,
                source_url TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (company_name)
            );
            """
        )
    logger.info("Initialized tables for bundle 'demo'")


def upsert_items(items: list[dict[str, Any]]) -> int:
    """Insert scraped rows, skipping ones already seen (by company_name)."""
    if not items:
        return 0
    with get_db_cursor(commit=True) as cursor:
        for item in items:
            cursor.execute(
                """
                INSERT INTO demo_items (company_name, summary, source_url)
                VALUES (%s, %s, %s)
                ON CONFLICT (company_name) DO UPDATE
                    SET summary = EXCLUDED.summary, source_url = EXCLUDED.source_url;
                """,
                (item.get("company_name"), item.get("summary"), item.get("source_url")),
            )
    return len(items)


def fetch_items() -> list[dict[str, Any]]:
    """Read back scraped rows, most recent first (used by exporter.py)."""
    with get_db_cursor(commit=False) as cursor:
        cursor.execute(
            "SELECT company_name, summary, source_url, created_at "
            "FROM demo_items ORDER BY created_at DESC;"
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]
