"""Backward-compatible pipeline event helper (optional webhooks only)."""
from __future__ import annotations

from typing import Any

from apps.notifications.notifier import send_webhook_event


def send_n8n_event(
    event_type: str,
    payload: dict[str, Any],
    webhook_url: str | None = None,
) -> bool:
    """
    Dispatch a pipeline event to configured webhooks.

    Fires only when NOTIFY_WEBHOOK_URL / N8N_WEBHOOK_URL / N8N_ALERT_WEBHOOK_URL
    is set, or when webhook_url is passed explicitly. n8n is optional.
    """
    urls = [webhook_url] if webhook_url else None
    return send_webhook_event(event_type, payload, webhook_urls=urls)
