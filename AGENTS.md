# 🤖 DataHarbor AI Agent System Context & Remediation Protocol

This document serves as the authoritative context and architectural specification for AI Agents (Gemini, Claude, Antigravity, GPT-4) performing autonomous diagnosis, code generation, and auto-remediation across DataHarbor.

## 0. Skill routing (mandatory, agent-agnostic)

This section is the **canonical router for every agent** (Cursor, Codex, Claude Code, Gemini, Antigravity, etc.). Do not depend on `.cursor/rules` — that file is a Cursor-only projection of this table.

Load **one** skill from `.agents/skills/<name>/SKILL.md` and follow it. Do not mix designer + operator in the same pass.

| User asked to… | Skill | Do first |
|---|---|---|
| Create, design schema, or change bundle/extractor code | `dataharbor-bundle-designer` | Discovery. No `harbor bundle new` until approved. |
| Operate, monitor, health, SLA, results, duty | `dataharbor-bundle-operator` | `harbor agent-protocol summary` — no source files. |
| Repair a broken scraper / ZERO_ROWS / HTTP 403–429 | `dataharbor-remediator` | `summary` then `diagnose`; surgical patch. |

Vague «бандл» → one clarifying question (develop / operate / repair). Operator `action=REMEDIATE` → remediator. Never scaffold from operator/remediator.

Register skills into each product's user dir with `harbor skill install` (does not replace this file).

Plugin playbooks are **not** extra skills. If `bundles/<name>/AGENT.md` or `extractors/<id>/AGENT.md` exists, the active skill reads it when that plugin is in scope. Do not copy those files into `~/.claude/skills`.

---

## 🏛️ 1. Platform Architecture Overview

DataHarbor is an open-core data platform and multi-modal AI processing engine.

### Core Architecture (`apps/`):
1. **PostgreSQL 16 + pgvector (Port 5432):** Transactional storage, relational metadata, and SQL presentation views (`v_*`).
2. **ClickHouse OLAP Engine (Port 8123 / 9000):** High-throughput analytical warehouse for event rows and timeseries aggregations.
3. **Qdrant (Port 6333 / 6334):** Vector search store for embeddings and RAG workloads.
4. **SeaweedFS S3 Storage (Port 8334 / 9334 / 8888):** Object storage for video, audio, thumbnails, and raw HTML dumps (`dataharbor-raw` bucket).
5. **Dagster Webserver (Port 3000):** Asset-based ETL pipeline orchestrator for core and bundle assets.
6. **Core Notifier (`apps/notifications/`):** Thin multi-channel alerts (Telegram, Slack webhook, optional generic JSON webhooks). n8n is optional (`harbor up --with-n8n` / compose profile `n8n`).
7. **Observability Subsystem (`apps/observability/`):** Telemetry logger, zero-row anomaly detector, SLA staleness monitor, and AI Auto-Remediator.
8. **Optional ML (`apps/ml/`, extra `ml`):** Whisper / EasyOCR / embeddings / HDBSCAN — install with `uv sync --extra ml`. Not required for Core.
9. **Backup CLI (`harbor backup`):** Master backup/restore; stays in Core (uses S3 + DB helpers, no heavy ML deps).

**Env follows the running stack.** `.env` / `.env.example` list only default Compose services. Optional profiles do not get their own env files: `harbor up --compose --with-n8n` appends n8n keys to `.env` once. Alerts, proxies, remediator, and bundle `requirements.env` are also added to that same `.env` only when you use them.

### Bundles Architecture (`bundles/`):
Modular, self-contained business domains (a task or a pipeline of tasks). Each bundle resides in `bundles/<bundle_name>/` and contains:
* **`manifest.json` (Required):** Bundle passport — `name`, `version`, `description`, optional `engines.dataharbor` (PEP 440 specifier), `requirements.extractors` / `requirements.python` / `requirements.env`, `entrypoints.dagster` (e.g. `assets:defs`; `entrypoints.celery` must be `null`), observability thresholds.
  Declare required resource extractors under `requirements.extractors` as:
  * local id: `"demo_site"`
  * private/public git URL: `"git@github.com:acme/dh-extractor-example.git"`
  * explicit object: `{"name": "example", "source": "https://github.com/acme/dh-extractor-example.git"}`
  Bundle itself is installed via CLI: `harbor bundle install <bundle-git-url>` — platform then auto-pulls declared extractor sources into `extractors/`. **Security:** installing a bundle clones and then imports/executes its Python (`assets.py`, `scraper.py`, `db.py`, …) — only install bundles from sources you trust, the same way you'd trust a package before running `pip install`.
  Declare extra env vars under `requirements.env` as `"FOO_API_KEY"` or `{"name":"FOO_API_KEY","required":true,"description":"..."}`. Secrets stay in repo-root `.env` (never in the bundle git). `harbor bundle install` prints the list; `harbor bundle doctor` fails if a required name is unset. Missing keys do **not** fail `harbor bundle validate` (install would otherwise roll back).
* **`AGENT.md` (Recommended):** Short domain playbook for agents (what to ingest, operate, env). Not a platform skill — do not `harbor skill install` it. Designer/operator/remediator read it when this bundle is in scope.
* **`scraper.py` / `fetch.py` (Optional):** Fetch + orchestration owned by the bundle author. Core provides thin `HttpFetcher` only.
* **`db.py` (Optional):** PostgreSQL tables/views & ClickHouse `MergeTree` schema initialization.
* **`exporter.py` (Optional):** Presentation View Layer — interactive HTML/JS domain dossier report generator combining PostgreSQL relational entities, ClickHouse OLAP telemetry, and SeaweedFS media assets (`harbor bundle export <bundle_name>` / `harbor bundle view <bundle_name>`).
* **`tests/` (Recommended):** Plugin tests co-located with the bundle (`tests/test_*.py`). Created by `harbor bundle new`. Run locally: `PYTHONPATH=. pytest bundles/<name>/tests`. Not committed in open-core (private git repos).
* **`grafana/` (Optional):** Dashboard JSON exports for Grafana (`grafana/*.json`). Picked up locally via Compose mount into `apps/observability/grafana/.../bundles/`.

### Extractors Architecture (`extractors/`):
Separately distributed parse adapters for a single content source. Reused by multiple bundles. Users keep custom extractors in private repos; the platform clones them on demand. Each extractor resides in `extractors/<extractor_id>/` and contains:
* **`manifest.json` (Required):** Passport with `name`, `version`, `description`, `domains`, `entrypoint` (`extractor:parse`).
* **`extractor.py` (Required):** `parse(html, source_url) -> list[dict]` and optional `generate_page_urls(base_url, max_pages)`. Extractors MUST NOT perform HTTP, proxy rotation, or browser control — only parse already-fetched content.
* **`AGENT.md` (Recommended):** Short parse playbook for agents. Not a platform skill.
* **`tests/` (Recommended):** Plugin tests co-located with the extractor. Created by `harbor extractor new`. Open-core CI runs only `extractors/demo_site/tests/`; private extractors run `pytest extractors/<id>/tests` in their own repo.

The open-core tree ships **`demo_site`** as a contract example. Domain-specific extractors and business bundles are installed from private/public git remotes.

Install/pack via `harbor extractor install|pack|list|remove|validate|publish`. Resolve from an installed bundle via `harbor extractor resolve <bundle>` / `harbor bundle resolve <bundle>`. Platform discovery is dynamic through `apps.scraper.extractors.registry`.

Publish flow (`harbor bundle|extractor publish <name>`):
* Validates the plugin, copies a clean snapshot to a **temporary** staging dir (or `--workdir` for a permanent checkout).
* Does **not** create nested `.git` inside the DataHarbor monorepo workspace.
* Pushes with `--remote <url>`, or auto-creates a **private** GitHub repo via `gh` when authenticated.
* `git` identity (`user.name` / `user.email`) is required to commit; `gh` is optional.
* Bundle publish **never auto-publishes extractors**. If `requirements.extractors` still lists local ids/paths (not git URLs), CLI lists them and suggests `harbor extractor publish <id>` (real publish stops; `--dry-run` warns; escape hatch `--allow-local-extractors`). Shipped example id `demo_site` is ignored.

---

## 🛠️ 2. Scraper Design Guidelines

All scrapers in `bundles/<bundle_name>/scraper.py` SHOULD follow these guidelines:
1. **HTTP fetch:** Prefer platform `HttpFetcher` (`apps.scraper.http_fetcher`) for simple pages.
2. **JS / browser fetch:** Owned entirely by the bundle (Playwright, curl_cffi, etc.). Declare deps in `manifest.json` → `requirements.python`. Core does **not** ship Playwright.
3. **Optional egress proxy:** Read `PROXY_URL` / `PROXY_LIST`, or use `proxy_manager.get_http_proxies()` / `get_browser_proxy()`.
4. **Structured Metrics Logging:** Wrap main scrape loop with `apps.observability.metrics.record_scraper_execution(...)`.
5. **Zero-Row Detection:** If 0 items are parsed, return `status="ZERO_ROWS"` so Observability can trigger AI Auto-Remediation.

Fetch strategy (headers, browsers, proxies, retries) is owned by the bundle author. Core only provides thin HTTP helpers and contracts.

---

## 🚨 3. AI Auto-Remediation Protocol (Scraper Failure Diagnosis)

When a scraper breaks or degrades, the AI Agent must follow this 4-step protocol:

### Step 1: Diagnose Failure Mode
* **Mode A: HTML Selector Drift (`ZERO_ROWS` status):** Target markup changed (CSS classes / DOM).
* **Mode B: Access / Rate Limit (`HTTP 403` / `HTTP 429`):** Adjust concurrency, egress, or fetch strategy in the bundle; inspect response headers/body.
* **Mode C: Python Exception (Syntax/Attribute/KeyError):** Broken API schema contract. Inspect exact traceback.

### Step 2: Extract Diagnostic Context
Fetch:
1. Bundle `manifest.json` and current `scraper.py` source code.
2. Last execution log from PostgreSQL `scraper_execution_logs`.
3. Raw HTML snippet or HTTP response headers captured during failure.

### Step 3: Propose Minimal Code Patch
AI Agent MUST NOT rewrite the entire codebase. Apply minimal, surgical edits targeting only broken CSS selectors, headers, or exception handling.

### Step 4: Validate Fix
Run:
```bash
PYTHONPATH=. .venv/bin/python bundles/<bundle_name>/scraper.py
harbor bundle validate
harbor health
```

---

## 📄 4. Core File Map for AI Agents

* `apps/cli/main.py` — Master `harbor` Typer CLI entrypoint (`uv` + `[project.scripts]`).
* `apps/cli/commands/` — Command groups: platform, bundle, extractor, backup, skill, agent-protocol.
* `apps/db/clickhouse_client.py` — ClickHouse OLAP connection helper.
* `apps/db/qdrant_client.py` — Qdrant vector store helper.
* `apps/db/connection.py` — PostgreSQL connection helper.
* `apps/observability/metrics.py` — Telemetry logger.
* `apps/observability/health_checker.py` — Anomaly detection engine.
* `apps/observability/alerts.py` — Observability alert messages via Core notifier.
* `apps/notifications/notifier.py` — Thin Telegram / Slack / webhook fan-out (n8n optional).
* `apps/scraper/extractor_api.py` — Extractor plugin contract helpers.
* `apps/scraper/extractors/registry.py` — Dynamic discovery of installed extractors.
* `apps/dagster_app/workspace_builder.py` — Generate multi code-location `workspace.yaml` (core + one location per bundle). Named profiles: `apps/dagster_app/workspace_profiles.yaml` → `harbor workspace refresh --name store_intel` → `workspaces/<name>.yaml`. Run with `DAGSTER_WORKSPACE_NAME=store_intel` (compose/env) → UI http://localhost:3000.
* `apps/dagster_app/run_dev.py` — Refresh selected workspace profile and start `dagster dev -w …`.
* `apps/bundle/` — bundle runtime (install, validate, scaffold, Dagster discovery): `loader.py`, `validator.py`, `distributor.py`, `doctor.py`, `scaffold.py`, `plugin_contract.py`.
* `bundles/<name>/` — installed business bundles only (local/private by default).
* `apps/extractor/` — extractor runtime (install, validate, scaffold, bundle resolution): `validator.py`, `distributor.py`, `requirements.py`, `scaffold.py`.
* `extractors/<id>/` — installed extractor plugins (`demo_site` ships in open-core).
* `apps/crawl/` — optional Common Crawl toolkit (`uv sync --extra crawl`): CDX HTTPS index, columnar Parquet via HTTPS path-manifest, WARC range fetch. Prefer CDX for URL patterns; Parquet for analytical SQL samples (`COMMONCRAWL_INDEX_MAX_SHARDS`).
---

## ⚖️ 5. Strict Verification & Compliance Protocol for AI Agents

1. **Comprehensive Bundle Verification Rule:** Before answering affirmative compliance questions (e.g. "Does bundle X conform to format Y?"), the AI Agent MUST inspect ALL 4 core bundle files (`manifest.json`, `scraper.py`, `assets.py`, `db.py`) and run `harbor bundle validate`. Never state compliance based on partial file views.
2. **Automated Cross-Validation Enforcement:** The `harbor bundle validate` CLI tool (`apps/bundle/validator.py`) verifies that every entry in `manifest.json` `requirements.extractors` (local id, git URL, or `{name,source}` object) resolves to an installed valid extractor under `extractors/`. It also fails when `scraper.py` calls `get_extractor("id")` / `require_extractor("id")` for an undeclared id. `harbor bundle install <url>` auto-resolves extractor sources before validation.
3. **Dual Environment Database Verification Rule (Host CLI vs Docker Container DB):** DataHarbor PostgreSQL uses `dbname="postgres"` when executing CLI commands on local host, but uses `dbname="dataharbor"` when executing inside Docker containers (`dataharbor_dagster`). When diagnosing or fixing database errors, schema updates, or Dagster asset failures, the AI Agent MUST run empirical verification tests BOTH on the host CLI AND inside the running Docker container (`docker exec dataharbor_dagster python ...`). Never declare a Dagster or database fix complete without verifying the active container database state.
4. **Test placement rule:** Platform/runtime tests live in repo-root `tests/` (pytest `testpaths`). Bundle and extractor business tests live in `bundles/<name>/tests/` and `extractors/<id>/tests/` inside each plugin repo — never in open-core `tests/` except scaffolding smoke tests for `apps/bundle` / `apps/extractor`.
