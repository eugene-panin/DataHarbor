"""Tests for demo_site — co-located open-core extractor example."""
from __future__ import annotations

from pathlib import Path

from apps.extractor.validator import ExtractorValidator
from apps.scraper.extractors.registry import clear_registry_cache, generate_page_urls_for_domain, require_extractor

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def setup_function() -> None:
    clear_registry_cache()


def teardown_function() -> None:
    clear_registry_cache()


def test_extractor_validates():
    is_valid, errors = ExtractorValidator(str(PLUGIN_ROOT)).validate()
    assert is_valid, errors


def test_parse_returns_source_url():
    parse_fn = require_extractor("demo_site")
    html = """
    <html><body>
      <h1>Acme Agency</h1>
      <div class="card">Beta Co</div>
    </body></html>
    """
    records = parse_fn(html, "https://demo_site.example/list")
    assert len(records) >= 1
    assert records[0]["source_url"] == "https://demo_site.example/list"
    assert records[0]["source_directory"] == "demo_site"


def test_generate_page_urls_for_domain():
    urls = generate_page_urls_for_domain("https://demo_site.example/list", max_pages=3)
    assert len(urls) == 3
    assert urls[0] == "https://demo_site.example/list"
    assert "page=1" in urls[1]
