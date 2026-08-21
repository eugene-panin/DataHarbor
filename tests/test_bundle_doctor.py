"""Tests for harbor bundle doctor."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from bundles.doctor import doctor_bundle, format_doctor_report
from bundles.scaffold import create_bundle

BUNDLES_ROOT = Path(__file__).resolve().parents[1] / "bundles"


def test_doctor_scaffold_bundle_ok():
    name = "zz_doctor_demo"
    target = BUNDLES_ROOT / name
    if target.exists():
        shutil.rmtree(target)

    try:
        create_bundle(name, description="doctor test")
        report = doctor_bundle(name, bundles_dir=str(BUNDLES_ROOT))
        assert report.ok, format_doctor_report(report)
        names = {c.name for c in report.checks}
        assert "structure" in names
        assert "engines" in names
        assert "entrypoints.dagster" in names
        assert any(c.name == "entrypoints.dagster" and c.status == "ok" for c in report.checks)
        text = format_doctor_report(report)
        assert "Result: OK" in text
    finally:
        if target.exists():
            shutil.rmtree(target)
        mod = f"bundles.{name}"
        for key in list(sys.modules):
            if key == mod or key.startswith(mod + "."):
                del sys.modules[key]


def test_doctor_missing_python_dep_fails():
    name = "zz_doctor_missing_dep"
    target = BUNDLES_ROOT / name
    if target.exists():
        shutil.rmtree(target)

    try:
        create_bundle(name)
        manifest_path = target / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["requirements"]["python"] = ["definitely-not-a-real-pkg-xyz==9.9.9"]
        manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

        report = doctor_bundle(name, bundles_dir=str(BUNDLES_ROOT))
        assert not report.ok
        assert any(
            c.name == "requirements.python" and c.status == "fail" for c in report.checks
        )
    finally:
        if target.exists():
            shutil.rmtree(target)
        mod = f"bundles.{name}"
        for key in list(sys.modules):
            if key == mod or key.startswith(mod + "."):
                del sys.modules[key]
