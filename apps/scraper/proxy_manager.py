"""Optional egress proxy helpers for DataHarbor Core."""
from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ProxyManager:
    """Resolves an optional egress proxy from environment variables."""

    def __init__(self) -> None:
        self._proxies: list[str] = []
        self._load_proxies()

    def _load_proxies(self) -> None:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        proxy_list_env = os.getenv("PROXY_LIST", "")
        single_proxy = os.getenv("PROXY_URL", "")

        if proxy_list_env:
            self._proxies = [p.strip() for p in proxy_list_env.split(",") if p.strip()]
        elif single_proxy:
            self._proxies = [single_proxy.strip()]

    def get_proxy_url(self, session_id: str | None = None) -> str | None:
        """Return a configured proxy URL, or None when unset.

        ``session_id`` is accepted for API compatibility; Core returns the
        first configured proxy without rewriting credentials. Bundles may
        implement their own sticky-session / rotation logic.
        """
        del session_id  # unused in Core
        if not self._proxies:
            return None
        return self._proxies[0]

    def get_browser_proxy(self, session_id: str | None = None) -> dict[str, str] | None:
        """Return browser-style proxy dict ({server, username?, password?}), or None.

        Useful for bundle-owned Playwright/Chromium clients. Core does not ship Playwright.
        """
        proxy_url = self.get_proxy_url(session_id=session_id)
        if not proxy_url:
            return None

        parsed = urlparse(proxy_url)
        if parsed.username and parsed.password:
            server = f"{parsed.scheme}://{parsed.hostname}"
            if parsed.port:
                server += f":{parsed.port}"
            return {
                "server": server,
                "username": parsed.username,
                "password": parsed.password,
            }
        return {"server": proxy_url}

    # Back-compat alias for older bundle code.
    get_playwright_proxy = get_browser_proxy

    def get_http_proxies(self, session_id: str | None = None) -> dict[str, str] | None:
        """Return proxies dict for urllib / requests-style clients."""
        proxy_url = self.get_proxy_url(session_id=session_id)
        if not proxy_url:
            return None
        return {"http": proxy_url, "https": proxy_url}

    # Back-compat alias used by older callers.
    get_curl_proxies = get_http_proxies


proxy_manager = ProxyManager()
