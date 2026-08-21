"""Scaffold generator for new DataHarbor bundles."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from bundles.validator import BundleValidator

BUNDLES_DIR = os.path.dirname(os.path.abspath(__file__))


def _normalize_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]+", "_", (name or "").strip()).strip("_").lower()
    if not cleaned or not cleaned.isidentifier() or cleaned[0].isdigit():
        raise ValueError(
            f"Invalid bundle name '{name}'. Use a Python identifier "
            "(letters/digits/underscore, not starting with a digit)."
        )
    return cleaned


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def create_bundle(
    name: str,
    *,
    description: Optional[str] = None,
    category: str = "custom",
    extractors: Optional[List[str]] = None,
    target_dir: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Create a minimal valid bundle scaffold (plugin contract v1).

    Default location: ``bundles/<name>/``.
    Use ``target_dir`` to scaffold into a private-repo working copy.
    """
    bundle_name = _normalize_name(name)
    root = os.path.abspath(target_dir) if target_dir else os.path.join(BUNDLES_DIR, bundle_name)

    if os.path.exists(root):
        if not force:
            raise ValueError(
                f"Bundle path already exists: {root}. Use --force to overwrite."
            )
        import shutil

        shutil.rmtree(root)

    os.makedirs(root, exist_ok=True)
    desc = description or f"DataHarbor bundle scaffold for {bundle_name}"
    extractor_reqs = list(extractors or [])

    manifest = {
        "name": bundle_name,
        "version": "0.1.0",
        "description": desc,
        "category": category,
        "author": "DataHarbor",
        "engines": {"dataharbor": ">=1.0.0,<2.0.0"},
        "requirements": {
            "extractors": extractor_reqs,
            "python": [],
            "min_python_version": "3.10",
        },
        "entrypoints": {
            "dagster": "assets:defs",
            "celery": None,
        },
        "observability": {
            "staleness_sla_hours": 24,
            "anomaly_threshold_ratio": 0.2,
        },
    }
    _write(os.path.join(root, "manifest.json"), json.dumps(manifest, indent=2) + "\n")
    _write(os.path.join(root, "__init__.py"), f'"""Bundle package: {bundle_name}."""\n')

    assets = f'''"""Dagster definitions for bundle `{bundle_name}`."""
from dagster import Definitions

# Declare assets / jobs / schedules / asset_checks here, then export defs.
# Core merges this object via Definitions.merge — do not rely on silent discovery.

defs = Definitions(
    assets=[],
    jobs=[],
    schedules=[],
    asset_checks=[],
)
'''
    _write(os.path.join(root, "assets.py"), assets)

    fetch = f'''"""Fetch helpers for bundle `{bundle_name}` (owned by the bundle author)."""
from __future__ import annotations

from typing import Any, Dict

from apps.scraper.http_fetcher import HttpFetcher


def fetch_url(url: str, *, session_id: str | None = None) -> Dict[str, Any]:
    """Minimal HTTP fetch via Core HttpFetcher.

    For JS-rendered pages, implement browser fetch inside this bundle and add
    e.g. ``"playwright>=1.41"`` to manifest ``requirements.python`` (not Core).
    """
    return HttpFetcher(session_id=session_id).fetch(url)
'''
    _write(os.path.join(root, "fetch.py"), fetch)

    class_name = "".join(part.capitalize() for part in bundle_name.split("_")) + "Scraper"
    scraper = f'''"""Scraper scaffold for bundle `{bundle_name}`."""
import logging
from typing import Any, Dict, List, Optional

from apps.observability.metrics import record_scraper_execution
from apps.scraper.extractors.registry import get_extractor
from bundles.{bundle_name}.fetch import fetch_url

logger = logging.getLogger(__name__)


class {class_name}:
    """Fetch pages; parse via installed extractors."""

    def scrape(self, target_url: str, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        logger.info("Fetching %s", target_url)
        res = fetch_url(target_url, session_id=session_id)
        status_code = res.get("status", 0)
        html = res.get("content", "")
        items: List[Dict[str, Any]] = []

        if status_code == 200 and html:
            parse_fn = get_extractor(target_url)
            if parse_fn is None:
                logger.error("No installed extractor matched URL: %s", target_url)
            else:
                items = parse_fn(html, target_url)

        exec_status = "SUCCESS" if items else ("ZERO_ROWS" if status_code == 200 else "FAILED")
        record_scraper_execution(
            bundle_name="{bundle_name}",
            status=exec_status,
            items_scraped=len(items),
            http_200_count=1 if status_code == 200 else 0,
            http_403_count=1 if status_code == 403 else 0,
            http_429_count=1 if status_code == 429 else 0,
        )
        return items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print({class_name}().scrape("https://example.com"))
'''
    _write(os.path.join(root, "scraper.py"), scraper)

    db = f'''"""Schema init scaffold for bundle `{bundle_name}`."""
import logging

from apps.db.connection import get_db_cursor

logger = logging.getLogger(__name__)


def init_bundle_tables() -> None:
    """Create PostgreSQL tables for this bundle."""
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS {bundle_name}_items (
                id SERIAL PRIMARY KEY,
                title TEXT,
                website TEXT,
                source_url TEXT,
                payload JSONB DEFAULT '{{}}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
    logger.info("Initialized tables for bundle '%s'", "{bundle_name}")
'''
    _write(os.path.join(root, "db.py"), db)

    is_valid, errors = BundleValidator(root).validate()
    if not is_valid:
        raise ValueError(
            "Scaffold created but failed validation:\n  - " + "\n  - ".join(errors)
        )

    return {
        "status": "success",
        "bundle_name": bundle_name,
        "path": root,
        "files": [
            "manifest.json",
            "__init__.py",
            "assets.py",
            "fetch.py",
            "scraper.py",
            "db.py",
        ],
        "message": f"Bundle scaffold '{bundle_name}' created at {root}",
    }
