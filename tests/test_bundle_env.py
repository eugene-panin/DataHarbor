"""Tests for manifest requirements.env."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from apps.bundle.doctor import doctor_bundle, format_doctor_report
from apps.bundle.env_requirements import (
    EnvRequirementError,
    check_env_requirements,
    format_env_install_hint,
    parse_env_requirements,
)
from apps.bundle.plugin_contract import validate_manifest_contract
from apps.bundle.scaffold import create_bundle
from apps.bundle.validator import BundleValidator

BUNDLES_ROOT = Path(__file__).resolve().parents[1] / "bundles"


def test_parse_string_and_object():
    specs = parse_env_requirements(
        [
            "FOO_API_KEY",
            {"name": "BAR_TOKEN", "required": False, "description": "optional judge"},
        ]
    )
    assert specs[0] == {"name": "FOO_API_KEY", "required": True, "description": ""}
    assert specs[1]["name"] == "BAR_TOKEN"
    assert specs[1]["required"] is False


def test_parse_rejects_bad_name_and_dupes():
    with pytest.raises(EnvRequirementError, match="must match"):
        parse_env_requirements(["not-a-name"])
    with pytest.raises(EnvRequirementError, match="duplicates"):
        parse_env_requirements(["FOO", "FOO"])
    with pytest.raises(EnvRequirementError, match="must be an array"):
        parse_env_requirements({"name": "FOO"})


def test_check_required_missing_fails_optional_warns():
    specs = parse_env_requirements(
        [
            {"name": "NEED_ME", "required": True},
            {"name": "NICE_ME", "required": False, "description": "quiz judge"},
        ]
    )
    rows = check_env_requirements(specs, environ={})
    assert rows[0]["status"] == "fail"
    assert rows[1]["status"] == "warn"
    rows_ok = check_env_requirements(specs, environ={"NEED_ME": "x", "NICE_ME": "y"})
    assert all(row["status"] == "ok" for row in rows_ok)


def test_install_hint_lists_missing():
    specs = parse_env_requirements(["QUIZ_API_KEY"])
    text = format_env_install_hint(specs, environ={})
    assert "QUIZ_API_KEY" in text
    assert "missing" in text
    assert ".env" in text


def test_invalid_env_schema_fails_validate_not_missing_value(tmp_path):
    errs = validate_manifest_contract({"requirements": {"env": "FOO"}})
    assert any("requirements.env" in e for e in errs)

    bundle = tmp_path / "zz_env_ok_schema"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(
        json.dumps(
            {
                "name": "zz_env_ok_schema",
                "version": "0.1.0",
                "description": "x",
                "requirements": {"extractors": [], "python": [], "env": ["MISSING_REQUIRED_KEY"]},
                "entrypoints": {"dagster": None, "celery": None},
            }
        ),
        encoding="utf-8",
    )
    (bundle / "db.py").write_text("x = 1\n", encoding="utf-8")
    ok, errors = BundleValidator(str(bundle)).validate()
    assert ok, errors


def test_doctor_required_env_missing_fails():
    name = "zz_doctor_env"
    target = BUNDLES_ROOT / name
    if target.exists():
        shutil.rmtree(target)
    try:
        create_bundle(name)
        manifest_path = target / "manifest.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["requirements"]["env"] = [
            {"name": "ZZ_DOCTOR_ENV_REQUIRED", "required": True, "description": "test key"},
        ]
        manifest_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        report = doctor_bundle(name, bundles_dir=str(BUNDLES_ROOT))
        assert not report.ok, format_doctor_report(report)
        assert any(
            c.name == "requirements.env" and c.status == "fail" for c in report.checks
        )
    finally:
        if target.exists():
            shutil.rmtree(target)
        mod = f"bundles.{name}"
        for key in list(sys.modules):
            if key == mod or key.startswith(mod + "."):
                del sys.modules[key]


def test_scaffold_declares_empty_env_array():
    name = "zz_scaffold_env"
    target = BUNDLES_ROOT / name
    if target.exists():
        shutil.rmtree(target)
    try:
        create_bundle(name)
        data = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        assert data["requirements"]["env"] == []
    finally:
        if target.exists():
            shutil.rmtree(target)
        mod = f"bundles.{name}"
        for key in list(sys.modules):
            if key == mod or key.startswith(mod + "."):
                del sys.modules[key]
