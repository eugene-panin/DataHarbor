"""Scaffold generator for new DataHarbor bundles (multi-template)."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from apps.bundle.paths import BUNDLES_DIR
from apps.bundle.validator import BundleValidator

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
            files=["manifest.json", "AGENT.md", "__init__.py", "assets.py", "fetch.py", "scraper.py", "db.py"],
        ),
        BundleTemplate(
            id="ml",
            title="ML / RAG",
            description="Dagster assets + model registry db; no scrape (datasets on S3 / Qdrant)",
            files=["manifest.json", "AGENT.md", "__init__.py", "assets.py", "db.py"],
        ),
        BundleTemplate(
            id="etl",
            title="ETL only",
            description="Dagster assets + Postgres schema; no fetch/scrape (data already in platform)",
            files=["manifest.json", "AGENT.md", "__init__.py", "assets.py", "db.py"],
        ),
        BundleTemplate(
            id="dagster",
            title="Dagster minimal",
            description="Empty Dagster code location only (assets.py + manifest)",
            files=["manifest.json", "AGENT.md", "__init__.py", "assets.py"],
        ),
        BundleTemplate(
            id="catalog",
            title="E-commerce catalog ops",
            description=(
                "Supplier feed ingest (DuckDB audit), Polars transform, fuzzy dedupe, "
                "GTIN/price QA, CSV/API export — library deps only, no extra Docker services"
            ),
            files=[
                "manifest.json",
                "AGENT.md",
                "__init__.py",
                "assets.py",
                "db.py",
                "ingest.py",
                "transform.py",
                "match.py",
                "validate.py",
                "export.py",
                "quarantine.py",
                "dogs/__init__.py",
                "dogs/base.py",
                "dogs/gtin_dog.py",
                "dogs/brand_dog.py",
                "dogs/color_dog.py",
                "dogs/category_dog.py",
                "dogs/price_dog.py",
            ],
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
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _write_agent_md(root: str, bundle_name: str) -> None:
    """Domain playbook for agents. Not a platform skill — do not copy to ~/.claude/skills."""
    _write(
        os.path.join(root, "AGENT.md"),
        f"""# {bundle_name} — agent playbook

Not a platform skill. Use `dataharbor-bundle-designer` / `operator` / `remediator`.
Read this file when the user names this bundle.

## What it is

TODO: one paragraph — domain, consumers, grain (one row per what).

## Operate

```bash
harbor agent-protocol summary {bundle_name}
```

Useful paths: `manifest.json`, `sources.json` if present. Do not read `scraper.py` on duty unless remediator.

## Env

Declare extra keys in `manifest.json` → `requirements.env`. User adds them to repo-root `.env`.
""",
    )


def _write_plugin_tests(root: str, bundle_name: str) -> list[str]:
    """Co-located pytest scaffold — travels with the plugin on publish."""
    tests_dir = os.path.join(root, "tests")
    _write(os.path.join(tests_dir, "__init__.py"), '"""Bundle plugin tests."""\n')
    _write(
        os.path.join(tests_dir, "test_plugin.py"),
        f'''"""Tests for `{bundle_name}` bundle (co-located with the plugin)."""
from __future__ import annotations

from pathlib import Path

from apps.bundle.validator import BundleValidator

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def test_bundle_validates():
    is_valid, errors = BundleValidator(str(PLUGIN_ROOT)).validate()
    assert is_valid, errors
''',
    )
    return ["tests/__init__.py", "tests/test_plugin.py"]


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
            "env": [],
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


CATALOG_PYTHON_REQS = [
    "duckdb>=1.0",
    "polars>=1.0",
    "rapidfuzz>=3.0",
    "python-stdnum>=1.19",
    "openpyxl>=3.1",
]


def _write_db_catalog(root: str, bundle_name: str) -> None:
    _write(
        os.path.join(root, "db.py"),
        f'''"""PostgreSQL staging schema for catalog bundle `{bundle_name}`."""
from __future__ import annotations

import logging

from apps.db.connection import get_db_cursor

logger = logging.getLogger(__name__)


def init_bundle_tables() -> None:
    """Create catalog staging tables (canonical product model)."""
    with get_db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS {bundle_name}_import_runs (
                id SERIAL PRIMARY KEY,
                source_path TEXT NOT NULL,
                row_count INT DEFAULT 0,
                qa_passed INT DEFAULT 0,
                qa_failed INT DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS {bundle_name}_products_staging (
                id SERIAL PRIMARY KEY,
                import_run_id INT REFERENCES {bundle_name}_import_runs(id),
                sku TEXT,
                gtin TEXT,
                brand TEXT,
                title TEXT,
                category TEXT,
                price NUMERIC(12, 2),
                stock INT,
                parent_sku TEXT,
                variant_key TEXT,
                payload JSONB DEFAULT '{{}}'::jsonb,
                row_hash TEXT,
                qa_status TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (import_run_id, sku)
            );
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS {bundle_name}_qa_issues (
                id SERIAL PRIMARY KEY,
                import_run_id INT REFERENCES {bundle_name}_import_runs(id),
                sku TEXT,
                field TEXT,
                severity TEXT,
                message TEXT,
                raw_value TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            """
        )
    logger.info("Initialized catalog staging tables for bundle '%s'", "{bundle_name}")
''',
    )


def _write_ingest(root: str, bundle_name: str) -> None:
    _write(
        os.path.join(root, "ingest.py"),
        '''"""Fast file ingest + SQL audit via DuckDB (in-process library, not a service)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def audit_supplier_file(path: str | Path) -> dict[str, Any]:
    """Profile CSV/JSON/Parquet with DuckDB before heavy transforms.

    Requires: ``uv sync --extra analytics`` (or manifest ``requirements.python``).
    XLSX: convert with openpyxl/polars first, or pre-export to CSV.
    """
    from apps.analytics import require_analytics

    require_analytics("duckdb")

    import duckdb

    src = Path(path)
    if not src.exists():
        raise FileNotFoundError(src)

    con = duckdb.connect(database=":memory:")
    suffix = src.suffix.lower()
    if suffix == ".csv":
        con.execute("CREATE TABLE raw AS SELECT * FROM read_csv_auto(?)", [str(src)])
    elif suffix == ".json":
        con.execute("CREATE TABLE raw AS SELECT * FROM read_json_auto(?)", [str(src)])
    elif suffix in {".parquet", ".pq"}:
        con.execute("CREATE TABLE raw AS SELECT * FROM read_parquet(?)", [str(src)])
    else:
        raise ValueError(f"Unsupported ingest format: {suffix} (use csv/json/parquet or convert xlsx)")

    row_count = con.execute("SELECT COUNT(*) FROM raw").fetchone()[0]
    columns = [r[0] for r in con.execute("DESCRIBE raw").fetchall()]
    null_counts = {
        col: con.execute(f"SELECT COUNT(*) FROM raw WHERE {col} IS NULL").fetchone()[0]
        for col in columns[:20]
    }
    report = {
        "path": str(src),
        "row_count": row_count,
        "columns": columns,
        "null_counts_sample": null_counts,
    }
    con.close()
    return report


def write_audit_report(path: str | Path, report: dict[str, Any], out: str | Path) -> None:
    Path(out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
''',
    )


def _write_transform(root: str, bundle_name: str) -> None:
    _write(
        os.path.join(root, "transform.py"),
        '''"""Polars cleaning and normalization (in-process library)."""
from __future__ import annotations

from typing import Any


def normalize_supplier_frame(path: str) -> Any:
    """Load CSV and apply baseline catalog normalizations.

    Returns a Polars DataFrame. Extend with your supplier-specific rules.
    """
    from apps.analytics import require_analytics

    require_analytics("polars")

    import polars as pl

    df = pl.read_csv(path)
    exprs = []
    for col in ("sku", "gtin", "brand", "title", "category", "parent_sku"):
        if col in df.columns:
            exprs.append(pl.col(col).cast(pl.Utf8).str.strip_chars().alias(col))
    if "price" in df.columns:
        exprs.append(pl.col("price").cast(pl.Float64, strict=False).alias("price"))
    if "stock" in df.columns:
        exprs.append(pl.col("stock").cast(pl.Int64, strict=False).fill_null(0).alias("stock"))
    if exprs:
        df = df.with_columns(exprs)
    return df
''',
    )


def _write_match(root: str, bundle_name: str) -> None:
    _write(
        os.path.join(root, "match.py"),
        '''"""Fuzzy dedupe and dictionary mapping via RapidFuzz + regex."""
from __future__ import annotations

from typing import Any


def fuzzy_dedupe_brands(values: list[str], *, threshold: int = 90) -> dict[str, str]:
    """Map raw brand strings to a canonical label using RapidFuzz token_sort_ratio."""
    from apps.analytics import require_analytics

    require_analytics("rapidfuzz")

    from rapidfuzz import fuzz, process

    canonical: list[str] = []
    mapping: dict[str, str] = {}
    for raw in values:
        label = (raw or "").strip()
        if not label:
            continue
        if not canonical:
            canonical.append(label)
            mapping[raw] = label
            continue
        match = process.extractOne(label, canonical, scorer=fuzz.token_sort_ratio)
        if match and match[1] >= threshold:
            mapping[raw] = match[0]
        else:
            canonical.append(label)
            mapping[raw] = label
    return mapping


def apply_brand_map(frame: Any, brand_map: dict[str, str], *, column: str = "brand") -> Any:
    """Replace brand column using a precomputed mapping dict."""
    import polars as pl

    if column not in frame.columns:
        return frame
    return frame.with_columns(
        pl.col(column).replace(brand_map, default=None).fill_null(pl.col(column)).alias(column)
    )
''',
    )


def _write_validate_catalog(root: str, bundle_name: str) -> None:
    _write(
        os.path.join(root, "validate.py"),
        '''"""Hard validators: GTIN/EAN, price, stock, variant integrity."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class QaIssue:
    sku: str
    field: str
    severity: str
    message: str
    raw_value: str | None = None


def validate_gtin(value: str | None) -> QaIssue | None:
    if not value:
        return None
    from apps.analytics import require_analytics

    require_analytics("stdnum")
    from stdnum.ean import is_valid

    cleaned = "".join(ch for ch in str(value) if ch.isdigit())
    if not is_valid(cleaned):
        return QaIssue("", "gtin", "error", "Invalid GTIN/EAN checksum", str(value))
    return None


def validate_price(value: float | None) -> QaIssue | None:
    if value is None:
        return QaIssue("", "price", "warning", "Missing price", None)
    if value <= 0:
        return QaIssue("", "price", "error", "Price must be > 0", str(value))
    return None


def validate_stock(value: int | None) -> QaIssue | None:
    if value is None:
        return None
    if value < 0:
        return QaIssue("", "stock", "error", "Stock cannot be negative", str(value))
    return None


def validate_product_row(row: dict[str, Any]) -> list[QaIssue]:
    """Run all row-level validators; attach SKU for reporting."""
    sku = str(row.get("sku") or "")
    issues: list[QaIssue] = []
    for issue in (
        validate_gtin(row.get("gtin")),
        validate_price(row.get("price")),
        validate_stock(row.get("stock")),
    ):
        if issue:
            issue.sku = sku
            issues.append(issue)
    if not sku:
        issues.append(QaIssue("", "sku", "error", "SKU is required", None))
    return issues
''',
    )


def _write_catalog_dogs(root: str, bundle_name: str) -> list[str]:
    dogs_dir = os.path.join(root, "dogs")
    os.makedirs(dogs_dir, exist_ok=True)
    rel_files: list[str] = []

    _write(
        os.path.join(dogs_dir, "base.py"),
        '''"""Base types for specialized catalog \"dogs\" (small single-task models/rules)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DogResult:
    """One prediction from a specialized dog."""

    dog_id: str
    field: str
    value: Any
    confidence: float
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.value is not None and self.confidence > 0.0


class CatalogDog(ABC):
    """Small specialized worker: one field, one job."""

    dog_id: str
    field: str

    @abstractmethod
    def sniff(self, row: dict[str, Any]) -> DogResult:
        """Inspect one product row and return a typed prediction."""
''',
    )
    rel_files.append("dogs/base.py")

    _write(
        os.path.join(dogs_dir, "gtin_dog.py"),
        '''"""GTIN/EAN dog — checksum rules, no neural net."""
from __future__ import annotations

import re
from typing import Any

from bundles.''' + bundle_name + '''.dogs.base import CatalogDog, DogResult


class GtinDog(CatalogDog):
    dog_id = "gtin"
    field = "gtin"

    def sniff(self, row: dict[str, Any]) -> DogResult:
        raw = row.get("gtin") or row.get("ean") or ""
        digits = re.sub(r"\\D", "", str(raw))
        if not digits:
            return DogResult(self.dog_id, self.field, None, 0.0, "missing gtin")
        try:
            from stdnum.ean import is_valid

            if is_valid(digits):
                return DogResult(self.dog_id, self.field, digits, 1.0, "valid ean/gtin")
            return DogResult(self.dog_id, self.field, digits, 0.2, "invalid checksum")
        except ImportError:
            if len(digits) in (8, 12, 13, 14):
                return DogResult(self.dog_id, self.field, digits, 0.6, "format ok (stdnum not installed)")
            return DogResult(self.dog_id, self.field, None, 0.0, "bad length")
''',
    )
    rel_files.append("dogs/gtin_dog.py")

    _write(
        os.path.join(dogs_dir, "brand_dog.py"),
        '''"""Brand dog — dictionary + optional fuzzy match from title."""
from __future__ import annotations

from typing import Any

from bundles.''' + bundle_name + '''.dogs.base import CatalogDog, DogResult

# Extend with client-specific aliases (private bundle data/brands.csv).
BRAND_ALIASES: dict[str, str] = {
    "apple": "Apple",
    "samsung": "Samsung",
    "xiaomi": "Xiaomi",
}


class BrandDog(CatalogDog):
    dog_id = "brand"
    field = "brand"

    def sniff(self, row: dict[str, Any]) -> DogResult:
        current = (row.get("brand") or "").strip()
        if current:
            key = current.lower()
            if key in BRAND_ALIASES:
                return DogResult(self.dog_id, self.field, BRAND_ALIASES[key], 0.95, "alias map")
            return DogResult(self.dog_id, self.field, current, 0.85, "supplier brand kept")

        title = (row.get("title") or "").lower()
        for needle, canonical in BRAND_ALIASES.items():
            if needle in title:
                return DogResult(self.dog_id, self.field, canonical, 0.75, "found in title")
        return DogResult(self.dog_id, self.field, None, 0.0, "brand unknown")
''',
    )
    rel_files.append("dogs/brand_dog.py")

    _write(
        os.path.join(dogs_dir, "color_dog.py"),
        '''"""Color dog — regex on title/description (swap for tiny NER/ONNX later)."""
from __future__ import annotations

import re
from typing import Any

from bundles.''' + bundle_name + '''.dogs.base import CatalogDog, DogResult

COLOR_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\\b(black|чёрн|черн)\\b", re.I), "Black"),
    (re.compile(r"\\b(white|бел)\\b", re.I), "White"),
    (re.compile(r"\\b(red|красн)\\b", re.I), "Red"),
    (re.compile(r"\\b(blue|син|голуб)\\b", re.I), "Blue"),
]


class ColorDog(CatalogDog):
    dog_id = "color"
    field = "color"

    def sniff(self, row: dict[str, Any]) -> DogResult:
        if row.get("color"):
            return DogResult(self.dog_id, self.field, str(row["color"]).strip(), 0.9, "already set")
        hay = f"{row.get('title') or ''} {row.get('description') or ''}"
        for pattern, label in COLOR_PATTERNS:
            if pattern.search(hay):
                return DogResult(self.dog_id, self.field, label, 0.8, "regex match")
        return DogResult(self.dog_id, self.field, None, 0.0, "color not found")
''',
    )
    rel_files.append("dogs/color_dog.py")

    _write(
        os.path.join(dogs_dir, "category_dog.py"),
        '''"""Category dog — keyword map now; plug ONNX classifier at predict()."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from bundles.''' + bundle_name + '''.dogs.base import CatalogDog, DogResult

# Replace with models/category_dog.onnx when you have a trained head.
ONNX_MODEL_PATH = Path(__file__).resolve().parent / "models" / "category_dog.onnx"

KEYWORD_CATEGORY: list[tuple[str, str]] = [
    ("phone case", "Accessories > Phone Cases"),
    ("charger", "Electronics > Chargers"),
    ("headphone", "Electronics > Audio"),
    ("shirt", "Apparel > Shirts"),
]


class CategoryDog(CatalogDog):
    dog_id = "category"
    field = "category"

    def sniff(self, row: dict[str, Any]) -> DogResult:
        if row.get("category"):
            return DogResult(self.dog_id, self.field, str(row["category"]).strip(), 0.9, "supplier category")

        onnx = self._predict_onnx(row)
        if onnx:
            return onnx

        title = (row.get("title") or "").lower()
        for needle, category in KEYWORD_CATEGORY:
            if needle in title:
                return DogResult(self.dog_id, self.field, category, 0.7, "keyword map")
        return DogResult(self.dog_id, self.field, None, 0.0, "category unknown")

    def _predict_onnx(self, row: dict[str, Any]) -> DogResult | None:
        if not ONNX_MODEL_PATH.exists():
            return None
        try:
            import numpy as np
            import onnxruntime as ort
        except ImportError:
            return DogResult(self.dog_id, self.field, None, 0.0, "onnxruntime not installed")

        # Stub: wire your vectorizer + ort session here.
        _ = ort  # placeholder until you add real inference
        _ = np
        return None
''',
    )
    rel_files.append("dogs/category_dog.py")

    _write(
        os.path.join(dogs_dir, "price_dog.py"),
        '''"""Price dog — sanity check (extend with category median outlier logic)."""
from __future__ import annotations

from typing import Any

from bundles.''' + bundle_name + '''.dogs.base import CatalogDog, DogResult


class PriceDog(CatalogDog):
    dog_id = "price"
    field = "price"

    def sniff(self, row: dict[str, Any]) -> DogResult:
        raw = row.get("price")
        if raw is None or raw == "":
            return DogResult(self.dog_id, self.field, None, 0.0, "missing price")
        try:
            price = float(raw)
        except (TypeError, ValueError):
            return DogResult(self.dog_id, self.field, None, 0.1, "not a number")
        if price <= 0:
            return DogResult(self.dog_id, self.field, price, 0.1, "price must be > 0")
        if price > 100_000:
            return DogResult(self.dog_id, self.field, price, 0.4, "suspiciously high")
        return DogResult(self.dog_id, self.field, price, 0.95, "price ok")
''',
    )
    rel_files.append("dogs/price_dog.py")

    _write(
        os.path.join(dogs_dir, "__init__.py"),
        f'''"""Army of small specialized catalog dogs for bundle `{bundle_name}`."""
from __future__ import annotations

import os
from typing import Any

from bundles.{bundle_name}.dogs.base import CatalogDog, DogResult
from bundles.{bundle_name}.dogs.brand_dog import BrandDog
from bundles.{bundle_name}.dogs.category_dog import CategoryDog
from bundles.{bundle_name}.dogs.color_dog import ColorDog
from bundles.{bundle_name}.dogs.gtin_dog import GtinDog
from bundles.{bundle_name}.dogs.price_dog import PriceDog

DEFAULT_CONFIDENCE_FLOOR = float(os.getenv("CATALOG_DOG_CONFIDENCE_FLOOR", "0.65"))

DEFAULT_DOGS: list[CatalogDog] = [
    GtinDog(),
    BrandDog(),
    ColorDog(),
    CategoryDog(),
    PriceDog(),
]


def run_all_dogs(row: dict[str, Any], dogs: list[CatalogDog] | None = None) -> list[DogResult]:
    """Run every registered dog on one product row."""
    pack = dogs if dogs is not None else DEFAULT_DOGS
    return [dog.sniff(row) for dog in pack]


def apply_dog_results(
    row: dict[str, Any],
    results: list[DogResult],
    *,
    confidence_floor: float | None = None,
) -> tuple[dict[str, Any], bool, list[DogResult]]:
    """Merge high-confidence dog outputs into row.

    Returns (enriched_row, quarantine?, low_confidence_results).
    """
    floor = confidence_floor if confidence_floor is not None else DEFAULT_CONFIDENCE_FLOOR
    enriched = dict(row)
    low_conf: list[DogResult] = []
    quarantine = False

    for res in results:
        if not res.ok:
            if res.message and res.confidence == 0.0:
                low_conf.append(res)
            continue
        if res.confidence < floor:
            low_conf.append(res)
            quarantine = True
            continue
        if enriched.get(res.field) in (None, ""):
            enriched[res.field] = res.value
        elif str(enriched.get(res.field)) != str(res.value) and res.confidence >= floor:
            low_conf.append(res)
            quarantine = True

    if not enriched.get("category") and not row.get("category"):
        quarantine = True

    return enriched, quarantine, low_conf
''',
    )
    rel_files.append("dogs/__init__.py")

    _write(
        os.path.join(root, "quarantine.py"),
        f'''"""Split catalog rows into clean vs quarantine using the dog pack."""
from __future__ import annotations

from typing import Any

from bundles.{bundle_name}.dogs import apply_dog_results, run_all_dogs


def process_rows_with_dogs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Run all dogs row-by-row; return enriched, quarantine, and stats."""
    clean: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    dog_stats: dict[str, int] = {{}}

    for row in rows:
        results = run_all_dogs(row)
        enriched, is_quarantine, _low = apply_dog_results(row, results)
        enriched["_dog_quarantine"] = is_quarantine
        for res in results:
            if res.ok:
                dog_stats[res.dog_id] = dog_stats.get(res.dog_id, 0) + 1
        if is_quarantine:
            quarantine.append(enriched)
        else:
            clean.append(enriched)

    return {{
        "clean_rows": clean,
        "quarantine_rows": quarantine,
        "clean_count": len(clean),
        "quarantine_count": len(quarantine),
        "dog_hits": dog_stats,
    }}
''',
    )
    rel_files.append("quarantine.py")
    return rel_files


def _write_export_catalog(root: str, bundle_name: str) -> None:
    _write(
        os.path.join(root, "export.py"),
        '''"""Export canonical catalog to CSV or push via channel API adapters."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def export_csv(frame: Any, out_path: str | Path) -> str:
    """Write Polars frame to CSV for manual QA or feed upload."""
    from apps.analytics import require_analytics

    require_analytics("polars")

    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    frame.write_csv(dest)
    return str(dest)


def push_to_channel_stub(frame: Any, *, channel: str = "woocommerce") -> dict[str, Any]:
    """Replace with WooCommerce / Shopify / Odoo API client in your private adapter."""
    return {
        "status": "stub",
        "channel": channel,
        "rows": frame.height if hasattr(frame, "height") else len(frame),
        "message": "Implement channel adapter in export.py or adapters/",
    }
''',
    )


def _write_assets_catalog(root: str, bundle_name: str) -> None:
    _write(
        os.path.join(root, "assets.py"),
        f'''"""Catalog operations pipeline for bundle `{bundle_name}`.

Libraries (DuckDB, Polars, RapidFuzz) run in-process inside Dagster ops —
not as separate Docker containers. Install once: ``uv sync --extra analytics``.

Optional enrichment: ``uv sync --extra ml`` for ONNX/LLM classification jobs.
"""
from __future__ import annotations

import os

from dagster import AssetCheckResult, Definitions, asset, asset_check

from bundles.{bundle_name}.db import init_bundle_tables
from bundles.{bundle_name}.export import export_csv
from bundles.{bundle_name}.ingest import audit_supplier_file
from bundles.{bundle_name}.transform import normalize_supplier_frame
from bundles.{bundle_name}.validate import validate_product_row


@asset(group_name="{bundle_name}", description="Ensure catalog staging tables exist")
def init_schema() -> None:
    init_bundle_tables()


@asset(
    group_name="{bundle_name}",
    deps=[init_schema],
    description="DuckDB audit of supplier file (profiling before transform)",
)
def ingest_audit() -> dict:
    feed = os.getenv("{bundle_name.upper()}_FEED_PATH", "scratch/supplier_feed.csv")
    return audit_supplier_file(feed)


@asset(
    group_name="{bundle_name}",
    deps=[ingest_audit],
    description="Polars normalize supplier feed",
)
def normalize_feed(ingest_audit: dict) -> dict:
    feed = ingest_audit["path"]
    frame = normalize_supplier_frame(feed)
    return {{"path": feed, "row_count": frame.height}}


@asset(
    group_name="{bundle_name}",
    deps=[normalize_feed],
    description="Run specialized dog pack (small models/rules) + quarantine low confidence",
)
def run_dog_pack(normalize_feed: dict) -> dict:
    from bundles.{bundle_name}.quarantine import process_rows_with_dogs

    feed = normalize_feed["path"]
    frame = normalize_supplier_frame(feed)
    pack = process_rows_with_dogs(frame.to_dicts())
    return {{
        "path": feed,
        "row_count": normalize_feed["row_count"],
        "clean_count": pack["clean_count"],
        "quarantine_count": pack["quarantine_count"],
        "dog_hits": pack["dog_hits"],
    }}


@asset(
    group_name="{bundle_name}",
    deps=[run_dog_pack],
    description="Hard validators on clean rows only",
)
def transform_and_validate(run_dog_pack: dict) -> dict:
    from bundles.{bundle_name}.quarantine import process_rows_with_dogs

    feed = run_dog_pack["path"]
    frame = normalize_supplier_frame(feed)
    pack = process_rows_with_dogs(frame.to_dicts())
    issues = []
    for row in pack["clean_rows"]:
        issues.extend(validate_product_row(row))
    return {{
        "path": feed,
        "row_count": run_dog_pack["row_count"],
        "clean_count": run_dog_pack["clean_count"],
        "quarantine_count": run_dog_pack["quarantine_count"],
        "dog_hits": run_dog_pack["dog_hits"],
        "qa_errors": sum(1 for i in issues if i.severity == "error"),
        "qa_warnings": sum(1 for i in issues if i.severity == "warning"),
    }}


@asset(
    group_name="{bundle_name}",
    deps=[transform_and_validate],
    description="Export clean CSV; quarantine rows stay for manual QA",
)
def export_catalog(transform_and_validate: dict) -> dict:
    from bundles.{bundle_name}.quarantine import process_rows_with_dogs

    feed = transform_and_validate["path"]
    frame = normalize_supplier_frame(feed)
    pack = process_rows_with_dogs(frame.to_dicts())
    import polars as pl

    clean_frame = pl.DataFrame(pack["clean_rows"]) if pack["clean_rows"] else pl.DataFrame()
    out = export_csv(clean_frame, "exports/{bundle_name}_catalog.csv")
    if pack["quarantine_rows"]:
        export_csv(pl.DataFrame(pack["quarantine_rows"]), "exports/{bundle_name}_quarantine.csv")
    return {{"export_path": out, **transform_and_validate}}


@asset_check(asset=transform_and_validate, description="Block export when hard QA errors exist")
def check_qa_gate(result: dict) -> AssetCheckResult:
    errors = result.get("qa_errors", 0)
    passed = errors == 0
    return AssetCheckResult(
        passed=passed,
        metadata={{
            "qa_errors": errors,
            "qa_warnings": result.get("qa_warnings", 0),
            "quarantine_count": result.get("quarantine_count", 0),
        }},
        description="No GTIN/price/SKU errors" if passed else f"{{errors}} QA errors — fix before export",
    )


defs = Definitions(
    assets=[init_schema, ingest_audit, normalize_feed, run_dog_pack, transform_and_validate, export_catalog],
    asset_checks=[check_qa_gate],
)
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


def _scaffold_catalog(root: str, bundle_name: str, manifest: dict[str, Any]) -> list[str]:
    _write_manifest(root, manifest)
    _write_init(root, bundle_name)
    _write_db_catalog(root, bundle_name)
    _write_ingest(root, bundle_name)
    _write_transform(root, bundle_name)
    _write_match(root, bundle_name)
    _write_validate_catalog(root, bundle_name)
    _write_export_catalog(root, bundle_name)
    dog_files = _write_catalog_dogs(root, bundle_name)
    _write_assets_catalog(root, bundle_name)
    return [
        "manifest.json",
        "__init__.py",
        "assets.py",
        "db.py",
        "ingest.py",
        "transform.py",
        "match.py",
        "validate.py",
        "export.py",
        "quarantine.py",
        *dog_files,
    ]


_TEMPLATE_BUILDERS: dict[str, Callable[..., list[str]]] = {
    "default": _scaffold_default,
    "ml": _scaffold_ml,
    "etl": _scaffold_etl,
    "dagster": _scaffold_dagster,
    "catalog": _scaffold_catalog,
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

    Templates: default | ml | etl | dagster | catalog
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
    elif tpl == "catalog":
        python_reqs = list(CATALOG_PYTHON_REQS)
        category = category if category != "custom" else "catalog"

    manifest = _base_manifest(
        bundle_name,
        description=desc,
        category=category,
        extractor_reqs=extractor_reqs,
        python_reqs=python_reqs,
    )

    files = _TEMPLATE_BUILDERS[tpl](root, bundle_name, manifest)
    _write_agent_md(root, bundle_name)
    files.append("AGENT.md")
    files.extend(_write_plugin_tests(root, bundle_name))

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
