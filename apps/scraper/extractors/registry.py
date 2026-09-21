"""Dynamic registry for installed DataHarbor extractor plugins."""
from __future__ import annotations

import importlib
import json
import logging
import os
import shutil
import sys
from typing import Any

from apps.cli.paths import PROJECT_ROOT
from apps.extractor.paths import EXTRACTORS_DIR
from apps.scraper.extractor_api import (
    DEFAULT_ENTRYPOINT,
    ParseFn,
    ensure_source_url,
    resolve_entrypoint,
)

logger = logging.getLogger(__name__)

_cache: dict[str, dict[str, Any]] | None = None


def get_extractors_dir() -> str:
    return EXTRACTORS_DIR


def _ensure_project_root_on_path() -> None:
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)


def clear_registry_cache() -> None:
    """Drop loaded extractor cache (used after install/remove and in tests).

    Clearing _cache alone wasn't enough: the next _discover() call still
    goes through importlib.import_module("extractors.<id>.<module_stem>"),
    which returns whatever is already sitting in sys.modules rather than
    re-reading the file — so reinstalling/upgrading an extractor kept
    serving the OLD parse() code until the process restarted. Drop the
    extractor package modules from sys.modules too so the next discovery
    actually re-imports from disk.
    """
    global _cache
    _cache = None
    for name in [m for m in sys.modules if m == "extractors" or m.startswith("extractors.")]:
        del sys.modules[name]
    importlib.invalidate_caches()
    # Dropping sys.modules alone isn't enough either: CPython's .pyc cache is
    # invalidated by comparing the SOURCE file's mtime to the one baked into
    # the .pyc header, both truncated to whole seconds — a reinstall that
    # rewrites the file within the same second as the previous load is
    # indistinguishable from "unchanged", and the stale compiled bytecode
    # gets reused even though sys.modules was cleared and the fresh source
    # is right there on disk. Removing the extractors tree's __pycache__
    # dirs forces every next import to recompile from the current source.
    for root, dirs, _files in os.walk(EXTRACTORS_DIR):
        if "__pycache__" in dirs:
            shutil.rmtree(os.path.join(root, "__pycache__"), ignore_errors=True)


def _load_manifest(extractor_path: str) -> dict[str, Any]:
    manifest_path = os.path.join(extractor_path, "manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
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


def _discover() -> dict[str, dict[str, Any]]:
    discovered: dict[str, dict[str, Any]] = {}
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

            def _bound_parse(html: str, source_url: str, _fn=parse_fn) -> list[dict[str, Any]]:
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


def _registry() -> dict[str, dict[str, Any]]:
    global _cache
    if _cache is None:
        _cache = _discover()
    return _cache


def list_installed_extractors() -> list[dict[str, Any]]:
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


def get_extractor_meta(extractor_id: str) -> dict[str, Any] | None:
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


def _host_matches_domain(host: str, domain: str) -> bool:
    """True if `host` IS `domain`, or a proper subdomain of it.

    Plain substring matching (`domain in host`) let "github.com" match
    "github.com.evil-phishing.example" (attacker-controlled suffix after a
    lookalike prefix) and "notgithub.com" (unrelated host that merely
    contains the string), routing scraped content to the wrong extractor.
    """
    return host == domain or host.endswith("." + domain)


def get_extractor(domain_or_id: str) -> ParseFn | None:
    """Resolve parse callable by exact extractor id, or by domain/subdomain match."""
    key = (domain_or_id or "").strip().lower()
    if not key:
        return None

    registry = _registry()
    normalized = key.replace("-", "_")
    if normalized in registry:
        return registry[normalized]["parse"]

    # Strip scheme/path/port for URL lookups
    needle = key
    for prefix in ("https://", "http://", "www."):
        needle = needle.removeprefix(prefix)
    needle = needle.split("/")[0].split(":")[0]

    for meta in registry.values():
        for domain in meta["domains"]:
            if _host_matches_domain(needle, domain):
                return meta["parse"]
    return None


def generate_page_urls_for_domain(base_url: str, max_pages: int = 10) -> list[str]:
    """Generate paginated URLs using the matching extractor, or a generic ?page= fallback."""
    registry = _registry()
    needle = (base_url or "").strip().lower()
    for prefix in ("https://", "http://", "www."):
        needle = needle.removeprefix(prefix)
    needle = needle.split("/")[0].split(":")[0]
    for meta in registry.values():
        matched = any(_host_matches_domain(needle, domain) for domain in meta["domains"])
        if matched and meta.get("generate_page_urls"):
            return meta["generate_page_urls"](base_url, max_pages=max_pages)

    urls = [base_url]
    limit = 10 if max_pages <= 0 else max_pages
    delim = "&" if "?" in base_url else "?"
    for page in range(1, limit):
        urls.append(f"{base_url}{delim}page={page}")
    return urls
