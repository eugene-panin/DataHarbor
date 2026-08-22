"""Phase 1 plugin contract: engines, entrypoints, Definitions merge."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from dagster import Definitions, asset

from bundles.loader import discover_bundle_definitions, merge_bundle_definitions
from bundles.plugin_contract import (
    BundleContractError,
    check_engines,
    resolve_dagster_entrypoint,
    validate_manifest_contract,
)
from bundles.scaffold import create_bundle

BUNDLES_ROOT = Path(__file__).resolve().parents[1] / "bundles"


def test_check_engines_ok_and_mismatch():
    assert check_engines({"engines": {"dataharbor": ">=1.0.0,<2.0.0"}}, platform_ver="1.0.0") == []
    errs = check_engines({"engines": {"dataharbor": ">=2.0.0"}}, platform_ver="1.0.0")
    assert errs and "does not satisfy" in errs[0]


def test_resolve_dagster_entrypoint():
    assert resolve_dagster_entrypoint({}) == ("assets", "defs")
    assert resolve_dagster_entrypoint({"entrypoints": {"dagster": "pipeline:defs"}}) == (
        "pipeline",
        "defs",
    )
    with pytest.raises(BundleContractError):
        resolve_dagster_entrypoint({"entrypoints": {"dagster": None}})


def test_celery_entrypoint_rejected():
    errs = validate_manifest_contract({"entrypoints": {"dagster": "assets:defs", "celery": "tasks:app"}})
    assert any("celery" in e for e in errs)


def test_scaffold_and_merge_defs():
    name = "zz_phase1_contract_demo"
    target = BUNDLES_ROOT / name
    if target.exists():
        shutil.rmtree(target)

    try:
        result = create_bundle(name, description="phase1 test")
        assert (Path(result["path"]) / "assets.py").exists()
        assert (Path(result["path"]) / "fetch.py").exists()

        manifest = json.loads((Path(result["path"]) / "manifest.json").read_text())
        assert manifest["engines"]["dataharbor"].startswith(">=")
        assert manifest["entrypoints"]["dagster"] == "assets:defs"
        assert manifest["entrypoints"]["celery"] is None

        @asset
        def core_probe():
            return 1

        core = Definitions(assets=[core_probe])
        merged = merge_bundle_definitions(core, bundles_dir=str(BUNDLES_ROOT), skip_invalid=False)
        assert merged is not None

        loaded = discover_bundle_definitions(str(BUNDLES_ROOT), skip_invalid=False)
        assert any(isinstance(d, Definitions) for d in loaded)
    finally:
        if target.exists():
            shutil.rmtree(target)
        # Drop cached import if any
        import sys

        mod = f"bundles.{name}"
        for key in list(sys.modules):
            if key == mod or key.startswith(mod + "."):
                del sys.modules[key]


def test_fail_fast_invalid_bundle(tmp_path, monkeypatch):
    name = "zz_phase1_invalid"
    path = BUNDLES_ROOT / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir()
    (path / "manifest.json").write_text('{"name": "x"}', encoding="utf-8")

    try:
        monkeypatch.delenv("DATAHARBOR_SKIP_INVALID_BUNDLES", raising=False)
        with pytest.raises(BundleContractError):
            discover_bundle_definitions(str(BUNDLES_ROOT), skip_invalid=False)

        skipped = discover_bundle_definitions(str(BUNDLES_ROOT), skip_invalid=True)
        assert isinstance(skipped, list)
    finally:
        if path.exists():
            shutil.rmtree(path)
