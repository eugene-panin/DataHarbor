"""Validates structural integrity of DataHarbor extractor plugins."""
from __future__ import annotations

import json
import os
import py_compile
from typing import Any

from apps.scraper.extractor_api import REQUIRED_MANIFEST_KEYS, resolve_entrypoint

EXTRACTORS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(EXTRACTORS_DIR)


class ExtractorValidator:
    """Validates manifest schema, syntax, and callable parse entrypoint."""

    def __init__(self, extractor_path: str):
        self.extractor_path = extractor_path
        self.extractor_name = os.path.basename(extractor_path)

    def validate(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        manifest_data: dict[str, Any] = {}

        if not self.extractor_name.isidentifier():
            errors.append(
                f"Invalid extractor directory name '{self.extractor_name}'. "
                "Must be a valid Python identifier."
            )

        manifest_path = os.path.join(self.extractor_path, "manifest.json")
        if not os.path.exists(manifest_path):
            errors.append(f"Missing required 'manifest.json' in extractor '{self.extractor_name}'.")
            return False, errors

        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest_data = json.load(f)
        except Exception as e:
            errors.append(f"Invalid JSON in 'manifest.json' for '{self.extractor_name}': {e}")
            return False, errors

        for key in REQUIRED_MANIFEST_KEYS:
            if key not in manifest_data or manifest_data[key] in (None, "", []):
                errors.append(
                    f"Manifest missing required field '{key}' in extractor '{self.extractor_name}'."
                )

        domains = manifest_data.get("domains")
        if domains is not None and not isinstance(domains, list):
            errors.append(f"Manifest field 'domains' must be an array in '{self.extractor_name}'.")

        entrypoint = manifest_data.get("entrypoint")
        module_stem = None
        attr_name = None
        if isinstance(entrypoint, str) and entrypoint:
            try:
                module_stem, attr_name = resolve_entrypoint(entrypoint)
            except ValueError as e:
                errors.append(str(e))

        for root, _, files in os.walk(self.extractor_path):
            for file in files:
                if not file.endswith(".py"):
                    continue
                py_file = os.path.join(root, file)
                rel_file = os.path.relpath(py_file, self.extractor_path)
                try:
                    py_compile.compile(py_file, doraise=True)
                except py_compile.PyCompileError as err:
                    errors.append(f"Syntax error in '{rel_file}': {err.msg}")

        if module_stem and attr_name and not errors:
            module_file = os.path.join(self.extractor_path, f"{module_stem}.py")
            if not os.path.exists(module_file):
                errors.append(
                    f"Entrypoint module '{module_stem}.py' missing in extractor '{self.extractor_name}'."
                )
            else:
                try:
                    import importlib.util

                    spec = importlib.util.spec_from_file_location(
                        f"dh_extractor_validate_{self.extractor_name}_{module_stem}",
                        module_file,
                    )
                    if spec is None or spec.loader is None:
                        raise ImportError(f"Cannot load module from {module_file}")
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    parse_fn = getattr(module, attr_name, None)
                    if not callable(parse_fn):
                        errors.append(
                            f"Entrypoint '{entrypoint}' is not callable in extractor '{self.extractor_name}'."
                        )
                except Exception as e:
                    errors.append(
                        f"Failed to import entrypoint '{entrypoint}' for '{self.extractor_name}': {e}"
                    )

        return len(errors) == 0, errors


def validate_all_extractors(extractors_dir: str = EXTRACTORS_DIR) -> dict[str, tuple[bool, list[str]]]:
    """Validate all extractor folders under extractors_dir."""
    results: dict[str, tuple[bool, list[str]]] = {}
    if not os.path.exists(extractors_dir):
        return results

    for entry in sorted(os.listdir(extractors_dir)):
        extractor_path = os.path.join(extractors_dir, entry)
        if os.path.isdir(extractor_path) and not entry.startswith((".", "_")):
            results[entry] = ExtractorValidator(extractor_path).validate()
    return results
