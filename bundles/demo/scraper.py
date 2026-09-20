"""Scraper for bundle `demo` — fetches the local demo_site fixture, no API keys needed."""
from __future__ import annotations

import logging
from typing import Any

from apps.observability.metrics import record_scraper_execution
from apps.scraper.extractors.registry import get_extractor
from bundles.demo.fetch import DEMO_SITE_URL, fetch_url

logger = logging.getLogger(__name__)

# Two static pages served by the `demo_site` compose service (deploy/demo_site/).
PAGES = ["/", "/page-2.html"]


class DemoScraper:
    """Fetch the demo fixture pages; parse via the installed `demo_site` extractor."""

    def scrape_all(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        pages_ok = 0

        for path in PAGES:
            url = f"{DEMO_SITE_URL}{path}"
            logger.info("Fetching %s", url)
            res = fetch_url(url)
            status_code = res.get("status", 0)
            html = res.get("content", "")

            if status_code != 200 or not html:
                logger.error("Demo site fetch failed for %s (status=%s)", url, status_code)
                continue

            parse_fn = get_extractor("demo_site")
            if parse_fn is None:
                logger.error("Extractor 'demo_site' is not installed.")
                continue

            page_items = parse_fn(html, url)
            items.extend(page_items)
            pages_ok += 1

        exec_status = "SUCCESS" if items else ("ZERO_ROWS" if pages_ok else "FAILED")
        record_scraper_execution(
            bundle_name="demo",
            status=exec_status,
            items_scraped=len(items),
            http_200_count=pages_ok,
        )
        return items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(DemoScraper().scrape_all())
