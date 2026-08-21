"""HTTP fetcher helper for DataHarbor Core."""
from __future__ import annotations

import logging
import ssl
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from apps.scraper.proxy_manager import proxy_manager

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "DataHarbor/1.0 (+https://github.com/eugene-panin/DataHarbor)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class HttpFetcher:
    """HTTP(S) fetcher with optional egress proxy."""

    def __init__(
        self,
        proxies: Optional[Dict[str, str]] = None,
        session_id: Optional[str] = None,
        use_proxy: bool = True,
        **_ignored: Any,
    ):
        self.session_id = session_id
        self.use_proxy = use_proxy
        if not use_proxy:
            self.proxies: Dict[str, str] = {}
        elif proxies is not None:
            self.proxies = proxies
        else:
            self.proxies = proxy_manager.get_http_proxies(session_id=session_id) or {}

    def fetch(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 20,
        require_proxy: bool = False,
    ) -> Dict[str, Any]:
        """Fetch a URL over HTTP(S). Returns status/headers/content dict."""
        if require_proxy and not self.proxies:
            return {
                "url": url,
                "status": 502,
                "headers": {},
                "content": "",
                "error": "A proxy is required but none is configured",
            }

        request_headers = DEFAULT_HEADERS.copy()
        if headers:
            request_headers.update(headers)

        logger.info("Fetching URL via HttpFetcher (proxy=%s): %s", bool(self.proxies), url)
        try:
            req = Request(url, headers=request_headers, method="GET")
            if self.proxies:
                opener = build_opener(ProxyHandler(self.proxies))
                response = opener.open(req, timeout=timeout)
            else:
                context = ssl.create_default_context()
                response = urlopen(req, timeout=timeout, context=context)

            with response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                content = raw.decode(charset, errors="replace")
                status = getattr(response, "status", None) or response.getcode() or 200
                return {
                    "url": url,
                    "status": int(status),
                    "headers": dict(response.headers.items()),
                    "content": content,
                }
        except HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            return {
                "url": url,
                "status": int(e.code),
                "headers": dict(e.headers.items()) if e.headers else {},
                "content": body,
                "error": str(e),
            }
        except (URLError, TimeoutError, OSError) as e:
            logger.warning("HttpFetcher request failed for %s: %s", url, e)
            return {
                "url": url,
                "status": 502,
                "headers": {},
                "content": "",
                "error": str(e),
            }


def scrape_with_http(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Helper wrapper for the core HTTP fetcher."""
    return HttpFetcher(session_id=session_id).fetch(url, headers=headers)


# Back-compat aliases for older imports (neutral behavior only).
CurlScraper = HttpFetcher
scrape_with_curl = scrape_with_http
