"""Tests for bundle scaffold templates."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

from bundles.scaffold import create_bundle, list_bundle_templates, resolve_template

BUNDLES_ROOT = Path(__file__).resolve().parents[1] / "bundles"


def _cleanup(name: str) -> None:
    target = BUNDLES_ROOT / name
    if target.exists():
        shutil.rmtree(target)
    mod = f"bundles.{name}"
    for key in list(sys.modules):
        if key == mod or key.startswith(mod + "."):
            del sys.modules[key]


@pytest.mark.parametrize("template_id", ["default", "ml", "etl", "dagster"])
def test_create_bundle_templates_validate(template_id: str):
    name = f"zz_tpl_{template_id}"
    _cleanup(name)
    try:
        result = create_bundle(name, template=template_id, target_dir=str(BUNDLES_ROOT / name))
        assert result["template"] == template_id
        root = Path(result["path"])
        assert (root / "manifest.json").exists()
        assert (root / "assets.py").exists()
        if template_id == "default":
            assert (root / "scraper.py").exists()
            assert (root / "fetch.py").exists()
        if template_id in ("default", "ml", "etl"):
            assert (root / "db.py").exists()
        if template_id in ("ml", "etl", "dagster"):
            assert not (root / "scraper.py").exists()
    finally:
        _cleanup(name)


def test_unknown_template_raises():
    with pytest.raises(ValueError, match="Unknown template"):
        resolve_template("not_a_template")


def test_list_templates_has_default():
    ids = {t.id for t in list_bundle_templates()}
    assert {"default", "ml", "etl", "dagster"}.issubset(ids)
