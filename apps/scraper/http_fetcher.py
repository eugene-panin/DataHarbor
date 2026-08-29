"""HTTP fetcher helper for DataHarbor Core."""
from __future__ import annotations

import logging
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from apps.scraper.proxy_manager import DEFAULT_PROXY_POOL, proxy_manager

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "DataHarbor/1.0 (+https://github.com/eugene-panin/DataHarbor)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class _RedirectRecorder(HTTPRedirectHandler):
    def __init__(self, chain: list[str]):
        super().__init__()
        self.chain = chain

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if newurl not in self.chain:
            self.chain.append(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpFetcher:
    """HTTP(S) fetcher with optional egress proxy."""

    def __init__(
        self,
        proxies: dict[str, str] | None = None,
        session_id: str | None = None,
        use_proxy: bool = True,
        proxy_pool: str = DEFAULT_PROXY_POOL,
        **_ignored: Any,
    ):
        self.session_id = session_id
        self.use_proxy = use_proxy
        self.proxy_pool = proxy_pool
        if not use_proxy:
            self.proxies: dict[str, str] = {}
        elif proxies is not None:
            self.proxies = proxies
        else:
            self.proxies = proxy_manager.get_http_proxies(session_id=session_id, pool=proxy_pool) or {}

    def fetch(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: int = 20,
        require_proxy: bool = False,
    ) -> dict[str, Any]:
        """Fetch a URL over HTTP(S). Returns status/headers/content dict."""
        if require_proxy and not self.proxies:
            return {
                "url": url,
                "requested_url": url,
                "final_url": url,
                "redirect_chain": [url],
                "status": 502,
                "headers": {},
                "content": "",
                "error": "A proxy is required but none is configured",
            }

        request_headers = DEFAULT_HEADERS.copy()
        if headers:
            request_headers.update(headers)

        logger.info("Fetching URL via HttpFetcher (proxy=%s): %s", bool(self.proxies), url)
        redirect_chain = [url]
        try:
            req = Request(url, headers=request_headers, method="GET")
            redirect_recorder = _RedirectRecorder(redirect_chain)
            if self.proxies:
                opener = build_opener(ProxyHandler(self.proxies), redirect_recorder)
            else:
                context = ssl.create_default_context()
                opener = build_opener(HTTPSHandler(context=context), redirect_recorder)
            response = opener.open(req, timeout=timeout)

            with response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                content = raw.decode(charset, errors="replace")
                status = getattr(response, "status", None) or response.getcode() or 200
                final_url = response.geturl() or url
                if final_url not in redirect_chain:
                    redirect_chain.append(final_url)
                return {
                    "url": url,
                    "requested_url": url,
                    "final_url": final_url,
                    "redirect_chain": redirect_chain,
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
                "requested_url": url,
                "final_url": e.geturl() or url,
                "redirect_chain": redirect_chain,
                "status": int(e.code),
                "headers": dict(e.headers.items()) if e.headers else {},
                "content": body,
                "error": str(e),
            }
        except (URLError, TimeoutError, OSError) as e:
            logger.warning("HttpFetcher request failed for %s: %s", url, e)
            return {
                "url": url,
                "requested_url": url,
                "final_url": url,
                "redirect_chain": redirect_chain,
                "status": 502,
                "headers": {},
                "content": "",
                "error": str(e),
            }


def scrape_with_http(
    url: str,
    headers: dict[str, str] | None = None,
    session_id: str | None = None,
    proxy_pool: str = DEFAULT_PROXY_POOL,
) -> dict[str, Any]:
    """Helper wrapper for the core HTTP fetcher."""
    return HttpFetcher(session_id=session_id, proxy_pool=proxy_pool).fetch(url, headers=headers)


# Back-compat aliases for older imports (neutral behavior only).
CurlScraper = HttpFetcher
scrape_with_curl = scrape_with_http
