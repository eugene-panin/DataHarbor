"""Thin multi-channel notifier (stdlib only). No n8n required."""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from apps.notifications.http_json import post_json
from apps.notifications.telegram import send_telegram_notification

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _env_urls(*keys: str) -> List[str]:
    urls: List[str] = []
    for key in keys:
        raw = (os.getenv(key) or "").strip()
        if not raw:
            continue
        for part in raw.split(","):
            url = part.strip()
            if url:
                urls.append(url)
    return urls


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _unique(urls: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def send_slack_notification(text: str, webhook_url: Optional[str] = None) -> bool:
    """Post plain text to a Slack incoming webhook."""
    url = webhook_url or (os.getenv("SLACK_WEBHOOK_URL") or "").strip()
    if not url:
        return False
    try:
        status, body = post_json(url, {"text": text}, timeout=5)
        if status in (200, 201, 204):
            return True
        logger.warning("Slack webhook returned status %s: %s", status, body)
        return False
    except Exception as e:
        logger.error("Failed to send Slack notification: %s", e)
        return False


def send_webhook_event(
    event_type: str,
    payload: Dict[str, Any],
    *,
    webhook_urls: Optional[Iterable[str]] = None,
) -> bool:
    """POST a JSON event to optional generic webhooks (n8n, Zapier, custom)."""
    urls = _unique(
        list(webhook_urls)
        if webhook_urls is not None
        else _env_urls("NOTIFY_WEBHOOK_URL", "N8N_WEBHOOK_URL", "N8N_ALERT_WEBHOOK_URL")
    )
    if not urls:
        return False

    body = {
        "event": event_type,
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    delivered = False
    for url in urls:
        try:
            status, _resp = post_json(url, body, timeout=5)
            if status in (200, 201, 204):
                logger.info("Delivered event '%s' to webhook %s", event_type, url)
                delivered = True
            else:
                logger.warning("Webhook %s returned status %s", url, status)
        except Exception as e:
            logger.debug("Could not reach webhook %s: %s", url, e)
    return delivered


def notify(
    *,
    text_html: Optional[str] = None,
    text_plain: Optional[str] = None,
    event: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Fan-out notification to configured Core channels.

    Channels (all optional, skip if unset):
    - Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
    - Slack: SLACK_WEBHOOK_URL
    - Generic JSON webhooks: NOTIFY_WEBHOOK_URL (comma-separated);
      legacy aliases N8N_WEBHOOK_URL / N8N_ALERT_WEBHOOK_URL
    """
    plain = text_plain or (_strip_html(text_html) if text_html else None)
    ok = False

    if text_html:
        if send_telegram_notification(text_html):
            ok = True

    if plain and send_slack_notification(plain):
        ok = True

    if event:
        if send_webhook_event(event, payload or {}):
            ok = True

    return ok
