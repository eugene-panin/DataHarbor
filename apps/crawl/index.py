"""SQL access to the Common Crawl columnar URL index via DuckDB.

Outside AWS, anonymous ``s3://commoncrawl`` List/Get via the S3 API is denied.
Use HTTPS object URLs from ``cc-index-table.paths.gz`` instead
(``https://data.commoncrawl.org/...``).
"""
from __future__ import annotations

import gzip
import logging
import os
from functools import lru_cache
from http.client import HTTPException
from pathlib import Path
from shutil import copyfileobj
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from apps.crawl.constants import (
    CC_DATA_HTTPS_BASE,
    CC_INDEX_S3_PREFIX,
    DEFAULT_INDEX_SUBSET,
    default_crawl_id,
)
from apps.crawl.gate import require_crawl

logger = logging.getLogger(__name__)

# Sampling default: full crawl has ~300 warc shards; scanning all over HTTPS is heavy.
DEFAULT_MAX_SHARDS = int(os.getenv("COMMONCRAWL_INDEX_MAX_SHARDS", "8"))
DEFAULT_DOWNLOAD_DIR = Path("downloads/commoncrawl")


def index_paths_manifest_url(crawl_id: str | None = None) -> str:
    """HTTPS URL of the per-crawl Parquet path listing (``cc-index-table.paths.gz``)."""
    crawl = crawl_id or default_crawl_id()
    return f"{CC_DATA_HTTPS_BASE}/crawl-data/{crawl}/cc-index-table.paths.gz"


def index_parquet_glob(
    crawl_id: str | None = None,
    *,
    subset: str = DEFAULT_INDEX_SUBSET,
) -> str:
    """Legacy S3 glob (usable inside AWS us-east-1 with authenticated S3)."""
    crawl = crawl_id or default_crawl_id()
    return f"{CC_INDEX_S3_PREFIX}/crawl={crawl}/subset={subset}/*.parquet"


@lru_cache(maxsize=8)
def list_index_parquet_urls(
    crawl_id: str | None = None,
    *,
    subset: str = DEFAULT_INDEX_SUBSET,
    max_shards: int | None = DEFAULT_MAX_SHARDS,
) -> tuple[str, ...]:
    """Return HTTPS Parquet shard URLs for one crawl/subset.

    Paths come from the public ``cc-index-table.paths.gz`` manifest (no S3 list).
    ``max_shards`` caps how many files DuckDB opens (``None`` / ``0`` = all).
    """
    crawl = crawl_id or default_crawl_id()
    manifest = index_paths_manifest_url(crawl)
    request = Request(manifest, headers={"User-Agent": "DataHarbor-crawl/1.0"})
    try:
        with urlopen(request, timeout=120) as resp:
            raw = resp.read()
    except HTTPError as e:
        raise RuntimeError(f"Failed to download index paths ({e.code}): {manifest}") from e
    except URLError as e:
        raise RuntimeError(f"Failed to download index paths: {manifest}: {e}") from e

    needle = f"/crawl={crawl}/subset={subset}/"
    urls: list[str] = []
    for line in gzip.decompress(raw).decode("utf-8", errors="replace").splitlines():
        path = line.strip()
        if not path or needle not in path:
            continue
        if not path.endswith(".parquet"):
            continue
        urls.append(f"{CC_DATA_HTTPS_BASE}/{path.lstrip('/')}")

    if not urls:
        raise RuntimeError(
            f"No Parquet shards for crawl={crawl!r} subset={subset!r} in {manifest}"
        )

    if max_shards is None or max_shards <= 0:
        selected = urls
    else:
        selected = urls[: int(max_shards)]
    logger.info(
        "CC index shards crawl=%s subset=%s selected=%s/%s",
        crawl,
        subset,
        len(selected),
        len(urls),
    )
    return tuple(selected)


def download_index_parquet(
    crawl_id: str | None = None,
    *,
    subset: str = DEFAULT_INDEX_SUBSET,
    shard: int = 0,
    output_dir: str | os.PathLike[str] = DEFAULT_DOWNLOAD_DIR,
    overwrite: bool = False,
) -> Path:
    """Download one Parquet index shard over HTTPS and return its local path.

    The file is streamed into a sibling ``.part`` file and renamed only after
    its byte count matches the server's ``Content-Length``. Existing completed
    files are preserved unless ``overwrite`` is true.
    """
    if shard < 0:
        raise ValueError("shard must be zero or greater")

    urls = list_index_parquet_urls(
        crawl_id,
        subset=subset,
        max_shards=shard + 1,
    )
    if shard >= len(urls):
        raise IndexError(
            f"Index shard {shard} does not exist for "
            f"crawl={crawl_id or default_crawl_id()!r} subset={subset!r}"
        )

    url = urls[shard]
    filename = Path(urlsplit(url).path).name
    if not filename:
        raise RuntimeError(f"Cannot determine a filename from index URL: {url}")

    crawl = crawl_id or default_crawl_id()
    destination = Path(output_dir).expanduser() / crawl / subset / filename
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Index shard already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f"{destination.name}.part")
    if partial.exists():
        partial.unlink()

    request = Request(url, headers={"User-Agent": "DataHarbor-crawl/1.0"})
    try:
        with urlopen(request, timeout=120) as response, partial.open("wb") as target:
            expected_header = response.headers.get("Content-Length")
            expected_size = int(expected_header) if expected_header else None
            copyfileobj(response, target, length=1024 * 1024)
    except (HTTPError, URLError, HTTPException, OSError) as exc:
        raise RuntimeError(f"Failed to download index shard: {url}: {exc}") from exc

    actual_size = partial.stat().st_size
    if expected_size is not None and actual_size != expected_size:
        raise RuntimeError(
            f"Incomplete index shard download: expected {expected_size} bytes, "
            f"received {actual_size}; partial file kept at {partial}"
        )

    partial.replace(destination)
    return destination


def index_from_clause(
    crawl_id: str | None = None,
    *,
    subset: str = DEFAULT_INDEX_SUBSET,
    alias: str = "cc",
    max_shards: int | None = DEFAULT_MAX_SHARDS,
    transport: str = "https",
) -> str:
    """DuckDB FROM expression for the columnar index table.

    ``transport='https'`` (default): anonymous path-manifest + HTTPS Parquet.
    ``transport='s3'``: legacy ``s3://commoncrawl/.../*.parquet`` glob (AWS / signed).
    """
    if transport == "s3":
        glob_path = index_parquet_glob(crawl_id, subset=subset)
        return f"read_parquet('{glob_path}', hive_partitioning=true, filename=true) AS {alias}"

    urls = list_index_parquet_urls(crawl_id, subset=subset, max_shards=max_shards)
    # DuckDB list literal of HTTPS objects — no S3 ListObjects required.
    listed = ", ".join(f"'{u}'" for u in urls)
    return f"read_parquet([{listed}], hive_partitioning=true, filename=true) AS {alias}"


def connect_duckdb():
    """Return a DuckDB connection with httpfs loaded (HTTPS + optional S3)."""
    require_crawl("duckdb")
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs;")
    con.execute("LOAD httpfs;")
    # Optional anonymous S3 secret for transport='s3' inside environments that allow it.
    try:
        con.execute(
            """
            CREATE OR REPLACE SECRET commoncrawl_anon (
                TYPE S3,
                PROVIDER CONFIG,
                KEY_ID '',
                SECRET '',
                REGION 'us-east-1',
                URL_STYLE 'path'
            );
            """
        )
    except Exception as exc:
        logger.debug("Could not create anonymous S3 secret (HTTPS path still works): %s", exc)
    return con


def query_index(sql: str, *, connection=None) -> list[dict[str, Any]]:
    """Run a SQL query and return rows as dicts.

    Build ``FROM`` with :func:`index_from_clause`, e.g.::

        sql = f'''
            SELECT url, url_host_name, warc_filename, warc_record_offset, warc_record_length
            FROM {index_from_clause(max_shards=4)}
            WHERE fetch_status = 200
              AND content_mime_type LIKE 'text/html%'
            LIMIT 100
        '''
        rows = query_index(sql)
    """
    require_crawl("duckdb")
    con = connection or connect_duckdb()
    cur = con.execute(sql)
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row, strict=False)) for row in cur.fetchall()]
