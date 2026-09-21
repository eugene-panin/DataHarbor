"""Regression tests for F09: a failed --force install must not destroy the
previously-working bundle/extractor. The new version is staged and validated
before ever replacing what's currently installed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.bundle.distributor import BundleDistributor
from apps.bundle.scaffold import create_bundle
from apps.extractor.distributor import ExtractorDistributor
from apps.extractor.scaffold import create_extractor


def _make_valid_bundle_source(tmp_path, name):
    src_dir = tmp_path / "sources" / name
    create_bundle(name, target_dir=str(src_dir))
    return src_dir


def _make_invalid_bundle_source(tmp_path, name, description="broken"):
    """A manifest with no .py files at all fails BundleValidator's checks."""
    src_dir = tmp_path / "bad_sources" / name
    src_dir.mkdir(parents=True)
    (src_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": "0.2.0",
                "description": description,
                "requirements": {"extractors": [], "python": [], "env": []},
                "entrypoints": {"dagster": None, "celery": None},
            }
        ),
        encoding="utf-8",
    )
    return src_dir


def _leftover_names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def test_bundle_failed_force_install_preserves_working_version(tmp_path):
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    distributor = BundleDistributor(bundles_dir=str(bundles_dir))

    good_source = _make_valid_bundle_source(tmp_path, "zz_install_test")
    result = distributor.install_bundle(str(good_source))
    assert result["status"] == "success"
    target_path = Path(result["installed_path"])
    original_manifest = (target_path / "manifest.json").read_text(encoding="utf-8")

    bad_source = _make_invalid_bundle_source(tmp_path, "zz_install_test")
    with pytest.raises(ValueError, match="validation failed"):
        distributor.install_bundle(str(bad_source), force=True)

    # The original, working bundle must be untouched — not deleted, not partially patched.
    assert target_path.is_dir()
    assert (target_path / "manifest.json").read_text(encoding="utf-8") == original_manifest
    # No __staging/__prev leftovers from the failed attempt.
    assert _leftover_names(bundles_dir) == ["zz_install_test"]


def test_bundle_successful_force_install_swaps_in_new_content(tmp_path):
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    distributor = BundleDistributor(bundles_dir=str(bundles_dir))

    v1 = _make_valid_bundle_source(tmp_path, "zz_swap_test")
    assert distributor.install_bundle(str(v1))["status"] == "success"

    v2 = tmp_path / "sources_v2" / "zz_swap_test"
    create_bundle("zz_swap_test", target_dir=str(v2), description="version two")
    result = distributor.install_bundle(str(v2), force=True)
    assert result["status"] == "success"

    manifest = json.loads((Path(result["installed_path"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["description"] == "version two"
    assert _leftover_names(bundles_dir) == ["zz_swap_test"]


def test_bundle_git_clone_failure_preserves_working_version(tmp_path, monkeypatch):
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    distributor = BundleDistributor(bundles_dir=str(bundles_dir))

    v1 = _make_valid_bundle_source(tmp_path, "zz_git_test")
    result = distributor.install_bundle(str(v1))
    target_path = Path(result["installed_path"])
    original_manifest = (target_path / "manifest.json").read_text(encoding="utf-8")

    import apps.bundle.distributor as bd_module

    def _boom(cmd, *a, **kw):
        raise RuntimeError("simulated git clone failure")

    monkeypatch.setattr(bd_module.subprocess, "check_call", _boom)

    with pytest.raises(RuntimeError):
        distributor.install_bundle("https://example.com/zz_git_test.git", force=True)

    assert target_path.is_dir()
    assert (target_path / "manifest.json").read_text(encoding="utf-8") == original_manifest
    assert _leftover_names(bundles_dir) == ["zz_git_test"]


def test_bundle_install_without_force_does_not_touch_existing(tmp_path):
    """Sanity check: the non-force "already exists" guard still fails fast,
    before any staging happens at all."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    distributor = BundleDistributor(bundles_dir=str(bundles_dir))

    v1 = _make_valid_bundle_source(tmp_path, "zz_noforce_test")
    distributor.install_bundle(str(v1))

    v2 = tmp_path / "sources_v2" / "zz_noforce_test"
    create_bundle("zz_noforce_test", target_dir=str(v2), description="should not land")

    with pytest.raises(ValueError, match="already exists"):
        distributor.install_bundle(str(v2), force=False)

    assert _leftover_names(bundles_dir) == ["zz_noforce_test"]


def _make_valid_extractor_source(tmp_path, name):
    src_dir = tmp_path / "ext_sources" / name
    create_extractor(name, target_dir=str(src_dir))
    return src_dir


def _make_invalid_extractor_source(tmp_path, name):
    src_dir = tmp_path / "bad_ext_sources" / name
    src_dir.mkdir(parents=True)
    (src_dir / "manifest.json").write_text(
        json.dumps({"name": name, "version": "0.2.0", "domains": [], "entrypoint": "extractor:parse"}),
        encoding="utf-8",
    )
    # No extractor.py at all -> ExtractorValidator fails (entrypoint module missing).
    return src_dir


def test_extractor_failed_force_install_preserves_working_version(tmp_path):
    extractors_dir = tmp_path / "extractors"
    extractors_dir.mkdir()
    distributor = ExtractorDistributor(extractors_dir=str(extractors_dir))

    good_source = _make_valid_extractor_source(tmp_path, "zz_ext_install_test")
    result = distributor.install_extractor(str(good_source))
    assert result["status"] == "success"
    target_path = Path(result["installed_path"])
    original_manifest = (target_path / "manifest.json").read_text(encoding="utf-8")

    bad_source = _make_invalid_extractor_source(tmp_path, "zz_ext_install_test")
    with pytest.raises(ValueError, match="validation failed"):
        distributor.install_extractor(str(bad_source), force=True)

    assert target_path.is_dir()
    assert (target_path / "manifest.json").read_text(encoding="utf-8") == original_manifest
    assert _leftover_names(extractors_dir) == ["zz_ext_install_test"]


def test_extractor_successful_force_install_swaps_in_new_content(tmp_path):
    extractors_dir = tmp_path / "extractors"
    extractors_dir.mkdir()
    distributor = ExtractorDistributor(extractors_dir=str(extractors_dir))

    v1 = _make_valid_extractor_source(tmp_path, "zz_ext_swap_test")
    assert distributor.install_extractor(str(v1))["status"] == "success"

    v2 = tmp_path / "ext_sources_v2" / "zz_ext_swap_test"
    create_extractor("zz_ext_swap_test", target_dir=str(v2))
    (v2 / "manifest.json").write_text(
        json.dumps(
            json.loads((v2 / "manifest.json").read_text(encoding="utf-8")) | {"version": "0.2.0"}
        ),
        encoding="utf-8",
    )
    result = distributor.install_extractor(str(v2), force=True)
    assert result["status"] == "success"

    manifest = json.loads((Path(result["installed_path"]) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.2.0"
    assert _leftover_names(extractors_dir) == ["zz_ext_swap_test"]
