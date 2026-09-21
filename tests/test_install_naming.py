"""Regression tests for F10: a git-URL install must derive the installed
bundle/extractor's identity from its own manifest.json "name", not from
parsing the repo URL. `harbor bundle publish` / `harbor extractor publish`
suggest repo names like "dh-bundle-<name>" / "dh-extractor-<name>"; deriving
the installed directory from that instead silently installs the plugin
under a different name than the one its own manifest/AGENT.md/docs use —
"install succeeded" followed by "bundle/extractor not found" at load time.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from apps.bundle.distributor import BundleDistributor
from apps.bundle.scaffold import create_bundle
from apps.extractor.distributor import ExtractorDistributor
from apps.extractor.scaffold import create_extractor


def _fake_git_clone(fixture_source: Path):
    """A subprocess.check_call replacement that "clones" by copying a fixture
    directory to the destination — cmd is ["git", "clone", source, dest]."""

    def _clone(cmd, *args, **kwargs):
        dest = cmd[3]
        shutil.copytree(str(fixture_source), dest)

    return _clone


def test_bundle_git_install_uses_manifest_name_not_repo_basename(tmp_path, monkeypatch):
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    distributor = BundleDistributor(bundles_dir=str(bundles_dir))

    # The bundle author's manifest says "audit"; the repo they publish it
    # under (following harbor bundle publish's own suggested convention)
    # is named "dh-bundle-audit" — a real, expected round trip, not a
    # contrived edge case.
    fixture_source = tmp_path / "fixture_source"
    create_bundle("audit", target_dir=str(fixture_source))

    import apps.bundle.distributor as bd_module

    monkeypatch.setattr(bd_module.subprocess, "check_call", _fake_git_clone(fixture_source))

    result = distributor.install_bundle("https://github.com/you/dh-bundle-audit.git")

    assert result["status"] == "success"
    assert result["bundle_name"] == "audit"
    assert (bundles_dir / "audit").is_dir()
    assert not (bundles_dir / "dh_bundle_audit").exists()
    assert not (bundles_dir / "_git_clone_temp").exists()


def test_extractor_git_install_uses_manifest_name_not_repo_basename(tmp_path, monkeypatch):
    extractors_dir = tmp_path / "extractors"
    extractors_dir.mkdir()
    distributor = ExtractorDistributor(extractors_dir=str(extractors_dir))

    fixture_source = tmp_path / "ext_fixture_source"
    create_extractor("example", target_dir=str(fixture_source))

    import apps.extractor.distributor as ed_module

    monkeypatch.setattr(ed_module.subprocess, "check_call", _fake_git_clone(fixture_source))

    result = distributor.install_extractor("https://github.com/you/dh-extractor-example.git")

    assert result["status"] == "success"
    assert result["extractor_name"] == "example"
    assert (extractors_dir / "example").is_dir()
    assert not (extractors_dir / "dh_extractor_example").exists()
