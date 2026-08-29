"""Common Crawl helpers (CDX + columnar URL index + WARC range fetch).

Install::

    uv sync --extra crawl

Outside AWS, prefer:
- CDX HTTPS (``query_cdx``) for URL/pattern lookups
- Columnar Parquet over HTTPS via ``cc-index-table.paths.gz`` (``index_from_clause``)

Anonymous S3 ListObjects on ``s3://commoncrawl`` is denied; use ``transport='https'``.
"""
from __future__ import annotations

from apps.crawl.cdx import cdx_index_url, query_cdx
from apps.crawl.constants import (
    CC_DATA_HTTPS_BASE,
    CC_DATA_S3_PREFIX,
    CC_INDEX_S3_PREFIX,
    DEFAULT_CRAWL_ID,
    default_crawl_id,
)
from apps.crawl.gate import (
    CRAWL_EXTRA_HINT,
    CRAWL_PACKAGE_NAMES,
    crawl_extra_installed,
    require_crawl,
)
from apps.crawl.index import (
    connect_duckdb,
    download_index_parquet,
    index_from_clause,
    index_parquet_glob,
    index_paths_manifest_url,
    list_index_parquet_urls,
    query_index,
)
from apps.crawl.warc import WarcHttpResponse, fetch_warc_record, fetch_warc_records, warc_data_url

__all__ = [
    "CC_DATA_HTTPS_BASE",
    "CC_DATA_S3_PREFIX",
    "CC_INDEX_S3_PREFIX",
    "CRAWL_EXTRA_HINT",
    "CRAWL_PACKAGE_NAMES",
    "DEFAULT_CRAWL_ID",
    "WarcHttpResponse",
    "cdx_index_url",
    "connect_duckdb",
    "crawl_extra_installed",
    "default_crawl_id",
    "download_index_parquet",
    "fetch_warc_record",
    "fetch_warc_records",
    "index_from_clause",
    "index_parquet_glob",
    "index_paths_manifest_url",
    "list_index_parquet_urls",
    "query_cdx",
    "query_index",
    "require_crawl",
    "warc_data_url",
]
