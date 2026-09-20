"""Presentation Layer for bundle `demo` — renders scraped rows as a standalone HTML report."""
from __future__ import annotations

import html
from typing import Any


def generate_report(db_conn: Any = None, clickhouse_client: Any = None) -> str:
    """Render `demo_items` as a self-contained HTML page (ignores injected connections;
    opens its own via apps.db.connection, matching the rest of the platform)."""
    from bundles.demo.db import fetch_items

    try:
        rows = fetch_items()
    except Exception as e:
        rows = []
        error = str(e)
    else:
        error = None

    cards = "\n".join(
        f'''<div class="card">
        <h2>{html.escape(row.get("company_name") or "")}</h2>
        <p>{html.escape(row.get("summary") or "")}</p>
        <a href="{html.escape(row.get("source_url") or "#")}">{html.escape(row.get("source_url") or "")}</a>
        </div>'''
        for row in rows
    )

    body = cards if rows else (
        '<p class="empty">No rows yet — run <code>harbor bundle run demo</code> '
        '(or materialize the <code>demo</code> assets in Dagster) first.</p>'
        + (f'<p class="empty">Error: {html.escape(error)}</p>' if error else "")
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>DataHarbor Demo — Scraped Companies</title>
<style>
  body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 16px; color: #1a1a2e; }}
  h1 {{ margin-bottom: 4px; }}
  .subtitle {{ color: #64748b; margin-top: 0; }}
  .card {{ border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin: 16px 0; }}
  .card h2 {{ margin: 0 0 4px; font-size: 18px; }}
  .card p {{ margin: 0 0 8px; color: #475569; font-size: 14px; }}
  .card a {{ color: #0f766e; font-size: 12px; }}
  .empty {{ color: #64748b; }}
</style>
</head>
<body>
  <h1>DataHarbor Demo — Scraped Companies</h1>
  <p class="subtitle">{len(rows)} row(s) scraped from the local demo_site fixture.</p>
  {body}
</body>
</html>
"""
