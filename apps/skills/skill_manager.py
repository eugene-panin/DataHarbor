import logging
import os
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCAL_SKILLS_DIR = os.path.join(PROJECT_ROOT, ".agents", "skills")

# Target Global Skill Directories (Codex User Skills & Gemini/Antigravity User Config)
# Respects strict separation: ~/.codex/skills/ for Codex user skills without duplicating in .system or global .agents
GLOBAL_SKILL_TARGETS = [
    os.path.expanduser("~/.codex/skills"),
    os.path.expanduser("~/.gemini/config/skills")
]

class SkillManagerEngine:
    """Manages skill registration and injects active runtime environment context (Kubernetes vs Docker Compose vs Local Host)."""

    def detect_runtime_environment(self) -> dict[str, Any]:
        """Detects whether DataHarbor is running in Kubernetes, Docker Compose, or Local Host environment."""
        is_k8s = False
        is_docker = False

        # 1. Check Kubernetes environment
        if os.path.exists("/var/run/secrets/kubernetes.io") or "KUBERNETES_SERVICE_HOST" in os.environ:
            is_k8s = True
        else:
            try:
                res = subprocess.run(["kubectl", "get", "pods", "-l", "app=postgres"], capture_output=True, text=True)
                if res.returncode == 0 and "postgres" in res.stdout:
                    is_k8s = True
            except Exception:
                pass

        # 2. Check Docker Compose environment
        if not is_k8s:
            if os.path.exists("/.dockerenv"):
                is_docker = True
            else:
                try:
                    res = subprocess.run(["docker", "ps", "--filter", "name=dataharbor"], capture_output=True, text=True)
                    if res.returncode == 0 and "dataharbor" in res.stdout:
                        is_docker = True
                except Exception:
                    pass

        if is_k8s:
            mode = "KUBERNETES_TILT"
            desc = "Kubernetes Cluster (Managed via Tilt)"
            db_host = "postgres.default.svc.cluster.local"
            ch_host = "clickhouse.default.svc.cluster.local"
            s3_url = "http://seaweedfs.default.svc.cluster.local:8333"
            dagster_url = "http://localhost:3000"
            qdrant_url = "http://localhost:6333"
        elif is_docker:
            mode = "DOCKER_COMPOSE"
            desc = "Docker Compose Microservices Stack"
            db_host = "postgres (Port 5432)"
            ch_host = "clickhouse (Port 8123)"
            s3_url = "http://seaweedfs:8333"
            dagster_url = "http://localhost:3000"
            qdrant_url = "http://localhost:6333"
        else:
            mode = "LOCAL_HOST"
            desc = "Local Machine Host (Dev Execution)"
            db_host = "127.0.0.1:5432"
            ch_host = "127.0.0.1:8123"
            s3_url = "http://localhost:8334"
            dagster_url = "http://localhost:3000"
            qdrant_url = "http://localhost:6333"

        return {
            "mode": mode,
            "description": desc,
            "postgres_host": db_host,
            "clickhouse_host": ch_host,
            "s3_url": s3_url,
            "dagster_url": dagster_url,
            "qdrant_url": qdrant_url,
        }

    def generate_environment_context_block(self, env_info: dict[str, Any]) -> str:
        """Generates markdown block detailing active environment runtime bindings for AI Agents."""
        return f"""
---

## 🌐 Active Target Runtime Environment Context
> [!NOTE]
> DataHarbor runtime environment automatically detected by `harbor skill install`.
> **Active Environment:** `{env_info['mode']}` ({env_info['description']})

- **PostgreSQL 16 (OLTP & pgvector):** `{env_info['postgres_host']}`
- **ClickHouse (OLAP Analytics):** `{env_info['clickhouse_host']}`
- **SeaweedFS S3 Storage:** `{env_info['s3_url']}`
- **Qdrant Vector Store:** `{env_info['qdrant_url']}`
- **Dagster UI Dashboard:** `{env_info['dagster_url']}`
- **Core Notifier:** Telegram / Slack / `NOTIFY_WEBHOOK_URL` (n8n optional via `--with-n8n`)
"""

    def install_bundled_skills(self) -> dict[str, Any]:
        """Installs bundled skills to local and global agent skill directories, injecting active environment context."""
        env_info = self.detect_runtime_environment()
        env_block = self.generate_environment_context_block(env_info)

        installed_skills = []
        os.makedirs(LOCAL_SKILLS_DIR, exist_ok=True)
        for target_dir in GLOBAL_SKILL_TARGETS:
            os.makedirs(target_dir, exist_ok=True)

        for skill_folder in os.listdir(LOCAL_SKILLS_DIR):
            local_skill_path = os.path.join(LOCAL_SKILLS_DIR, skill_folder)
            skill_md_path = os.path.join(local_skill_path, "SKILL.md")

            if os.path.isdir(local_skill_path) and os.path.exists(skill_md_path):
                # Read SKILL.md
                with open(skill_md_path, encoding="utf-8") as f:
                    content = f.read()

                # Strip existing environment block if present
                if "## 🌐 Active Target Runtime Environment Context" in content:
                    content = content.split("## 🌐 Active Target Runtime Environment Context")[0].strip()

                # Append fresh environment context
                updated_content = content + "\n\n" + env_block.strip() + "\n"

                # Update local SKILL.md
                with open(skill_md_path, "w", encoding="utf-8") as f:
                    f.write(updated_content)

                # Copy to all global user skill directories for Codex, Antigravity, Claude, and Gemini
                for target_dir in GLOBAL_SKILL_TARGETS:
                    dest_skill_dir = os.path.join(target_dir, skill_folder)
                    os.makedirs(dest_skill_dir, exist_ok=True)
                    shutil.copy2(skill_md_path, os.path.join(dest_skill_dir, "SKILL.md"))

                installed_skills.append(skill_folder)
                logger.info(f"Installed & registered skill '{skill_folder}' across all Codex and global agent directories for '{env_info['mode']}'.")

        return {
            "status": "SUCCESS",
            "environment": env_info,
            "installed_skills": installed_skills
        }

    def list_installed_skills(self) -> list[dict[str, Any]]:
        """Lists installed skills and their runtime environment context."""
        env_info = self.detect_runtime_environment()
        skills = []
        if os.path.exists(LOCAL_SKILLS_DIR):
            for entry in sorted(os.listdir(LOCAL_SKILLS_DIR)):
                skill_path = os.path.join(LOCAL_SKILLS_DIR, entry)
                skill_md = os.path.join(skill_path, "SKILL.md")
                if os.path.isdir(skill_path) and os.path.exists(skill_md):
                    skills.append({
                        "name": entry,
                        "path": skill_md,
                        "target_environment": env_info["mode"],
                        "env_description": env_info["description"]
                    })
        return skills

if __name__ == "__main__":
    manager = SkillManagerEngine()
    print("Detected Runtime Environment:", manager.detect_runtime_environment())
    res = manager.install_bundled_skills()
    print("Install Result:", res)
