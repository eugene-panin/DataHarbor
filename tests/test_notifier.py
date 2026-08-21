"""Tests for Core thin notifier (no external services)."""
from __future__ import annotations

from unittest.mock import patch

from apps.notifications import notifier


def test_notify_telegram_and_slack_and_webhook(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    monkeypatch.setenv("NOTIFY_WEBHOOK_URL", "http://example.test/hook")

    calls = []

    def fake_post(url, payload, timeout=10, headers=None):
        calls.append((url, payload))
        return 200, "ok"

    with patch.object(notifier, "post_json", side_effect=fake_post):
        with patch.object(notifier, "send_telegram_notification", return_value=True) as tg:
            ok = notifier.notify(
                text_html="<b>hi</b>",
                event="TEST",
                payload={"a": 1},
            )

    assert ok is True
    tg.assert_called_once()
    assert any("hooks.slack.test" in u for u, _ in calls)
    assert any("example.test/hook" in u for u, _ in calls)


def test_notify_noop_without_channels(monkeypatch):
    for key in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "SLACK_WEBHOOK_URL",
        "NOTIFY_WEBHOOK_URL",
        "N8N_WEBHOOK_URL",
        "N8N_ALERT_WEBHOOK_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    assert notifier.notify(text_html="<b>x</b>", event="E", payload={}) is False


def test_send_webhook_event_skips_when_unset(monkeypatch):
    for key in ("NOTIFY_WEBHOOK_URL", "N8N_WEBHOOK_URL", "N8N_ALERT_WEBHOOK_URL"):
        monkeypatch.delenv(key, raising=False)
    assert notifier.send_webhook_event("E", {"x": 1}) is False
