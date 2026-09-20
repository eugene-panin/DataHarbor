"""Fetch helpers for bundle `demo` (owned by the bundle author)."""
from __future__ import annotations

import os
from typing import Any

from apps.scraper.http_fetcher import HttpFetcher

# Docker network hostname of the `demo_site` compose service (see docker-compose.yml).
# Override with DEMO_SITE_URL when running the scraper outside that network
# (e.g. `DEMO_SITE_URL=http://localhost:8098 harbor bundle run demo --runtime host`).
DEMO_SITE_URL = os.getenv("DEMO_SITE_URL", "http://demo_site")


def fetch_url(url: str) -> dict[str, Any]:
    """Minimal HTTP fetch via Core HttpFetcher, no proxy needed for the local fixture."""
    return HttpFetcher(use_proxy=False).fetch(url)
