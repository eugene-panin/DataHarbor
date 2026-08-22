"""Deprecated module path — use ``apps.scraper.http_fetcher``."""
from apps.scraper.http_fetcher import (
    CurlScraper,
    HttpFetcher,
    scrape_with_curl,
    scrape_with_http,
)

__all__ = ["CurlScraper", "HttpFetcher", "scrape_with_curl", "scrape_with_http"]
