"""Tests for AIRemediatorEngine.autofix_bundle_scraper: patch -> verify -> rollback.

No DB/network needed: diagnose_bundle_failure degrades gracefully without Postgres,
and the LLM gateway + verification test are mocked per-test.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.observability.ai_remediator import AIRemediatorEngine

ORIGINAL_CODE = "def scrape():\n    return []\n"
GOOD_PATCH = "```python\ndef scrape():\n    return [1, 2, 3]\n```"
BAD_SYNTAX_PATCH = "```python\ndef scrape(:\n```"


@pytest.fixture
def bundle_dir(tmp_path, monkeypatch):
    bundles_root = tmp_path / "bundles"
    target = bundles_root / "zz_autofix_test"
    target.mkdir(parents=True)
    (target / "scraper.py").write_text(ORIGINAL_CODE, encoding="utf-8")
    monkeypatch.setattr("apps.observability.ai_remediator.BUNDLES_DIR", str(bundles_root))
    return target


def test_no_llm_response_fails_and_leaves_file_untouched(bundle_dir):
    engine = AIRemediatorEngine()
    with patch.object(engine.gateway, "query_provider", return_value=""):
        result = engine.autofix_bundle_scraper("zz_autofix_test")
    assert result["status"] == "FAILED"
    assert (bundle_dir / "scraper.py").read_text(encoding="utf-8") == ORIGINAL_CODE
    assert not (bundle_dir / "scraper.py.bak").exists()


def test_ast_invalid_patch_fails_and_leaves_file_untouched(bundle_dir):
    engine = AIRemediatorEngine()
    with patch.object(engine.gateway, "query_provider", return_value=BAD_SYNTAX_PATCH):
        result = engine.autofix_bundle_scraper("zz_autofix_test")
    assert result["status"] == "FAILED"
    assert "AST" in result["message"]
    assert (bundle_dir / "scraper.py").read_text(encoding="utf-8") == ORIGINAL_CODE


def test_successful_patch_is_verified_and_applied(bundle_dir):
    engine = AIRemediatorEngine()
    with (
        patch.object(engine.gateway, "query_provider", return_value=GOOD_PATCH),
        patch.object(
            engine, "run_verification_test", return_value={"status": "SUCCESS", "items_scraped": 3}
        ),
    ):
        result = engine.autofix_bundle_scraper("zz_autofix_test", verify_url="http://example.test/")
    assert result["status"] == "SUCCESS"
    assert "return [1, 2, 3]" in (bundle_dir / "scraper.py").read_text(encoding="utf-8")
    assert (bundle_dir / "scraper.py.bak").read_text(encoding="utf-8") == ORIGINAL_CODE


def test_verification_fails_both_attempts_rolls_back(bundle_dir):
    engine = AIRemediatorEngine()
    with (
        patch.object(engine.gateway, "query_provider", return_value=GOOD_PATCH),
        patch.object(
            engine, "run_verification_test", return_value={"status": "ZERO_ROWS", "items_scraped": 0}
        ),
    ):
        result = engine.autofix_bundle_scraper("zz_autofix_test", verify_url="http://example.test/")
    assert result["status"] == "FAILED"
    assert "Rolled back" in result["message"]
    assert (bundle_dir / "scraper.py").read_text(encoding="utf-8") == ORIGINAL_CODE


def test_second_attempt_succeeds_after_feedback(bundle_dir):
    engine = AIRemediatorEngine()
    verifications = [
        {"status": "ZERO_ROWS", "items_scraped": 0},
        {"status": "SUCCESS", "items_scraped": 3},
    ]
    with (
        patch.object(engine.gateway, "query_provider", return_value=GOOD_PATCH),
        patch.object(engine, "run_verification_test", side_effect=verifications),
    ):
        result = engine.autofix_bundle_scraper("zz_autofix_test", verify_url="http://example.test/")
    assert result["status"] == "SUCCESS"
    assert result["verification"]["status"] == "SUCCESS"


def test_no_verify_url_only_checks_import(bundle_dir):
    """Without --url, a syntactically-valid-but-untested patch still applies (import-only proof)."""
    engine = AIRemediatorEngine()
    with (
        patch.object(engine.gateway, "query_provider", return_value=GOOD_PATCH),
        patch.object(engine, "run_verification_test", return_value={"status": "IMPORT_OK"}),
    ):
        result = engine.autofix_bundle_scraper("zz_autofix_test")
    assert result["status"] == "SUCCESS"
    assert "import-only" in result["message"]
