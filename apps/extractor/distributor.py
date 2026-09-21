"""Install, pack, list, and remove DataHarbor extractor plugins."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from typing import Any

from apps.extractor.paths import EXTRACTORS_DIR
from apps.extractor.validator import ExtractorValidator

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_extract_zip(zip_ref: zipfile.ZipFile, dest_dir: str) -> None:
    """Extract a zip archive, rejecting members that would escape ``dest_dir`` (zip-slip)."""
    dest_root = os.path.realpath(dest_dir)
    for member in zip_ref.namelist():
        member_path = os.path.realpath(os.path.join(dest_root, member))
        if member_path != dest_root and not member_path.startswith(dest_root + os.sep):
            raise ValueError(f"Archive member '{member}' would extract outside the target directory.")
    zip_ref.extractall(dest_root)


def _sanitize_plugin_name(raw_name: str, fallback: str) -> str:
    """Reject a manifest ``name`` that isn't a safe directory-name identifier.

    ``manifest.json`` is untrusted content from the source being installed — using
    its ``name`` field as a path component without validation lets a crafted value
    like ``"../../etc/cron.d/evil"`` install outside ``extractors_dir``.
    """
    candidate = (raw_name or "").replace("-", "_").strip()
    if _SAFE_NAME_RE.match(candidate):
        return candidate
    safe_fallback = (fallback or "custom_extractor").replace("-", "_")
    logger.warning(f"Manifest name {raw_name!r} is not a safe identifier; using {safe_fallback!r} instead.")
    return safe_fallback if _SAFE_NAME_RE.match(safe_fallback) else "custom_extractor"


class ExtractorDistributor:
    """Manages installation, packaging, listing, and removal of extractor plugins."""

    def __init__(self, extractors_dir: str = EXTRACTORS_DIR):
        self.extractors_dir = extractors_dir

    def list_extractors(self) -> list[dict[str, Any]]:
        extractors_info: list[dict[str, Any]] = []
        if not os.path.exists(self.extractors_dir):
            return extractors_info

        for entry in sorted(os.listdir(self.extractors_dir)):
            extractor_path = os.path.join(self.extractors_dir, entry)
            if not os.path.isdir(extractor_path) or entry.startswith((".", "_")):
                continue

            manifest_data: dict[str, Any] = {}
            manifest_path = os.path.join(extractor_path, "manifest.json")
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, encoding="utf-8") as f:
                        manifest_data = json.load(f)
                except Exception:
                    pass

            is_valid, errors = ExtractorValidator(extractor_path).validate()
            extractors_info.append(
                {
                    "name": manifest_data.get("name", entry),
                    "dir_name": entry,
                    "version": manifest_data.get("version", "0.1.0"),
                    "description": manifest_data.get("description", "No description provided."),
                    "domains": manifest_data.get("domains") or [],
                    "is_valid": is_valid,
                    "errors": errors,
                    "path": extractor_path,
                }
            )
        return extractors_info

    def install_extractor(self, source: str, force: bool = False) -> dict[str, Any]:
        logger.info(f"Installing extractor from source: {source}")
        try:
            if (
                source.endswith(".git")
                or (source.startswith(("http://", "https://", "git@")) and not source.endswith((".zip", ".tar.gz", ".tgz")))
            ):
                extractor_name = source.rstrip("/").split("/")[-1].replace(".git", "").replace("-", "_")
                target_path = os.path.join(self.extractors_dir, extractor_name)
                if os.path.exists(target_path):
                    if not force:
                        raise ValueError(
                            f"Extractor '{extractor_name}' is already installed at {target_path}. "
                            "Use --force to overwrite."
                        )
                    shutil.rmtree(target_path)
                subprocess.check_call(["git", "clone", source, target_path])

            elif os.path.isfile(source) and source.endswith((".tar.gz", ".tgz", ".zip")):
                temp_extract = os.path.join(self.extractors_dir, "_temp_extract")
                if os.path.exists(temp_extract):
                    shutil.rmtree(temp_extract)
                os.makedirs(temp_extract, exist_ok=True)

                if source.endswith(".zip"):
                    with zipfile.ZipFile(source, "r") as zip_ref:
                        _safe_extract_zip(zip_ref, temp_extract)
                else:
                    with tarfile.open(source, "r:*") as tar_ref:
                        tar_ref.extractall(temp_extract, filter="data")

                extracted_entries = [e for e in os.listdir(temp_extract) if not e.startswith(".")]
                if len(extracted_entries) == 1 and os.path.isdir(
                    os.path.join(temp_extract, extracted_entries[0])
                ):
                    source_dir = os.path.join(temp_extract, extracted_entries[0])
                else:
                    source_dir = temp_extract

                manifest_path = os.path.join(source_dir, "manifest.json")
                if not os.path.exists(manifest_path):
                    shutil.rmtree(temp_extract)
                    raise ValueError("Archive is missing 'manifest.json' file.")

                with open(manifest_path, encoding="utf-8") as f:
                    mdata = json.load(f)

                extractor_name = _sanitize_plugin_name(mdata.get("name", ""), "custom_extractor")
                target_path = os.path.join(self.extractors_dir, extractor_name)
                if os.path.exists(target_path):
                    if not force:
                        shutil.rmtree(temp_extract)
                        raise ValueError(
                            f"Extractor '{extractor_name}' already exists. Use --force to overwrite."
                        )
                    shutil.rmtree(target_path)

                shutil.move(source_dir, target_path)
                if os.path.exists(temp_extract):
                    shutil.rmtree(temp_extract)

            elif os.path.isdir(source):
                manifest_path = os.path.join(source, "manifest.json")
                if not os.path.exists(manifest_path):
                    raise ValueError(f"Local source directory '{source}' is missing 'manifest.json'.")

                with open(manifest_path, encoding="utf-8") as f:
                    mdata = json.load(f)

                extractor_name = _sanitize_plugin_name(mdata.get("name", ""), os.path.basename(source))
                target_path = os.path.join(self.extractors_dir, extractor_name)
                if os.path.exists(target_path):
                    if not force:
                        raise ValueError(
                            f"Extractor '{extractor_name}' already exists. Use --force to overwrite."
                        )
                    shutil.rmtree(target_path)

                shutil.copytree(
                    source,
                    target_path,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
                )
            else:
                raise ValueError(f"Unsupported extractor installation source: {source}")

            is_valid, errors = ExtractorValidator(target_path).validate()
            if not is_valid:
                shutil.rmtree(target_path)
                raise ValueError(
                    "Extractor validation failed post-installation:\n  - " + "\n  - ".join(errors)
                )

            try:
                from apps.scraper.extractors.registry import clear_registry_cache

                clear_registry_cache()
            except Exception:
                pass

            return {
                "status": "success",
                "extractor_name": extractor_name,
                "installed_path": target_path,
                "message": f"Extractor '{extractor_name}' installed and validated successfully!",
            }
        except Exception as e:
            logger.error(f"Extractor installation failed: {e}")
            raise

    def pack_extractor(self, extractor_name: str, output_dir: str | None = None) -> str:
        extractor_path = os.path.join(self.extractors_dir, extractor_name)
        if not os.path.exists(extractor_path):
            raise ValueError(f"Extractor '{extractor_name}' does not exist in {self.extractors_dir}.")

        is_valid, errors = ExtractorValidator(extractor_path).validate()
        if not is_valid:
            raise ValueError(
                f"Cannot pack invalid extractor '{extractor_name}':\n  - " + "\n  - ".join(errors)
            )

        with open(os.path.join(extractor_path, "manifest.json"), encoding="utf-8") as f:
            mdata = json.load(f)

        version = mdata.get("version", "0.1.0")
        output_dir = output_dir or os.path.join(os.path.dirname(self.extractors_dir), "exports")
        os.makedirs(output_dir, exist_ok=True)
        archive_path = os.path.join(output_dir, f"{extractor_name}-v{version}.tar.gz")

        def filter_fn(tarinfo):
            if any(part in tarinfo.name for part in [".git", "__pycache__", ".DS_Store", ".venv"]):
                return None
            return tarinfo

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(extractor_path, arcname=extractor_name, filter=filter_fn)

        logger.info(f"Extractor '{extractor_name}' packed to: {archive_path}")
        return archive_path

    def remove_extractor(self, extractor_name: str) -> bool:
        extractor_path = os.path.join(self.extractors_dir, extractor_name)
        if not os.path.exists(extractor_path):
            raise ValueError(f"Extractor '{extractor_name}' is not installed.")

        shutil.rmtree(extractor_path)
        try:
            from apps.scraper.extractors.registry import clear_registry_cache

            clear_registry_cache()
        except Exception:
            pass
        logger.info(f"Extractor '{extractor_name}' removed from {extractor_path}.")
        return True
