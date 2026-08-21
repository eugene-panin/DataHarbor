"""Diagnostic checks for an installed DataHarbor bundle (plugin contract)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version as pkg_version
from typing import Any, Dict, List, Optional

from packaging.requirements import InvalidRequirement, Requirement

from bundles.plugin_contract import (
    BundleContractError,
    check_engines,
    iter_bundle_dirs,
    load_bundle_definitions_object,
    load_manifest,
    platform_version,
    resolve_dagster_entrypoint,
)
from bundles.validator import BundleValidator

BUNDLES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bundles")


@dataclass
class CheckResult:
    name: str
    status: str  # ok | warn | fail | skip
    detail: str = ""


@dataclass
class DoctorReport:
    bundle_name: str
    bundle_path: str
    platform_version: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(c.status == "fail" for c in self.checks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bundle_name": self.bundle_name,
            "bundle_path": self.bundle_path,
            "platform_version": self.platform_version,
            "ok": self.ok,
            "checks": [
                {"name": c.name, "status": c.status, "detail": c.detail} for c in self.checks
            ],
        }


def _resolve_bundle_path(name: str, bundles_dir: str) -> str:
    path = os.path.join(bundles_dir, name)
    if not os.path.isdir(path):
        raise FileNotFoundError(f"Bundle '{name}' not found under {bundles_dir}")
    return path


def _check_python_deps(manifest: Dict[str, Any]) -> List[CheckResult]:
    results: List[CheckResult] = []
    reqs = (manifest.get("requirements") or {}).get("python")
    if not reqs:
        results.append(
            CheckResult(
                "requirements.python",
                "skip",
                "none declared (add Playwright etc. here when needed)",
            )
        )
        return results

    if not isinstance(reqs, list):
        results.append(
            CheckResult("requirements.python", "fail", "must be a list of requirement strings")
        )
        return results

    for raw in reqs:
        if not isinstance(raw, str) or not raw.strip():
            results.append(CheckResult("requirements.python", "fail", f"invalid entry: {raw!r}"))
            continue
        try:
            req = Requirement(raw.strip())
        except InvalidRequirement as e:
            results.append(CheckResult("requirements.python", "fail", f"{raw!r}: {e}"))
            continue

        try:
            installed = pkg_version(req.name)
        except PackageNotFoundError:
            results.append(
                CheckResult(
                    "requirements.python",
                    "fail",
                    f"{req.name} not installed (declared: {raw})",
                )
            )
            continue

        if req.specifier and installed not in req.specifier:
            results.append(
                CheckResult(
                    "requirements.python",
                    "fail",
                    f"{req.name}=={installed} does not satisfy '{raw}'",
                )
            )
        else:
            results.append(
                CheckResult(
                    "requirements.python",
                    "ok",
                    f"{req.name}=={installed} satisfies '{raw}'",
                )
            )
    return results


def _check_extractors(manifest: Dict[str, Any], bundle_name: str) -> List[CheckResult]:
    raw = (manifest.get("requirements") or {}).get("extractors")
    if not raw:
        return [CheckResult("extractors", "skip", "none declared")]

    try:
        from apps.scraper.extractors.registry import is_extractor_installed
        from extractors.requirements import parse_extractor_requirements
        from extractors.validator import EXTRACTORS_DIR, ExtractorValidator
    except Exception as e:
        return [CheckResult("extractors", "fail", f"cannot load extractor tooling: {e}")]

    try:
        requirements = parse_extractor_requirements(raw)
    except Exception as e:
        return [CheckResult("extractors", "fail", f"invalid requirements.extractors: {e}")]

    out: List[CheckResult] = []
    for req in requirements:
        extractor_id = req.get("name") or "?"
        source = req.get("source")
        path = os.path.join(EXTRACTORS_DIR, extractor_id)
        if not os.path.isdir(path):
            hint = f" (source: {source})" if source else ""
            out.append(
                CheckResult(
                    "extractors",
                    "fail",
                    f"'{extractor_id}' not installed under extractors/{hint}",
                )
            )
            continue
        if not is_extractor_installed(extractor_id):
            out.append(
                CheckResult("extractors", "fail", f"'{extractor_id}' present but not loadable")
            )
            continue
        ok, errs = ExtractorValidator(path).validate()
        if not ok:
            out.append(
                CheckResult(
                    "extractors",
                    "fail",
                    f"'{extractor_id}' invalid: " + "; ".join(errs),
                )
            )
        else:
            out.append(CheckResult("extractors", "ok", f"'{extractor_id}' installed and valid"))
    if not out:
        out.append(CheckResult("extractors", "skip", "none declared"))
    return out


def _check_dagster_entrypoint(bundle_name: str, bundle_path: str, manifest: Dict[str, Any]) -> List[CheckResult]:
    entrypoints = manifest.get("entrypoints") or {}
    if isinstance(entrypoints, dict) and entrypoints.get("dagster") is None:
        return [
            CheckResult(
                "entrypoints.dagster",
                "skip",
                "null — bundle has no Dagster definitions (scraper/db only)",
            )
        ]

    try:
        module_leaf, attr = resolve_dagster_entrypoint(manifest)
    except BundleContractError as e:
        return [CheckResult("entrypoints.dagster", "fail", str(e))]

    module_file = os.path.join(bundle_path, f"{module_leaf}.py")
    if not os.path.exists(module_file):
        return [
            CheckResult(
                "entrypoints.dagster",
                "fail",
                f"{module_leaf}:{attr} — missing file {module_leaf}.py",
            )
        ]

    try:
        defs = load_bundle_definitions_object(bundle_name, bundle_path)
    except BundleContractError as e:
        return [CheckResult("entrypoints.dagster", "fail", f"{module_leaf}:{attr} — {e}")]
    except Exception as e:
        return [CheckResult("entrypoints.dagster", "fail", f"{module_leaf}:{attr} — import error: {e}")]

    from dagster import Definitions

    if not isinstance(defs, Definitions):
        return [
            CheckResult(
                "entrypoints.dagster",
                "fail",
                f"{module_leaf}:{attr} is not a Definitions instance",
            )
        ]

    return [
        CheckResult(
            "entrypoints.dagster",
            "ok",
            f"{module_leaf}:{attr} loaded as Definitions",
        )
    ]


def doctor_bundle(
    bundle_name: str,
    *,
    bundles_dir: Optional[str] = None,
) -> DoctorReport:
    """Run full diagnostic suite for one bundle."""
    root = bundles_dir or BUNDLES_DIR
    path = _resolve_bundle_path(bundle_name, root)
    plat = platform_version()
    report = DoctorReport(bundle_name=bundle_name, bundle_path=path, platform_version=plat)

    is_valid, struct_errors = BundleValidator(path).validate()
    if is_valid:
        report.checks.append(CheckResult("structure", "ok", "manifest + syntax + extractors OK"))
    else:
        report.checks.append(
            CheckResult("structure", "fail", "; ".join(struct_errors) or "validation failed")
        )

    try:
        manifest = load_manifest(path)
    except Exception as e:
        report.checks.append(CheckResult("manifest", "fail", str(e)))
        return report

    engines = (manifest.get("engines") or {}).get("dataharbor") if isinstance(manifest.get("engines"), dict) else None
    if not engines:
        report.checks.append(
            CheckResult(
                "engines",
                "warn",
                "engines.dataharbor not declared (recommended: \">=1.0.0,<2.0.0\")",
            )
        )
    else:
        engine_errs = check_engines(manifest, platform_ver=plat)
        if engine_errs:
            report.checks.append(CheckResult("engines", "fail", "; ".join(engine_errs)))
        else:
            report.checks.append(
                CheckResult("engines", "ok", f"platform {plat} satisfies '{engines}'")
            )

    report.checks.extend(_check_python_deps(manifest))
    report.checks.extend(_check_extractors(manifest, bundle_name))
    report.checks.extend(_check_dagster_entrypoint(bundle_name, path, manifest))

    return report


def doctor_all_bundles(*, bundles_dir: Optional[str] = None) -> List[DoctorReport]:
    root = bundles_dir or BUNDLES_DIR
    return [doctor_bundle(name, bundles_dir=root) for name, _path in iter_bundle_dirs(root)]


def format_doctor_report(report: DoctorReport) -> str:
    symbols = {"ok": "✅", "warn": "⚠️", "fail": "❌", "skip": "➖"}
    lines = [
        f"🩺 Bundle doctor: {report.bundle_name}",
        f"   path: {report.bundle_path}",
        f"   platform: {report.platform_version}",
        "",
    ]
    for check in report.checks:
        sym = symbols.get(check.status, "•")
        detail = f" — {check.detail}" if check.detail else ""
        lines.append(f"{sym} {check.name}{detail}")
    lines.append("")
    lines.append("Result: " + ("OK" if report.ok else "FAIL"))
    return "\n".join(lines)
