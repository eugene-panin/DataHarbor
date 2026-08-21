# 🌊 DataHarbor

**DataHarbor**, 360° yapay zekâ analitiği (Whisper speech-to-text, EasyOCR, vektör gömmeleri, ClickHouse OLAP, HDBSCAN kümeleme) ve otonom scraper kendi kendini onarma (modele bağımlı olmayan AI auto-remediation ve HAP v1.0) sunan modüler bir open-core veri platformudur.

> **Diller / Languages:** [🇬🇧 English](README.md) · [🇷🇺 Русский](README.ru.md) · [🇺🇦 Українська](README.uk.md) · [🇪🇸 Español](README.es.md) · 🇹🇷 Türkçe

---

## 🏛 Mimari: Core / Bundles / Extractors

* **Core (`apps/`)** — açık çekirdek: PostgreSQL `pgvector`, ClickHouse OLAP, Qdrant, SeaweedFS S3, Dagster, Core bildirimleri. İsteğe bağlı: `uv sync --extra ml`, n8n için `--with-n8n`.
* **Bundles (`bundles/`)** — iş pipeline’ları (fetch → schema → Dagster → HTML/CSV export). Yayınlanırken bir bundle = bir git deposu.
* **Extractors (`extractors/`)** — tek bir kaynak için ayrıştırma eklentileri (yalnızca `parse(html, …)`; HTTP/proxy yok). Birden fazla bundle tarafından yeniden kullanılır. Open-core `demo_site` örneğini içerir; alan extractors git’ten kurulur.

Bir bundle bağımlılıklarını `manifest.json` → `requirements.extractors` içinde bildirir (yerel id, git URL veya `{name, source}`). `harbor bundle install` sırasında platform bildirilen extractor kaynaklarını `extractors/` altına çeker.

---

## ⚡ Hızlı başlangıç

### 1. Kurulum
```bash
git clone https://github.com/eugene-panin/DataHarbor.git
cd DataHarbor
./install.sh   # uv gerektirir; deps’i `uv sync` ile kurar ve `harbor` bağlar
```

```bash
uv sync
uv run harbor --help
uv run harbor doctor   # Publish readiness dahil (git kimliği; gh isteğe bağlı)
```

### 2. Platformu başlatma
```bash
harbor up
```
*Platform mikroservislerini Kubernetes (Tilt) veya Docker Compose (`harbor up --compose`) ile başlatır.*

### 3. Durumu kontrol etme
```bash
harbor status
```

---

## 📦 Publish: bundle’lar ve extractor’lar

Model: **1 eklenti = 1 git deposu**. Staging geçici bir dizin (veya `--workdir`) kullanır; monorepo içinde iç içe `.git` oluşturulmaz.

```bash
# Yeni extractor / bundle
harbor extractor new demo_site
harbor bundle new my_leads --extractors demo_site

# Önce özel extractor’ı yayınlayın
harbor extractor publish demo_site --dry-run
harbor extractor publish demo_site
# → bundle manifest’ine: git@github.com:<you>/dh-extractor-demo-site.git

# Sonra bundle
harbor bundle publish my_leads --dry-run
harbor bundle publish my_leads
# veya açıkça: --remote git@github.com:ORG/dh-bundle-my_leads.git
```

**Önemli:** `harbor bundle publish` GitHub’da extractor depolarını **kendiliğinden oluşturmaz**. `requirements.extractors` hâlâ yerel id/path listeliyorsa (git URL değil), CLI bunları listeler ve `harbor extractor publish <id>` önerir. Gerçek publish durur; `--dry-run` yalnızca uyarır. Escape hatch: `--allow-local-extractors`. Gönderilen `demo_site` örneği atlanır.

Bayraklar: `--remote`, `--workdir`, `--repo-name`, `--visibility private|public`, `--public`, `--dry-run`. `git` ile birlikte `user.name` / `user.email` gerekir; `gh` isteğe bağlıdır (özel GitHub deposu oluşturma).

---

## 🌐 Yerel web servisleri ve portlar

| Servis | Açıklama | Yerel URL |
| :--- | :--- | :--- |
| ☸️ **Tilt** | Yerel Kubernetes kontrol paneli | [http://localhost:10350](http://localhost:10350) |
| ⚡ **Dagster UI** | ETL orkestratörü ve otomatik onarım panosu | [http://localhost:3000](http://localhost:3000) |
| 🚀 **ClickHouse** | Analitik için OLAP deposu | [http://localhost:8123](http://localhost:8123) |
| 🧭 **Qdrant** | Vektör arama / RAG | [http://localhost:6333/dashboard](http://localhost:6333/dashboard) |
| 📊 **Grafana** | Gözlemlenebilirlik panelleri | [http://localhost:3001](http://localhost:3001) |
| 🔄 **n8n** (isteğe bağlı) | No-code otomasyon | [http://localhost:56780](http://localhost:56780) (`harbor up --with-n8n`) |

---

## 🛠 CLI (`harbor`)

### 1. Ortam teşhisi ve kontrol
```bash
harbor doctor             # Docker, Tilt, Kind, Python, Git + Publish readiness
harbor health             # Scraper sağlığı, sıfır satır anomalileri, SLA
harbor health --auto-fix <bnd> # AST doğrulamalı AI onarıcı
harbor up                 # Kubernetes/Tilt (veya --compose)
harbor down
harbor status
harbor uninstall          # ~/DataHarbor_Backups’a otomatik yedekle kaldırma
```

### 2. Ana yedekleme ve geri yükleme
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
harbor bundle install <src>   # Git / archive / folder; bildirilen extractors’ı çeker
harbor bundle resolve <name>  # Manifest’ten eksik extractors’ı kur
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

## 🤖 AI agent skill ve otonom onarım

Depoda **[.agents/skills/dataharbor-remediator/SKILL.md](.agents/skills/dataharbor-remediator/SKILL.md)** altında bir agent skill bulunur.

Ajanlar (**Codex**, **Antigravity**, **Claude Code**, **Gemini CLI**) arızaları güvenli ve token-verimli şekilde onarmak için HAP v1.0’ı izleyebilir.

---

## 📄 Lisans

MIT License © DataHarbor Core Team
