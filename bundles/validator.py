import json
import logging
import os
import py_compile
import re
from typing import Any

from bundles.plugin_contract import validate_manifest_contract

logger = logging.getLogger(__name__)

REQUIRED_MANIFEST_KEYS = ["name", "version", "description"]
_EXTRACTOR_ID_RE = re.compile(
    r"""(?:get_extractor|require_extractor)\(\s*['"]([a-zA-Z_][\w-]*)['"]\s*\)"""
)


class BundleValidationError(Exception):
    """Exception raised when bundle validation fails."""


class BundleValidator:
    """Validates structural integrity, manifest schema, and code syntax of bundles."""

    def __init__(self, bundle_path: str):
        self.bundle_path = bundle_path
        self.bundle_name = os.path.basename(bundle_path)

    def validate(self) -> tuple[bool, list[str]]:
        """Executes all validation checks. Returns (is_valid, error_messages)."""
        errors = []
        manifest_data: dict[str, Any] = {}
        declared_names: list[str] = []

        # Check 1: Directory name syntax
        if not self.bundle_name.isidentifier():
            errors.append(
                f"Invalid bundle directory name '{self.bundle_name}'. Must be valid Python identifier."
            )

        # Check 2: Manifest file presence & schema
        manifest_path = os.path.join(self.bundle_path, "manifest.json")
        if not os.path.exists(manifest_path):
            errors.append(f"Missing required 'manifest.json' file in bundle '{self.bundle_name}'.")
        else:
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest_data = json.load(f)
            except Exception as e:
                errors.append(
                    f"Invalid JSON format in 'manifest.json' for bundle '{self.bundle_name}': {e}"
                )
            else:
                for key in REQUIRED_MANIFEST_KEYS:
                    if key not in manifest_data or not manifest_data[key]:
                        errors.append(
                            f"Manifest missing required field '{key}' in bundle '{self.bundle_name}'."
                        )
                errors.extend(validate_manifest_contract(manifest_data))

        # Check 3: Python syntax compilation check
        py_files = [
            os.path.join(root, file)
            for root, _, files in os.walk(self.bundle_path)
            for file in files
            if file.endswith(".py")
        ]

        if not py_files:
            errors.append(f"No Python (.py) source files found in bundle '{self.bundle_name}'.")

        for py_file in py_files:
            rel_file = os.path.relpath(py_file, self.bundle_path)
            try:
                py_compile.compile(py_file, doraise=True)
            except py_compile.PyCompileError as err:
                errors.append(f"Syntax error in '{rel_file}': {err.msg}")

        # Check 4: Declared extractors (id | URL | {name,source}) must resolve to installed plugins
        raw_extractors = (manifest_data.get("requirements") or {}).get("extractors") if manifest_data else None
        if raw_extractors is not None and not isinstance(raw_extractors, list):
            errors.append(
                f"Manifest requirements.extractors must be an array in bundle '{self.bundle_name}'."
            )
        elif raw_extractors:
            try:
                from apps.scraper.extractors.registry import is_extractor_installed
                from extractors.requirements import parse_extractor_requirements
                from extractors.validator import EXTRACTORS_DIR, ExtractorValidator

                requirements = parse_extractor_requirements(raw_extractors)
                declared_names = [req["name"] for req in requirements if req.get("name")]

                for req in requirements:
                    extractor_id = req["name"]
                    source = req.get("source")
                    extractor_path = os.path.join(EXTRACTORS_DIR, extractor_id)
                    if not os.path.isdir(extractor_path):
                        if source:
                            errors.append(
                                f"Bundle '{self.bundle_name}' requires extractor '{extractor_id}' "
                                f"from '{source}' but it is not installed. "
                                f"Install via 'harbor bundle install <bundle-src>' "
                                f"or 'harbor extractor resolve {self.bundle_name}'."
                            )
                        else:
                            errors.append(
                                f"Bundle '{self.bundle_name}' requires extractor '{extractor_id}' "
                                f"but it is not installed under extractors/ and has no source URL."
                            )
                        continue
                    is_valid, ext_errors = ExtractorValidator(extractor_path).validate()
                    if not is_valid:
                        errors.append(
                            f"Required extractor '{extractor_id}' failed validation: "
                            + "; ".join(ext_errors)
                        )
                    elif not is_extractor_installed(extractor_id):
                        errors.append(
                            f"Required extractor '{extractor_id}' is present but failed to load "
                            f"into the registry."
                        )
            except Exception as e:
                errors.append(
                    f"Failed to cross-validate extractors for bundle '{self.bundle_name}': {e}"
                )

        # Check 5: scraper references to get_extractor/require_extractor must be declared
        scraper_path = os.path.join(self.bundle_path, "scraper.py")
        if os.path.exists(scraper_path):
            try:
                with open(scraper_path, encoding="utf-8") as f:
                    scraper_code = f.read()
                referenced = set(_EXTRACTOR_ID_RE.findall(scraper_code))
                declared_set = set(declared_names)
                for extractor_id in sorted(referenced):
                    normalized = extractor_id.replace("-", "_")
                    if normalized not in declared_set:
                        errors.append(
                            f"Extractor '{normalized}' is used in scraper.py via get_extractor/"
                            f"require_extractor but not declared in manifest.json "
                            f"requirements.extractors."
                        )
            except Exception as e:
                logger.debug(f"Error cross-validating extractor references: {e}")

        # Check 6: Flexible Entrypoints (Must have at least one functional component)
        entrypoint_files = ["assets.py", "db.py", "scraper.py", "exporter.py", "fetch.py"]
        has_entrypoint = any(
            os.path.exists(os.path.join(self.bundle_path, f)) for f in entrypoint_files
        )
        if not has_entrypoint:
            errors.append(
                f"Bundle '{self.bundle_name}' must contain at least one functional file: "
                f"{', '.join(entrypoint_files)}."
            )

        is_valid = len(errors) == 0
        return is_valid, errors


def validate_all_bundles(bundles_dir: str) -> dict[str, tuple[bool, list[str]]]:
    """Validates all bundle folders in bundles_dir."""
    results = {}
    if not os.path.exists(bundles_dir):
        return results

    for entry in os.listdir(bundles_dir):
        bundle_path = os.path.join(bundles_dir, entry)
        if os.path.isdir(bundle_path) and not entry.startswith((".", "_")):
            validator = BundleValidator(bundle_path)
            results[entry] = validator.validate()

    return results
