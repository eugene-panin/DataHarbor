import logging
import os

from apps.notifications.http_json import post_json

logger = logging.getLogger(__name__)


def send_telegram_notification(
    text: str,
    is_step_notification: bool = False,
    bot_token: str | None = None,
    chat_id: str | None = None,
) -> bool:
    """Sends HTML-formatted notification messages directly via Telegram Bot API."""
    if is_step_notification and os.getenv("TELEGRAM_NOTIFY_EVERY_STEP", "true").lower() == "false":
        logger.info("Skipping intermediate step Telegram notification (TELEGRAM_NOTIFY_EVERY_STEP=false)")
        return False

    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    cid = chat_id or os.getenv("TELEGRAM_CHAT_ID")

    if not token or not cid:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing. Skipping Telegram notification.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        logger.info("Sending Telegram notification to chat %s...", cid)
        status, body = post_json(url, payload, timeout=10)
        if status == 200:
            logger.info("Telegram notification delivered successfully.")
            return True
        logger.warning("Telegram API returned status %s: %s", status, body)
        return False
    except Exception as e:
        logger.error("Error sending Telegram notification: %s", e)
        return False
