"""Dependency gate for optional crawl extras."""
from __future__ import annotations

from collections.abc import Iterable

CRAWL_EXTRA_HINT = (
    "Optional crawl dependency missing. Install with: uv sync --extra crawl "
    "(duckdb, warcio)."
)

CRAWL_PACKAGE_NAMES = (
    "duckdb",
    "warcio",
)


def crawl_extra_installed(packages: Iterable[str] | None = None) -> bool:
    import importlib.util

    names = list(packages) if packages is not None else list(CRAWL_PACKAGE_NAMES)
    return all(importlib.util.find_spec(name) is not None for name in names)


def require_crawl(*packages: str) -> None:
    import importlib.util

    missing = [name for name in packages if importlib.util.find_spec(name) is None]
    if missing:
        raise ImportError(f"{CRAWL_EXTRA_HINT} Missing: {', '.join(missing)}")
