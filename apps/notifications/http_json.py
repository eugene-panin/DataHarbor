"""Minimal JSON HTTP helpers (stdlib only)."""
from __future__ import annotations

import json
import ssl
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def post_json(
    url: str,
    payload: Dict[str, Any],
    *,
    timeout: float = 10,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, str]:
    """POST JSON and return (status_code, response_text)."""
    body = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    req = Request(url, data=body, headers=req_headers, method="POST")
    try:
        with urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return int(getattr(resp, "status", None) or resp.getcode() or 200), raw
    except HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return int(e.code), raw
    except (URLError, TimeoutError, OSError) as e:
        raise ConnectionError(str(e)) from e
