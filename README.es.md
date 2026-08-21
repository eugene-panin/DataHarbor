# 🌊 DataHarbor

**DataHarbor** es una plataforma de datos open-core modular con analítica de IA 360° (Whisper speech-to-text, EasyOCR, embeddings vectoriales, ClickHouse OLAP, clustering HDBSCAN) y autorreparación autónoma de scrapers (AI auto-remediation agnóstica al modelo y HAP v1.0).

> **Idiomas / Languages:** [🇬🇧 English](README.md) · [🇷🇺 Русский](README.ru.md) · [🇺🇦 Українська](README.uk.md) · 🇪🇸 Español · [🇹🇷 Türkçe](README.tr.md)

---

## 🏛 Arquitectura: Core / Bundles / Extractors

* **Core (`apps/`)** — runtime abierto: PostgreSQL `pgvector`, ClickHouse OLAP, Qdrant, SeaweedFS S3, Dagster, notificador Core. Opcional: `uv sync --extra ml`, n8n con `--with-n8n`.
* **Bundles (`bundles/`)** — pipelines de negocio (fetch → schema → Dagster → export HTML/CSV). Un bundle = un repositorio git al publicarlo.
* **Extractors (`extractors/`)** — plugins de parseo de una sola fuente (solo `parse(html, …)`; sin HTTP/proxy). Reutilizables por varios bundles. El open-core incluye el ejemplo `demo_site`; los extractores de dominio se instalan desde git.

Un bundle declara dependencias en `manifest.json` → `requirements.extractors` (id local, URL git o `{name, source}`). Con `harbor bundle install`, la plataforma descarga los extractores declarados en `extractors/`.

---

## ⚡ Inicio rápido

### 1. Instalación
```bash
git clone https://github.com/eugene-panin/DataHarbor.git
cd DataHarbor
./install.sh   # requiere uv; instala deps con `uv sync` y enlaza `harbor`
```

```bash
uv sync
uv run harbor --help
uv run harbor doctor   # incluye Publish readiness (identidad git; gh opcional)
```

### 2. Arrancar la plataforma
```bash
harbor up
```
*Inicia los microservicios en Kubernetes (Tilt) o Docker Compose (`harbor up --compose`).*

### 3. Comprobar estado
```bash
harbor status
```

---

## 📦 Publish: bundles y extractores

Modelo: **1 plugin = 1 repo git**. El staging usa un directorio temporal (o `--workdir`); no se crea un `.git` anidado dentro del monorepo.

```bash
# Nuevo extractor / bundle
harbor extractor new demo_site
harbor bundle new my_leads --extractors demo_site

# Publicar primero el extractor personalizado
harbor extractor publish demo_site --dry-run
harbor extractor publish demo_site
# → en el manifest del bundle: git@github.com:<you>/dh-extractor-demo-site.git

# Luego el bundle
harbor bundle publish my_leads --dry-run
harbor bundle publish my_leads
# o explícitamente: --remote git@github.com:ORG/dh-bundle-my_leads.git
```

**Importante:** `harbor bundle publish` **no** crea repos de extractores en GitHub automáticamente. Si `requirements.extractors` aún lista ids/rutas locales (no URLs git), la CLI los muestra y sugiere `harbor extractor publish <id>`. El publish real se detiene; `--dry-run` solo advierte. Escape hatch: `--allow-local-extractors`. El ejemplo `demo_site` se omite.

Flags: `--remote`, `--workdir`, `--repo-name`, `--visibility private|public`, `--public`, `--dry-run`. Se necesita `git` más `user.name` / `user.email`; `gh` es opcional (crear un repo privado de GitHub).

---

## 🌐 Servicios web locales y puertos

| Servicio | Descripción | URL local |
| :--- | :--- | :--- |
| ☸️ **Tilt** | Panel de control de Kubernetes local | [http://localhost:10350](http://localhost:10350) |
| ⚡ **Dagster UI** | Orquestador ETL y panel de autorreparación | [http://localhost:3000](http://localhost:3000) |
| 🚀 **ClickHouse** | Almacén OLAP para analítica | [http://localhost:8123](http://localhost:8123) |
| 🧭 **Qdrant** | Búsqueda vectorial / RAG | [http://localhost:6333/dashboard](http://localhost:6333/dashboard) |
| 📊 **Grafana** | Paneles de observabilidad | [http://localhost:3001](http://localhost:3001) |
| 🔄 **n8n** (opcional) | Hub de automatización no-code | [http://localhost:56780](http://localhost:56780) (`harbor up --with-n8n`) |

---

## 🛠 CLI (`harbor`)

### 1. Diagnóstico y control del entorno
```bash
harbor doctor             # Docker, Tilt, Kind, Python, Git + Publish readiness
harbor health             # Salud de scrapers, anomalías de 0 filas, SLA
harbor health --auto-fix <bnd> # Remediador IA con validación AST
harbor up                 # Kubernetes/Tilt (o --compose)
harbor down
harbor status
harbor uninstall          # Eliminación con backup automático en ~/DataHarbor_Backups
```

### 2. Backup maestro y restauración
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
harbor bundle new <name> [--extractors id1,id2]
harbor bundle install <src>   # Git / archive / folder; descarga extractors declarados
harbor bundle resolve <name>  # Instalar extractors faltantes del manifest
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

## 🤖 Skill de agente IA y reparación autónoma

El repositorio incluye un skill de agente en **[.agents/skills/dataharbor-remediator/SKILL.md](.agents/skills/dataharbor-remediator/SKILL.md)**.

Los agentes (**Codex**, **Antigravity**, **Claude Code**, **Gemini CLI**) pueden seguir HAP v1.0 para reparar fallos de forma segura y eficiente en tokens.

---

## 📄 Licencia

MIT License © DataHarbor Core Team
