import glob
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from apps.db.connection import get_db_cursor
from apps.observability.alerts import send_scraper_alert
from apps.observability.metrics import init_metrics_db, record_scraper_execution

logger = logging.getLogger(__name__)

# Dynamic Global Fallback Thresholds from .env
DEFAULT_STALENESS_SLA_HOURS = int(os.getenv("OBSERVABILITY_STALENESS_SLA_HOURS", "12"))
DEFAULT_ANOMALY_THRESHOLD_RATIO = float(os.getenv("OBSERVABILITY_ANOMALY_THRESHOLD_RATIO", "0.3"))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUNDLES_DIR = os.path.join(PROJECT_ROOT, "bundles")

STDOUT_ERROR_PATTERNS = [
    r"\[ERROR\]",
    r"\[CRITICAL\]",
    r"OperationalError",
    r"NameError",
    r"KeyError",
    r"AttributeError",
    r"Authentication failed",
    r"no password supplied",
    r"ConnectionRefusedError",
    r"Connection refused",
    r"Cloudflare challenge or 403"
]

class ScraperHealthChecker:
    """Performs automated anomaly detection, SLA staleness checks, Dagster stdout log monitoring, and health audits."""

    def __init__(self):
        init_metrics_db()

    def get_bundle_observability_settings(self, bundle_name: str) -> tuple[int, float]:
        """Loads SLA hours and anomaly ratio threshold from manifest.json or defaults to .env."""
        sla_hours = DEFAULT_STALENESS_SLA_HOURS
        anomaly_ratio = DEFAULT_ANOMALY_THRESHOLD_RATIO

        manifest_path = os.path.join(BUNDLES_DIR, bundle_name, "manifest.json")
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    data = json.load(f)
                obs = data.get("observability", {})
                if "staleness_sla_hours" in obs:
                    sla_hours = int(obs["staleness_sla_hours"])
                if "anomaly_threshold_ratio" in obs:
                    anomaly_ratio = float(obs["anomaly_threshold_ratio"])
            except Exception as e:
                logger.warning(f"Could not parse manifest observability settings for '{bundle_name}': {e}")

        return sla_hours, anomaly_ratio

    def scan_dagster_stdout_logs(self) -> dict[str, list[str]]:
        """Scans Dagster process stdout/stderr log files for active errors and matches them to bundles."""
        dagster_home = os.getenv("DAGSTER_HOME", "/tmp/dagster_home")
        log_patterns = [
            f"{dagster_home}/**/*.log",
            "/tmp/dagster_home/**/*.log",
            "/opt/dagster/**/*.log"
        ]

        found_logs = []
        for pat in log_patterns:
            found_logs.extend(glob.glob(pat, recursive=True))

        bundle_stdout_errors = {}
        combined_regex = re.compile("|".join(STDOUT_ERROR_PATTERNS), re.IGNORECASE)

        for log_file in found_logs:
            try:
                if not os.path.isfile(log_file) or os.path.getsize(log_file) == 0:
                    continue
                
                with open(log_file, encoding="utf-8", errors="ignore") as f:
                    # Read last 300 lines of process stdout/stderr
                    lines = f.readlines()[-300:]

                for line in lines:
                    if combined_regex.search(line):
                        # Attempt to resolve bundle context from log text or default to active bundle
                        matched_bundle = "unknown_bundle"
                        if "bundle" in line:
                            b_match = re.search(r"bundle[s]?/([a-zA-Z0-9_]+)", line)
                            if b_match:
                                matched_bundle = b_match.group(1)

                        clean_err = line.strip()[:140]
                        if matched_bundle not in bundle_stdout_errors:
                            bundle_stdout_errors[matched_bundle] = []

                        if clean_err not in bundle_stdout_errors[matched_bundle]:
                            bundle_stdout_errors[matched_bundle].append(clean_err)
            except Exception as e:
                logger.debug(f"Could not scan log file '{log_file}': {e}")

        return bundle_stdout_errors

    def cleanup_orphaned_dagster_runs(self):
        """Automatically checks Dagster instance storage for orphaned runs stuck in STARTED state and cancels them."""
        try:
            from dagster import DagsterInstance, DagsterRunStatus, RunsFilter
            instance = DagsterInstance.get()
            stuck_statuses = [DagsterRunStatus.STARTED, DagsterRunStatus.STARTING, DagsterRunStatus.QUEUED]
            # update_timestamp lives on RunRecord, not on DagsterRun itself.
            records = instance.get_run_records(RunsFilter(statuses=stuck_statuses))
            now = datetime.now(timezone.utc)
            for record in records:
                stuck_seconds = (now - record.update_timestamp).total_seconds()
                if stuck_seconds > 1800:
                    run_id = record.dagster_run.run_id
                    logger.warning(f"⚡ Observability Cleaner: Canceling orphaned Dagster run {run_id[:8]} (stuck >30m)")
                    instance.report_run_canceled(record.dagster_run)
        except Exception as e:
            logger.debug(f"Could not audit/cancel orphaned Dagster runs: {e}")

    def check_all_scrapers_health(self, *, emit_alerts: bool = True) -> list[dict[str, Any]]:
        """Audits all scrapers using connection pool, Dagster stdout, and per-bundle thresholds.

        ``emit_alerts=False`` is read-only (operator ``summary``): no notifier, no extra
        FAILED rows written to ``scraper_execution_logs``.
        """
        self.cleanup_orphaned_dagster_runs()
        rows = []
        try:
            with get_db_cursor(commit=False) as cursor:
                cursor.execute("SELECT * FROM v_scraper_health_status;")
                rows = cursor.fetchall()
        except Exception as e:
            logger.error(f"Error reading scraper health status from DB pool: {e}")
            rows = []

        # Scan Dagster process stdout/stderr logs
        stdout_errors_by_bundle = self.scan_dagster_stdout_logs()

        health_results = []
        now = datetime.now(timezone.utc)

        # Gather list of all bundles from directory if DB rows empty
        all_bundle_names = set([r["bundle_name"] for r in rows]) if rows else set()
        if os.path.exists(BUNDLES_DIR):
            for item in os.listdir(BUNDLES_DIR):
                if os.path.isdir(os.path.join(BUNDLES_DIR, item)) and not item.startswith(".") and not item.startswith("__"):
                    all_bundle_names.add(item)

        for bundle_name in sorted(all_bundle_names):
            r = next((row for row in rows if row["bundle_name"] == bundle_name), {})
            total_runs = r.get("total_runs_24h") or 0
            success_runs = r.get("success_runs_24h") or 0
            anomaly_runs = r.get("anomaly_runs_24h") or 0
            last_success = r.get("last_success_timestamp")

            sla_hours, anomaly_threshold_ratio = self.get_bundle_observability_settings(bundle_name)

            status = "HEALTHY"
            issues = []

            # Check 1: Dagster Process STDOUT / STDERR Errors
            if stdout_errors_by_bundle.get(bundle_name):
                status = "DEGRADED"
                top_err = stdout_errors_by_bundle[bundle_name][0]
                issues.append(f"Dagster process STDOUT error detected: '{top_err}'")
                if emit_alerts:
                    record_scraper_execution(
                        bundle_name=bundle_name,
                        status="FAILED",
                        items_scraped=0,
                        error_message=f"STDOUT: {top_err}",
                    )
                    send_scraper_alert(bundle_name, "DAGSTER_STDOUT_ERROR", issues[-1])

            # Check 2: Zero-Row / Anomaly Rate
            if anomaly_runs > 0 and (anomaly_runs / max(1, total_runs)) >= anomaly_threshold_ratio:
                status = "DEGRADED"
                issues.append(
                    f"High anomaly rate ({anomaly_runs}/{total_runs} runs returned 0 items, threshold: {int(anomaly_threshold_ratio*100)}%). Target HTML selector changed?"
                )
                if emit_alerts:
                    send_scraper_alert(bundle_name, "ZERO_ROWS_ANOMALY", issues[-1])

            # Check 3: Staleness SLA
            if last_success:
                # created_at is TIMESTAMP WITH TIME ZONE; assume UTC if the driver ever hands us a naive value.
                last_success_utc = (
                    last_success.replace(tzinfo=timezone.utc)
                    if last_success.tzinfo is None
                    else last_success.astimezone(timezone.utc)
                )
                hours_since_success = (now - last_success_utc).total_seconds() / 3600.0
                if hours_since_success > sla_hours:
                    status = "CRITICAL"
                    issues.append(
                        f"Staleness SLA breached! Last successful run was {hours_since_success:.1f} hours ago (SLA: {sla_hours}h)."
                    )
                    if emit_alerts:
                        send_scraper_alert(bundle_name, "SLA_STALENESS_EXCEEDED", issues[-1])

            health_results.append({
                "bundle_name": bundle_name,
                "status": status,
                "total_runs_24h": total_runs,
                "success_runs_24h": success_runs,
                "items_scraped_24h": r.get("total_items_scraped_24h") or 0,
                "last_success_timestamp": str(last_success) if last_success else "Never",
                "configured_sla_hours": sla_hours,
                "configured_anomaly_ratio": anomaly_threshold_ratio,
                "stdout_errors": stdout_errors_by_bundle.get(bundle_name, []),
                "issues": issues
            })

        return health_results

    def _last_execution_log(self, bundle_name: str) -> dict[str, Any] | None:
        try:
            with get_db_cursor(commit=False) as cursor:
                cursor.execute(
                    """
                    SELECT status, items_scraped, http_403_count, http_429_count,
                           error_message, created_at
                    FROM scraper_execution_logs
                    WHERE bundle_name = %s
                    ORDER BY created_at DESC
                    LIMIT 1;
                    """,
                    (bundle_name,),
                )
                row = cursor.fetchone()
        except Exception as e:
            logger.debug("last execution log unavailable for '%s': %s", bundle_name, e)
            return None
        if not row:
            return None
        payload = dict(row)
        created = payload.get("created_at")
        if hasattr(created, "isoformat"):
            payload["created_at"] = created.isoformat()
        err = payload.get("error_message")
        if isinstance(err, str) and len(err) > 140:
            payload["error_message"] = err[:140]
        return payload

    @staticmethod
    def _action_for(status: str) -> str:
        if status == "CRITICAL":
            return "REMEDIATE"
        if status == "DEGRADED":
            return "WATCH"
        if status == "HEALTHY":
            return "OK"
        return "WATCH"

    def summarize_bundle(self, bundle_name: str) -> dict[str, Any]:
        """Compact one-bundle digest for operator sessions (no source code)."""
        exists = os.path.isdir(os.path.join(BUNDLES_DIR, bundle_name))
        report = self.check_all_scrapers_health(emit_alerts=False)
        row = next((r for r in report if r["bundle_name"] == bundle_name), None)
        if row is None:
            return {
                "protocol": "HAP/1.0",
                "kind": "summary",
                "bundle_name": bundle_name,
                "bundle_exists": exists,
                "status": "UNKNOWN",
                "action": "STOP" if not exists else "WATCH",
                "error": (
                    f"Bundle '{bundle_name}' not found under bundles/."
                    if not exists
                    else "No health row yet (no runs)."
                ),
            }
        issues = [str(i)[:140] for i in (row.get("issues") or [])[:2]]
        status = row["status"]
        action = self._action_for(status)
        if issues and action == "OK":
            action = "WATCH"
        next_cmd = None
        if action == "REMEDIATE":
            next_cmd = f"harbor agent-protocol diagnose {bundle_name}"
        return {
            "protocol": "HAP/1.0",
            "kind": "summary",
            "bundle_name": bundle_name,
            "bundle_exists": exists,
            "status": status,
            "action": action,
            "runs_24h": row.get("total_runs_24h") or 0,
            "success_24h": row.get("success_runs_24h") or 0,
            "items_24h": row.get("items_scraped_24h") or 0,
            "last_success": row.get("last_success_timestamp") or "Never",
            "sla_hours": row.get("configured_sla_hours"),
            "issues": issues,
            "last_log": self._last_execution_log(bundle_name),
            "next": next_cmd,
        }

    def summarize_all(self) -> dict[str, Any]:
        """Fleet digest: one short row per bundle, no code, no last_log."""
        report = self.check_all_scrapers_health(emit_alerts=False)
        bundles = []
        worst = "OK"
        for row in report:
            action = self._action_for(row["status"])
            issue_n = len(row.get("issues") or [])
            if issue_n and action == "OK":
                action = "WATCH"
            if action == "REMEDIATE":
                worst = "REMEDIATE"
            elif action == "WATCH" and worst == "OK":
                worst = "WATCH"
            bundles.append(
                {
                    "name": row["bundle_name"],
                    "status": row["status"],
                    "action": action,
                    "items_24h": row.get("items_scraped_24h") or 0,
                    "runs_24h": row.get("total_runs_24h") or 0,
                    "issues_n": issue_n,
                }
            )
        return {
            "protocol": "HAP/1.0",
            "kind": "summary_all",
            "action": worst,
            "count": len(bundles),
            "bundles": bundles,
            "next": "harbor agent-protocol summary <name>" if worst != "OK" else None,
        }

if __name__ == "__main__":
    checker = ScraperHealthChecker()
    report = checker.check_all_scrapers_health()
    print(json.dumps(report, indent=2))
