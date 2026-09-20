"""Platform runtime commands: doctor, up, down, status, health, uninstall."""
from __future__ import annotations

import os
import shutil
import subprocess

import typer

from apps.cli.env_files import ensure_compose_profile_env
from apps.cli.paths import PROJECT_ROOT


def check_active_runtime() -> str:
    """Return 'KUBERNETES', 'DOCKER_COMPOSE', or 'NONE'."""
    if shutil.which("kubectl"):
        try:
            res = subprocess.run(
                ["kubectl", "get", "pods", "-n", "dataharbor-local"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and "dagster" in res.stdout:
                return "KUBERNETES"
        except Exception:
            pass

    if shutil.which("docker"):
        try:
            res = subprocess.run(
                ["docker", "ps", "--filter", "name=dataharbor", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
            )
            if res.stdout.strip():
                return "DOCKER_COMPOSE"
        except Exception:
            pass

    return "NONE"


def doctor() -> None:
    """Check system dependencies and publish readiness."""
    from apps.cli.publish import check_publish_readiness

    print("\n🩺 DATAHARBOR SYSTEM DOCTOR (Dependency Check):")
    print("=" * 60)

    deps = {
        "uv": ("uv", True),
        "Docker": ("docker", True),
        "Tilt": ("tilt", False),
        "Kind": ("kind", True),
        "Python 3": ("python3", True),
        "Git": ("git", True),
    }

    all_ok = True
    for name, (binary, required) in deps.items():
        path = shutil.which(binary)
        if path:
            print(f"  ✅ {name:<12} : Found at {path}")
        else:
            label = "Required" if required else "Optional (compose fallback)"
            print(f"  ❌ {name:<12} : NOT FOUND ({label})")
            if required:
                all_ok = False

    print("=" * 60)
    print("\n📣 PUBLISH READINESS (bundles / extractors):")
    print("=" * 60)
    readiness = check_publish_readiness()
    if readiness.git_ok:
        print(f"  ✅ git          : {readiness.git_path}")
    else:
        print("  ❌ git          : NOT FOUND (required for install/publish)")
        all_ok = False

    if readiness.git_user_name:
        print(f"  ✅ user.name    : {readiness.git_user_name}")
    else:
        print("  ⚠️ user.name    : not set (required to commit on publish)")

    if readiness.git_user_email:
        print(f"  ✅ user.email   : {readiness.git_user_email}")
    else:
        print("  ⚠️ user.email   : not set (required to commit on publish)")

    if readiness.gh_ok:
        auth = "authenticated" if readiness.gh_authed else "NOT authenticated"
        symbol = "✅" if readiness.gh_authed else "⚠️"
        print(f"  {symbol} gh           : {readiness.gh_path} ({auth})")
    else:
        print("  ⚠️ gh           : not found (optional; auto-create GitHub repos)")

    if readiness.ssh_key_found:
        print("  ✅ SSH pubkey   : found under ~/.ssh/id_*.pub")
    else:
        print("  ⚠️ SSH pubkey   : none found (HTTPS credentials may still work)")

    print("=" * 60)
    if all_ok:
        print("✨ Required runtime dependencies are available on PATH.")
        if not readiness.can_commit or not readiness.can_auto_create_github:
            print(
                "💡 Publish tips: set git user.name/email; optional `gh auth login` "
                "or use `harbor … publish --remote <url>`.\n"
            )
        else:
            print("✨ Publish readiness looks good (git identity + gh auth).\n")
    else:
        print("⚠️ Missing required dependencies. Install them before proceeding.\n")
        raise typer.Exit(code=1)


def up(
    compose: bool = typer.Option(False, "--compose", help="Use Docker Compose instead of Kubernetes Tilt"),
    with_n8n: bool = typer.Option(
        False,
        "--with-n8n",
        help="Also start optional n8n (compose profile / ENABLE_N8N=1 for Tilt)",
    ),
) -> None:
    """Start DataHarbor platform microservices."""
    env = "compose" if compose else "tilt"
    active_runtime = check_active_runtime()

    if env == "compose" and active_runtime == "KUBERNETES":
        print("\n❌ DEPLOYMENT BLOCKED: DataHarbor is already running in KUBERNETES (Tilt).")
        print("💡 You cannot deploy in Docker Compose while Kubernetes is active.")
        print("👉 Please run 'harbor down' first to safely stop Kubernetes services.\n")
        raise typer.Exit(code=1)

    if env == "tilt" and active_runtime == "DOCKER_COMPOSE":
        print("\n❌ DEPLOYMENT BLOCKED: DataHarbor is already running in DOCKER COMPOSE.")
        print("💡 You cannot deploy in Kubernetes while Docker Compose is active.")
        print("👉 Please run 'harbor down' first to safely stop Docker Compose services.\n")
        raise typer.Exit(code=1)

    print(f"\n🚀 Starting DataHarbor Platform Services (Environment: {env.upper()})...")
    print("=" * 60)
    try:
        if env == "tilt":
            if not shutil.which("tilt"):
                print("❌ 'tilt' binary not found. Falling back to docker-compose...")
                env = "compose"
            else:
                tilt_env = os.environ.copy()
                if with_n8n:
                    tilt_env["ENABLE_N8N"] = "1"
                subprocess.run(["tilt", "up"], check=True, env=tilt_env)
                return

        if env == "compose":
            cmd = ["docker", "compose"]
            if with_n8n:
                from pathlib import Path

                note = ensure_compose_profile_env(Path(PROJECT_ROOT), "n8n")
                if note:
                    print(f"📎 {note}")
                cmd.extend(["--profile", "n8n"])
            cmd.extend(["up", "-d"])
            subprocess.run(cmd, check=True)
            print("✨ DataHarbor services started in background via Docker Compose!")
            if with_n8n:
                print("📎 Optional n8n profile enabled (http://localhost:56780).")
            print("Run 'harbor status' to check service health.\n")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to start DataHarbor services: {e}")
        raise typer.Exit(code=1) from e
    except FileNotFoundError as e:
        print(f"❌ '{e.filename}' not found on PATH. Install Docker (and Docker Compose) first.")
        raise typer.Exit(code=1) from e
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")


def down(
    compose: bool = typer.Option(False, "--compose", help="Use Docker Compose instead of Kubernetes Tilt"),
) -> None:
    """Stop DataHarbor platform services."""
    print("\n🛑 Stopping DataHarbor Platform Services...")
    print("=" * 60)
    try:
        if compose or not shutil.which("tilt"):
            subprocess.run(["docker", "compose", "down"], check=True)
        else:
            subprocess.run(["tilt", "down"], check=True)
        print("✨ DataHarbor services stopped successfully.\n")
    except FileNotFoundError as e:
        print(f"❌ '{e.filename}' not found on PATH. Install Docker (and Docker Compose) first.")
        raise typer.Exit(code=1) from e
    except Exception as e:
        print(f"Error stopping services: {e}")
        raise typer.Exit(code=1) from e


def status() -> None:
    """Display health and status of running microservices."""
    print("\n📊 DATAHARBOR MICROSERVICES STATUS AUDIT:")
    print("=" * 70)

    if shutil.which("kubectl"):
        try:
            res_k8s = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "pods",
                    "-n",
                    "dataharbor-local",
                    "-o",
                    "custom-columns=POD_NAME:.metadata.name,STATUS:.status.phase,RESTARTS:.status.containerStatuses[0].restartCount,AGE:.metadata.creationTimestamp",
                ],
                capture_output=True,
                text=True,
            )
            if res_k8s.returncode == 0 and "dagster" in res_k8s.stdout:
                print("☸️ KUBERNETES (KIND / TILT) RUNNING PODS:")
                print("-" * 70)
                print(res_k8s.stdout.strip())
                print("-" * 70)
        except Exception:
            pass

    if shutil.which("docker"):
        try:
            res_docker = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    "name=dataharbor",
                    "--format",
                    "table {{.Names}}\t{{.Status}}\t{{.Ports}}",
                ],
                capture_output=True,
                text=True,
            )
            if res_docker.stdout.strip():
                print("\n🐳 DOCKER COMPOSE RUNNING CONTAINERS:")
                print("-" * 70)
                print(res_docker.stdout.strip())
                print("-" * 70)
        except Exception:
            pass
    print()


def health(
    fix: str | None = typer.Option(
        None, "--fix", help="Generate AI Auto-Remediation prompt for a bundle"
    ),
    auto_fix: str | None = typer.Option(
        None, "--auto-fix", help="Autonomously patch scraper.py for a bundle"
    ),
) -> None:
    """Audit scrapers: zero-row anomalies, SLA staleness, AI auto-healing."""
    if auto_fix:
        print(f"\n🤖 EXECUTING AUTONOMOUS AI REPAIR FOR BUNDLE: '{auto_fix}'")
        print("=" * 70)
        from apps.observability.ai_remediator import AIRemediatorEngine

        remediator = AIRemediatorEngine()
        result = remediator.autofix_bundle_scraper(auto_fix)
        status_symbol = "✅ SUCCESS" if result["status"] == "SUCCESS" else "❌ FAILED"
        print(f"[{status_symbol}] {result['message']}\n")
        if result["status"] != "SUCCESS":
            raise typer.Exit(code=1)
        return

    if fix:
        print(f"\n🤖 GENERATING AI AUTO-REMEDIATION DIAGNOSTIC FOR: '{fix}'")
        print("=" * 70)
        from apps.observability.ai_remediator import AIRemediatorEngine

        remediator = AIRemediatorEngine()
        diag = remediator.diagnose_bundle_failure(fix)
        print(diag["ai_prompt"])
        return

    print("\n🩺 DATAHARBOR SCRAPER OBSERVABILITY & HEALTH AUDIT:")
    print("=" * 70)
    try:
        from apps.observability.health_checker import ScraperHealthChecker

        checker = ScraperHealthChecker()
        report = checker.check_all_scrapers_health()

        if not report:
            print("No scraper execution metrics logged yet.")
            print("Run scrapers to populate telemetry logs.\n")
            return

        for r in report:
            status_symbol = (
                "✅ HEALTHY"
                if r["status"] == "HEALTHY"
                else ("⚠️ DEGRADED" if r["status"] == "DEGRADED" else "🚨 CRITICAL")
            )
            print(f"• Bundle: {r['bundle_name']} [{status_symbol}]")
            print(f"  Runs 24h:       {r['success_runs_24h']}/{r['total_runs_24h']}")
            print(f"  Items 24h:      {r['items_scraped_24h']:,}")
            print(f"  Last Success:   {r['last_success_timestamp']}")
            if r["issues"]:
                print("  Issues:")
                for issue in r["issues"]:
                    print(f"    - {issue}")
                print(f"  💡 Run AI Diagnosis: harbor health --fix {r['bundle_name']}")
                print(f"  🤖 Run Autonomous AI Fix: harbor health --auto-fix {r['bundle_name']}")
            print("-" * 70)
        print()
    except Exception as e:
        print(f"Error checking scraper health: {e}")
        raise typer.Exit(code=1) from e


def uninstall(
    purge: bool = typer.Option(False, "--purge", help="Purge without master data backup"),
    keep_data: bool = typer.Option(
        False, "--keep-data", help="Force master data backup before uninstall"
    ),
) -> None:
    """Safely uninstall DataHarbor with optional data backup."""
    uninstall_script = os.path.join(PROJECT_ROOT, "uninstall.sh")
    if not os.path.isfile(uninstall_script):
        print(f"❌ '{uninstall_script}' not found. Nothing to run.")
        raise typer.Exit(code=1)
    cmd = [uninstall_script]
    if purge:
        cmd.append("--purge")
    elif keep_data:
        cmd.append("--keep-data")
    raise typer.Exit(code=subprocess.run(cmd).returncode)
