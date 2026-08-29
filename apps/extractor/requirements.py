"""Parse and resolve bundle ``requirements.extractors`` declarations.

Supported entry forms (least entropy, private-repo friendly):

1. Local / already-installed id::
       "demo_site"

2. Git / archive / path source (name derived from repo basename)::
       "https://github.com/acme/dh-extractor-example.git"
       "git@github.com:acme/dh-extractor-example.git"

3. Explicit object::
       {"name": "example", "source": "git@github.com:acme/dh-extractor-example.git"}
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_GIT_URL_RE = re.compile(
    r"^(?:git@|https?://|ssh://).+",
    re.IGNORECASE,
)

# Shipped example extractor(s) that do not need a separate git publish.
CORE_EXTRACTOR_IDS = frozenset({"demo_site"})


def looks_like_git_url(value: str) -> bool:
    """Return True for git remotes (not local paths/archives)."""
    text = (value or "").strip()
    if not text:
        return False
    if text.endswith(".git") and _GIT_URL_RE.match(text):
        return True
    if text.startswith(("git@", "ssh://")):
        return True
    if text.startswith(("http://", "https://")) and (
        "github.com" in text or "gitlab." in text or "bitbucket." in text or text.endswith(".git")
    ):
        return True
    return bool(_GIT_URL_RE.match(text) and not os.path.exists(text))


def looks_like_source(value: str) -> bool:
    """Return True if value is a git URL, archive path, or existing directory."""
    text = (value or "").strip()
    if not text:
        return False
    if text.endswith((".git", ".zip", ".tar.gz", ".tgz")):
        return True
    if _GIT_URL_RE.match(text):
        return True
    if os.path.isdir(text) or os.path.isfile(text):
        return True
    return False


def derive_extractor_name_from_source(source: str) -> str:
    """Derive a Python-identifier extractor directory name from a source URL/path."""
    raw = source.rstrip("/").split("/")[-1]
    raw = raw.replace(".git", "").replace(".tar.gz", "").replace(".tgz", "").replace(".zip", "")
    for prefix in ("dh-extractor-", "dh_extractor_", "extractor-", "extractor_"):
        if raw.lower().startswith(prefix):
            raw = raw[len(prefix) :]
            break
    name = re.sub(r"[^0-9a-zA-Z_]+", "_", raw).strip("_").lower()
    if not name:
        raise ValueError(f"Cannot derive extractor name from source: {source}")
    if name[0].isdigit():
        name = f"ext_{name}"
    return name


def parse_extractor_requirement(entry: Any) -> dict[str, str | None]:
    """Normalize one requirements.extractors entry to ``{name, source}``."""
    if isinstance(entry, str):
        text = entry.strip()
        if not text:
            raise ValueError("Empty extractor requirement entry.")
        if looks_like_source(text):
            return {"name": derive_extractor_name_from_source(text), "source": text}
        return {"name": text.replace("-", "_"), "source": None}

    if isinstance(entry, dict):
        source = entry.get("source") or entry.get("url") or entry.get("repo")
        name = entry.get("name") or entry.get("id")
        if source:
            source = str(source).strip()
        if name:
            name = str(name).replace("-", "_").strip()
        elif source:
            name = derive_extractor_name_from_source(source)
        if not name:
            raise ValueError(
                f"Extractor requirement object missing 'name'/'source': {entry}"
            )
        if source and not looks_like_source(str(source)):
            raise ValueError(f"Invalid extractor source '{source}' in requirement: {entry}")
        return {"name": name, "source": source}

    raise ValueError(
        f"Unsupported extractor requirement type {type(entry).__name__}: {entry}"
    )


def parse_extractor_requirements(raw_entries: Any) -> list[dict[str, str | None]]:
    """Parse full ``requirements.extractors`` array."""
    if raw_entries is None:
        return []
    if not isinstance(raw_entries, list):
        raise ValueError("requirements.extractors must be an array.")
    return [parse_extractor_requirement(entry) for entry in raw_entries]


def find_unpublished_local_extractors(bundle_path: str) -> list[dict[str, Any]]:
    """Return extractors declared without a git remote (need user publish).

    Core platform example extractors (e.g. demo_site) are ignored.
    Does not auto-publish — caller should prompt the user.
    """
    import json

    manifest_path = os.path.join(bundle_path, "manifest.json")
    if not os.path.exists(manifest_path):
        return []

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    requirements = parse_extractor_requirements(
        (manifest.get("requirements") or {}).get("extractors")
    )
    unpublished: list[dict[str, Any]] = []

    for req in requirements:
        name = req.get("name") or ""
        source = req.get("source")

        if source and looks_like_git_url(source):
            continue

        if name in CORE_EXTRACTOR_IDS and not source:
            continue

        reason = "local id without git source"
        if source and os.path.isdir(str(source)):
            reason = "local filesystem path (not a git remote)"
        elif source:
            reason = f"non-git source: {source}"

        unpublished.append(
            {
                "name": name,
                "source": source,
                "reason": reason,
                "suggest": f"harbor extractor publish {name}",
            }
        )

    return unpublished


def resolve_bundle_extractors(
    bundle_path: str,
    *,
    force: bool = False,
    install_missing: bool = True,
) -> list[dict[str, Any]]:
    """Install extractors declared with a source URL; return resolution report.

    Entries without ``source`` must already exist under ``extractors/``
    (core/platform extractors or previously installed plugins).
    """
    from apps.extractor.distributor import ExtractorDistributor
    from apps.extractor.paths import EXTRACTORS_DIR
    from apps.scraper.extractors.registry import (
        clear_registry_cache,
        is_extractor_installed,
    )

    manifest_path = os.path.join(bundle_path, "manifest.json")
    if not os.path.exists(manifest_path):
        raise ValueError(f"Bundle manifest missing: {manifest_path}")

    import json

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    requirements = parse_extractor_requirements(
        (manifest.get("requirements") or {}).get("extractors")
    )
    distributor = ExtractorDistributor()
    report: list[dict[str, Any]] = []

    for req in requirements:
        name = req["name"]
        source = req["source"]
        already = os.path.isdir(os.path.join(EXTRACTORS_DIR, name)) and is_extractor_installed(
            name
        )

        if already and not force:
            report.append(
                {
                    "name": name,
                    "source": source,
                    "status": "already_installed",
                    "path": os.path.join(EXTRACTORS_DIR, name),
                }
            )
            continue

        if source:
            if not install_missing:
                report.append(
                    {
                        "name": name,
                        "source": source,
                        "status": "missing",
                        "path": None,
                    }
                )
                continue
            logger.info(f"Installing extractor '{name}' from {source}")
            result = distributor.install_extractor(source, force=force or already)
            # Ensure directory name matches declared name when git basename differs
            installed_name = result.get("extractor_name")
            installed_path = result.get("installed_path")
            if installed_name and installed_name != name and installed_path:
                target = os.path.join(EXTRACTORS_DIR, name)
                if os.path.abspath(installed_path) != os.path.abspath(target):
                    if os.path.exists(target):
                        import shutil

                        if force:
                            shutil.rmtree(target)
                        else:
                            raise ValueError(
                                f"Extractor '{name}' target exists but install produced "
                                f"'{installed_name}'. Use --force to overwrite."
                            )
                    import shutil

                    shutil.move(installed_path, target)
                    clear_registry_cache()
                    installed_path = target
                    installed_name = name
            report.append(
                {
                    "name": installed_name or name,
                    "source": source,
                    "status": "installed",
                    "path": installed_path,
                }
            )
            continue

        # Local id without source
        if not already:
            raise ValueError(
                f"Extractor '{name}' is required by the bundle but is not installed and "
                f"has no 'source' URL in requirements.extractors. "
                f"Add a private-repo URL or run: harbor extractor install <source>"
            )
        report.append(
            {
                "name": name,
                "source": None,
                "status": "already_installed",
                "path": os.path.join(EXTRACTORS_DIR, name),
            }
        )

    clear_registry_cache()
    return report
