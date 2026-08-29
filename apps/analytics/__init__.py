"""Optional catalog/analytics helpers (Polars, DuckDB, RapidFuzz).

Install on the host or in the bundle venv:
    uv sync --extra analytics

Bundles declare the same packages in ``manifest.json`` → ``requirements.python``.
These are in-process libraries — not Docker services.
"""
from __future__ import annotations

from collections.abc import Iterable

ANALYTICS_EXTRA_HINT = (
    "Optional analytics dependency missing. Install with: uv sync --extra analytics "
    "(duckdb, polars, rapidfuzz, python-stdnum, openpyxl)."
)

ANALYTICS_PACKAGE_NAMES = (
    "duckdb",
    "polars",
    "rapidfuzz",
    "stdnum",
    "openpyxl",
)


def analytics_extra_installed(packages: Iterable[str] | None = None) -> bool:
    import importlib.util

    names = list(packages) if packages is not None else list(ANALYTICS_PACKAGE_NAMES)
    return all(importlib.util.find_spec(name) is not None for name in names)


def require_analytics(*packages: str) -> None:
    import importlib.util

    missing = [name for name in packages if importlib.util.find_spec(name) is None]
    if missing:
        raise ImportError(f"{ANALYTICS_EXTRA_HINT} Missing: {', '.join(missing)}")


__all__ = [
    "ANALYTICS_EXTRA_HINT",
    "ANALYTICS_PACKAGE_NAMES",
    "analytics_extra_installed",
    "require_analytics",
]
