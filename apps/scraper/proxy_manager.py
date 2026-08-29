"""Optional egress proxy helpers for DataHarbor Core."""
from __future__ import annotations

import logging
import os
from typing import Final
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)

DEFAULT_PROXY_POOL: Final = "default"
RESIDENTIAL_PROXY_POOL: Final = "residential"
DATACENTER_PROXY_POOL: Final = "datacenter"
PROXY_POOLS: Final = frozenset(
    {DEFAULT_PROXY_POOL, RESIDENTIAL_PROXY_POOL, DATACENTER_PROXY_POOL}
)


class ProxyManager:
    """Resolve optional named egress-proxy pools from environment variables.

    The legacy ``PROXY_URL`` / ``PROXY_LIST`` pool remains the default and is
    also used as the residential fallback. New deployments should declare
    ``RESIDENTIAL_PROXY_*`` and ``DATACENTER_PROXY_*`` explicitly.
    """

    def __init__(self) -> None:
        self._pools: dict[str, list[str]] = {}
        self._load_proxies()

    def _load_proxies(self) -> None:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        legacy_default = self._read_pool("PROXY_LIST", "PROXY_URL")
        self._pools[RESIDENTIAL_PROXY_POOL] = self._read_pool(
            "RESIDENTIAL_PROXY_LIST", "RESIDENTIAL_PROXY_URL"
        ) or list(legacy_default)
        self._pools[DEFAULT_PROXY_POOL] = legacy_default or list(
            self._pools[RESIDENTIAL_PROXY_POOL]
        )
        self._pools[DATACENTER_PROXY_POOL] = self._read_pool(
            "DATACENTER_PROXY_LIST", "DATACENTER_PROXY_URL"
        )

    @staticmethod
    def _read_pool(list_variable: str, url_variable: str) -> list[str]:
        proxy_list_env = os.getenv(list_variable, "")
        single_proxy = os.getenv(url_variable, "")
        if proxy_list_env:
            return [
                ProxyManager._normalize_proxy_url(proxy)
                for proxy in proxy_list_env.split(",")
                if proxy.strip()
            ]
        if single_proxy:
            return [ProxyManager._normalize_proxy_url(single_proxy)]
        return []

    @staticmethod
    def _normalize_proxy_url(value: str) -> str:
        """Accept a URL or GeoNode's ``host:port:user:password`` export format."""
        proxy = value.strip()
        scheme, separator, authority = proxy.partition("://")
        parts = (authority if separator else proxy).split(":", 3)
        if len(parts) == 4 and parts[1].isdigit():
            host, port, username, password = parts
            return (
                f"{scheme if separator else 'http'}://{quote(username, safe='')}:{quote(password, safe='')}"
                f"@{host}:{port}"
            )
        return proxy

    def get_proxy_url(
        self,
        session_id: str | None = None,
        *,
        pool: str = DEFAULT_PROXY_POOL,
    ) -> str | None:
        """Return a configured proxy URL, or None when unset.

        ``session_id`` is accepted for API compatibility; Core returns the
        first configured proxy without rewriting credentials. Bundles may
        implement their own sticky-session / rotation logic.
        """
        del session_id  # unused in Core
        if pool not in PROXY_POOLS:
            supported = ", ".join(sorted(PROXY_POOLS))
            raise ValueError(f"Unsupported proxy pool {pool!r}. Use one of: {supported}")
        proxies = self._pools[pool]
        if not proxies:
            return None
        return proxies[0]

    def get_browser_proxy(
        self,
        session_id: str | None = None,
        *,
        pool: str = DEFAULT_PROXY_POOL,
    ) -> dict[str, str] | None:
        """Return browser-style proxy dict ({server, username?, password?}), or None.

        Useful for bundle-owned Playwright/Chromium clients. Core does not ship Playwright.
        """
        proxy_url = self.get_proxy_url(session_id=session_id, pool=pool)
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

    def get_http_proxies(
        self,
        session_id: str | None = None,
        *,
        pool: str = DEFAULT_PROXY_POOL,
    ) -> dict[str, str] | None:
        """Return proxies dict for urllib / requests-style clients."""
        proxy_url = self.get_proxy_url(session_id=session_id, pool=pool)
        if not proxy_url:
            return None
        return {"http": proxy_url, "https": proxy_url}

    # Back-compat alias used by older callers.
    get_curl_proxies = get_http_proxies


proxy_manager = ProxyManager()
