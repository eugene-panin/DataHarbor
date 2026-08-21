import logging
from datetime import datetime

from apps.notifications.notifier import notify

logger = logging.getLogger(__name__)


def send_scraper_alert(
    bundle_name: str,
    alert_type: str,
    details: str,
    http_403_count: int = 0,
    http_429_count: int = 0,
) -> bool:
    """Send scraper degradation alert via Core notifier channels."""
    now_str = datetime.now().strftime("%H:%M:%S (%d %b)")

    alert_msg = (
        f"🚨 <b>DATAHARBOR OBSERVABILITY ALERT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Bundle:</b> <code>{bundle_name}</code>\n"
        f"⚠️ <b>Anomaly Type:</b> <code>{alert_type}</code>\n"
        f"🕒 <b>Timestamp:</b> <code>{now_str}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 <b>Diagnostic Details:</b>\n"
        f"<i>{details}</i>\n\n"
        f"📊 <b>HTTP Error Breakdown:</b>\n"
        f"• 🚫 <b>HTTP 403:</b> {http_403_count}\n"
        f"• 🛑 <b>HTTP 429:</b> {http_429_count}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 <b>Quick Action:</b>\n"
        f"<code>harbor health --auto-fix {bundle_name}</code>\n\n"
        f"💡 <i>Or diagnose via agent protocol:</i>\n"
        f"<code>harbor agent-protocol diagnose {bundle_name}</code>"
    )

    logger.warning("SCRAPER ALERT for '%s': %s - %s", bundle_name, alert_type, details)
    return notify(
        text_html=alert_msg,
        event="SCRAPER_ALERT",
        payload={
            "bundle_name": bundle_name,
            "alert_type": alert_type,
            "details": details,
            "http_403_count": http_403_count,
            "http_429_count": http_429_count,
        },
    )


def send_auto_repair_success_alert(
    bundle_name: str,
    model_used: str,
    attempt: int,
    modified_lines_count: int,
) -> bool:
    """Notify when AI auto-repair successfully patches a scraper."""
    now_str = datetime.now().strftime("%H:%M:%S (%d %b)")
    msg = (
        f"✅ <b>DATAHARBOR SCRAPER AUTO-REPAIRED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Bundle:</b> <code>{bundle_name}</code>\n"
        f"🤖 <b>AI Provider:</b> <code>{model_used}</code>\n"
        f"🔄 <b>Attempt:</b> #{attempt}\n"
        f"🕒 <b>Timestamp:</b> <code>{now_str}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✨ <b>Repair Summary:</b>\n"
        f"• AST Validation: <b>PASSED</b>\n"
        f"• Verification Scrape: <b>SUCCESS</b>\n"
        f"• Lines Modified: <b>{modified_lines_count} lines</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎉 <i>Scraper logic is back online and healthy!</i>"
    )
    return notify(
        text_html=msg,
        event="AUTO_REPAIR_SUCCESS",
        payload={
            "bundle_name": bundle_name,
            "model_used": model_used,
            "attempt": attempt,
            "modified_lines_count": modified_lines_count,
        },
    )


def send_human_attention_alert(
    bundle_name: str,
    retries_count: int,
    last_error: str,
) -> bool:
    """Notify when circuit breaker exhausts max retries."""
    now_str = datetime.now().strftime("%H:%M:%S (%d %b)")
    msg = (
        f"🆘 <b>HUMAN INTERVENTION REQUIRED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Bundle:</b> <code>{bundle_name}</code>\n"
        f"🚨 <b>Status:</b> Circuit Breaker Exhausted ({retries_count}/{retries_count} retries)\n"
        f"🕒 <b>Timestamp:</b> <code>{now_str}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>Reason for Failure:</b>\n"
        f"<code>{last_error}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛠️ <b>Manual Repair Command:</b>\n"
        f"<code>harbor health --fix {bundle_name}</code>"
    )
    return notify(
        text_html=msg,
        event="HUMAN_ATTENTION",
        payload={
            "bundle_name": bundle_name,
            "retries_count": retries_count,
            "last_error": last_error,
        },
    )
