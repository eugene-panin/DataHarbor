"""Validates structural integrity of DataHarbor extractor plugins."""
from __future__ import annotations

import importlib.util
import json
import os
import py_compile
import sys
from typing import Any

from apps.extractor.paths import EXTRACTORS_DIR
from apps.scraper.extractor_api import REQUIRED_MANIFEST_KEYS, resolve_entrypoint


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
        elif entrypoint not in (None, "", []):
            # A non-string entrypoint (e.g. entrypoint: 123) previously fell
            # through both the required-field check (it's non-empty, so that
            # passed) and this string check (isinstance() is False, so this
            # silently skipped too) — validate() reported no error at all.
            errors.append(
                f"Manifest field 'entrypoint' must be a string like 'module:function' "
                f"in extractor '{self.extractor_name}', got {entrypoint!r}."
            )

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
                    parse_fn = self._import_entrypoint_attr(module_stem, attr_name, module_file)
                    if not callable(parse_fn):
                        errors.append(
                            f"Entrypoint '{entrypoint}' is not callable in extractor '{self.extractor_name}'."
                        )
                except Exception as e:
                    errors.append(
                        f"Failed to import entrypoint '{entrypoint}' for '{self.extractor_name}': {e}"
                    )

        return len(errors) == 0, errors

    def _import_entrypoint_attr(self, module_stem: str, attr_name: str, module_file: str) -> Any:
        """Import the entrypoint module as a submodule of a synthetic package
        rooted at the extractor's own directory, then return `attr_name`.

        Loading it with spec_from_file_location() and no parent package (as
        this used to do) gives it __package__ = "" — any `from . import
        helper` inside a real extractor breaks with "attempted relative
        import with no known parent package", so validation rejected
        perfectly working extractors that split code across local modules.
        The registry's real runtime import (apps/scraper/extractors/
        registry.py) doesn't have this problem because it imports through
        the actual `extractors.<id>` package — but validate() also runs
        against staging paths before an extractor is installed there, so it
        can't rely on that path existing. Registering a throwaway package
        module with __path__ pointed at the extractor directory gives
        relative imports something real to resolve against either way.
        """
        pkg_name = f"dh_extractor_validate_{self.extractor_name}"
        module_name = f"{pkg_name}.{module_stem}"
        added: list[str] = []
        try:
            if pkg_name not in sys.modules:
                pkg_spec = importlib.util.spec_from_loader(pkg_name, loader=None, is_package=True)
                pkg_module = importlib.util.module_from_spec(pkg_spec)
                pkg_module.__path__ = [self.extractor_path]
                sys.modules[pkg_name] = pkg_module
                added.append(pkg_name)

            spec = importlib.util.spec_from_file_location(module_name, module_file)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot load module from {module_file}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            added.append(module_name)
            spec.loader.exec_module(module)
            return getattr(module, attr_name, None)
        finally:
            for name in added:
                sys.modules.pop(name, None)


def validate_all_extractors(extractors_dir: str = EXTRACTORS_DIR) -> dict[str, tuple[bool, list[str]]]:
    """Validate installed extractor folders (directories with manifest.json)."""
    results: dict[str, tuple[bool, list[str]]] = {}
    if not os.path.exists(extractors_dir):
        return results

    for entry in sorted(os.listdir(extractors_dir)):
        extractor_path = os.path.join(extractors_dir, entry)
        manifest_path = os.path.join(extractor_path, "manifest.json")
        if os.path.isdir(extractor_path) and os.path.isfile(manifest_path):
            results[entry] = ExtractorValidator(extractor_path).validate()
    return results
