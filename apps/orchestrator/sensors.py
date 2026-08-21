import logging
from dagster import sensor, RunRequest, SkipReason, SensorEvaluationContext
from apps.observability.health_checker import ScraperHealthChecker

logger = logging.getLogger(__name__)

@sensor(name="scraper_health_sensor", minimum_interval_seconds=300)
def scraper_health_sensor(context: SensorEvaluationContext):
    """Dagster sensor that monitors scraper health and triggers auto-remediation jobs in Dagster UI."""
    checker = ScraperHealthChecker()
    report = checker.check_all_scrapers_health()

    degraded_bundles = [r["bundle_name"] for r in report if r["status"] in ["DEGRADED", "CRITICAL"]]

    if not degraded_bundles:
        return SkipReason("All scrapers are HEALTHY. No auto-remediation needed.")

    run_requests = []
    for bundle_name in degraded_bundles:
        context.log.info(f"🚨 Sensor detected anomaly in bundle '{bundle_name}'. Triggering Dagster remediation run.")
        run_requests.append(
            RunRequest(
                run_key=f"auto_repair_{bundle_name}_{context.cursor}",
                run_config={
                    "ops": {
                        "auto_repair_op": {
                            "inputs": {"bundle_name": bundle_name}
                        }
                    }
                }
            )
        )

    return run_requests

if __name__ == "__main__":
    print("Testing Dagster scraper_health_sensor initialization...")
    checker = ScraperHealthChecker()
    print("Scraper Health Audit:", checker.check_all_scrapers_health())
