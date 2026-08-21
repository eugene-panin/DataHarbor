"""Tests for Dagster multi code-location workspace builder."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

from apps.dagster_app.workspace_builder import (
    build_workspace_document,
    location_names,
    write_workspace_yaml,
)
from bundles.scaffold import create_bundle

BUNDLES_ROOT = Path(__file__).resolve().parents[1] / "bundles"
PROJECT_ROOT = BUNDLES_ROOT.parent


def test_workspace_includes_core_and_bundle(tmp_path):
    name = "zz_mcl_demo"
    target = BUNDLES_ROOT / name
    if target.exists():
        shutil.rmtree(target)

    try:
        create_bundle(name)
        doc, warnings = build_workspace_document(
            bundles_dir=str(BUNDLES_ROOT),
            project_root=str(PROJECT_ROOT),
            skip_invalid=True,
        )
        names = location_names(doc)
        assert "core" in names
        assert f"bundle_{name}" in names

        out = tmp_path / "workspace.yaml"
        path, written, _ = write_workspace_yaml(
            str(out),
            bundles_dir=str(BUNDLES_ROOT),
            project_root=str(PROJECT_ROOT),
        )
        assert Path(path).exists()
        loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        assert loaded["load_from"][0]["python_module"]["location_name"] == "core"
        assert any(
            e.get("python_module", {}).get("location_name") == f"bundle_{name}"
            for e in loaded["load_from"]
        )
        assert written == loaded
    finally:
        if target.exists():
            shutil.rmtree(target)
        mod = f"bundles.{name}"
        for key in list(sys.modules):
            if key == mod or key.startswith(mod + "."):
                del sys.modules[key]


def test_core_definitions_has_no_bundle_merge():
    from apps.dagster_app import definitions as core_defs_mod

    src = Path(core_defs_mod.__file__).read_text(encoding="utf-8")
    assert "merge_bundle_definitions" not in src
    assert hasattr(core_defs_mod, "defs")
