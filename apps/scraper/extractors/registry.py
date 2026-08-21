"""Dynamic registry for installed DataHarbor extractor plugins."""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from typing import Any, Callable, Dict, List, Optional

from apps.scraper.extractor_api import (
    DEFAULT_ENTRYPOINT,
    ParseFn,
    ensure_source_url,
    resolve_entrypoint,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
EXTRACTORS_DIR = os.path.join(_PROJECT_ROOT, "extractors")

_cache: Optional[Dict[str, Dict[str, Any]]] = None


def get_extractors_dir() -> str:
    return EXTRACTORS_DIR


def _ensure_project_root_on_path() -> None:
    if _PROJECT_ROOT not in sys.path:
        sys.path.insert(0, _PROJECT_ROOT)


def clear_registry_cache() -> None:
    """Drop loaded extractor cache (used after install/remove and in tests)."""
    global _cache
    _cache = None


def _load_manifest(extractor_path: str) -> Dict[str, Any]:
    manifest_path = os.path.join(extractor_path, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _import_entrypoint(extractor_id: str, entrypoint: str):
    module_stem, attr_name = resolve_entrypoint(entrypoint)
    _ensure_project_root_on_path()
    module_name = f"extractors.{extractor_id}.{module_stem}"
    module = importlib.import_module(module_name)
    if not hasattr(module, attr_name):
        raise AttributeError(
            f"Extractor '{extractor_id}' entrypoint '{entrypoint}' not found in {module_name}."
        )
    return getattr(module, attr_name), module


def _discover() -> Dict[str, Dict[str, Any]]:
    discovered: Dict[str, Dict[str, Any]] = {}
    if not os.path.isdir(EXTRACTORS_DIR):
        return discovered

    for entry in sorted(os.listdir(EXTRACTORS_DIR)):
        extractor_path = os.path.join(EXTRACTORS_DIR, entry)
        if not os.path.isdir(extractor_path) or entry.startswith((".", "_")):
            continue
        manifest_path = os.path.join(extractor_path, "manifest.json")
        if not os.path.exists(manifest_path):
            continue
        try:
            manifest = _load_manifest(extractor_path)
            extractor_id = str(manifest.get("name") or entry).replace("-", "_")
            entrypoint = manifest.get("entrypoint") or DEFAULT_ENTRYPOINT
            parse_fn, module = _import_entrypoint(extractor_id, entrypoint)
            if not callable(parse_fn):
                raise TypeError(f"Extractor '{extractor_id}' parse entrypoint is not callable.")

            paginate_fn = getattr(module, "generate_page_urls", None)
            if paginate_fn is not None and not callable(paginate_fn):
                paginate_fn = None

            domains = [str(d).lower() for d in (manifest.get("domains") or [])]

            def _bound_parse(html: str, source_url: str, _fn=parse_fn) -> List[Dict[str, Any]]:
                records = _fn(html, source_url) or []
                return ensure_source_url(list(records), source_url)

            discovered[extractor_id] = {
                "id": extractor_id,
                "path": extractor_path,
                "manifest": manifest,
                "domains": domains,
                "parse": _bound_parse,
                "generate_page_urls": paginate_fn,
            }
        except Exception as e:
            logger.warning(f"Failed to load extractor '{entry}': {e}")
    return discovered


def _registry() -> Dict[str, Dict[str, Any]]:
    global _cache
    if _cache is None:
        _cache = _discover()
    return _cache


def list_installed_extractors() -> List[Dict[str, Any]]:
    """Return metadata for every successfully loaded extractor plugin."""
    return [
        {
            "id": meta["id"],
            "version": meta["manifest"].get("version", "0.0.0"),
            "description": meta["manifest"].get("description", ""),
            "domains": list(meta["domains"]),
            "path": meta["path"],
            "capabilities": meta["manifest"].get("capabilities") or [],
        }
        for meta in _registry().values()
    ]


def is_extractor_installed(extractor_id: str) -> bool:
    return extractor_id.replace("-", "_") in _registry()


def get_extractor_meta(extractor_id: str) -> Optional[Dict[str, Any]]:
    return _registry().get(extractor_id.replace("-", "_"))


def require_extractor(extractor_id: str) -> ParseFn:
    """Return parse callable or raise if the extractor is not installed."""
    meta = get_extractor_meta(extractor_id)
    if not meta:
        raise LookupError(
            f"Extractor '{extractor_id}' is not installed. "
            f"Install with: harbor extractor install <source>"
        )
    return meta["parse"]


def get_extractor(domain_or_id: str) -> Optional[ParseFn]:
    """Resolve parse callable by extractor id or by domain substring in URL/host."""
    key = (domain_or_id or "").strip().lower()
    if not key:
        return None

    registry = _registry()
    normalized = key.replace("-", "_")
    if normalized in registry:
        return registry[normalized]["parse"]

    # Strip scheme/path for URL lookups
    needle = key
    for prefix in ("https://", "http://", "www."):
        if needle.startswith(prefix):
            needle = needle[len(prefix):]
    needle = needle.split("/")[0]

    for meta in registry.values():
        if meta["id"] in key or meta["id"] in needle:
            return meta["parse"]
        for domain in meta["domains"]:
            if domain in key or domain in needle:
                return meta["parse"]
    return None


def generate_page_urls_for_domain(base_url: str, max_pages: int = 10) -> List[str]:
    """Generate paginated URLs using the matching extractor, or a generic ?page= fallback."""
    registry = _registry()
    url_lower = (base_url or "").lower()
    for meta in registry.values():
        matched = any(domain in url_lower for domain in meta["domains"]) or meta["id"] in url_lower
        if matched and meta.get("generate_page_urls"):
            return meta["generate_page_urls"](base_url, max_pages=max_pages)

    urls = [base_url]
    limit = 10 if max_pages <= 0 else max_pages
    delim = "&" if "?" in base_url else "?"
    for page in range(1, limit):
        urls.append(f"{base_url}{delim}page={page}")
    return urls
