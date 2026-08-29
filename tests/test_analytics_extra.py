"""Tests for optional analytics extra gate."""
from __future__ import annotations

import importlib


def test_require_analytics_raises_when_missing(monkeypatch):
    mod = importlib.import_module("apps.analytics")
    monkeypatch.setattr(mod, "analytics_extra_installed", lambda packages=None: False)
    try:
        mod.require_analytics("polars")
        raised = False
    except ImportError as exc:
        raised = True
        assert "analytics" in str(exc).lower()
    assert raised
