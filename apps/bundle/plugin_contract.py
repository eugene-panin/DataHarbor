"""Bundle plugin contract: engines, entrypoints, Definitions discovery."""
from __future__ import annotations

import importlib
import json
import logging
import os
import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet

logger = logging.getLogger(__name__)

DEFAULT_DAGSTER_ENTRYPOINT = "assets:defs"
_ENTRYPOINT_RE = re.compile(r"^([A-Za-z_][\w]*)(?::([A-Za-z_][\w]*))?$")

# Legacy: bundles/ no longer ships Core helpers; kept empty for old tooling.
CORE_BUNDLE_PACKAGE_NAMES = frozenset()


class BundleContractError(Exception):
    """Raised when a bundle violates the plugin contract or fails to load."""


def platform_version() -> str:
    try:
        return pkg_version("dataharbor")
    except PackageNotFoundError:
        return "0.0.0"


def load_manifest(bundle_path: str) -> dict[str, Any]:
    manifest_path = os.path.join(bundle_path, "manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise BundleContractError(f"manifest.json must be a JSON object in '{bundle_path}'")
    return data


def check_engines(manifest: dict[str, Any], *, platform_ver: str | None = None) -> list[str]:
    """Return error messages if engines.dataharbor does not match the platform."""
    errors: list[str] = []
    engines = manifest.get("engines")
    if engines is None:
        return errors
    if not isinstance(engines, dict):
        errors.append("manifest 'engines' must be an object")
        return errors

    req = engines.get("dataharbor")
    if req is None:
        return errors
    if not isinstance(req, str) or not req.strip():
        errors.append("manifest engines.dataharbor must be a non-empty version specifier string")
        return errors

    try:
        spec = SpecifierSet(req)
    except InvalidSpecifier as e:
        errors.append(f"invalid engines.dataharbor specifier '{req}': {e}")
        return errors

    current = platform_ver or platform_version()
    if current not in spec:
        errors.append(
            f"platform version '{current}' does not satisfy engines.dataharbor '{req}'"
        )
    return errors


def resolve_dagster_entrypoint(manifest: dict[str, Any]) -> tuple[str, str]:
    """
    Resolve (module_leaf, attr) for Dagster Definitions.

    entrypoints.dagster examples:
      - "assets:defs"  → module assets.py, attr defs
      - "assets"       → module assets.py, attr defs (default)
      - null / missing → DEFAULT_DAGSTER_ENTRYPOINT when assets.py exists
    """
    entrypoints = manifest.get("entrypoints") or {}
    if entrypoints is not None and not isinstance(entrypoints, dict):
        raise BundleContractError("manifest 'entrypoints' must be an object")

    raw = (entrypoints or {}).get("dagster", DEFAULT_DAGSTER_ENTRYPOINT)
    if raw is None:
        raise BundleContractError("entrypoints.dagster is null — no Dagster definitions to load")
    if not isinstance(raw, str) or not raw.strip():
        raise BundleContractError("entrypoints.dagster must be a string like 'assets:defs'")

    match = _ENTRYPOINT_RE.match(raw.strip())
    if not match:
        raise BundleContractError(
            f"invalid entrypoints.dagster '{raw}' (expected 'module' or 'module:attr')"
        )
    module_leaf = match.group(1)
    attr = match.group(2) or "defs"
    return module_leaf, attr


def validate_manifest_contract(manifest: dict[str, Any]) -> list[str]:
    """Structural checks for engines / entrypoints / requirements.python."""
    errors: list[str] = []
    errors.extend(check_engines(manifest))

    entrypoints = manifest.get("entrypoints")
    if entrypoints is not None:
        if not isinstance(entrypoints, dict):
            errors.append("manifest 'entrypoints' must be an object")
        else:
            dagster_ep = entrypoints.get("dagster", DEFAULT_DAGSTER_ENTRYPOINT)
            if dagster_ep is not None:
                if not isinstance(dagster_ep, str) or not _ENTRYPOINT_RE.match(dagster_ep.strip()):
                    errors.append(
                        "entrypoints.dagster must look like 'assets:defs' "
                        f"(got {dagster_ep!r})"
                    )
            celery_ep = entrypoints.get("celery")
            if celery_ep not in (None,):
                errors.append(
                    "entrypoints.celery must be null "
                    "(Celery is not part of DataHarbor Core; use Dagster assets)"
                )

    reqs = manifest.get("requirements") or {}
    if reqs is not None and not isinstance(reqs, dict):
        errors.append("manifest 'requirements' must be an object")
    elif isinstance(reqs, dict):
        py_deps = reqs.get("python")
        if py_deps is not None and not (
            isinstance(py_deps, list) and all(isinstance(x, str) and x.strip() for x in py_deps)
        ):
            errors.append("requirements.python must be a list of non-empty strings")

    return errors


def load_bundle_definitions_object(bundle_name: str, bundle_path: str) -> Any:
    """Import and return a dagster.Definitions instance for one bundle."""
    from dagster import (
        Definitions,
        load_asset_checks_from_modules,
        load_assets_from_modules,
    )

    manifest = load_manifest(bundle_path)
    engine_errors = check_engines(manifest)
    if engine_errors:
        raise BundleContractError("; ".join(engine_errors))

    try:
        module_leaf, attr = resolve_dagster_entrypoint(manifest)
    except BundleContractError:
        # No dagster entrypoint → empty Definitions (bundle may be scraper/db only)
        entrypoints = manifest.get("entrypoints") or {}
        if isinstance(entrypoints, dict) and entrypoints.get("dagster") is None:
            logger.info("Bundle '%s' has entrypoints.dagster=null; skipping Dagster defs", bundle_name)
            return Definitions()
        raise

    module_file = os.path.join(bundle_path, f"{module_leaf}.py")
    if not os.path.exists(module_file):
        raise BundleContractError(
            f"Dagster entrypoint module '{module_leaf}.py' not found in bundle '{bundle_name}'"
        )

    module_name = f"bundles.{bundle_name}.{module_leaf}"
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        raise BundleContractError(f"failed to import {module_name}: {e}") from e

    if hasattr(mod, attr):
        defs_obj = getattr(mod, attr)
        if not isinstance(defs_obj, Definitions):
            raise BundleContractError(
                f"{module_name}.{attr} must be a dagster.Definitions instance, "
                f"got {type(defs_obj).__name__}"
            )
        return defs_obj

    # Legacy fallback: assets declared without `defs = Definitions(...)`
    logger.warning(
        "Bundle '%s': %s.%s missing — falling back to load_assets_from_modules "
        "(add `defs = Definitions(...)` to satisfy the plugin contract)",
        bundle_name,
        module_name,
        attr,
    )
    assets = load_assets_from_modules([mod])
    checks = load_asset_checks_from_modules([mod])
    return Definitions(assets=assets, asset_checks=checks)


def iter_bundle_dirs(bundles_dir: str) -> list[tuple[str, str]]:
    """Return [(bundle_name, absolute_path), ...] for installable bundle folders."""
    if not os.path.isdir(bundles_dir):
        return []
    out: list[tuple[str, str]] = []
    for entry in sorted(os.listdir(bundles_dir)):
        if entry.startswith((".", "_")) or entry in CORE_BUNDLE_PACKAGE_NAMES:
            continue
        path = os.path.join(bundles_dir, entry)
        if os.path.isdir(path):
            out.append((entry, path))
    return out
