---
name: dataharbor-bundle-designer
description: Authoritative architecture, schema, and implementation guide for designing and building DataHarbor modular domain bundles. Trigger whenever asked to create a new bundle, design a bundle schema, or modify an existing DataHarbor bundle.
---

# 📦 DataHarbor Bundle Designer Skill

This skill provides comprehensive architectural guidelines, file structures, and code standards for designing and implementing high-quality, modular business domain bundles in DataHarbor.

---

## 🏛️ 1. Bundle Directory Structure

Every bundle resides in `bundles/<bundle_name>/`. All entrypoints are auto-discovered by DataHarbor Core:

```text
bundles/<bundle_name>/
├── manifest.json       # [REQUIRED] Passport: engines, requirements, entrypoints, observability
├── assets.py           # [RECOMMENDED] Export `defs = Definitions(...)` (merged by Core)
├── fetch.py            # [OPTIONAL] Bundle-owned fetch helpers
├── scraper.py          # [OPTIONAL] Fetch + orchestration
├── db.py               # [OPTIONAL] PostgreSQL (pgvector) & ClickHouse OLAP schema init
└── exporter.py         # [OPTIONAL] HTML/CSV dataset report generator
```

---

## 🧱 1b. Scaffold templates (`harbor bundle new --template`)

| Template | Use case | Files |
|----------|----------|-------|
| `default` | Ingest: fetch → scrape → store → Dagster | manifest, assets, fetch, scraper, db |
| `ml` | Train/RAG from S3; no scrape | manifest, assets, db (run registry) |
| `etl` | Transform/load only (data already in platform) | manifest, assets, db |
| `dagster` | Minimal code location (assets only) | manifest, assets |

```bash
harbor bundle templates
harbor bundle new my_leads --template default --extractors demo_site
harbor bundle new my_ml --template ml
```

---

## 📋 2. Mandatory File Specs & Code Templates

### A. Manifest File (`manifest.json`)
The `manifest.json` file is the bundle passport. It defines observability thresholds used by the health checker:

```json
{
  "name": "my_domain_bundle",
  "version": "1.0.0",
  "description": "High-throughput scraper and analytical pipeline for target domain data",
  "category": "Market Intelligence",
  "author": "DataHarbor Team",
  "engines": { "dataharbor": ">=1.0.0,<2.0.0" },
  "requirements": {
    "extractors": [],
    "python": []
  },
  "entrypoints": {
    "dagster": "assets:defs",
    "celery": null
  },
  "observability": {
    "staleness_sla_hours": 12,
    "anomaly_threshold_ratio": 0.3
  }
}
```

---

### B. Database Schema (`db.py`)
Must initialize PostgreSQL tables (with `pgvector` 512D embeddings if applicable) and ClickHouse `MergeTree` OLAP tables for high-speed analytics:

```python
import logging
from apps.db.connection import get_db_cursor
from apps.db.clickhouse_client import get_clickhouse_client

logger = logging.getLogger(__name__)

def init_bundle_tables():
    """Initializes PostgreSQL OLTP and ClickHouse OLAP tables for the bundle."""
    # 1. PostgreSQL Schema
    with get_db_cursor(commit=True) as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS my_domain_items (
                id SERIAL PRIMARY KEY,
                item_title VARCHAR(255) NOT NULL,
                url TEXT UNIQUE NOT NULL,
                vector_embedding vector(512),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)

    # 2. ClickHouse OLAP Schema
    ch_client = get_clickhouse_client()
    if ch_client:
        ch_client.command("""
            CREATE TABLE IF NOT EXISTS clickhouse_my_domain_analytics (
                item_id UInt64,
                title String,
                created_at DateTime DEFAULT now()
            ) ENGINE = MergeTree()
            ORDER BY (created_at, item_id);
        """)
```

---

### C. Scraper (`scraper.py`)
Scrapers SHOULD:
1. Fetch content (Core `HttpFetcher` for simple HTTP; JS/browser fetch is bundle-owned — declare Playwright etc. in `requirements.python`).
2. Parse via installed extractors when applicable.
3. Optionally use egress via `.env` (`PROXY_URL` / `PROXY_LIST`).
4. Log metrics via `apps.observability.metrics.record_scraper_execution()`.

How a bundle fetches is up to its author; Core does not prescribe or restrict fetch technique.

```python
import logging
from typing import List, Dict, Any
from apps.scraper.http_fetcher import HttpFetcher
from apps.observability.metrics import record_scraper_execution

logger = logging.getLogger(__name__)

class MyDomainScraper:
    def __init__(self):
        self.fetcher = HttpFetcher()

    def scrape(self) -> List[Dict[str, Any]]:
        target_url = "https://example.com/data"
        res = self.fetcher.fetch(target_url)
        items = []

        if res.get("status") == 200:
            # Parse HTML / JSON items here
            items = [{"title": "Sample Item"}]

        status = "SUCCESS" if items else "ZERO_ROWS"
        record_scraper_execution(
            bundle_name="my_domain_bundle",
            status=status,
            items_scraped=len(items),
            http_200_count=1 if res.get("status") == 200 else 0,
            http_403_count=1 if res.get("status") == 403 else 0
        )
        return items
```

---

### D. Dagster Assets, Partitions & Data Quality Checks (`assets.py`)
All bundle asset declarations MUST:
1. Use a **human-readable group name** (e.g. `group_name="my_pipeline"`).
2. Include stage tags and markdown descriptions (`description="[1/3] 🚢 Scrape -> S3"`).
3. **MANDATORY PARTITIONING:** Define `partitions_def` using `StaticPartitionsDefinition` (by category/domain subtype) or `DailyPartitionsDefinition` (by date), allowing single-partition re-runs in Dagster UI.
4. **MANDATORY REAL-TIME LOGGING & LIVE UI OBSERVATIONS:** Emit `context.log.info()` per page/batch iteration and yield `AssetObservation` metadata events so Dagster UI streams real-time progress and live item counts without black-box delays.
5. **MANDATORY ASSET CHECKS:** Include `@asset_check` Data Quality assertions for payload non-emptiness, PostgreSQL key uniqueness, and schema value range sanity:

```python
from dagster import asset, asset_check, AssetCheckResult, AssetCheckSeverity, Config, Output, MetadataValue, StaticPartitionsDefinition, AssetExecutionContext, AssetObservation
from apps.db.connection import get_db_cursor

# 1. Define Static or Daily Partitions
my_category_partitions = StaticPartitionsDefinition(["category_a", "category_b", "category_c"])

@asset(
    group_name="my_domain_b2b",
    partitions_def=my_category_partitions,
    description="[1/2] 🚢 Scrape domain directory by category partition into raw S3 JSON"
)
def raw_my_domain_s3(context: AssetExecutionContext):
    target_category = context.partition_key if context.has_partition_key else None
    ...

@asset(
    group_name="my_domain_b2b",
    partitions_def=my_category_partitions,
    deps=[raw_my_domain_s3],
    description="[2/2] 💾 Ingest category partition S3 payload into PostgreSQL database"
)
def postgres_my_domain(context: AssetExecutionContext):
    target_category = context.partition_key if context.has_partition_key else None
    ...

# --- MANDATORY ASSET CHECKS (DATA QUALITY ASSERTIONS) ---

@asset_check(asset=raw_my_domain_s3, description="Verifies S3 payload is not empty")
def check_raw_my_domain_non_empty():
    # Verify count > 0 in S3
    ...
    return AssetCheckResult(passed=True, metadata={"items_count": 100})

@asset_check(asset=postgres_my_domain, description="Verifies PostgreSQL domain uniqueness")
def check_postgres_my_domain_uniqueness():
    # Check no duplicate URLs in Postgres
    ...
    return AssetCheckResult(passed=True, metadata={"duplicate_count": 0})
```

---

## 🛠️ 3. Bundle Validation & Packaging Guidelines

After creating or editing a bundle, ALWAYS run:
```bash
# 1. Validate bundle manifest and schema integrity
harbor bundle validate

# 2. Audit scraper health status
harbor health

# 3. Pack bundle for distribution
harbor bundle pack <bundle_name>
```


---

---

---

---

---

---

## 🌐 Active Target Runtime Environment Context
> [!NOTE]
> DataHarbor runtime environment automatically detected by `harbor skill install`.
> **Active Environment:** `DOCKER_COMPOSE` (Docker Compose Microservices Stack)

- **PostgreSQL 16 (OLTP & pgvector):** `postgres (Port 5432)`
- **ClickHouse (OLAP Analytics):** `clickhouse (Port 8123)`
- **SeaweedFS S3 Storage:** `http://seaweedfs:8333`
- **Dagster UI Dashboard:** `http://localhost:3000`
- **Core Notifier:** Telegram / Slack / `NOTIFY_WEBHOOK_URL` (n8n optional: `harbor up --with-n8n`)
