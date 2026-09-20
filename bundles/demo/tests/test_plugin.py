"""Tests for `demo` bundle (co-located with the plugin). No network/docker needed:
parses the static fixture files directly from deploy/demo_site/."""
from __future__ import annotations

from pathlib import Path

from apps.bundle.validator import BundleValidator
from apps.scraper.extractors.registry import clear_registry_cache, require_extractor

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
FIXTURE_DIR = REPO_ROOT / "deploy" / "demo_site"


def setup_function() -> None:
    clear_registry_cache()


def teardown_function() -> None:
    clear_registry_cache()


def test_bundle_validates():
    is_valid, errors = BundleValidator(str(PLUGIN_ROOT)).validate()
    assert is_valid, errors


def test_fixture_pages_parse_into_company_rows():
    parse_fn = require_extractor("demo_site")

    page1 = (FIXTURE_DIR / "index.html").read_text(encoding="utf-8")
    page2 = (FIXTURE_DIR / "page-2.html").read_text(encoding="utf-8")

    rows1 = parse_fn(page1, "http://demo_site/")
    rows2 = parse_fn(page2, "http://demo_site/page-2.html")

    names = {row["company_name"] for row in rows1 + rows2}
    assert "Acme Analytics" in names
    assert "Harbor Notary" in names
    assert len(names) == 8

    acme = next(row for row in rows1 if row["company_name"] == "Acme Analytics")
    assert acme["summary"] == "Self-serve BI dashboards for seed-stage startups."
