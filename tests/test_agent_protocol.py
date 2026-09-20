"""HAP v1.0 diagnose/test behavior (no live network)."""
from __future__ import annotations

import json
from pathlib import Path

from apps.observability.ai_remediator import AIRemediatorEngine

BUNDLES_ROOT = Path(__file__).resolve().parents[1] / "bundles"


def test_diagnose_missing_bundle_does_not_invent_html_fields():
    payload = AIRemediatorEngine().get_compressed_diagnostic_json("zz_no_such_bundle")
    assert payload["protocol"] == "HAP/1.0"
    assert payload["bundle_name"] == "zz_no_such_bundle"
    assert payload["bundle_exists"] is False
    assert payload["scraper_exists"] is False
    if not payload.get("last_log", {}).get("status"):
        assert payload["status"] == "UNKNOWN"
    assert "failing_selectors" not in payload
    assert "html_sample" not in payload
    assert "failing_selectors" in payload["missing_fields"]
    json.dumps(payload, default=str)


def test_verification_missing_bundle_fails():
    result = AIRemediatorEngine().run_verification_test("zz_no_such_bundle")
    assert result["status"] == "FAILED"
    assert result["phase"] == "lookup"


def test_verification_import_ok_on_default_scaffold():
    from apps.bundle.scaffold import create_bundle

    name = "zz_hap_verify_demo"
    target = BUNDLES_ROOT / name
    if target.exists():
        import shutil

        shutil.rmtree(target)

    try:
        create_bundle(name, description="hap test")
        result = AIRemediatorEngine().run_verification_test(name)
        assert result["status"] == "IMPORT_OK"
        assert result["live_scrape"] is False
    finally:
        if target.exists():
            import shutil

            shutil.rmtree(target)
        import sys

        mod = f"bundles.{name}"
        for key in list(sys.modules):
            if key == mod or key.startswith(mod + "."):
                del sys.modules[key]


def test_operator_summary_missing_bundle_is_stop():
    from apps.observability.health_checker import ScraperHealthChecker

    payload = ScraperHealthChecker().summarize_bundle("zz_no_such_bundle")
    assert payload["kind"] == "summary"
    assert payload["bundle_exists"] is False
    assert payload["action"] == "STOP"
    assert "code_snippet" not in payload
    assert "html_sample" not in payload
    json.dumps(payload, separators=(",", ":"), default=str)


def test_operator_summary_all_has_no_source_fields():
    from apps.observability.health_checker import ScraperHealthChecker

    payload = ScraperHealthChecker().summarize_all()
    assert payload["kind"] == "summary_all"
    assert "code_snippet" not in payload
    for row in payload["bundles"]:
        assert set(row) <= {
            "name",
            "status",
            "action",
            "items_24h",
            "runs_24h",
            "issues_n",
        }


def test_skill_manager_env_block_mentions_host_ports():
    from apps.skills.skill_manager import SkillManagerEngine

    block = SkillManagerEngine().generate_environment_context_block(
        {
            "mode": "DOCKER_COMPOSE",
            "description": "test",
            "postgres_host": "postgres (Port 5432)",
            "clickhouse_host": "clickhouse (Port 8123)",
            "s3_url": "http://seaweedfs:8333",
            "qdrant_url": "http://qdrant:6333",
            "dagster_url": "http://localhost:3000",
        }
    )
    assert "54320" in block
    assert "8334" in block
    assert "dataharbor_dagster" in block


def test_skill_install_targets_cover_major_agents():
    from apps.skills.skill_manager import default_global_skill_targets

    joined = " ".join(default_global_skill_targets())
    assert ".codex/skills" in joined
    assert ".claude/skills" in joined
    assert ".gemini" in joined
