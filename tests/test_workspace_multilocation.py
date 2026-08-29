"""Tests for Dagster multi code-location workspace builder."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

from apps.bundle.scaffold import create_bundle
from apps.dagster_app.workspace_builder import (
    build_workspace_document,
    location_names,
    write_workspace_yaml,
)

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


def test_workspace_include_bundles_filter(tmp_path):
    name_a = "zz_ws_a"
    name_b = "zz_ws_b"
    for name in (name_a, name_b):
        target = BUNDLES_ROOT / name
        if target.exists():
            shutil.rmtree(target)

    try:
        create_bundle(name_a)
        create_bundle(name_b)
        doc, _ = build_workspace_document(
            bundles_dir=str(BUNDLES_ROOT),
            project_root=str(PROJECT_ROOT),
            include_bundles=[name_a],
        )
        names = location_names(doc)
        assert "core" in names
        assert f"bundle_{name_a}" in names
        assert f"bundle_{name_b}" not in names
    finally:
        for name in (name_a, name_b):
            target = BUNDLES_ROOT / name
            if target.exists():
                shutil.rmtree(target)
            mod = f"bundles.{name}"
            for key in list(sys.modules):
                if key == mod or key.startswith(mod + "."):
                    del sys.modules[key]


def test_named_workspace_writes_under_workspaces(tmp_path, monkeypatch):
    from apps.dagster_app import workspace_builder as wb

    profiles = tmp_path / "profiles.yaml"
    profiles.write_text(
        "profiles:\n  solo:\n    bundles: [zz_solo]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(wb, "PROFILES_PATH", str(profiles))
    monkeypatch.setattr(wb, "WORKSPACES_DIR", str(tmp_path / "workspaces"))

    name = "zz_solo"
    target = BUNDLES_ROOT / name
    if target.exists():
        shutil.rmtree(target)
    try:
        create_bundle(name)
        path, doc, warnings = wb.write_named_workspace(
            "solo",
            project_root=str(PROJECT_ROOT),
            profiles_path=str(profiles),
        )
        assert path.endswith("solo.yaml")
        assert Path(path).exists()
        names = location_names(doc)
        assert names == ["core", f"bundle_{name}"]
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
