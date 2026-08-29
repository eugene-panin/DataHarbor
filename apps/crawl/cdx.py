"""Common Crawl CDX Server API (HTTPS) — anonymous URL → WARC pointers.

Columnar Parquet index on ``s3://commoncrawl/`` may require credentials /
Athena; the public CDX endpoint works without AWS keys.

Docs: https://index.commoncrawl.org/
"""
from __future__ import annotations

import json
import logging
import time
from http.client import IncompleteRead, RemoteDisconnected
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from apps.crawl.constants import default_crawl_id

logger = logging.getLogger(__name__)

CDX_INDEX_BASE = "https://index.commoncrawl.org"
# Transient disconnects from index.commoncrawl.org are common from Docker/cloud egress.
_RETRY_DELAYS_SEC = (1.5, 4.0, 10.0)
_TRANSIENT = (
    URLError,
    RemoteDisconnected,
    IncompleteRead,
    TimeoutError,
    ConnectionResetError,
    ConnectionAbortedError,
    BrokenPipeError,
    OSError,
)


def cdx_index_url(crawl_id: str | None = None) -> str:
    """CDX collection endpoint for one crawl (``…/CC-MAIN-YYYY-NN-index``)."""
    crawl = crawl_id or default_crawl_id()
    return f"{CDX_INDEX_BASE}/{crawl}-index"


def _cdx_get_payload(full_url: str, *, timeout: int) -> str:
    """GET CDX URL with retries on disconnect / timeout."""
    request = Request(
        full_url,
        headers={
            "User-Agent": "DataHarbor-crawl/1.0 (+https://github.com/dataharbor)",
            "Accept": "application/json,text/plain,*/*",
            "Connection": "close",
        },
    )
    attempts = 1 + len(_RETRY_DELAYS_SEC)
    last_exc: BaseException | None = None

    for attempt in range(1, attempts + 1):
        if attempt > 1:
            delay = _RETRY_DELAYS_SEC[attempt - 2]
            logger.warning(
                "CDX retry %s/%s after %.1fs (%s)",
                attempt,
                attempts,
                delay,
                type(last_exc).__name__ if last_exc else "error",
            )
            time.sleep(delay)
        try:
            with urlopen(request, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            # Empty result set — not retryable; signal as empty payload.
            if e.code == 404 and ("No Captures" in body or "no captures" in body.lower()):
                return ""
            # 5xx / 429 — retry
            if e.code in {429, 500, 502, 503, 504} and attempt < attempts:
                last_exc = e
                continue
            raise RuntimeError(
                f"CDX query failed ({e.code}) for {full_url}: {body[:200] or e.reason}"
            ) from e
        except _TRANSIENT as e:
            last_exc = e
            if attempt >= attempts:
                break
            continue

    raise RuntimeError(
        f"CDX query failed after {attempts} attempts for {full_url}: {last_exc}"
    ) from last_exc


def query_cdx(
    url: str,
    *,
    crawl_id: str | None = None,
    limit: int = 100,
    match_type: str | None = None,
    filter_status: int | None = 200,
    filter_mime: str | None = "text/html",
    timeout: int = 120,
) -> list[dict[str, Any]]:
    """Query CDX for WARC pointers matching a URL / pattern.

    ``url`` examples: ``shopify.com/``, ``*.myshopify.com/*``, ``example.com/*``.
    Returns rows normalized to the same pointer fields as the Parquet index
    helpers (``url``, ``warc_filename``, ``warc_record_offset``, ``warc_record_length``).
    """
    if not (url or "").strip():
        raise ValueError("CDX url pattern is required")

    limit = max(1, min(int(limit), 10_000))
    params: dict[str, str] = {
        "url": url.strip(),
        "output": "json",
        "limit": str(limit),
    }
    if match_type:
        params["matchType"] = match_type
    # Over-fetch slightly when client-side filters are applied
    if filter_status is not None or filter_mime:
        params["limit"] = str(min(limit * 5, 10_000))

    endpoint = cdx_index_url(crawl_id)
    full_url = f"{endpoint}?{urlencode(params)}"

    try:
        payload = _cdx_get_payload(full_url, timeout=timeout)
    except RuntimeError:
        raise

    if not payload.strip():
        logger.info(
            "CDX empty/no-captures for pattern=%r crawl=%s",
            url.strip(),
            crawl_id or default_crawl_id(),
        )
        return []

    out: list[dict[str, Any]] = []
    for line in payload.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed CDX line")
            continue
        status = str(row.get("status") or "")
        mime = str(row.get("mime-detected") or row.get("mime") or "")
        if filter_status is not None and status != str(filter_status):
            continue
        if filter_mime and filter_mime not in mime:
            continue
        filename = row.get("filename")
        offset = row.get("offset")
        length = row.get("length")
        if not filename or offset is None or length is None:
            continue
        page_url = str(row.get("url") or "")
        host = ""
        try:
            from urllib.parse import urlparse

            host = (urlparse(page_url).hostname or "").lower()
        except Exception:
            host = ""
        out.append(
            {
                "url": page_url,
                "url_host_name": host,
                "warc_filename": str(filename),
                "warc_record_offset": int(offset),
                "warc_record_length": int(length),
                "timestamp": row.get("timestamp"),
                "status": int(status) if status.isdigit() else None,
                "mime": mime,
                "source": "cdx",
            }
        )
        if len(out) >= limit:
            break
    return out
