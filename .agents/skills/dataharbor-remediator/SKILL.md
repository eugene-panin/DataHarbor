---
name: dataharbor-remediator
description: Autonomous self-healing protocol for DataHarbor scrapers via HAP v1.0 CLI. Trigger when scrapers break, return zero rows, or when asked to repair a DataHarbor bundle.
---

# 🤖 DataHarbor Autonomous Scraper Remediation Skill

This skill provides step-by-step instructions for AI Agents (Codex, Antigravity, Claude Code, Gemini CLI) to autonomously diagnose, repair, and verify broken DataHarbor web scrapers using the token-optimized Harbor Agent Protocol (HAP v1.0).

---

## 🛠️ Step-by-Step Execution Protocol

### Step 1: Check Scraper Health Status
Execute the following CLI command to get a compact JSON status report of all installed bundles:
```bash
harbor agent-protocol status
```
Inspect the returned JSON array for any bundles marked with `DEGRADED`, `CRITICAL`, or `ZERO_ROWS`.

---

### Step 2: Fetch Compressed Diagnostic Context (< 200 Tokens)
For any failing bundle, retrieve the token-compressed diagnostic payload:
```bash
harbor agent-protocol diagnose <bundle_name>
```
> [!NOTE]
> Do NOT read the entire 100KB HTML source or full scraper file. The HAP v1.0 diagnostic output compresses failing CSS selectors, error messages, and target code snippets down to ~200 tokens.

---

### Step 3: Synthesize Surgical Python Patch
Analyze the `code_snippet`, `failing_selectors`, and `html_sample` from Step 2.
Generate the complete, corrected Python code for `bundles/<bundle_name>/scraper.py`.

Save the replacement Python code to a temporary file: `/tmp/<bundle_name>_patch.py`.

---

### Step 4: Apply Patch & Validate Python AST
Apply the patch using Harbor's AST-validated patch command:
```bash
harbor agent-protocol patch <bundle_name> --code-file /tmp/<bundle_name>_patch.py
```
> [!IMPORTANT]
> Harbor automatically runs `ast.parse()` on the patch before writing to disk. If AST validation fails, fix the syntax error in `/tmp/<bundle_name>_patch.py` and retry.

---

### Step 5: Execute Verification Test
Run a 1-page verification scrape to confirm the fix:
```bash
harbor agent-protocol test <bundle_name>
```
If the test returns `"status": "SUCCESS"`, commit the changes to Git:
```bash
git add bundles/<bundle_name>/scraper.py
git commit -m "fix(<bundle_name>): Auto-remediated HTML selector drift via HAP v1.0 AI agent"
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
