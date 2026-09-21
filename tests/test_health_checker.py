"""Tests for ScraperHealthChecker.check_all_scrapers_health status logic
(F01, F02, F19).

No real Postgres/Dagster needed: get_db_cursor and the Dagster-touching methods
are mocked per-test so only the pure status-computation logic is exercised.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apps.observability import health_checker as hc_module


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *args, **kwargs):
        pass

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeCursorCtx:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return _FakeCursor(self._rows)

    def __exit__(self, *exc):
        return False


def _fake_get_db_cursor(rows):
    def _factory(commit=False):
        return _FakeCursorCtx(rows)

    return _factory


@pytest.fixture
def checker(tmp_path, monkeypatch):
    """A ScraperHealthChecker with Dagster/stdout-log/alert side effects neutered,
    so tests exercise only the pure status logic driven by DB rows."""
    bundles_root = tmp_path / "bundles"
    bundles_root.mkdir()
    monkeypatch.setattr(hc_module, "BUNDLES_DIR", str(bundles_root))
    monkeypatch.setattr(hc_module.ScraperHealthChecker, "cleanup_orphaned_dagster_runs", lambda self: None)
    monkeypatch.setattr(
        hc_module.ScraperHealthChecker, "scan_dagster_stdout_logs", lambda self, **kw: {}
    )
    monkeypatch.setattr(hc_module.ScraperHealthChecker, "get_bundle_observability_settings", lambda self, name: (12, 0.3))
    monkeypatch.setattr(hc_module, "send_scraper_alert", lambda *a, **k: None)
    monkeypatch.setattr(hc_module, "record_scraper_execution", lambda *a, **k: 1)

    def _make_bundle_dir(name: str):
        (bundles_root / name).mkdir(exist_ok=True)

    c = hc_module.ScraperHealthChecker.__new__(hc_module.ScraperHealthChecker)  # skip __init__'s init_metrics_db()
    c._make_bundle_dir = _make_bundle_dir
    return c


def _row(bundle_name, **overrides):
    base = {
        "bundle_name": bundle_name,
        "total_runs_24h": 0,
        "success_runs_24h": 0,
        "anomaly_runs_24h": 0,
        "failed_runs_24h": 0,
        "total_items_scraped_24h": 0,
        "last_run_timestamp": None,
        "last_success_timestamp": None,
    }
    base.update(overrides)
    return base


def _status_for(checker, monkeypatch, bundle_name, rows, *, emit_alerts=False):
    checker._make_bundle_dir(bundle_name)
    monkeypatch.setattr(hc_module, "get_db_cursor", _fake_get_db_cursor(rows))
    report = checker.check_all_scrapers_health(emit_alerts=emit_alerts)
    return next(r for r in report if r["bundle_name"] == bundle_name)


def test_all_failed_runs_is_not_healthy(checker, monkeypatch):
    """F01: a bundle with only FAILED runs previously reported HEALTHY, because
    only ZERO_ROWS/DEGRADED counted toward the anomaly ratio."""
    row = _row("zz_all_failed", total_runs_24h=10, failed_runs_24h=10, last_success_timestamp=None)
    result = _status_for(checker, monkeypatch, "zz_all_failed", [row])
    assert result["status"] != "HEALTHY"
    assert result["status"] == "CRITICAL"


def test_never_succeeded_with_recent_runs_is_flagged(checker, monkeypatch):
    """F01: runs exist (e.g. ZERO_ROWS, not enough to cross the anomaly ratio) but
    no SUCCESS has ever been recorded — must not silently default to HEALTHY."""
    row = _row("zz_never_succeeded", total_runs_24h=2, anomaly_runs_24h=1, last_success_timestamp=None)
    result = _status_for(checker, monkeypatch, "zz_never_succeeded", [row])
    assert result["status"] == "CRITICAL"
    assert any("never" in i.lower() for i in result["issues"])


def test_no_data_at_all_is_unknown_not_healthy(checker, monkeypatch):
    """F01: a bundle that has never run at all is not evidence of health."""
    result = _status_for(checker, monkeypatch, "zz_no_data", [])
    assert result["status"] == "UNKNOWN"


def test_stale_success_beyond_24h_window_still_breaches_sla(checker, monkeypatch):
    """F01: last_success_timestamp must not be lost just because it falls outside
    the 24h aggregation window — the view now joins it in separately (metrics.py)."""
    old_success = datetime.now(timezone.utc) - timedelta(hours=48)
    row = _row("zz_stale", total_runs_24h=0, last_success_timestamp=old_success)
    result = _status_for(checker, monkeypatch, "zz_stale", [row])
    assert result["status"] == "CRITICAL"
    assert "SLA" in " ".join(result["issues"])


def test_healthy_bundle_stays_healthy(checker, monkeypatch):
    recent_success = datetime.now(timezone.utc) - timedelta(hours=1)
    row = _row(
        "zz_healthy",
        total_runs_24h=5,
        success_runs_24h=5,
        last_success_timestamp=recent_success,
        total_items_scraped_24h=50,
    )
    result = _status_for(checker, monkeypatch, "zz_healthy", [row])
    assert result["status"] == "HEALTHY"
    assert result["issues"] == []


def test_readonly_summary_does_not_mutate_dagster(checker, monkeypatch):
    """F02: emit_alerts=False (operator `summary`) must not call the
    Dagster-run-canceling cleanup — it's documented as read-only."""
    called = {"cleanup": False}
    monkeypatch.setattr(
        hc_module.ScraperHealthChecker,
        "cleanup_orphaned_dagster_runs",
        lambda self: called.__setitem__("cleanup", True),
    )
    checker._make_bundle_dir("zz_readonly")
    monkeypatch.setattr(hc_module, "get_db_cursor", _fake_get_db_cursor([]))
    checker.check_all_scrapers_health(emit_alerts=False)
    assert called["cleanup"] is False


def test_full_audit_does_mutate_dagster(checker, monkeypatch):
    """F02 (inverse): the real `harbor health` audit (emit_alerts=True) still runs
    cleanup — only the read-only summary path should skip it."""
    called = {"cleanup": False}
    monkeypatch.setattr(
        hc_module.ScraperHealthChecker,
        "cleanup_orphaned_dagster_runs",
        lambda self: called.__setitem__("cleanup", True),
    )
    checker._make_bundle_dir("zz_full_audit")
    monkeypatch.setattr(hc_module, "get_db_cursor", _fake_get_db_cursor([]))
    checker.check_all_scrapers_health(emit_alerts=True)
    assert called["cleanup"] is True


# --- F19: stdout log scanning must not re-report the same old error forever. ---


@pytest.fixture
def raw_checker():
    """A ScraperHealthChecker without __init__'s init_metrics_db() call."""
    return hc_module.ScraperHealthChecker.__new__(hc_module.ScraperHealthChecker)


def test_stdout_scan_does_not_repeat_an_old_error_on_the_next_scan(raw_checker, tmp_path, monkeypatch):
    monkeypatch.setenv("DAGSTER_HOME", str(tmp_path))
    log_file = tmp_path / "dagster.log"
    log_file.write_text("normal line\n[ERROR] boom in bundle demo\n", encoding="utf-8")

    first = raw_checker.scan_dagster_stdout_logs(advance_cursor=True)
    assert any("boom" in e for errs in first.values() for e in errs)

    # Nothing new was appended — a second scan must find nothing to report,
    # not the same "[ERROR] boom" line again.
    second = raw_checker.scan_dagster_stdout_logs(advance_cursor=True)
    assert second == {}


def test_stdout_scan_reports_only_new_content_after_old_error(raw_checker, tmp_path, monkeypatch):
    monkeypatch.setenv("DAGSTER_HOME", str(tmp_path))
    log_file = tmp_path / "dagster.log"
    log_file.write_text("[ERROR] first boom in bundle demo\n", encoding="utf-8")
    raw_checker.scan_dagster_stdout_logs(advance_cursor=True)

    with open(log_file, "a", encoding="utf-8") as f:
        f.write("[ERROR] second boom in bundle demo\n")

    result = raw_checker.scan_dagster_stdout_logs(advance_cursor=True)
    joined = " ".join(e for errs in result.values() for e in errs)
    assert "second boom" in joined
    assert "first boom" not in joined


def test_stdout_scan_readonly_does_not_consume_the_error(raw_checker, tmp_path, monkeypatch):
    """advance_cursor=False (the operator summary path) must not stop a later
    real check (emit_alerts=True) from still seeing and alerting on it."""
    monkeypatch.setenv("DAGSTER_HOME", str(tmp_path))
    log_file = tmp_path / "dagster.log"
    log_file.write_text("[ERROR] boom in bundle demo\n", encoding="utf-8")

    readonly_first = raw_checker.scan_dagster_stdout_logs(advance_cursor=False)
    readonly_second = raw_checker.scan_dagster_stdout_logs(advance_cursor=False)
    assert readonly_first == readonly_second  # unchanged — nothing was consumed

    real_check = raw_checker.scan_dagster_stdout_logs(advance_cursor=True)
    assert real_check == readonly_first  # the real check still sees it once
