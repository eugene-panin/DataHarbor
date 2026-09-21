"""Tests for AIRemediatorEngine.autofix_bundle_scraper: patch -> verify -> rollback.

No DB/network needed: diagnose_bundle_failure degrades gracefully without Postgres,
and the LLM gateway + verification test are mocked per-test.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from apps.observability.ai_remediator import AIRemediatorEngine

ORIGINAL_CODE = "def scrape():\n    return []\n"
GOOD_PATCH = "```python\ndef scrape():\n    return [1, 2, 3]\n```"
BAD_SYNTAX_PATCH = "```python\ndef scrape(:\n```"

EXTRACTOR_ORIGINAL = "def parse(html, url):\n    return []\n"


@pytest.fixture
def bundle_dir(tmp_path, monkeypatch):
    bundles_root = tmp_path / "bundles"
    target = bundles_root / "zz_autofix_test"
    target.mkdir(parents=True)
    (target / "scraper.py").write_text(ORIGINAL_CODE, encoding="utf-8")
    monkeypatch.setattr("apps.observability.ai_remediator.BUNDLES_DIR", str(bundles_root))
    return target


@pytest.fixture
def extractor_dir(bundle_dir, tmp_path, monkeypatch):
    """A bundle that declares one extractor — for testing extractor-targeted patches (F05)."""
    (bundle_dir / "manifest.json").write_text(
        json.dumps({"requirements": {"extractors": ["zz_extractor"]}}), encoding="utf-8"
    )
    extractors_root = tmp_path / "extractors"
    target = extractors_root / "zz_extractor"
    target.mkdir(parents=True)
    (target / "extractor.py").write_text(EXTRACTOR_ORIGINAL, encoding="utf-8")
    monkeypatch.setattr("apps.extractor.paths.EXTRACTORS_DIR", str(extractors_root))
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


# --- F03 regression: a request failure on the SECOND attempt must still roll back
# the first attempt's patch, not return early and leave it on disk. ---


def test_second_attempt_llm_failure_still_rolls_back_first_patch(bundle_dir):
    engine = AIRemediatorEngine()
    with (
        patch.object(engine.gateway, "query_provider", side_effect=[GOOD_PATCH, ""]),
        patch.object(engine, "run_verification_test", return_value={"status": "ZERO_ROWS", "items_scraped": 0}),
    ):
        result = engine.autofix_bundle_scraper("zz_autofix_test", verify_url="http://example.test/")
    assert result["status"] == "FAILED"
    assert "Rolled back" in result["message"]
    # The critical assertion: attempt 1's patch (which failed verification) must NOT
    # be left on disk just because attempt 2 never produced a response.
    assert (bundle_dir / "scraper.py").read_text(encoding="utf-8") == ORIGINAL_CODE


def test_second_attempt_ast_invalid_still_rolls_back_first_patch(bundle_dir):
    engine = AIRemediatorEngine()
    with (
        patch.object(engine.gateway, "query_provider", side_effect=[GOOD_PATCH, BAD_SYNTAX_PATCH]),
        patch.object(engine, "run_verification_test", return_value={"status": "ZERO_ROWS", "items_scraped": 0}),
    ):
        result = engine.autofix_bundle_scraper("zz_autofix_test", verify_url="http://example.test/")
    assert result["status"] == "FAILED"
    assert (bundle_dir / "scraper.py").read_text(encoding="utf-8") == ORIGINAL_CODE


# --- F05 regression: selector drift lives in extractor.py, not scraper.py. The
# diagnostic prompt must offer it as a patch target, and a model that patches only
# the extractor must not be forced through (or silently dropped by) a scraper-only
# patch path. ---


def test_prompt_includes_declared_extractor_source(extractor_dir, bundle_dir):
    engine = AIRemediatorEngine()
    diag = engine.diagnose_bundle_failure("zz_autofix_test")
    assert "extractors/zz_extractor/extractor.py" in diag["candidate_files"]
    assert "extractors/zz_extractor/extractor.py" in diag["ai_prompt"]
    assert EXTRACTOR_ORIGINAL.strip() in diag["ai_prompt"]


def test_model_can_patch_only_the_extractor(extractor_dir, bundle_dir):
    """The demo's actual failure mode: extractor.py is broken, scraper.py is fine.
    A correct patch touches only the extractor — scraper.py must stay untouched."""
    extractor_patch = (
        "### FILE: extractors/zz_extractor/extractor.py\n"
        "```python\n"
        "def parse(html, url):\n"
        "    return [{'x': 1}]\n"
        "```\n"
    )
    engine = AIRemediatorEngine()
    with (
        patch.object(engine.gateway, "query_provider", return_value=extractor_patch),
        patch.object(engine, "run_verification_test", return_value={"status": "SUCCESS", "items_scraped": 1}),
    ):
        result = engine.autofix_bundle_scraper("zz_autofix_test", verify_url="http://example.test/")
    assert result["status"] == "SUCCESS"
    assert result["patched_files"] == ["extractors/zz_extractor/extractor.py"]
    assert "return [{'x': 1}]" in (extractor_dir / "extractor.py").read_text(encoding="utf-8")
    assert (extractor_dir / "extractor.py.bak").read_text(encoding="utf-8") == EXTRACTOR_ORIGINAL
    # scraper.py was never part of the fix — must be untouched.
    assert (bundle_dir / "scraper.py").read_text(encoding="utf-8") == ORIGINAL_CODE
    assert not (bundle_dir / "scraper.py.bak").exists()


def test_model_can_patch_both_files_in_one_response(extractor_dir, bundle_dir):
    multi_patch = (
        "### FILE: bundles/zz_autofix_test/scraper.py\n"
        "```python\ndef scrape():\n    return [1]\n```\n\n"
        "### FILE: extractors/zz_extractor/extractor.py\n"
        "```python\ndef parse(html, url):\n    return [{'x': 1}]\n```\n"
    )
    engine = AIRemediatorEngine()
    with (
        patch.object(engine.gateway, "query_provider", return_value=multi_patch),
        patch.object(engine, "run_verification_test", return_value={"status": "SUCCESS", "items_scraped": 1}),
    ):
        result = engine.autofix_bundle_scraper("zz_autofix_test", verify_url="http://example.test/")
    assert result["status"] == "SUCCESS"
    assert set(result["patched_files"]) == {
        "bundles/zz_autofix_test/scraper.py",
        "extractors/zz_extractor/extractor.py",
    }
    assert "return [1]" in (bundle_dir / "scraper.py").read_text(encoding="utf-8")
    assert "return [{'x': 1}]" in (extractor_dir / "extractor.py").read_text(encoding="utf-8")


# --- F04 regression: verification must not accept stale module state or
# non-record items as proof of a working scrape. ---


def test_fresh_module_import_does_not_leak_stale_names(tmp_path):
    """importlib.reload() re-executes into the SAME namespace, so a name the new
    source removed can still be found from the previous version. A fresh module
    object has no prior state to leak from."""
    scraper_path = tmp_path / "scraper.py"
    scraper_path.write_text(
        "OLD_HELPER = 'still here'\ndef scrape(target_url=None):\n    return [OLD_HELPER]\n",
        encoding="utf-8",
    )
    engine = AIRemediatorEngine()
    mod1 = engine._fresh_module_import("bundles.zz_stale_test.scraper", str(scraper_path))
    assert mod1.OLD_HELPER == "still here"

    scraper_path.write_text("def scrape(target_url=None):\n    return [{'x': 1}]\n", encoding="utf-8")
    mod2 = engine._fresh_module_import("bundles.zz_stale_test.scraper", str(scraper_path))
    assert not hasattr(mod2, "OLD_HELPER")
    assert mod2.scrape()[0] == {"x": 1}


def test_verification_rejects_non_dict_items_as_success(tmp_path, monkeypatch):
    """[None] is a non-empty list, but it isn't scraped data — must not read as SUCCESS."""
    bundles_root = tmp_path / "bundles"
    target = bundles_root / "zz_verify_test"
    target.mkdir(parents=True)
    (target / "scraper.py").write_text("def scrape(target_url=None):\n    return [None, None]\n", encoding="utf-8")
    monkeypatch.setattr("apps.observability.ai_remediator.BUNDLES_DIR", str(bundles_root))

    engine = AIRemediatorEngine()
    result = engine.run_verification_test("zz_verify_test", url="http://example.test/")
    assert result["status"] == "ZERO_ROWS"
    assert result["items_scraped"] == 0


def test_verification_counts_only_real_dict_records(tmp_path, monkeypatch):
    bundles_root = tmp_path / "bundles"
    target = bundles_root / "zz_verify_test2"
    target.mkdir(parents=True)
    (target / "scraper.py").write_text(
        "def scrape(target_url=None):\n    return [{'a': 1}, {}, 'not a record']\n", encoding="utf-8"
    )
    monkeypatch.setattr("apps.observability.ai_remediator.BUNDLES_DIR", str(bundles_root))

    engine = AIRemediatorEngine()
    result = engine.run_verification_test("zz_verify_test2", url="http://example.test/")
    assert result["status"] == "SUCCESS"
    assert result["items_scraped"] == 1
    assert result["discarded_non_record_items"] == 2


def test_patch_for_undeclared_path_is_ignored_and_fails_safely(bundle_dir):
    """A model that only offers a patch for a file we never showed it must not be
    allowed to write there — no candidate files means no patch is applied."""
    sneaky_patch = "### FILE: apps/db/connection.py\n```python\nDROP = True\n```\n"
    engine = AIRemediatorEngine()
    with patch.object(engine.gateway, "query_provider", return_value=sneaky_patch):
        result = engine.autofix_bundle_scraper("zz_autofix_test")
    assert result["status"] == "FAILED"
    assert "no patch for a known file" in result["message"].lower()
    assert (bundle_dir / "scraper.py").read_text(encoding="utf-8") == ORIGINAL_CODE


# --- _invoke_scrape: must call the scraper exactly once (additional observation) ---


def test_invoke_scrape_calls_keyword_only_param_by_name():
    calls = []

    def scrape(*, target_url):
        calls.append(target_url)
        return []

    AIRemediatorEngine._invoke_scrape(scrape, "http://example.test/")
    assert calls == ["http://example.test/"]


def test_invoke_scrape_calls_positional_only_param_positionally():
    calls = []

    def scrape(url, /):
        calls.append(url)
        return []

    AIRemediatorEngine._invoke_scrape(scrape, "http://example.test/")
    assert calls == ["http://example.test/"]


def test_invoke_scrape_does_not_retry_and_double_execute_on_internal_type_error():
    """Before the fix, a keyword call that raised TypeError for ANY reason —
    not just an unexpected-keyword-argument mismatch — was blindly retried
    positionally `except TypeError`. A scraper that makes a real request (or
    writes to a DB) before hitting an internal bug that happens to raise
    TypeError would get run a second time, silently, as if that were a
    retry-safe no-op."""
    call_count = {"n": 0}

    def scrape(url):
        call_count["n"] += 1
        raise TypeError("boom: unrelated bug inside the scraper itself")

    with pytest.raises(TypeError, match="boom"):
        AIRemediatorEngine._invoke_scrape(scrape, "http://example.test/")

    assert call_count["n"] == 1, "scrape() must be called exactly once, never retried"
