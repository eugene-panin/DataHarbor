"""Platform contract for DataHarbor resource extractors.

Extractors are separately distributed plugins under ``extractors/<id>/``.
They parse already-fetched content only — no HTTP, proxies, or browser control.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

ParseFn = Callable[[str, str], list[dict[str, Any]]]
PaginateFn = Callable[[str, int], list[str]]


@runtime_checkable
class ExtractorModule(Protocol):
    """Required surface of an extractor plugin module (``extractor.py``)."""

    def parse(self, html: str, source_url: str) -> list[dict[str, Any]]:
        """Parse HTML into structured records. Each record should include ``source_url``."""
        ...


REQUIRED_MANIFEST_KEYS = ("name", "version", "description", "domains", "entrypoint")
DEFAULT_ENTRYPOINT = "extractor:parse"
SOURCE_URL_KEY = "source_url"


def resolve_entrypoint(entrypoint: str) -> tuple[str, str]:
    """Parse ``module:function`` entrypoint string into (module_stem, attr_name)."""
    if ":" not in entrypoint:
        raise ValueError(
            f"Invalid extractor entrypoint '{entrypoint}'. Expected 'module:function' "
            f"(e.g. '{DEFAULT_ENTRYPOINT}')."
        )
    module_stem, attr_name = entrypoint.split(":", 1)
    module_stem = module_stem.strip()
    attr_name = attr_name.strip()
    if not module_stem or not attr_name:
        raise ValueError(f"Invalid extractor entrypoint '{entrypoint}'.")
    return module_stem, attr_name


def ensure_source_url(records: list[dict[str, Any]], source_url: str) -> list[dict[str, Any]]:
    """Fill missing ``source_url`` on parsed records (contract minimum)."""
    for record in records:
        if not record.get(SOURCE_URL_KEY):
            record[SOURCE_URL_KEY] = source_url
    return records
