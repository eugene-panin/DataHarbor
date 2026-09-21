import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from typing import Any

from apps.bundle.paths import BUNDLES_DIR
from apps.bundle.validator import BundleValidator

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
    like ``"../../etc/cron.d/evil"`` install outside ``bundles_dir``.
    """
    candidate = (raw_name or "").replace("-", "_").strip()
    if _SAFE_NAME_RE.match(candidate):
        return candidate
    safe_fallback = (fallback or "custom_bundle").replace("-", "_")
    logger.warning(f"Manifest name {raw_name!r} is not a safe identifier; using {safe_fallback!r} instead.")
    return safe_fallback if _SAFE_NAME_RE.match(safe_fallback) else "custom_bundle"


class BundleDistributor:
    """Manages installation, packaging, listing, updating, and removal of DataHarbor bundles."""

    def __init__(self, bundles_dir: str = BUNDLES_DIR):
        self.bundles_dir = bundles_dir

    def list_bundles(self) -> list[dict[str, Any]]:
        """Lists all installed bundles with metadata and validation status."""
        bundles_info = []
        if not os.path.exists(self.bundles_dir):
            return bundles_info

        for entry in sorted(os.listdir(self.bundles_dir)):
            bundle_path = os.path.join(self.bundles_dir, entry)
            if os.path.isdir(bundle_path) and not entry.startswith((".", "_")):
                manifest_path = os.path.join(bundle_path, "manifest.json")
                manifest_data = {}
                if os.path.exists(manifest_path):
                    try:
                        with open(manifest_path, encoding="utf-8") as f:
                            manifest_data = json.load(f)
                    except Exception:
                        pass

                validator = BundleValidator(bundle_path)
                is_valid, errors = validator.validate()

                # Check Git origin if git repo
                git_dir = os.path.join(bundle_path, ".git")
                git_url = None
                if os.path.exists(git_dir):
                    try:
                        out = subprocess.check_output(["git", "-C", bundle_path, "config", "--get", "remote.origin.url"])
                        git_url = out.decode("utf-8").strip()
                    except Exception:
                        pass

                bundles_info.append({
                    "name": manifest_data.get("name", entry),
                    "dir_name": entry,
                    "version": manifest_data.get("version", "0.1.0"),
                    "description": manifest_data.get("description", "No description provided."),
                    "author": manifest_data.get("author", "Unknown"),
                    "is_valid": is_valid,
                    "errors": errors,
                    "git_url": git_url,
                    "path": bundle_path
                })

        return bundles_info

    def install_bundle(self, source: str, force: bool = False) -> dict[str, Any]:
        """Installs a bundle from a Git URL, local directory, or tar.gz/zip archive."""
        logger.info(f"Installing bundle from source: {source}")

        try:
            # 1. Git Repository Source
            if source.endswith(".git") or source.startswith(("http://", "https://", "git@")) and not source.endswith((".zip", ".tar.gz", ".tgz")):
                bundle_name = source.rstrip("/").split("/")[-1].replace(".git", "").replace("-", "_")
                target_path = os.path.join(self.bundles_dir, bundle_name)

                if os.path.exists(target_path):
                    if not force:
                        raise ValueError(f"Bundle '{bundle_name}' is already installed at {target_path}. Use --force to overwrite.")
                    shutil.rmtree(target_path)

                logger.info(f"Cloning Git repository '{source}' into '{target_path}'...")
                subprocess.check_call(["git", "clone", source, target_path])

            # 2. Local Archive File (.tar.gz / .zip)
            elif os.path.isfile(source) and source.endswith((".tar.gz", ".tgz", ".zip")):
                temp_extract = os.path.join(self.bundles_dir, "_temp_extract")
                if os.path.exists(temp_extract):
                    shutil.rmtree(temp_extract)
                os.makedirs(temp_extract, exist_ok=True)

                if source.endswith(".zip"):
                    with zipfile.ZipFile(source, 'r') as zip_ref:
                        _safe_extract_zip(zip_ref, temp_extract)
                else:
                    with tarfile.open(source, 'r:*') as tar_ref:
                        tar_ref.extractall(temp_extract, filter="data")

                # Locate manifest inside extracted directory
                extracted_entries = [e for e in os.listdir(temp_extract) if not e.startswith(".")]
                if len(extracted_entries) == 1 and os.path.isdir(os.path.join(temp_extract, extracted_entries[0])):
                    source_dir = os.path.join(temp_extract, extracted_entries[0])
                else:
                    source_dir = temp_extract

                manifest_path = os.path.join(source_dir, "manifest.json")
                if not os.path.exists(manifest_path):
                    shutil.rmtree(temp_extract)
                    raise ValueError("Archive is missing 'manifest.json' file.")

                with open(manifest_path, encoding="utf-8") as f:
                    mdata = json.load(f)

                bundle_name = _sanitize_plugin_name(mdata.get("name", ""), "custom_bundle")
                target_path = os.path.join(self.bundles_dir, bundle_name)

                if os.path.exists(target_path):
                    if not force:
                        shutil.rmtree(temp_extract)
                        raise ValueError(f"Bundle '{bundle_name}' already exists. Use --force to overwrite.")
                    shutil.rmtree(target_path)

                shutil.move(source_dir, target_path)
                if os.path.exists(temp_extract):
                    shutil.rmtree(temp_extract)

            # 3. Local Directory Source
            elif os.path.isdir(source):
                manifest_path = os.path.join(source, "manifest.json")
                if not os.path.exists(manifest_path):
                    raise ValueError(f"Local source directory '{source}' is missing 'manifest.json'.")

                with open(manifest_path, encoding="utf-8") as f:
                    mdata = json.load(f)

                bundle_name = _sanitize_plugin_name(mdata.get("name", ""), os.path.basename(source))
                target_path = os.path.join(self.bundles_dir, bundle_name)

                if os.path.exists(target_path):
                    if not force:
                        raise ValueError(f"Bundle '{bundle_name}' already exists. Use --force to overwrite.")
                    shutil.rmtree(target_path)

                shutil.copytree(source, target_path, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))

            else:
                raise ValueError(f"Unsupported bundle installation source: {source}")

            # Auto-install extractors declared with source URLs in the bundle manifest
            from apps.extractor.requirements import resolve_bundle_extractors

            try:
                extractor_report = resolve_bundle_extractors(target_path, force=force)
            except Exception:
                if os.path.exists(target_path):
                    shutil.rmtree(target_path)
                raise

            for item in extractor_report:
                logger.info(
                    f"Extractor resolve [{item['status']}]: {item['name']}"
                    + (f" <- {item['source']}" if item.get("source") else "")
                )

            # Validate installed bundle
            validator = BundleValidator(target_path)
            is_valid, errors = validator.validate()
            if not is_valid:
                shutil.rmtree(target_path)
                raise ValueError("Bundle validation failed post-installation:\n  - " + "\n  - ".join(errors))

            return {
                "status": "success",
                "bundle_name": bundle_name,
                "installed_path": target_path,
                "extractors": extractor_report,
                "message": f"Bundle '{bundle_name}' installed and validated successfully!"
            }

        except Exception as e:
            logger.error(f"Bundle installation failed: {e}")
            raise e

    def resolve_extractors(self, bundle_name: str, force: bool = False) -> list[dict[str, Any]]:
        """Install/update extractors declared by an already-installed bundle."""
        from apps.extractor.requirements import resolve_bundle_extractors

        bundle_path = os.path.join(self.bundles_dir, bundle_name)
        if not os.path.exists(bundle_path):
            raise ValueError(f"Bundle '{bundle_name}' is not installed.")
        return resolve_bundle_extractors(bundle_path, force=force)

    def pack_bundle(self, bundle_name: str, output_dir: str | None = None) -> str:
        """Packs a bundle into a clean distribution tar.gz archive."""
        bundle_path = os.path.join(self.bundles_dir, bundle_name)
        if not os.path.exists(bundle_path):
            raise ValueError(f"Bundle '{bundle_name}' does not exist in {self.bundles_dir}.")

        validator = BundleValidator(bundle_path)
        is_valid, errors = validator.validate()
        if not is_valid:
            raise ValueError(f"Cannot pack invalid bundle '{bundle_name}':\n  - " + "\n  - ".join(errors))

        manifest_path = os.path.join(bundle_path, "manifest.json")
        with open(manifest_path, encoding="utf-8") as f:
            mdata = json.load(f)

        version = mdata.get("version", "0.1.0")
        output_dir = output_dir or os.path.join(os.path.dirname(self.bundles_dir), "exports")
        os.makedirs(output_dir, exist_ok=True)

        archive_filename = f"{bundle_name}-v{version}.tar.gz"
        archive_path = os.path.join(output_dir, archive_filename)

        def filter_fn(tarinfo):
            if any(part in tarinfo.name for part in [".git", "__pycache__", ".DS_Store", ".venv"]):
                return None
            return tarinfo

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(bundle_path, arcname=bundle_name, filter=filter_fn)

        logger.info(f"Bundle '{bundle_name}' packed to: {archive_path}")
        return archive_path

    def remove_bundle(self, bundle_name: str) -> bool:
        """Removes an installed bundle directory."""
        bundle_path = os.path.join(self.bundles_dir, bundle_name)
        if not os.path.exists(bundle_path):
            raise ValueError(f"Bundle '{bundle_name}' is not installed.")

        shutil.rmtree(bundle_path)
        logger.info(f"Bundle '{bundle_name}' removed from {bundle_path}.")
        return True

    def render_bundle_exporter(self, bundle_name: str, db_conn=None, clickhouse_client=None) -> str:
        """Dynamically loads and renders a bundle's Presentation Layer HTML view via exporter.py."""
        import importlib
        bundle_path = os.path.join(self.bundles_dir, bundle_name)
        exporter_path = os.path.join(bundle_path, "exporter.py")

        if not os.path.exists(exporter_path):
            raise ValueError(f"Bundle '{bundle_name}' does not contain an exporter.py presentation module.")

        module_name = f"bundles.{bundle_name}.exporter"
        exporter_module = importlib.import_module(module_name)

        if hasattr(exporter_module, "generate_report"):
            return exporter_module.generate_report(db_conn=db_conn, clickhouse_client=clickhouse_client)
        else:
            raise ValueError(f"Bundle exporter '{module_name}' is missing required 'generate_report()' entry point.")
