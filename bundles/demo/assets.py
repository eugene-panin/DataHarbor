"""Dagster definitions for bundle `demo` — scrape the local fixture end to end."""
from __future__ import annotations

from dagster import Definitions, asset

from bundles.demo.db import init_bundle_tables, upsert_items
from bundles.demo.scraper import DemoScraper


@asset(group_name="demo", description="Ensure PostgreSQL tables exist for the demo bundle")
def init_schema() -> None:
    init_bundle_tables()


@asset(
    group_name="demo",
    deps=[init_schema],
    description="Scrape the local demo_site fixture and upsert results into PostgreSQL",
)
def demo_scrape() -> dict:
    items = DemoScraper().scrape_all()
    stored = upsert_items(items)
    return {"scraped": len(items), "stored": stored}


defs = Definitions(assets=[init_schema, demo_scrape])
