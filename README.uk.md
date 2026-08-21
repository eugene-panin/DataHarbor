# 🌊 DataHarbor

**DataHarbor** — модульна відкрита дата-платформа з 360° AI-аналітикою (Whisper speech-to-text, EasyOCR, векторні ембедінги, ClickHouse OLAP, кластеризація HDBSCAN) та автономним самовідновленням парсерів (model-agnostic AI auto-remediation & HAP v1.0).

> **Мови / Languages:** [🇬🇧 English](README.md) · [🇷🇺 Русский](README.ru.md) · 🇺🇦 Українська · [🇪🇸 Español](README.es.md) · [🇹🇷 Türkçe](README.tr.md)

---

## 🏛 Архітектура: Core / Bundles / Extractors

* **Core (`apps/`)** — відкрите ядро: PostgreSQL `pgvector`, ClickHouse OLAP, Qdrant, SeaweedFS S3, Dagster, Core-нотифікатор. Опційно: `uv sync --extra ml`, n8n через `--with-n8n`.
* **Bundles (`bundles/`)** — бізнес-пайплайни (fetch → schema → Dagster → HTML/CSV export). Один бандл = один git-репозиторій під час публікації.
* **Extractors (`extractors/`)** — плагіни парсингу одного джерела (лише `parse(html, …)`; без HTTP/proxy). Повторно використовуються кількома бандлами. В open-core — приклад `demo_site`; доменні екстрактори встановлюються з git.

Бандл оголошує залежності в `manifest.json` → `requirements.extractors` (локальний id, git URL або `{name, source}`). Під час `harbor bundle install` платформа підтягує оголошені джерела екстракторів у `extractors/`.

---

## ⚡ Швидкий старт

### 1. Встановлення
```bash
git clone https://github.com/eugene-panin/DataHarbor.git
cd DataHarbor
./install.sh   # потребує uv; ставить deps через `uv sync` і лінкує `harbor`
```

```bash
uv sync
uv run harbor --help
uv run harbor doctor   # зокрема Publish readiness (git identity; gh опційно)
```

### 2. Запуск платформи
```bash
harbor up
```
*Запускає мікросервіси платформи в Kubernetes (Tilt) або Docker Compose (`harbor up --compose`).*

### 3. Перевірка статусу
```bash
harbor status
```

---

## 📦 Publish: бандли та екстрактори

Модель: **1 плагін = 1 git-репо**. Staging у тимчасову теку (або `--workdir`); вкладений `.git` усередині monorepo не створюється.

```bash
# Новий extractor / bundle
harbor extractor new demo_site
harbor bundle new my_leads --extractors demo_site

# Спочатку публікуємо кастомний extractor
harbor extractor publish demo_site --dry-run
harbor extractor publish demo_site
# → у manifest бандла: git@github.com:<you>/dh-extractor-demo-site.git

# Потім бандл
harbor bundle publish my_leads --dry-run
harbor bundle publish my_leads
# або явно: --remote git@github.com:ORG/dh-bundle-my_leads.git
```

**Важливо:** `harbor bundle publish` **не** створює репозиторії екстракторів на GitHub сам. Якщо в `requirements.extractors` ще локальні id/path (не git URL), CLI покаже список і запропонує `harbor extractor publish <id>`. Реальний publish зупиниться; `--dry-run` лише попередить. Escape hatch: `--allow-local-extractors`. Приклад `demo_site` пропускається.

Прапорці: `--remote`, `--workdir`, `--repo-name`, `--visibility private|public`, `--public`, `--dry-run`. Потрібні `git` + `user.name` / `user.email`; `gh` опційний (автостворення private GitHub repo).

---

## 🌐 Локальні веб-сервіси та порти

| Сервіс | Опис | Локальний URL |
| :--- | :--- | :--- |
| ☸️ **Tilt** | Панель керування локальним Kubernetes-кластером | [http://localhost:10350](http://localhost:10350) |
| ⚡ **Dagster UI** | Оркестратор ETL-пайплайнів і дашборд авторемонту | [http://localhost:3000](http://localhost:3000) |
| 🚀 **ClickHouse** | Швидке OLAP-сховище аналітики | [http://localhost:8123](http://localhost:8123) |
| 🧭 **Qdrant** | Векторний пошук / RAG | [http://localhost:6333/dashboard](http://localhost:6333/dashboard) |
| 📊 **Grafana** | Дашборди спостережуваності | [http://localhost:3001](http://localhost:3001) |
| 🔄 **n8n** (опційно) | No-code автоматизація | [http://localhost:56780](http://localhost:56780) (`harbor up --with-n8n`) |

---

## 🛠 CLI (`harbor`)

### 1. Діагностика та керування оточенням
```bash
harbor doctor             # Docker, Tilt, Kind, Python, Git + Publish readiness
harbor health             # Здоров'я парсерів, аномалії 0 рядків, SLA
harbor health --auto-fix <bnd> # AI-ремонт парсера з валідацією AST
harbor up                 # Kubernetes/Tilt (або --compose)
harbor down
harbor status
harbor uninstall          # Видалення з авто-бекапом у ~/DataHarbor_Backups
```

### 2. Майстер-бекап і відновлення
```bash
harbor backup create
harbor backup restore <file.tar.gz>
harbor backup list
```

### 3. Протокол для AI-агентів (HAP v1.0)
```bash
harbor agent-protocol status
harbor agent-protocol diagnose <bnd>
harbor agent-protocol patch <bnd> --code-file <file>
harbor agent-protocol test <bnd>
```

### 4. Бандли
```bash
harbor bundle list
harbor bundle new <name> [--extractors id1,id2]
harbor bundle install <src>   # Git / archive / folder; тягне declared extractors
harbor bundle resolve <name>  # Довстановити extractors з manifest
harbor bundle pack <name>
harbor bundle publish <name> [--dry-run] [--remote URL] [--allow-local-extractors]
harbor bundle remove <name>
harbor bundle export / view
harbor bundle validate
harbor bundle doctor [name]
harbor workspace refresh
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

## 🤖 AI agent skill і автономний ремонт

У репозиторії є готовий skill для AI-агентів **[.agents/skills/dataharbor-remediator/SKILL.md](.agents/skills/dataharbor-remediator/SKILL.md)**.

Агенти (**Codex**, **Antigravity**, **Claude Code**, **Gemini CLI**) можуть слідувати HAP v1.0 для безпечного та економного виправлення збоїв.

---

## 📄 Ліцензія

MIT License © DataHarbor Core Team
