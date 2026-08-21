import logging
from dagster import asset, Output, MetadataValue
from apps.scraper.http_fetcher import scrape_with_http

logger = logging.getLogger(__name__)

HEALTHCHECK_TARGETS = [
    "https://httpbin.org/headers",
    "https://httpbin.org/user-agent",
    "https://httpbin.org/ip",
]

@asset(
    group_name="01_system_health",
    description="[Core Engine] Diagnostic healthcheck verifying the platform HTTP fetcher",
)
def core_engine_healthcheck():
    """Diagnostic healthcheck for core HTTP fetcher connectivity."""
    results = []
    for url in HEALTHCHECK_TARGETS:
        logger.info(f"Healthcheck scraping {url}")
        res = scrape_with_http(url)
        results.append(res)

    success_count = sum(1 for r in results if r.get("status") == 200)

    return Output(
        value=results,
        metadata={
            "status": "HEALTHY" if success_count == len(results) else "DEGRADED",
            "successful_requests": f"{success_count}/{len(results)}",
            "tested_urls": MetadataValue.json([r["url"] for r in results]),
        }
    )
