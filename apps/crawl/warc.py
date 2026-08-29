"""Fetch individual HTTP responses from Common Crawl WARC by index pointer."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from apps.crawl.constants import CC_DATA_HTTPS_BASE
from apps.crawl.gate import require_crawl

logger = logging.getLogger(__name__)


@dataclass
class WarcHttpResponse:
    """One ``response`` record from a WARC slice."""

    url: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    @property
    def text(self) -> str:
        charset = "utf-8"
        for key, value in self.headers.items():
            if key.lower() == "content-type" and "charset=" in value.lower():
                charset = value.lower().split("charset=", 1)[1].split(";", 1)[0].strip()
                break
        return self.body.decode(charset, errors="replace")


def warc_data_url(warc_filename: str) -> str:
    """HTTPS URL for a WARC object path from the index ``warc_filename`` column."""
    path = warc_filename.lstrip("/")
    return f"{CC_DATA_HTTPS_BASE}/{path}"


def fetch_warc_record(
    warc_filename: str,
    offset: int,
    length: int,
    *,
    timeout: int = 120,
) -> WarcHttpResponse:
    """Download a byte range from a WARC file and parse the embedded HTTP response."""
    require_crawl("warcio")
    from warcio.archiveiterator import ArchiveIterator

    if length <= 0:
        raise ValueError("warc_record_length must be positive")
    if offset < 0:
        raise ValueError("warc_record_offset must be non-negative")

    url = warc_data_url(warc_filename)
    end = offset + length - 1
    request = Request(url, headers={"Range": f"bytes={offset}-{end}"})

    try:
        with urlopen(request, timeout=timeout) as resp:
            payload = resp.read()
    except HTTPError as e:
        raise RuntimeError(f"WARC range fetch failed ({e.code}) for {url}") from e
    except URLError as e:
        raise RuntimeError(f"WARC range fetch failed for {url}: {e}") from e

    for record in ArchiveIterator(io.BytesIO(payload)):
        if record.rec_type != "response":
            continue
        http_headers = record.http_headers
        status = int(http_headers.get_statuscode()) if http_headers else 0
        headers: dict[str, str] = {}
        if http_headers:
            headers = {k: v for k, v in http_headers.headers}
        body = record.content_stream().read()
        target_uri = record.rec_headers.get_header("WARC-Target-URI") if record.rec_headers else ""
        return WarcHttpResponse(url=target_uri or "", status=status, headers=headers, body=body)

    raise ValueError(f"No response record in WARC slice {warc_filename}@{offset}+{length}")


def fetch_warc_records(rows: list[dict[str, Any]], *, limit: int | None = None) -> list[WarcHttpResponse]:
    """Fetch multiple index rows that include warc_filename/offset/length columns."""
    out: list[WarcHttpResponse] = []
    for row in rows[:limit] if limit is not None else rows:
        try:
            out.append(
                fetch_warc_record(
                    row["warc_filename"],
                    int(row["warc_record_offset"]),
                    int(row["warc_record_length"]),
                )
            )
        except Exception as e:
            logger.warning("Skipping WARC row %s: %s", row.get("url"), e)
    return out
