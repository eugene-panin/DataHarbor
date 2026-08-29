"""Common Crawl public dataset locations (columnar index + WARC)."""
from __future__ import annotations

import os

# Columnar URL index (Parquet, hive-partitioned). See:
# https://commoncrawl.org/url-index
CC_INDEX_S3_PREFIX = "s3://commoncrawl/cc-index/table/cc-main/warc"

# WARC/WAT/WET payloads referenced by index rows (warc_filename column).
CC_DATA_HTTPS_BASE = "https://data.commoncrawl.org"
CC_DATA_S3_PREFIX = "s3://commoncrawl"

DEFAULT_CRAWL_ID = "CC-MAIN-2026-30"
DEFAULT_INDEX_SUBSET = "warc"


def default_crawl_id() -> str:
    """Active crawl partition; override with COMMONCRAWL_CRAWL_ID."""
    return (os.getenv("COMMONCRAWL_CRAWL_ID") or DEFAULT_CRAWL_ID).strip()
