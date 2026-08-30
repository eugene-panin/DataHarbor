---
name: dataharbor-remediator
description: Diagnose and repair DataHarbor scrapers/extractors using real HAP CLI plus harbor validate/health. Trigger when scrapers break, return zero rows, or when asked to repair a DataHarbor bundle.
---

# DataHarbor Scraper Remediation

Working protocol against the live Harbor Agent Protocol (HAP v1.0) in `apps/cli/commands/agent.py` and `apps/observability/ai_remediator.py`. Do not assume fields or commands that are not listed here.

Authoritative companion: `AGENTS.md` §3 (failure modes) and §5 (validate + dual-env DB).

Do **not** auto-commit. Do **not** treat import-only HAP test as a scrape success.

---

## What HAP actually returns

| Command | Real behavior |
|---------|----------------|
| `harbor agent-protocol status` | JSON array from `ScraperHealthChecker`. Per bundle: `HEALTHY` \| `DEGRADED` \| `CRITICAL`. **Not** `ZERO_ROWS`. Anomalies live in `issues` and metrics (`anomaly_runs` via DB). |
| `harbor agent-protocol diagnose <name>` | Last `scraper_execution_logs` row + first 600 chars of `scraper.py`. Fields: `protocol`, `bundle_exists`, `scraper_exists`, `declared_extractors`, `status`, `error_message`, `last_log` (`status`, `items_scraped`, `http_*_count`, `error_message`, `created_at`), `code_snippet`, `missing_fields`, `instruction`. **No** `failing_selectors`. **No** `html_sample`. |
| `harbor agent-protocol patch <name> --code-file <file>` | `ast.parse` then **overwrite entire** `bundles/<name>/scraper.py`. Will not patch extractors. Prefer surgical file edits in Cursor; use HAP patch only when you intend a full-file replace. |
| `harbor agent-protocol test <name>` | Import `bundles.<name>.scraper` only → `"status": "IMPORT_OK"`, `"live_scrape": false`. Exit 0. **Not a scrape proof.** |
| `harbor agent-protocol test <name> --url <url>` | One live `scrape(...)`. `"SUCCESS"` (items > 0), `"ZERO_ROWS"`, or `"FAILED"`. Non-success exits 1. Bundles without `scraper.py` (etl/ml/catalog) fail lookup — skip HAP test. |

Health `ZERO_ROWS` is a **log status**, not a `status` value in the health array.

---

## Step 1 — Health

```bash
harbor agent-protocol status
harbor health
```

Act on bundles with `DEGRADED` or `CRITICAL`, or `issues` mentioning zero-row / stdout errors. Confirm with `last_log.status` from diagnose (`ZERO_ROWS` / `FAILED` / `DEGRADED`).

---

## Step 2 — Diagnose (HAP + files + optional live HTML)

```bash
harbor agent-protocol diagnose <bundle_name>
```

Then read (do not skip):

1. `bundles/<name>/manifest.json` — extractors, python deps, observability.
2. `bundles/<name>/scraper.py` and `fetch.py` if present.
3. Declared `extractors/<id>/extractor.py` (selector drift usually lives here).
4. Last log fields from diagnose (`error_message`, `http_403_count`, `http_429_count`).

HAP does not store HTML. For Mode A, fetch one target page (or a saved SeaweedFS dump) yourself and inspect markup.

### Failure modes (`AGENTS.md`)

- **A — HTML selector drift:** log `ZERO_ROWS`, HTTP 200. Patch **extractor** selectors, not the whole bundle.
- **B — Access / rate limit:** `http_403_count` / `http_429_count`. Adjust bundle fetch, headers, concurrency, proxy (`PROXY_URL` / `PROXY_LIST`). Core has no Playwright.
- **C — Python exception:** traceback in `error_message` or Dagster stdout (`issues`). Minimal fix to contract/schema handling.

---

## Step 3 — Surgical patch

Change only the broken selectors, headers, or exception path. Do not rewrite `assets.py` / `db.py` unless the failure is there.

- Extractor parse bugs → edit `extractors/<id>/extractor.py`.
- Fetch/orchestration → `scraper.py` / `fetch.py`.
- Full-file HAP replace (only `scraper.py`):

```bash
harbor agent-protocol patch <bundle_name> --code-file /tmp/<bundle_name>_patch.py
```

If AST validation fails, fix the file and retry. If the bundle directory is missing, patch exits 1.

---

## Step 4 — Verify (required; stub-free)

```bash
harbor bundle validate
harbor bundle doctor <bundle_name>
PYTHONPATH=. pytest bundles/<bundle_name>/tests extractors/<id>/tests
harbor agent-protocol test <bundle_name> --url <same URL the scraper uses>
harbor health
```

- `IMPORT_OK` without `--url` is insufficient.
- `ZERO_ROWS` after `--url` means the fix did not work (or URL/extractor mismatch).
- If Compose is up and the bug was schema/Dagster: also `docker exec dataharbor_dagster python ...` against the container DB. Host CLI uses `.env` (`POSTGRES_PORT` often `54320`); the container uses `postgres:5432`.

Optional local smoke (same as scaffold `__main__`):

```bash
PYTHONPATH=. .venv/bin/python bundles/<bundle_name>/scraper.py
```

---

## Step 5 — Stop conditions

- Success: live `--url` test `"status": "SUCCESS"`, validate green, health no longer CRITICAL for this cause.
- Do not `git commit` unless the user asked.
- If rights, personal data, or ToS block fetching the target, stop and report `DISCOVERY_BLOCKED` / `REVIEW_REQUIRED` instead of patching around the policy.


---

---

## 🌐 Active Target Runtime Environment Context
> [!NOTE]
> DataHarbor runtime environment automatically detected by `harbor skill install`.
> **Active Environment:** `LOCAL_HOST` (Local Machine Host (Dev Execution))

Use `.env` as the host-CLI source of truth (`POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_DB`).
Detected bindings this install: postgres `127.0.0.1:5432`, ClickHouse `127.0.0.1:8123`.

| Service | Inside Compose network | Typical host publish |
|---------|------------------------|----------------------|
| PostgreSQL 16 + pgvector | `postgres:5432` | `127.0.0.1:54320` |
| ClickHouse | `clickhouse:8123` | `127.0.0.1:8123` |
| SeaweedFS S3 | `http://seaweedfs:8333` | `http://localhost:8334` |
| Qdrant | `http://qdrant:6333` | `http://localhost:6333` |
| Dagster UI | n/a | `http://localhost:3000` |
| Grafana | n/a | `http://127.0.0.1:3001` |

- **Core Notifier:** Telegram / Slack / `NOTIFY_WEBHOOK_URL` (n8n optional: `harbor up --with-n8n`)
- **Dagster DB verification:** when Compose is up, confirm schema/asset fixes with `docker exec dataharbor_dagster python ...` — do not assume the host CLI hits the same DB as the container.
