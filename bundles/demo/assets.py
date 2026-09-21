"""Dagster definitions for bundle `demo` — scrape the local fixture end to end."""
from __future__ import annotations

from dagster import Definitions, Failure, MetadataValue, asset

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
    """Raises on a fetch or sink failure instead of returning a plain dict —
    a plain-dict return always materializes "successfully" no matter what's
    inside it, so an HTTP failure or a broken sink previously looked
    identical to a real 8-row scrape in the Dagster UI (green check, zeros).
    """
    items = DemoScraper().scrape_all()
    if not items:
        raise Failure(
            description=(
                "demo_scrape returned 0 items — the demo_site fixture was unreachable "
                "or its markup no longer matches extractors/demo_site/extractor.py."
            ),
            metadata={"scraped": MetadataValue.int(0)},
        )
    stored = upsert_items(items)
    if stored != len(items):
        raise Failure(
            description=f"Only {stored}/{len(items)} scraped item(s) were stored in demo_items.",
            metadata={"scraped": MetadataValue.int(len(items)), "stored": MetadataValue.int(stored)},
        )
    return {"scraped": len(items), "stored": stored}


defs = Definitions(assets=[init_schema, demo_scrape])
