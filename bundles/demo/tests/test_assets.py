"""Tests for bundles/demo/assets.py (F16): a fetch or sink failure must fail
the Dagster asset, not materialize "successfully" with a plain dict full of
zeros. No DB/network needed — DemoScraper and upsert_items are mocked."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from dagster import Failure

from bundles.demo.assets import demo_scrape


def test_zero_items_raises_failure():
    with patch("bundles.demo.assets.DemoScraper") as mock_scraper_cls:
        mock_scraper_cls.return_value.scrape_all.return_value = []
        with pytest.raises(Failure):
            demo_scrape()


def test_partial_store_raises_failure():
    with (
        patch("bundles.demo.assets.DemoScraper") as mock_scraper_cls,
        patch("bundles.demo.assets.upsert_items", return_value=1),
    ):
        mock_scraper_cls.return_value.scrape_all.return_value = [{"company_name": "a"}, {"company_name": "b"}]
        with pytest.raises(Failure):
            demo_scrape()


def test_success_returns_counts():
    with (
        patch("bundles.demo.assets.DemoScraper") as mock_scraper_cls,
        patch("bundles.demo.assets.upsert_items", return_value=2),
    ):
        mock_scraper_cls.return_value.scrape_all.return_value = [{"company_name": "a"}, {"company_name": "b"}]
        result = demo_scrape()
    assert result == {"scraped": 2, "stored": 2}
