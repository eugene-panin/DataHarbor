---
name: dataharbor-bundle-designer
description: "Use when the user wants to create, write, scaffold, or design a DataHarbor bundle or its schema (RU: написать бандл, новый бандл, схема бандла, extractors). Also when changing existing bundle code. Do not use for health/monitor/results (operator) or scrape repair (remediator)."
---

# DataHarbor Bundle Designer

Working tool, not a wish-list. If this skill and the code disagree, trust the code:

Operate/monitor/results sessions: use `dataharbor-bundle-operator` (`harbor agent-protocol summary`), not this skill.

- `AGENTS.md`
- `apps/bundle/scaffold.py` — what `harbor bundle new` actually writes
- `apps/bundle/plugin_contract.py` — engines / entrypoints / Celery ban
- `apps/bundle/validator.py` — what `harbor bundle validate` fails on
- `apps/dagster_app/workspace_builder.py` — one Dagster code location per bundle
- `bundles/<name>/AGENT.md` — domain playbook if present (not a fourth skill)

Do not invent Celery workers, Core Playwright, `CurlScraper` impersonation, or Core merging all `assets.py` into one location.

---

## 0. Mandatory interactive discovery (hard gate)

Do not scaffold, edit `manifest.json`, write schemas/scrapers/assets, or run mutating Harbor commands until discovery is completed and the user explicitly approves the record. Read-only inspection of an existing bundle is allowed only to frame questions.

### Protocol

1. State that the bundle is in `DISCOVERY` and implementation is gated.
2. Ask **exactly one** single-focus question at a time, in the user's language. Do not show this question map, rounds, or a numbered form.
3. Wait. Acknowledge the answer in one sentence (record the fact, or mark `UNKNOWN` / `REVIEW_REQUIRED`).
4. If the answer is still ambiguous, ask one follow-up. Otherwise ask the next unanswered item.
5. Skip genuinely inapplicable prompts and record why. Bring source authorization, personal data, and external-action questions forward as soon as they matter.
6. After all applicable questions, return a **Bundle Discovery Record** and list blockers / assumptions.
7. Ask for explicit approval. Only unambiguous approval → `DISCOVERY_APPROVED`. Unresolved rights, personal-data handling, or untestable acceptance → stay `DISCOVERY_BLOCKED`.

### Question map (agent-only)

**Entry.** “What do you want to do with a DataHarbor bundle: create a new bundle, design its schema, or change an existing bundle?”

- New / schema: next ask for a short snake_case working name and domain description.
- Existing: next ask for name or path and the requested change; then read `bundles/<name>/AGENT.md` if present; then read-only inspect.

**Round 1 — outcome**

1. What decision or workflow does this change, and who consumes the output?
2. Smallest useful first release: primary entity, grain (one row per what?), required fields.
3. Explicitly out of scope.
4. Geography, languages, historical period, refresh cadence, expected volume.

**Round 2 — sources and safety**

5. Each source: canonical URL/API, access method, owner, credentials / payment / proxy.
6. What permits collection and use (API terms, licence, contract, written authorization)? Intended use and redistribution.
7. Personal data, credentials, regulated data, copyrighted content, rate limits? Minimization, retention, access, deletion.
8. External actions? Default is read-only collection. Contact, CRM writes, purchasing, publishing need separate authorization.

**Round 3 — pipeline**

9. Path raw → normalized → derived → output. Which fields need evidence URL, timestamp, or raw snapshot?
10. Components needed **now** from this set only: PostgreSQL, ClickHouse, SeaweedFS, Qdrant, Dagster, HttpFetcher/scraper, extractor plugin, exporter, Grafana. Mark the rest `NOT_NEEDED`. **Celery is not Core** (`entrypoints.celery` must be `null`). n8n is optional compose profile, not a bundle runtime.
11. Trigger (manual / schedule / event), concurrency, retry, idempotency, checkpoints, terminal states.
12. Which failures stop the run vs `ZERO_ROWS` / `FAILED` / `ENV_ERROR` / `REVIEW_REQUIRED`, and who reviews?

**Round 4 — quality**

13. Coverage, freshness, completeness, uniqueness, anomaly thresholds; what to report when missed.
14. How consumers get the result (tables, CSV/HTML export, Dagster UI, Grafana, alert) and who may access it.
15. Observability: `record_scraper_execution`, asset checks, alerts, log retention.
16. Acceptance scenarios: one successful run, one empty/partial, one recoverable failure.
17. Owner after release, SLA, deadline, budget, deploy environment (Compose vs host CLI).

### Bundle Discovery Record

```yaml
bundle_discovery:
  status: DISCOVERY | DISCOVERY_BLOCKED | DISCOVERY_APPROVED
  request:
    operation: CREATE | DESIGN_SCHEMA | MODIFY
    existing_bundle_path: <path_or_NOT_APPLICABLE>
    requested_change: <answer_or_NOT_APPLICABLE>
  bundle_name: <snake_case>
  outcome_and_consumer: <answer>
  first_release:
    entity_and_grain: <answer>
    required_fields: []
    out_of_scope: []
  scope:
    geography: <answer>
    languages: []
    historical_period: <answer>
    refresh_cadence: <answer>
    expected_volume: <answer>
  sources:
    - canonical_url_or_api: <answer>
      access_method: <answer>
      credentials_or_cost: <answer>
      permission_and_terms: <answer>
      intended_use_and_redistribution_rights: <answer>
  data_handling:
    sensitive_or_personal_data: <answer>
    minimization_and_retention: <answer>
    access_and_deletion: <answer>
  authorized_external_actions: <read_only_or_explicitly_authorized>
  pipeline:
    raw_normalized_derived_output: <answer>
    evidence_and_provenance: <answer>
    required_components: []
    trigger_and_execution_controls: <answer>
    failure_states_and_review_owner: <answer>
  delivery_and_access: <answer>
  quality_and_observability:
    acceptance_thresholds: <answer>
    metrics_alerts_and_retention: <answer>
  acceptance_scenarios: []
  ownership_and_constraints: <answer>
  assumptions: []
  blockers: []
  user_approval: <pending_or_approved>
```

---

## 1. How Core actually loads a bundle

- Bundles live in `bundles/<name>/` (Python identifier). Open-core ships **none**; install or scaffold them.
- `harbor workspace refresh` writes `apps/dagster_app/workspace.yaml`: location `core` plus `bundle_<name>` per valid bundle. Named profiles: `harbor workspace refresh --name <profile>` → `apps/dagster_app/workspaces/<name>.yaml`.
- Each bundle exports `defs = Definitions(...)` from the module in `entrypoints.dagster` (default `assets:defs`). Core does **not** merge all bundle assets into one location. An invalid bundle is skipped (unless `--strict`); it does not take down others.
- Fetch is bundle-owned. Core ships thin `HttpFetcher` (`apps.scraper.http_fetcher`). `CurlScraper` is a **compat alias** of `HttpFetcher` — no Chrome impersonation.
- Parse adapters are **extractors** under `extractors/<id>/`, not inlined as Core scrapers. Extractors must not perform HTTP.

---

## 2. Scaffold first — do not hand-roll the skeleton

```bash
harbor bundle templates
harbor bundle new <name> --template default|ml|etl|dagster|catalog [--extractors demo_site,other_id]
harbor extractor resolve <name>   # clone declared extractor sources
harbor bundle validate
harbor bundle doctor <name>
harbor workspace refresh
```

| Template | Use | Files Core actually writes |
|----------|-----|----------------------------|
| `default` | ingest: fetch → scrape → store | `manifest.json`, `__init__.py`, `assets.py`, `fetch.py`, `scraper.py`, `db.py`, `tests/` |
| `ml` | train/RAG from S3; no scrape | manifest, `__init__.py`, `assets.py`, `db.py`, `tests/` |
| `etl` | transform/load only | same as ml-style (no fetch/scraper) |
| `dagster` | empty code location | manifest, `__init__.py`, `assets.py`, `tests/` |
| `catalog` | feed ops (DuckDB/Polars/RapidFuzz) | + `ingest.py`, `transform.py`, `match.py`, `validate.py`, `export.py`, `quarantine.py`, `dogs/` |

Catalog extras: `uv sync --extra analytics`, `CATALOG_DOG_CONFIDENCE_FLOOR` (default 0.65). Low-confidence rows → `exports/<bundle>_quarantine.csv`.

Optional later: `exporter.py` (`harbor bundle export` / `view`), `grafana/*.json` (Compose mounts `bundles/` into Grafana).

`default` `assets.py` is an **empty** `Definitions(assets=[])`. Partitions and `@asset_check` are **recommended** for ingest pipelines, not enforced by the validator.

---

## 3. `manifest.json` — passport the validator actually reads

Required keys: `name`, `version`, `description`.

Scaffold defaults (follow these unless discovery says otherwise):

```json
{
  "name": "my_domain_bundle",
  "version": "0.1.0",
  "description": "...",
  "category": "custom",
  "author": "DataHarbor",
  "engines": { "dataharbor": ">=1.0.0,<2.0.0" },
  "requirements": {
    "extractors": [],
    "python": [],
    "env": [],
    "min_python_version": "3.10"
  },
  "entrypoints": {
    "dagster": "assets:defs",
    "celery": null
  },
  "observability": {
    "staleness_sla_hours": 24,
    "anomaly_threshold_ratio": 0.2
  }
}
```

- `engines.dataharbor`: PEP 440 specifier; optional, but if present must match installed `dataharbor`.
- `entrypoints.celery` must be **null**. Non-null fails `validate_manifest_contract`.
- `entrypoints.dagster: null` means no Dagster defs (workspace skips the location).
- `requirements.extractors`: local id (`"demo_site"`), git URL, or `{"name": "...", "source": "https://..."}`.
- `requirements.python`: extra pip specs for **this bundle** (e.g. `"playwright>=1.41"`). Core does not ship Playwright.
- `requirements.env`: extra `.env` names this bundle reads. String (`"FOO_API_KEY"`) or `{"name","required","description"}`. Core never writes `.env`. Install prints the list; `harbor bundle doctor` fails on missing **required** keys. Optional unset → warn. Schema errors fail `validate`; missing values do not (so install is not rolled back).
- Observability thresholds are read by `ScraperHealthChecker`. Env fallbacks: `OBSERVABILITY_STALENESS_SLA_HOURS=12`, `OBSERVABILITY_ANOMALY_THRESHOLD_RATIO=0.3`.

Validator also fails if `scraper.py` calls `get_extractor("id")` / `require_extractor("id")` for an undeclared id, or if a declared extractor is missing/invalid under `extractors/`.

---

## 4. Extractors (parse-only plugins)

```text
extractors/<id>/
├── manifest.json    # name, version, description, domains, entrypoint (extractor:parse)
├── AGENT.md         # optional parse playbook (not a platform skill)
├── extractor.py     # parse(html, source_url) -> list[dict]; optional generate_page_urls
└── tests/
```

- Each record should include `source_url`.
- Scaffold: `harbor extractor new <id> --domains example.com`
- Resolve from a bundle: `harbor extractor resolve <bundle>` / `harbor bundle resolve <bundle>`
- Open-core ships `demo_site` as the contract example.

Ingest scraper pattern (what `default` scaffold generates): fetch with `fetch.py` → `get_extractor(url)` → `record_scraper_execution`. Selector drift is usually **extractor** code, not Core.

---

## 5. Fetch and scrape

Prefer `apps.scraper.http_fetcher.HttpFetcher` / bundle `fetch.py`. JS/browser fetch stays in the bundle; declare deps in `requirements.python`.

Optional egress: `PROXY_URL` / `PROXY_LIST`, or `proxy_manager.get_http_proxies()` / `get_browser_proxy()`.

Always log:

```python
record_scraper_execution(
    bundle_name="<name>",
    status="SUCCESS" if items else "ZERO_ROWS",  # or FAILED
    items_scraped=len(items),
    http_200_count=...,
    http_403_count=...,
    http_429_count=...,
)
```

Statuses used in `scraper_execution_logs`: `SUCCESS`, `DEGRADED`, `FAILED`, `ZERO_ROWS`. Health roll-up statuses are `HEALTHY` | `DEGRADED` | `CRITICAL` — not `ZERO_ROWS`.

---

## 6. `db.py` and dual-environment Postgres

`init_bundle_tables()` should be idempotent (`CREATE TABLE IF NOT EXISTS`). PostgreSQL is the OLTP sink; ClickHouse `MergeTree` is optional OLAP.

When Compose is the runtime:

| | Host CLI | `dataharbor_dagster` |
|--|----------|----------------------|
| Host | `.env` `POSTGRES_HOST` / `POSTGRES_PORT` (example: `127.0.0.1:54320`) | `postgres:5432` |
| DB name | `.env` `POSTGRES_DB` | compose env (example: `dataharbor`) |

Never mark a schema or Dagster asset fix done until it is verified in the **container that runs the asset** (`docker exec dataharbor_dagster python ...`) as well as, if relevant, the host CLI.

---

## 7. `assets.py` — recommended quality (not validator law)

Must: `defs = Definitions(...)` matching `entrypoints.dagster`.

Should (ingest pipelines):

1. `group_name` matching the bundle.
2. Stage descriptions (`[1/n] ...`).
3. `partitions_def` (`StaticPartitionsDefinition` or `DailyPartitionsDefinition`) when re-running a slice in the UI matters.
4. `context.log.info` per batch; `AssetObservation` when live counts help.
5. `@asset_check` for non-empty payload, uniqueness, range sanity.

Register checks on `Definitions(..., asset_checks=[...])`. Catalog template already includes a QA gate check.

After edits: `harbor workspace refresh` (or restart `harbor` / compose Dagster so locations reload).

---

## 8. Publish and pack

```bash
harbor bundle pack <name>
harbor bundle publish <name> [--remote <url>] [--dry-run] [--allow-local-extractors]
```

- Validates, copies a **temporary** snapshot (or `--workdir`). Does **not** create nested `.git` in the monorepo.
- Needs git `user.name` / `user.email`. `gh` optional (private repo by default).
- Bundle publish **never** auto-publishes extractors. Local extractor ids (except shipped `demo_site`) block real publish unless `--allow-local-extractors`.

---

## 9. Definition of done

Before claiming the bundle is valid or “conforms”:

1. Read `manifest.json`, `assets.py`, and any present `scraper.py` / `db.py` / extractor files — not a partial view.
2. `harbor bundle validate` and `harbor bundle doctor <name>`.
3. `PYTHONPATH=. pytest bundles/<name>/tests`.
4. If scraping: one live run (`PYTHONPATH=. .venv/bin/python bundles/<name>/scraper.py` or `harbor agent-protocol test <name> --url ...`) plus `harbor health`.
5. If Dagster/DB: verify inside `dataharbor_dagster` when Compose is up.

Do not commit unless the user asked. Do not pack/publish unless they asked.


---

---

---

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
