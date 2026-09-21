"""ClickHouse client should fail soft and not spam logs when CH is down."""
from __future__ import annotations

import logging

from apps.db import clickhouse_client as ch


def test_get_clickhouse_client_caches_unavailable(monkeypatch, caplog):
    ch.reset_clickhouse_client_cache()
    monkeypatch.setattr(ch, "_CLICKHOUSE_ENABLED", True)

    def boom(**kwargs):
        raise RuntimeError("auth failed")

    monkeypatch.setattr(ch.clickhouse_connect, "get_client", boom)

    with caplog.at_level(logging.WARNING):
        assert ch.get_clickhouse_client() is None
        assert ch.get_clickhouse_client() is None
        assert ch.insert_batch("t", ["a"], [[1]]) is False

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "unavailable" in r.message]
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(warnings) == 1
    assert errors == []


def test_get_clickhouse_client_retries_after_cooldown(monkeypatch, caplog):
    """F14: a transient failure must not disable ClickHouse for the rest of
    the process's life — only until the cooldown elapses."""
    ch.reset_clickhouse_client_cache()
    monkeypatch.setattr(ch, "_CLICKHOUSE_ENABLED", True)
    monkeypatch.setattr(ch, "_RETRY_COOLDOWN_SECONDS", 5.0)

    def boom(**kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(ch.clickhouse_connect, "get_client", boom)
    assert ch.get_clickhouse_client() is None
    assert ch._unavailable_since is not None

    # Still within the cooldown: no retry attempt.
    monkeypatch.setattr(ch.time, "monotonic", lambda: ch._unavailable_since + 1.0)
    assert ch.get_clickhouse_client() is None

    # Cooldown elapsed: it must try again — and this time succeed.
    class _FakeConnected:
        def query(self, *a, **k):
            return None

    monkeypatch.setattr(ch.clickhouse_connect, "get_client", lambda **kw: _FakeConnected())
    monkeypatch.setattr(ch.time, "monotonic", lambda: ch._unavailable_since + 10.0)
    result = ch.get_clickhouse_client()
    assert result is not None


def test_clickhouse_disabled_via_env(monkeypatch, caplog):
    ch.reset_clickhouse_client_cache()
    monkeypatch.setattr(ch, "_CLICKHOUSE_ENABLED", False)

    with caplog.at_level(logging.WARNING):
        assert ch.get_clickhouse_client() is None
        assert ch.get_clickhouse_client() is None

    warnings = [r for r in caplog.records if "CLICKHOUSE_ENABLED=0" in r.message]
    assert len(warnings) == 1
