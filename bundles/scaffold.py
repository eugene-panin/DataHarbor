"""Scaffold generator for new DataHarbor bundles (multi-template)."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from bundles.validator import BundleValidator

BUNDLES_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_TEMPLATE = "default"


@dataclass(frozen=True)
class BundleTemplate:
    id: str
    title: str
    description: str
    files: list[str] = field(default_factory=list)


def list_bundle_templates() -> list[BundleTemplate]:
    """Return available scaffold templates for ``harbor bundle new --template``."""
    return [
        BundleTemplate(
            id="default",
            title="Full pipeline",
            description="Fetch + scraper + db + Dagster assets (standard ingest bundle)",
            files=["manifest.json", "__init__.py", "assets.py", "fetch.py", "scraper.py", "db.py"],
        ),
        BundleTemplate(
            id="ml",
            title="ML / RAG",
            description="Dagster assets + model registry db; no scrape (datasets on S3 / Qdrant)",
            files=["manifest.json", "__init__.py", "assets.py", "db.py"],
        ),
        BundleTemplate(
            id="etl",
            title="ETL only",
            description="Dagster assets + Postgres schema; no fetch/scrape (data already in platform)",
            files=["manifest.json", "__init__.py", "assets.py", "db.py"],
        ),
        BundleTemplate(
            id="dagster",
            title="Dagster minimal",
            description="Empty Dagster code location only (assets.py + manifest)",
            files=["manifest.json", "__init__.py", "assets.py"],
        ),
    ]


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


def _class_name(bundle_name: str) -> str:
    return "".join(part.capitalize() for part in bundle_name.split("_")) + "Scraper"


def _base_manifest(
    bundle_name: str,
    *,
    description: str,
    category: str,
    extractor_reqs: list[str],
    python_reqs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": bundle_name,
        "version": "0.1.0",
        "description": description,
        "category": category,
        "author": "DataHarbor",
        "engines": {"dataharbor": ">=1.0.0,<2.0.0"},
        "requirements": {
            "extractors": extractor_reqs,
            "python": python_reqs or [],
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


def _write_manifest(root: str, manifest: dict[str, Any]) -> None:
    _write(os.path.join(root, "manifest.json"), json.dumps(manifest, indent=2) + "\n")


def _write_init(root: str, bundle_name: str) -> None:
    _write(os.path.join(root, "__init__.py"), f'"""Bundle package: {bundle_name}."""\n')


def _write_assets_default(root: str, bundle_name: str) -> None:
    _write(
        os.path.join(root, "assets.py"),
        f'''"""Dagster definitions for bundle `{bundle_name}`."""
from dagster import Definitions

# Export jobs / schedules / asset_checks here. Core loads this as a separate code location.

defs = Definitions(
    assets=[],
    jobs=[],
    schedules=[],
    asset_checks=[],
)
''',
    )


def _write_assets_ml(root: str, bundle_name: str) -> None:
    _write(
        os.path.join(root, "assets.py"),
        f'''"""ML pipeline assets for bundle `{bundle_name}`."""
from dagster import Definitions, asset

# Platform ML helpers (optional): uv sync --extra ml
# from apps.ml.embeddings import generate_multimodal_embedding
# from apps.storage.s3 import upload_payload_to_s3


@asset(group_name="{bundle_name}", description="Load dataset from S3 and run training step")
def train_model() -> dict:
    """Replace with your train/eval/infer assets."""
    return {{"status": "stub", "bundle": "{bundle_name}"}}


defs = Definitions(assets=[train_model])
''',
    )


def _write_assets_etl(root: str, bundle_name: str) -> None:
    _write(
        os.path.join(root, "assets.py"),
        f'''"""ETL assets for bundle `{bundle_name}`."""
from dagster import Definitions, asset

from bundles.{bundle_name}.db import init_bundle_tables


@asset(group_name="{bundle_name}", description="Ensure PostgreSQL tables exist")
def init_schema() -> None:
    init_bundle_tables()


@asset(group_name="{bundle_name}", deps=[init_schema], description="Transform and load data")
def etl_run() -> dict:
    return {{"status": "stub", "bundle": "{bundle_name}"}}


defs = Definitions(assets=[init_schema, etl_run])
''',
    )


def _write_fetch(root: str, bundle_name: str) -> None:
    _write(
        os.path.join(root, "fetch.py"),
        f'''"""Fetch helpers for bundle `{bundle_name}` (owned by the bundle author)."""
from __future__ import annotations

from typing import Any, Dict

from apps.scraper.http_fetcher import HttpFetcher


def fetch_url(url: str, *, session_id: str | None = None) -> Dict[str, Any]:
    """Minimal HTTP fetch via Core HttpFetcher.

    For JS-rendered pages, implement browser fetch in this bundle and add
    e.g. ``"playwright>=1.41"`` to manifest ``requirements.python`` (not Core).
    """
    return HttpFetcher(session_id=session_id).fetch(url)
''',
    )


def _write_scraper(root: str, bundle_name: str) -> None:
    class_name = _class_name(bundle_name)
    _write(
        os.path.join(root, "scraper.py"),
        f'''"""Scraper scaffold for bundle `{bundle_name}`."""
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
''',
    )


def _write_db_items(root: str, bundle_name: str) -> None:
    _write(
        os.path.join(root, "db.py"),
        f'''"""Schema init scaffold for bundle `{bundle_name}`."""
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
''',
    )


def _write_db_ml(root: str, bundle_name: str) -> None:
    _write(
        os.path.join(root, "db.py"),
        f'''"""Model / run registry for ML bundle `{bundle_name}`."""
import logging

from apps.db.connection import get_db_cursor

logger = logging.getLogger(__name__)


def init_bundle_tables() -> None:
    """Create PostgreSQL tables for ML runs and artifact metadata."""
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS {bundle_name}_runs (
                id SERIAL PRIMARY KEY,
                run_id TEXT UNIQUE NOT NULL,
                model_name TEXT,
                metrics JSONB DEFAULT '{{}}'::jsonb,
                artifact_uri TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
    logger.info("Initialized ML registry tables for bundle '%s'", "{bundle_name}")
''',
    )


def _scaffold_default(root: str, bundle_name: str, manifest: dict[str, Any]) -> list[str]:
    _write_manifest(root, manifest)
    _write_init(root, bundle_name)
    _write_assets_default(root, bundle_name)
    _write_fetch(root, bundle_name)
    _write_scraper(root, bundle_name)
    _write_db_items(root, bundle_name)
    return ["manifest.json", "__init__.py", "assets.py", "fetch.py", "scraper.py", "db.py"]


def _scaffold_ml(root: str, bundle_name: str, manifest: dict[str, Any]) -> list[str]:
    _write_manifest(root, manifest)
    _write_init(root, bundle_name)
    _write_assets_ml(root, bundle_name)
    _write_db_ml(root, bundle_name)
    return ["manifest.json", "__init__.py", "assets.py", "db.py"]


def _scaffold_etl(root: str, bundle_name: str, manifest: dict[str, Any]) -> list[str]:
    _write_manifest(root, manifest)
    _write_init(root, bundle_name)
    _write_assets_etl(root, bundle_name)
    _write_db_items(root, bundle_name)
    return ["manifest.json", "__init__.py", "assets.py", "db.py"]


def _scaffold_dagster(root: str, bundle_name: str, manifest: dict[str, Any]) -> list[str]:
    _write_manifest(root, manifest)
    _write_init(root, bundle_name)
    _write_assets_default(root, bundle_name)
    return ["manifest.json", "__init__.py", "assets.py"]


_TEMPLATE_BUILDERS: dict[str, Callable[..., list[str]]] = {
    "default": _scaffold_default,
    "ml": _scaffold_ml,
    "etl": _scaffold_etl,
    "dagster": _scaffold_dagster,
}


def resolve_template(template: str | None) -> str:
    key = (template or DEFAULT_TEMPLATE).strip().lower()
    if key not in _TEMPLATE_BUILDERS:
        available = ", ".join(sorted(_TEMPLATE_BUILDERS))
        raise ValueError(f"Unknown template '{template}'. Choose one of: {available}")
    return key


def create_bundle(
    name: str,
    *,
    template: str = DEFAULT_TEMPLATE,
    description: str | None = None,
    category: str = "custom",
    extractors: list[str] | None = None,
    target_dir: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Create a bundle scaffold from a named template.

    Templates: default | ml | etl | dagster
    """
    bundle_name = _normalize_name(name)
    tpl = resolve_template(template)
    root = os.path.abspath(target_dir) if target_dir else os.path.join(BUNDLES_DIR, bundle_name)

    if os.path.exists(root):
        if not force:
            raise ValueError(
                f"Bundle path already exists: {root}. Use --force to overwrite."
            )
        import shutil

        shutil.rmtree(root)

    os.makedirs(root, exist_ok=True)

    tpl_meta = next(t for t in list_bundle_templates() if t.id == tpl)
    desc = description or f"{tpl_meta.title} bundle scaffold for {bundle_name}"
    extractor_reqs = list(extractors or [])

    python_reqs: list[str] = []
    if tpl == "ml":
        python_reqs = ["polars>=1.0"]
        category = category if category != "custom" else "ml"
    elif tpl == "etl":
        category = category if category != "custom" else "etl"

    manifest = _base_manifest(
        bundle_name,
        description=desc,
        category=category,
        extractor_reqs=extractor_reqs,
        python_reqs=python_reqs,
    )

    files = _TEMPLATE_BUILDERS[tpl](root, bundle_name, manifest)

    is_valid, errors = BundleValidator(root).validate()
    if not is_valid:
        raise ValueError(
            "Scaffold created but failed validation:\n  - " + "\n  - ".join(errors)
        )

    return {
        "status": "success",
        "bundle_name": bundle_name,
        "template": tpl,
        "path": root,
        "files": files,
        "message": f"Bundle scaffold '{bundle_name}' ({tpl}) created at {root}",
    }
