"""Build Dagster workspace.yaml with one code location per bundle (+ core).

Named profiles live in ``workspace_profiles.yaml``; generated files go under
``workspaces/<name>.yaml``. Default (all bundles) still writes ``workspace.yaml``.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from typing import Any

import yaml

from apps.bundle.plugin_contract import (
    BundleContractError,
    iter_bundle_dirs,
    load_manifest,
    resolve_dagster_entrypoint,
)
from apps.bundle.validator import BundleValidator

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DAGSTER_APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_WORKSPACE_PATH = os.path.join(DAGSTER_APP_DIR, "workspace.yaml")
WORKSPACES_DIR = os.path.join(DAGSTER_APP_DIR, "workspaces")
PROFILES_PATH = os.path.join(DAGSTER_APP_DIR, "workspace_profiles.yaml")
BUNDLES_DIR = os.path.join(PROJECT_ROOT, "bundles")


def _core_location(working_directory: str) -> dict[str, Any]:
    return {
        "python_module": {
            "module_name": "apps.dagster_app.definitions",
            "attribute": "defs",
            "location_name": "core",
            "working_directory": working_directory,
        }
    }


def _bundle_location(
    bundle_name: str,
    module_leaf: str,
    attr: str,
    working_directory: str,
) -> dict[str, Any]:
    return {
        "python_module": {
            "module_name": f"bundles.{bundle_name}.{module_leaf}",
            "attribute": attr,
            "location_name": f"bundle_{bundle_name}",
            "working_directory": working_directory,
        }
    }


def _normalize_bundle_filter(include_bundles: Iterable[str] | None) -> set[str] | None:
    """None means "no filter, all bundles". An explicit (even empty) iterable
    means "only these" — collapsing an empty set back to None previously
    turned a profile/`--only` selection of zero bundles into "all bundles",
    the opposite of what was asked for.
    """
    if include_bundles is None:
        return None
    return {str(x).strip() for x in include_bundles if str(x).strip()}


def load_workspace_profiles(path: str | None = None) -> dict[str, Any]:
    """Load named workspace profiles. Missing file → built-in defaults."""
    target = path or PROFILES_PATH
    if not os.path.isfile(target):
        return {
            "profiles": {
                "all": {"description": "All installed bundles", "bundles": "*"},
            }
        }
    with open(target, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    if not isinstance(doc.get("profiles"), dict):
        raise ValueError(f"Invalid workspace profiles file (missing profiles:): {target}")
    return doc


def resolve_profile_bundles(profile_name: str, *, profiles_path: str | None = None) -> tuple[list[str] | None, dict[str, Any]]:
    """Return (bundle allowlist or None for all, profile dict)."""
    doc = load_workspace_profiles(profiles_path)
    profiles = doc["profiles"]
    if profile_name not in profiles:
        known = ", ".join(sorted(profiles)) or "(none)"
        raise KeyError(f"Unknown workspace profile '{profile_name}'. Known: {known}")
    profile = profiles[profile_name] or {}
    bundles = profile.get("bundles", "*")
    if bundles == "*" or bundles is None:
        return None, profile
    if isinstance(bundles, str):
        items = [b.strip() for b in bundles.split(",") if b.strip()]
        return items, profile
    if isinstance(bundles, list):
        return [str(b).strip() for b in bundles if str(b).strip()], profile
    raise ValueError(f"Profile '{profile_name}' bundles must be '*' or a list of names")


def workspace_path_for_name(name: str) -> str:
    """Path for a named generated workspace file."""
    safe = name.strip().replace("/", "_").replace("\\", "_")
    if not safe or safe == "all":
        return DEFAULT_WORKSPACE_PATH
    return os.path.join(WORKSPACES_DIR, f"{safe}.yaml")


def discover_workspace_locations(
    *,
    bundles_dir: str | None = None,
    project_root: str | None = None,
    skip_invalid: bool = True,
    include_bundles: Iterable[str] | None = None,
    include_core: bool = True,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Return (load_from entries, warnings).

    ``include_bundles=None`` → all valid bundles.
    ``include_bundles={'store_intel'}`` → only those names (plus core if enabled).
    """
    root = os.path.abspath(project_root or PROJECT_ROOT)
    bundles_root = bundles_dir or os.path.join(root, "bundles")
    allow = _normalize_bundle_filter(include_bundles)
    load_from: list[dict[str, Any]] = []
    if include_core:
        load_from.append(_core_location(root))
    warnings: list[str] = []
    seen: set[str] = set()

    for name, path in iter_bundle_dirs(bundles_root):
        if allow is not None and name not in allow:
            continue
        seen.add(name)

        is_valid, errors = BundleValidator(path).validate()
        if not is_valid:
            msg = f"skip bundle '{name}' (invalid): " + "; ".join(errors)
            if skip_invalid:
                warnings.append(msg)
                logger.warning(msg)
                continue
            raise BundleContractError(msg)

        try:
            manifest = load_manifest(path)
        except Exception as e:
            warnings.append(f"skip bundle '{name}' (manifest): {e}")
            continue

        entrypoints = manifest.get("entrypoints") or {}
        if isinstance(entrypoints, dict) and entrypoints.get("dagster") is None:
            warnings.append(f"skip bundle '{name}' (entrypoints.dagster=null)")
            continue

        try:
            module_leaf, attr = resolve_dagster_entrypoint(manifest)
        except BundleContractError as e:
            warnings.append(f"skip bundle '{name}' (entrypoint): {e}")
            continue

        module_file = os.path.join(path, f"{module_leaf}.py")
        if not os.path.exists(module_file):
            warnings.append(
                f"skip bundle '{name}' (missing {module_leaf}.py for Dagster entrypoint)"
            )
            continue

        load_from.append(_bundle_location(name, module_leaf, attr, root))
        logger.info(
            "Workspace location bundle_%s → bundles.%s.%s:%s",
            name,
            name,
            module_leaf,
            attr,
        )

    if allow is not None:
        missing = sorted(allow - seen)
        for name in missing:
            warnings.append(f"requested bundle '{name}' not found under {bundles_root}")

    return load_from, warnings


def build_workspace_document(
    *,
    bundles_dir: str | None = None,
    project_root: str | None = None,
    skip_invalid: bool = True,
    include_bundles: Iterable[str] | None = None,
    include_core: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    load_from, warnings = discover_workspace_locations(
        bundles_dir=bundles_dir,
        project_root=project_root,
        skip_invalid=skip_invalid,
        include_bundles=include_bundles,
        include_core=include_core,
    )
    return {"load_from": load_from}, warnings


def write_workspace_yaml(
    path: str | None = None,
    *,
    bundles_dir: str | None = None,
    project_root: str | None = None,
    skip_invalid: bool = True,
    include_bundles: Iterable[str] | None = None,
    include_core: bool = True,
    profile_name: str | None = None,
) -> tuple[str, dict[str, Any], list[str]]:
    """Write workspace.yaml and return (path, document, warnings)."""
    out = os.path.abspath(path or DEFAULT_WORKSPACE_PATH)
    doc, warnings = build_workspace_document(
        bundles_dir=bundles_dir,
        project_root=project_root,
        skip_invalid=skip_invalid,
        include_bundles=include_bundles,
        include_core=include_core,
    )
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    profile_line = f"# profile: {profile_name}\n" if profile_name else ""
    filter_line = (
        f"# bundles: {', '.join(sorted(include_bundles))}\n"
        if include_bundles is not None
        else "# bundles: * (all)\n"
    )
    header = (
        "# Auto-generated by DataHarbor (apps.dagster_app.workspace_builder).\n"
        "# One Dagster code location per selected bundle (+ core). Do not edit by hand;\n"
        "# run: harbor workspace refresh [--name PROFILE] [--only a,b]\n"
        f"{profile_line}{filter_line}"
    )
    with open(out, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(doc, f, sort_keys=False, default_flow_style=False)
    return out, doc, warnings


def write_named_workspace(
    name: str,
    *,
    only: Iterable[str] | None = None,
    include_core: bool = True,
    skip_invalid: bool = True,
    project_root: str | None = None,
    profiles_path: str | None = None,
) -> tuple[str, dict[str, Any], list[str]]:
    """Resolve profile or explicit ``only`` list and write ``workspaces/<name>.yaml``."""
    profile_name: str | None = None
    include: list[str] | None
    if only is not None:
        include = list(only)
    else:
        include, _profile = resolve_profile_bundles(name, profiles_path=profiles_path)
        profile_name = name

    out = workspace_path_for_name(name)
    return write_workspace_yaml(
        out,
        project_root=project_root,
        skip_invalid=skip_invalid,
        include_bundles=include,
        include_core=include_core,
        profile_name=profile_name,
    )


def location_names(doc: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for entry in doc.get("load_from") or []:
        for key in ("python_module", "python_file", "grpc_server"):
            block = entry.get(key)
            if isinstance(block, dict) and block.get("location_name"):
                names.append(str(block["location_name"]))
    return names
