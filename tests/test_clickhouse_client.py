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


def test_clickhouse_disabled_via_env(monkeypatch, caplog):
    ch.reset_clickhouse_client_cache()
    monkeypatch.setattr(ch, "_CLICKHOUSE_ENABLED", False)

    with caplog.at_level(logging.WARNING):
        assert ch.get_clickhouse_client() is None
        assert ch.get_clickhouse_client() is None

    warnings = [r for r in caplog.records if "CLICKHOUSE_ENABLED=0" in r.message]
    assert len(warnings) == 1
