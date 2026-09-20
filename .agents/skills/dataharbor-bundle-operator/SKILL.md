---
name: dataharbor-bundle-operator
description: "Use when the user wants to operate, monitor, or check results/health/SLA of an installed DataHarbor bundle (RU: оперируй, проверь бандл, результаты, здоровье, как там бандл). First command: harbor agent-protocol summary. Not for writing a new bundle or repairing scrapers unless summary action is REMEDIATE."
---

# DataHarbor Bundle Operator

Duty session. Do **not** load `dataharbor-bundle-designer`. Do **not** read `scraper.py`, extractors, or `AGENTS.md` until `action` is `REMEDIATE`. You **may** read `bundles/<name>/AGENT.md` after `summary` when the user named that bundle (duty playbook only).

If the user actually asked to **create or change** a bundle, stop and follow `dataharbor-bundle-designer` instead. If they asked to **fix** a broken scrape and `action` is already `REMEDIATE`, follow `dataharbor-remediator`.

Repair is a different skill: `dataharbor-remediator`.

## Commands

```bash
harbor agent-protocol summary              # fleet: name, status, action, items_24h, issues_n
harbor agent-protocol summary <bundle>     # one bundle + last_log + sla_hours; no code
```

JSON is compact (no indent). Fields that will **never** appear: `code_snippet`, `html_sample`, `failing_selectors`.

`action`: `OK` | `WATCH` | `REMEDIATE` | `STOP`

| action | What you do |
|--------|-------------|
| `OK` | One short line. Stop. |
| `WATCH` | Quote `issues` / `last_log.status`. Do not open source. |
| `REMEDIATE` | Tell the user to switch to remediator (or follow that skill). Next: `harbor agent-protocol diagnose <name>`. |
| `STOP` | Bundle missing. Do not scaffold. |

Do not run `status` (verbose + alerts), `diagnose`, `test`, `patch`, `bundle export`, or pytest in this session unless `REMEDIATE` and the user wants a fix now.

Chat budget: ≤10 lines. Prefer the summary JSON as-is over a prose restatement.

Do not commit. Do not live-scrape.


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
