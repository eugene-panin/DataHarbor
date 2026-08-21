# 🌊 DataHarbor

**DataHarbor** — модульная открытая дата-платформа (ClickHouse OLAP, Qdrant, Dagster, бандлы/экстракторы) с автономным самоисцелением парсеров (HAP v1.0). Опциональный ML-extra (`uv sync --extra ml`): Whisper, EasyOCR, embeddings, HDBSCAN.

> **Языки / Languages:** [🇬🇧 English](README.md) · 🇷🇺 Русский · [🇺🇦 Українська](README.uk.md) · [🇪🇸 Español](README.es.md) · [🇹🇷 Türkçe](README.tr.md)

---

## 🏛 Архитектура: Core / Bundles / Extractors

* **Core (`apps/`)** — открытое ядро: PostgreSQL `pgvector`, ClickHouse OLAP, Qdrant, SeaweedFS S3, Dagster, Core-нотификатор (Telegram/Slack/webhooks). Опционально: `uv sync --extra ml`, n8n через `--with-n8n`. Backup CLI в Core (`harbor backup`).
* **Bundles (`bundles/`)** — бизнес-пайплайны (fetch → schema → Dagster → HTML/CSV export). Один бандл = один git-репозиторий при публикации.
* **Extractors (`extractors/`)** — плагины парсинга одного источника (только `parse(html, …)`, без HTTP/proxy). Переиспользуются несколькими бандлами. В open-core — пример `demo_site`; доменные экстракторы ставятся из git.

Бандл объявляет зависимости в `manifest.json` → `requirements.extractors` (локальный id, git URL или `{name, source}`). При `harbor bundle install` платформа сама подтягивает extractor-ы с git-источников.

---

## ⚡ Быстрый старт

### 1. Установка
```bash
git clone https://github.com/eugene-panin/DataHarbor.git
cd DataHarbor
./install.sh   # требует uv; ставит deps через `uv sync` и линкует `harbor`
```

```bash
uv sync
uv run harbor --help
uv run harbor doctor   # в т.ч. Publish readiness (git identity, gh optional)
```

### 2. Запуск платформы
```bash
harbor up
```
*Запустит платформенные микросервисы в Kubernetes (Tilt) или Docker Compose (`harbor up --compose`).*

### 3. Проверка статуса
```bash
harbor status
```

---

## 📦 Publish: бандлы и экстракторы

Модель: **1 плагин = 1 git-репо**. Staging во временную папку (или `--workdir`); внутри monorepo nested `.git` не создаётся.

```bash
# Новый extractor / bundle
harbor extractor new demo_site
harbor bundle new my_leads --extractors demo_site

# Сначала публикуем кастомный extractor
harbor extractor publish demo_site --dry-run
harbor extractor publish demo_site
# → в manifest бандла: git@github.com:<you>/dh-extractor-demo-site.git

# Затем бандл
harbor bundle publish my_leads --dry-run
harbor bundle publish my_leads
# или явно: --remote git@github.com:ORG/dh-bundle-my_leads.git
```

**Важно:** `harbor bundle publish` **не** создаёт extractor-репозитории на GitHub сам. Если в `requirements.extractors` ещё локальные id/path (не git URL), CLI покажет список и предложит `harbor extractor publish <id>`. Реальный publish остановится; `--dry-run` только предупредит. Escape hatch: `--allow-local-extractors`. Пример `demo_site` пропускается.

Флаги: `--remote`, `--workdir`, `--repo-name`, `--visibility private|public`, `--public`, `--dry-run`. Нужны `git` + `user.name`/`user.email`; `gh` опционален (автосоздание private GitHub repo).

---

## 🌐 Локальные веб-сервисы и порты

| Сервис | Описание | Локальный URL |
| :--- | :--- | :--- |
| ☸️ **Tilt** | Панель управления локальным Kubernetes-кластером | [http://localhost:10350](http://localhost:10350) |
| ⚡ **Dagster UI** | Оркестратор ETL-пайплайнов и дашборд авто-ремонта | [http://localhost:3000](http://localhost:3000) |
| 🚀 **ClickHouse** | Быстрое OLAP хранилище аналитических данных | [http://localhost:8123](http://localhost:8123) |
| 🧭 **Qdrant** | Векторный поиск / RAG | [http://localhost:6333/dashboard](http://localhost:6333/dashboard) |
| 📊 **Grafana** | Дашборды наблюдаемости | [http://localhost:3001](http://localhost:3001) |
| 🔄 **n8n** (опционально) | No-code автоматизация | [http://localhost:56780](http://localhost:56780) (`harbor up --with-n8n`) |

---

## 🛠 Консольные команды CLI (`harbor`)

### 1. Диагностика и управление окружением
```bash
harbor doctor             # Docker, Tilt, Kind, Python, Git + Publish readiness
harbor health             # Аудит здоровья парсеров, аномалий 0 записей и SLA
harbor health --auto-fix <bnd> # Автономный AI-ремонт парсера с валидацией AST
harbor up                 # Kubernetes/Tilt (или --compose)
harbor down
harbor status
harbor uninstall          # Удаление с авто-бэкапом в ~/DataHarbor_Backups
```

### 2. Мастер-бэкап и восстановление
```bash
harbor backup create
harbor backup restore <file.tar.gz>
harbor backup list
```

### 3. Протокол для ИИ-агентов (HAP v1.0)
```bash
harbor agent-protocol status
harbor agent-protocol diagnose <bnd>
harbor agent-protocol patch <bnd> --code-file <file>
harbor agent-protocol test <bnd>
```

### 4. Бандлы
```bash
harbor bundle list
harbor bundle new <name> [--extractors id1,id2]
harbor bundle install <src>   # Git / archive / folder; тянет declared extractors
harbor bundle resolve <name>  # Доустановить extractors из manifest
harbor bundle pack <name>
harbor bundle publish <name> [--dry-run] [--remote URL] [--allow-local-extractors]
harbor bundle remove <name>
harbor bundle export / view
harbor bundle validate
harbor bundle doctor [name]   # engines, python deps, extractors, Dagster defs
harbor workspace refresh      # multi code-location workspace.yaml
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

## 🤖 AI Agent Skill & автономный ремонт

В репозиторий встроен готовый скилл ИИ-агентов **[.agents/skills/dataharbor-remediator/SKILL.md](.agents/skills/dataharbor-remediator/SKILL.md)**.

Любой агент (**Codex**, **Antigravity**, **Claude Code**, **Gemini CLI**) автоматически распознает инструкции и использует протокол HAP v1.0 для безопасного и экономного исправления сбоев.

---

## 📄 Лицензия

MIT License © DataHarbor Core Team
