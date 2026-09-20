# 🌊 DataHarbor

[![CI](https://github.com/eugene-panin/DataHarbor/actions/workflows/ci.yml/badge.svg)](https://github.com/eugene-panin/DataHarbor/actions/workflows/ci.yml)

**DataHarbor** is a modular open-core data platform (ClickHouse OLAP, Qdrant, Dagster, plugin bundles/extractors) with autonomous scraper self-healing (model-agnostic AI auto-remediation & HAP v1.0). Optional ML extras (`uv sync --extra ml`): Whisper, EasyOCR, embeddings, HDBSCAN.

> **Languages:** 🇬🇧 English · [🇷🇺 Русский](README.ru.md) · [🇺🇦 Українська](README.uk.md) · [🇪🇸 Español](README.es.md) · [🇹🇷 Türkçe](README.tr.md)

---

## 🏛 Architecture: Core / Bundles / Extractors

* **Core (`apps/`)** — open platform runtime: PostgreSQL `pgvector`, ClickHouse OLAP, Qdrant, SeaweedFS S3, Dagster, Core notifier (Telegram/Slack/webhooks). Optional: `uv sync --extra ml`, n8n via `--with-n8n`. Backup CLI stays in Core (`harbor backup`).
* **Bundles (`bundles/`)** — business pipelines (fetch → schema → Dagster → HTML/CSV export). One bundle = one git repository when published.
* **Extractors (`extractors/`)** — parse plugins for a single source (`parse(html, …)` only; no HTTP/proxy). Reused by multiple bundles. Open-core ships the `demo_site` example; domain extractors are installed from git.

A bundle declares dependencies in `manifest.json` → `requirements.extractors` (local id, git URL, or `{name, source}`). On `harbor bundle install`, the platform pulls declared extractor sources into `extractors/`.

---

## ⚡ Quick Start

### 1. Install
```bash
git clone https://github.com/eugene-panin/DataHarbor.git
cd DataHarbor
./install.sh   # requires uv; installs deps via `uv sync` and links `harbor`
```

```bash
uv sync
uv sync --extra ml   # optional: Whisper / EasyOCR / embeddings / HDBSCAN
uv run harbor --help
uv run harbor doctor   # includes Publish readiness (git identity; gh optional)
```

### 2. Start the platform
```bash
harbor up
```
*Starts platform services in Kubernetes (Tilt) or Docker Compose (`harbor up --compose`).*

### 3. Check status
```bash
harbor status
```

### 4. Try the demo bundle (no API keys, no external network)

Open-core ships a working end-to-end example: a static `demo_site` fixture
(`deploy/demo_site/`) scraped into PostgreSQL by the `demo` bundle
(`bundles/demo/`).

```bash
harbor bundle run demo    # scrapes the local fixture, writes to PostgreSQL
harbor bundle view demo   # renders an HTML report of the scraped rows
```

`harbor bundle run` shells out to `dagster asset materialize`; you can do the
same by hand in the Dagster UI (materialize the `demo` asset group). Use this
bundle's files (`fetch.py` / `scraper.py` / `db.py` / `assets.py` /
`exporter.py`) as a starting point for your own.

---

## 📦 Publish: bundles and extractors

Model: **1 plugin = 1 git repo**. Staging uses a temp directory (or `--workdir`); nested `.git` is never created inside the monorepo.

```bash
# New extractor / bundle
harbor extractor new demo_site
harbor bundle new my_leads --extractors demo_site

# Publish a custom extractor first
harbor extractor publish demo_site --dry-run
harbor extractor publish demo_site
# → put in the bundle manifest: git@github.com:<you>/dh-extractor-demo-site.git

# Then publish the bundle
harbor bundle publish my_leads --dry-run
harbor bundle publish my_leads
# or explicitly: --remote git@github.com:ORG/dh-bundle-my_leads.git
```

**Important:** `harbor bundle publish` does **not** auto-create extractor repos on GitHub. If `requirements.extractors` still lists local ids/paths (not git URLs), the CLI lists them and suggests `harbor extractor publish <id>`. A real publish stops; `--dry-run` only warns. Escape hatch: `--allow-local-extractors`. The shipped `demo_site` example is skipped.

Flags: `--remote`, `--workdir`, `--repo-name`, `--visibility private|public`, `--public`, `--dry-run`. Requires `git` plus `user.name` / `user.email`; `gh` is optional (auto-create a private GitHub repo).

---

## 🌐 Local web services and ports

| Service | Description | Local URL |
| :--- | :--- | :--- |
| ☸️ **Tilt** | Local Kubernetes control panel | [http://localhost:10350](http://localhost:10350) |
| ⚡ **Dagster UI** | ETL orchestrator and auto-repair dashboard | [http://localhost:3000](http://localhost:3000) |
| 🚀 **ClickHouse** | OLAP warehouse for analytics | [http://localhost:8123](http://localhost:8123) |
| 🧭 **Qdrant** | Vector search / RAG | [http://localhost:6333/dashboard](http://localhost:6333/dashboard) |
| 📊 **Grafana** | Observability dashboards | [http://localhost:3001](http://localhost:3001) |
| 🔄 **n8n** (optional) | No-code automation hub | [http://localhost:56780](http://localhost:56780) (`harbor up --with-n8n`) |
| 🧪 **demo_site** | Static fixture scraped by the `demo` bundle | [http://localhost:8098](http://localhost:8098) |

---

## 🛠 CLI (`harbor`)

### 1. Environment diagnostics and control
```bash
harbor doctor             # Docker, Tilt, Kind, Python, Git + Publish readiness
harbor health             # Scraper health, zero-row anomalies, SLA
harbor health --auto-fix <bnd> # AI remediator with AST validation
harbor up                 # Kubernetes/Tilt (or --compose)
harbor down
harbor status
harbor uninstall          # Remove with auto-backup to ~/DataHarbor_Backups
```

### 2. Master backup and restore
```bash
harbor backup create
harbor backup restore <file.tar.gz>
harbor backup list
```

### 3. Harbor Agent Protocol (HAP v1.0)
```bash
harbor agent-protocol status
harbor agent-protocol diagnose <bnd>
harbor agent-protocol patch <bnd> --code-file <file>
harbor agent-protocol test <bnd>
```

### 4. Bundles
```bash
harbor bundle list
harbor bundle new <name> [--template default|ml|etl|dagster]
harbor bundle templates
harbor bundle install <src>   # Git / archive / folder; pulls declared extractors
harbor bundle resolve <name>  # Install missing extractors from manifest
harbor bundle pack <name>
harbor bundle publish <name> [--dry-run] [--remote URL] [--allow-local-extractors]
harbor bundle remove <name>
harbor bundle run <name>      # materialize all Dagster assets synchronously (no UI needed)
harbor bundle export / view
harbor bundle validate
harbor bundle doctor [name]   # engines, python deps, extractors, Dagster defs
harbor workspace refresh      # regenerate multi code-location workspace.yaml
harbor workspace show
```

### 5. Extractors
```bash
harbor extractor list
harbor extractor new <name> [--path DIR]
harbor extractor install <src>
harbor extractor pack <name>
harbor extractor publish <name> [--dry-run] [--remote URL]
harbor extractor resolve <bundle>
harbor extractor validate [name]
harbor extractor remove <name>
```

---

## 🤖 AI agent skill & autonomous repair

The repo includes an agent skill at **[.agents/skills/dataharbor-remediator/SKILL.md](.agents/skills/dataharbor-remediator/SKILL.md)**.

Agents (**Codex**, **Antigravity**, **Claude Code**, **Gemini CLI**) can follow HAP v1.0 for safe, token-efficient failure repair.

---

## 🤝 Contributing

Contributions to the open-core platform are welcome — see
**[CONTRIBUTING.md](CONTRIBUTING.md)** for dev setup, the test/lint gates
CI runs, and PR guidelines. Please also read the
**[Code of Conduct](CODE_OF_CONDUCT.md)**.

Found a security issue? Please report it privately — see
**[SECURITY.md](SECURITY.md)**, don't open a public issue.

---

## 📄 License

MIT License © DataHarbor Core Team
